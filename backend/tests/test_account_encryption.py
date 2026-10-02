"""Real SQL field storage, strict authenticity and legacy migration boundaries."""

import base64
import hashlib
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest
from cryptography.fernet import Fernet
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from backend import config
from backend.compat.ui_contracts import ensure_ui_contracts
from backend.db.auth_models import AuthSetupORM  # noqa: F401 — include complete installation metadata
from backend.db.orm_models import AccountORM, Base
from backend.error_helpers import DatabaseOperationError
from backend.models import AccountCreate, AccountPatch, PortfolioCreate
from backend.repositories.sql_store import SQLAlchemyStore
from backend.services.iban_encryption import (
    IBANEncryptionError,
    IBANKeyring,
    current_keyring,
    decrypt_iban,
    encrypt_iban,
    keyring_from_configuration,
    mask_iban,
)
from backend.services.iban_http import register_iban_exception_handler
from backend.services.iban_schema import ensure_account_encryption_schema, guard_account_write
from backend.storage import InMemoryStore

KEY = base64.urlsafe_b64encode(b"a" * 32).decode()
INDEX = base64.urlsafe_b64encode(b"i" * 32).decode()
OTHER = base64.urlsafe_b64encode(b"b" * 32).decode()
IBAN = "DE89370400440532013000"
LEGACY = "synthetic-old-jwt-secret"


def configure(monkeypatch, *, key=KEY, index=INDEX, keyring="", active="default", jwt=LEGACY):
    monkeypatch.setattr(
        config,
        "settings",
        SimpleNamespace(
            encryption_key=key,
            encryption_index_key=index,
            encryption_keyring=keyring,
            encryption_active_key_id=active,
            encryption_legacy_jwt_keys="[]",
            jwt_secret_key=jwt,
        ),
    )


def legacy_cipher(value=IBAN, secret=LEGACY):
    raw = hashlib.pbkdf2_hmac("sha256", secret.encode(), b"immomanager-iban-encryption-salt", 100_000)
    return "enc:" + Fernet(base64.urlsafe_b64encode(raw)).encrypt(value.encode()).decode()


