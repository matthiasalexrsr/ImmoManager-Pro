"""Real PostgreSQL encryption tests own UUID schemas, never public/user tables."""

import json
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.db.orm_models import AccountORM, PortfolioORM
from backend.error_helpers import DatabaseOperationError
from backend.models import PortfolioCreate
from backend.repositories.sql_store import SQLAlchemyStore
from backend.services.iban_encryption import IBANEncryptionError, current_keyring
from backend.services.iban_rotation import create_backup_proof, inspect_account_encryption, rotate_account_ibans
from backend.tests import test_private_server_concurrency as postgres_support
from backend.tests.test_account_encryption import IBAN, KEY, OTHER, configure, payload
from backend.tests.test_iban_rotation import rotation_keyring

postgres_database = postgres_support.postgres_database
postgres_backup_database = postgres_support.postgres_database


def seed(engine):
    with Session(engine) as session:
        store = SQLAlchemyStore(session)
        portfolio = store.create_portfolio(PortfolioCreate(name="Synthetic PG encryption"))
        account = store.create_account(payload(portfolio.id))
    return portfolio, account


def test_pg_ciphertext_roundtrip_and_cross_key_canonical_uniqueness(postgres_database, monkeypatch):
    configure(monkeypatch)
    engine, _, _, _ = postgres_database
    portfolio, account = seed(engine)
    with engine.connect() as connection:
        raw, fingerprint = connection.execute(text("SELECT iban, iban_fingerprint FROM accounts")).one()
    assert raw.startswith("enc:v1:default:") and IBAN not in raw
    assert current_keyring().decrypt(raw) == IBAN and fingerprint == current_keyring().fingerprint(IBAN)
    configure(monkeypatch, key="", keyring=json.dumps({"default": KEY, "new": OTHER}), active="new")

    def create(_):
        with Session(engine) as session:
            try:
                SQLAlchemyStore(session).create_account(payload(portfolio.id, "de89 3704 0044 0532 0130 00"))
                return True
            except DatabaseOperationError:
                return False

    with ThreadPoolExecutor(2) as pool:
        assert list(pool.map(create, range(2))) == [False, False]
    with Session(engine) as session:
        assert SQLAlchemyStore(session).get_account(account.id).iban == IBAN
    assert engine.pool.checkedout() == 0


def test_pg_separate_restore_proof_atomic_rotation_and_late_rollback(
    postgres_database, postgres_backup_database, monkeypatch
):
    configure(monkeypatch)
    engine, _, _, _ = postgres_database
    restored, _, _, _ = postgres_backup_database
    portfolio, account = seed(engine)
    with engine.connect() as source, restored.begin() as backup:
        for table in (PortfolioORM.__table__, AccountORM.__table__):
            source_rows = source.execute(text(f'SELECT * FROM "{table.name}"')).mappings().all()
            backup.execute(table.insert(), [dict(row) for row in source_rows])
    ring = rotation_keyring()
    proof = create_backup_proof(restored, ring)

    def fail_after_chunk(count):
        raise RuntimeError("Synthetic interruption")

    with pytest.raises(RuntimeError):
        rotate_account_ibans(engine, ring, proof, offline=True, chunks=1, after_chunk=fail_after_chunk)
    with engine.connect() as connection:
        assert inspect_account_encryption(connection, ring)["encrypted_by_key_id"] == {"default": 1}
    assert rotate_account_ibans(engine, ring, proof, offline=True, chunks=1)["updated"] == 1
    configure(monkeypatch, key="", keyring=json.dumps({"default": KEY, "new": OTHER}), active="new")
    with Session(engine) as session:
        assert SQLAlchemyStore(session).get_account(account.id).iban == IBAN
    with engine.connect() as connection:
        assert inspect_account_encryption(connection, current_keyring())["encrypted_by_key_id"] == {"new": 1}
    with pytest.raises(IBANEncryptionError, match="SNAPSHOT_MISMATCH"):
        rotate_account_ibans(engine, ring, proof, offline=True)
    assert engine.pool.checkedout() == restored.pool.checkedout() == 0