@pytest.fixture
def account_database(tmp_path, monkeypatch):
    configure(monkeypatch)
    ensure_ui_contracts()
    engine = create_engine(
        "sqlite:///" + (tmp_path / "accounts.db").as_posix(),
        connect_args={"check_same_thread": False, "timeout": 15},
        hide_parameters=True,
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        portfolio = SQLAlchemyStore(session).create_portfolio(PortfolioCreate(name="Synthetic portfolio"))
    yield engine, portfolio.id
    engine.dispose()


def payload(portfolio, iban=IBAN):
    return AccountCreate(portfolio_id=portfolio, name="Synthetic bank", account_type="checking", iban=iban)


@pytest.mark.parametrize("backend", ["memory", "sql"])
def test_account_create_get_put_patch_list_roundtrip(backend, account_database):
    engine, portfolio = account_database
    with Session(engine) as session:
        store = SQLAlchemyStore(session) if backend == "sql" else InMemoryStore()
        if backend == "memory":
            portfolio = store.create_portfolio(PortfolioCreate(name="Memory")).id
        account = store.create_account(payload(portfolio))
        assert account.iban == IBAN
        assert store.get_account(account.id).iban == IBAN
        assert store.list_accounts()[0].iban == IBAN
        changed = store.update_account(account.id, payload(portfolio, "DE" + "2" * 20))
        assert changed.iban == "DE" + "2" * 20
        restored = store._patch_entity("account", account.id, AccountPatch(iban=IBAN))
        assert restored.iban == IBAN
    if backend == "sql":
        with engine.connect() as connection:
            raw, fingerprint = connection.execute(text("SELECT iban, iban_fingerprint FROM accounts")).one()
        assert raw.startswith("enc:v1:default:") and IBAN not in raw
        assert current_keyring().decrypt(raw) == IBAN
        assert fingerprint == current_keyring().fingerprint(IBAN)


def test_native_orm_writes_use_the_type_and_index(account_database):
    engine, portfolio = account_database
    with Session(engine) as session:
        account = AccountORM(portfolio_id=portfolio, name="Native", account_type="checking", iban=IBAN)
        session.add(account)
        session.commit()
        assert account.iban == IBAN
        account.iban = "FR" + "3" * 20
        session.commit()
    with engine.connect() as connection:
        stored, fingerprint = connection.execute(text("SELECT iban, iban_fingerprint FROM accounts")).one()
    assert decrypt_iban(stored) == "FR" + "3" * 20
    assert fingerprint == current_keyring().fingerprint("FR" + "3" * 20)


def test_token_signing_rotation_does_not_change_existing_iban_access(account_database, monkeypatch):
    engine, portfolio = account_database
    with Session(engine) as session:
        account = SQLAlchemyStore(session).create_account(payload(portfolio))
    configure(monkeypatch, jwt="deliberately-different-token-secret")
    with Session(engine) as session:
        assert SQLAlchemyStore(session).get_account(account.id).iban == IBAN


@pytest.mark.parametrize("stored", [IBAN, legacy_cipher()], ids=["plaintext", "legacy-encrypted"])
def test_existing_fields_read_without_automatic_mutation_and_block_writes_until_migration(stored, account_database):
    engine, portfolio = account_database
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO accounts (id, portfolio_id, name, account_type, iban, opening_balance, balance, created_at, updated_at) VALUES ('legacy', :p, 'Legacy', 'checking', :iban, 0, 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            ),
            dict(p=portfolio, iban=stored),
        )
    with Session(engine) as session:
        store = SQLAlchemyStore(session)
        assert store.get_account("legacy").iban == IBAN
        with pytest.raises(IBANEncryptionError, match="ENCRYPTION_MIGRATION_REQUIRED"):
            store.create_account(payload(portfolio, "FR" + "2" * 20))
        with pytest.raises(IBANEncryptionError, match="ENCRYPTION_MIGRATION_REQUIRED"):
            store._patch_entity("account", "legacy", AccountPatch(name="Must not silently migrate"))
    with engine.connect() as connection:
        assert connection.execute(text("SELECT iban, iban_fingerprint, name FROM accounts")).one() == (
            stored,
            None,
            "Legacy",
        )


@pytest.mark.parametrize("mode", ["wrong-key", "missing-key", "wrong-index"])
def test_wrong_configuration_never_replaces_data_with_a_mask_or_plaintext(mode, account_database, monkeypatch):
    engine, portfolio = account_database
    with Session(engine) as session:
        account = SQLAlchemyStore(session).create_account(payload(portfolio))
    with engine.connect() as connection:
        before = connection.execute(text("SELECT * FROM accounts")).one()
    configure(
        monkeypatch,
        key=OTHER if mode == "wrong-key" else "" if mode == "missing-key" else KEY,
        index=OTHER if mode == "wrong-index" else INDEX,
    )
    with Session(engine) as session:
        with pytest.raises(IBANEncryptionError):
            SQLAlchemyStore(session)._patch_entity("account", account.id, AccountPatch(iban="DE" + "9" * 20))
    with engine.connect() as connection:
        assert connection.execute(text("SELECT * FROM accounts")).one() == before
    configure(monkeypatch)
    with Session(engine) as session:
        assert SQLAlchemyStore(session).get_account(account.id).iban == IBAN


def test_api_crypto_error_has_repair_code_and_no_secrets(account_database, monkeypatch, caplog):
    engine, portfolio = account_database
    with Session(engine) as session:
        account = SQLAlchemyStore(session).create_account(payload(portfolio))
    configure(monkeypatch, key=OTHER)
    app = FastAPI()
    register_iban_exception_handler(app)

    @app.get("/account")
    def read():
        with Session(engine) as session:
            return SQLAlchemyStore(session).get_account(account.id)

    with TestClient(app) as client:
        response = client.get("/account")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "ENCRYPTION_AUTHENTICATION_FAILED"
    for secret in (IBAN, KEY, OTHER, INDEX):
        assert secret not in response.text + caplog.text


def test_canonical_duplicate_uniqueness_survives_key_versions_and_concurrent_sessions(account_database, monkeypatch):
    import json

    engine, portfolio = account_database
    with Session(engine) as session:
        first = SQLAlchemyStore(session).create_account(payload(portfolio))
    configure(monkeypatch, key="", keyring=json.dumps({"default": KEY, "new": OTHER}), active="new")

    def create(index):
        with Session(engine) as session:
            try:
                return (
                    SQLAlchemyStore(session)
                    .create_account(payload(portfolio, "de89 3704 0044 0532 0130 00" if index == 0 else IBAN))
                    .id
                )
            except DatabaseOperationError:
                return None

    assert list(ThreadPoolExecutor(2).map(create, range(2))) == [None, None]
    with Session(engine) as session:
        assert [account.id for account in SQLAlchemyStore(session).list_accounts()] == [first.id]


def test_ciphertext_authenticates_version_field_and_key_identity(monkeypatch):
    configure(monkeypatch)
    ring = IBANKeyring("one", {"one": KEY, "two": KEY}, index_key=INDEX)
    token = ring.encrypt(IBAN)
    assert token == ring.encrypt(IBAN)
    for changed in (token.replace(":one:", ":two:"), token[:-3] + "AA=", token.replace(":v1:", ":v2:")):
        with pytest.raises(IBANEncryptionError):
            ring.decrypt(changed)
    assert IBAN not in repr(ring) and KEY not in repr(ring)


def test_missing_crypto_dependency_fails_closed(monkeypatch):
    from backend.services import iban_encryption as module

    configure(monkeypatch)

    def missing():
        raise IBANEncryptionError("ENCRYPTION_DEPENDENCY_MISSING")

    monkeypatch.setattr(module, "_dependencies", missing)
    with pytest.raises(IBANEncryptionError, match="ENCRYPTION_DEPENDENCY_MISSING"):
        encrypt_iban(IBAN)
    assert decrypt_iban(IBAN) == IBAN


def test_legacy_only_key_configuration_is_readable_but_never_used_for_new_encryption():
    ring = keyring_from_configuration({"JWT_SECRET_KEY": LEGACY})
    assert ring.decrypt(legacy_cipher()) == IBAN
    with pytest.raises(IBANEncryptionError, match="ENCRYPTION_KEY_MISSING"):
        ring.encrypt(IBAN)
    assert mask_iban(IBAN) == "****3000"


@pytest.mark.parametrize("provisioning", ["orm", "unstamped-runtime"])
def test_legacy_guard_uses_partial_index_instead_of_scanning_blank_accounts(account_database, provisioning):
    engine, portfolio = account_database
    lookup = "SELECT 1 FROM accounts WHERE iban IS NOT NULL AND iban != '' AND iban_fingerprint IS NULL LIMIT 1"
    with engine.begin() as connection:
        if provisioning == "unstamped-runtime":
            connection.execute(text("DROP INDEX ix_accounts_iban_unindexed"))
            ensure_account_encryption_schema(connection)
        connection.execute(
            text(
                "INSERT INTO accounts (id, portfolio_id, name, account_type, iban, opening_balance, balance, created_at, updated_at) "
                "VALUES (:id, :portfolio, 'Synthetic cash', 'cash', NULL, 0, 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            ),
            [{"id": f"cash-{index}", "portfolio": portfolio} for index in range(2000)],
        )
        plan = connection.execute(text("EXPLAIN QUERY PLAN " + lookup)).fetchall()
        assert any("ix_accounts_iban_unindexed" in row[3] for row in plan), plan
        assert connection.execute(text(lookup)).first() is None
        guard_account_write(connection, current_keyring())
        connection.execute(
            text(
                "INSERT INTO accounts (id, portfolio_id, name, account_type, iban, opening_balance, balance, created_at, updated_at) "
                "VALUES ('legacy-index-proof', :portfolio, 'Legacy', 'checking', :iban, 0, 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            ),
            {"portfolio": portfolio, "iban": IBAN},
        )
        assert connection.execute(text(lookup)).first() is not None
        with pytest.raises(IBANEncryptionError, match="ENCRYPTION_MIGRATION_REQUIRED"):
            guard_account_write(connection, current_keyring())
