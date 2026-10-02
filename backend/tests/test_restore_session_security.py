"""Real restored SQLite families, old signatures and offline CLI boundaries."""

import json
import os
import shutil
import sqlite3
import subprocess
import sys
import time

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from backend import auth
from backend.services import auth_sessions
from backend.services import full_recovery as recovery
from backend.services.recovery_sessions import (
    SessionRestoreError,
    invalidate_and_inspect,
    rotated_configuration,
    secure_sqlite_restore,
)
from backend.tests.test_account_encryption import IBAN, INDEX, KEY, LEGACY, OTHER, legacy_cipher
from backend.tests.test_full_recovery import PASSPHRASE, ROOT
from backend.tests.test_full_recovery import plan as plan  # noqa: F401 fixture
from backend.tests.test_full_recovery import runtime_template as runtime_template  # noqa: F401 fixture
from backend.tests.test_private_server_concurrency import postgres_database  # noqa: F401 fixture


def test_signing_rotation_preserves_field_keys_and_retains_original_only_as_explicit_legacy_key():
    original = dict(JWT_SECRET_KEY=LEGACY, ENCRYPTION_KEY=KEY, ENCRYPTION_INDEX_KEY=INDEX,
        ENCRYPTION_KEYRING="", ENCRYPTION_ACTIVE_KEY_ID="default", ENCRYPTION_LEGACY_JWT_KEYS='["previous"]')
    current = rotated_configuration(original)
    assert current["JWT_SECRET_KEY"] != original["JWT_SECRET_KEY"]
    assert {k: v for k, v in current.items() if k != "JWT_SECRET_KEY"} == {k: v for k, v in original.items() if k != "JWT_SECRET_KEY"}
    legacy = rotated_configuration(original, legacy_iban_present=True)
    assert json.loads(legacy["ENCRYPTION_LEGACY_JWT_KEYS"]) == ["previous", LEGACY]
    assert legacy["JWT_SECRET_KEY"] != LEGACY
    assert original["ENCRYPTION_LEGACY_JWT_KEYS"] == '["previous"]'


PROBE = r'''
import json, sys
from pathlib import Path
from backend.services.full_recovery import load_recovered_environment
root, new_tokens = Path(sys.argv[1]), Path(sys.argv[2])
load_recovered_environment(root)
from backend.app import app
from backend.config import settings
from fastapi.testclient import TestClient
from scripts.private_server_backup import protected_new_file
old = json.loads(sys.stdin.read())
assert settings.jwt_secret_key != old['signer']
with TestClient(app) as client:
    for token in old['access']:
        assert client.get('/api/v1/auth/me', headers={'Authorization':'Bearer '+token}).status_code == 401
    for token in old['refresh']:
        assert client.post('/api/v1/auth/refresh', json={'refresh_token':token}).status_code == 401
    logged_in = client.post('/api/v1/auth/login', json={'username':'recovery-owner','password':'SyntheticPassword123!'})
    assert logged_in.status_code == 200, logged_in.status_code
    pair = logged_in.json()
    assert client.get('/api/v1/auth/me', headers={'Authorization':'Bearer '+pair['access_token']}).status_code == 200
    listed = client.get('/api/v1/auth/sessions', headers={'Authorization':'Bearer '+pair['access_token']}).json()
    assert sum(row['revoke_reason']=='database_restore' for row in listed['items']) == 2
    assert any(row['revoke_reason']=='explicit_user_revoke' for row in listed['items'])
    with protected_new_file(new_tokens) as output:
        output.write(json.dumps(pair).encode())
print('RESTORED_SESSION_BOUNDARY_OK')
'''

RESTART = r'''
import json, sys
from pathlib import Path
from backend.services.full_recovery import load_recovered_environment
load_recovered_environment(Path(sys.argv[1]))
from backend.app import app
from fastapi.testclient import TestClient
pair = json.loads(sys.stdin.read())
with TestClient(app) as client:
    assert client.get('/api/v1/auth/me', headers={'Authorization':'Bearer '+pair['access_token']}).status_code == 200
    assert client.post('/api/v1/auth/refresh', json={'refresh_token':pair['refresh_token']}).status_code == 200
print('NORMAL_RESTART_SESSION_OK')
'''


def test_source_gone_full_restore_rejects_managed_legacy_and_consumed_tokens_but_normal_restart_keeps_new_family(plan, tmp_path, monkeypatch):
    engine = create_engine("sqlite:///" + plan.database.as_posix())
    factory = sessionmaker(bind=engine, autoflush=False)
    monkeypatch.setattr(auth, "SECRET_KEY", plan.configuration["JWT_SECRET_KEY"])
    monkeypatch.setattr(auth, "_auth_session_factory", factory)
    monkeypatch.setattr(auth, "_user_store", auth.SQLUserStore(factory))
    monkeypatch.setattr(auth, "_token_blacklist", set())
    monkeypatch.setattr(auth, "_blacklist_expiry", {})
    owner = auth.authenticate_user("recovery-owner", "SyntheticPassword123!")
    assert owner is not None
    first = auth_sessions.login_pair(owner["id"])
    rotated = auth_sessions.rotate(first.refresh_token)
    second = auth_sessions.login_pair(owner["id"])
    finished = auth_sessions.login_pair(owner["id"])
    with engine.begin() as db:
        db.exec_driver_sql("UPDATE auth_sessions SET revoked_at=CURRENT_TIMESTAMP, revoke_reason='explicit_user_revoke' WHERE current_refresh_hash=?", (auth_sessions.fingerprint(finished.refresh_token),))
    legacy_access, legacy_refresh = auth.create_access_token(owner["id"]), auth.create_refresh_token(owner["id"])
    archive = tmp_path / "older-session-snapshot.immobak"
    recovery.create_full_backup(plan, archive, PASSPHRASE, offline=True)
    with sqlite3.connect(plan.database) as db:
        receipts = db.execute("SELECT * FROM auth_refresh_tokens ORDER BY token_hash").fetchall()
        assert any(row[-1] is not None for row in receipts)
    db.close()
    # Decisions made AFTER the older snapshot must not be undone by restoring it.
    auth.revoke_token(legacy_access)
    with engine.begin() as db:
        db.exec_driver_sql("UPDATE auth_sessions SET revoked_at=CURRENT_TIMESTAMP, revoke_reason='later_revoke' WHERE revoked_at IS NULL")
    engine.dispose()
    original = plan.database.parent.resolve()
    assert original.is_relative_to(tmp_path.resolve()) and original.name == "source"
    shutil.rmtree(original)
    destination = tmp_path / "restored-session-boundary"
    result = recovery.restore_full_backup(archive, destination, PASSPHRASE)
    assert result["sessions_revoked"] == 2 and result["signing_key_rotated"] is True
    with sqlite3.connect(destination / "database.sqlite3") as db:
        assert db.execute("SELECT * FROM auth_refresh_tokens ORDER BY token_hash").fetchall() == receipts
        assert db.execute("SELECT COUNT(*) FROM auth_sessions WHERE revoked_at IS NULL").fetchone()[0] == 0
    old = dict(signer=plan.configuration["JWT_SECRET_KEY"], access=[first.access_token, rotated.access_token, second.access_token, legacy_access],
        refresh=[first.refresh_token, rotated.refresh_token, second.refresh_token, legacy_refresh])
    tokens = tmp_path / "new-session.json"
    process = subprocess.run([sys.executable, "-c", PROBE, str(destination), str(tokens)], cwd=ROOT,
        input=json.dumps(old), env=os.environ | {"JWT_SECRET_KEY":"foreign-ambient-signer"}, capture_output=True, text=True, timeout=90)
    assert process.returncode == 0, process.stderr
    assert "RESTORED_SESSION_BOUNDARY_OK" in process.stdout
    restarted = subprocess.run([sys.executable, "-c", RESTART, str(destination)], cwd=ROOT,
        input=tokens.read_text(encoding="utf-8"), capture_output=True, text=True, timeout=90)
    assert restarted.returncode == 0, restarted.stderr
    assert "NORMAL_RESTART_SESSION_OK" in restarted.stdout


def test_legacy_iban_ciphertext_and_field_keys_survive_signing_rotation(tmp_path):
    database = tmp_path / "legacy.sqlite"
    values = dict(JWT_SECRET_KEY=LEGACY, ENCRYPTION_KEY=KEY, ENCRYPTION_INDEX_KEY=INDEX, ENCRYPTION_LEGACY_JWT_KEYS="[]")
    encrypted = legacy_cipher()
    with sqlite3.connect(database) as db:
        db.execute("CREATE TABLE accounts(id TEXT PRIMARY KEY, iban TEXT)")
        db.execute("INSERT INTO accounts VALUES (?,?)", ("legacy", encrypted))
    restored, report = secure_sqlite_restore(database, values, deadline=time.monotonic()+30)
    assert report == {"revoked_session_count": 0, "legacy_iban_present": True}
    assert json.loads(restored["ENCRYPTION_LEGACY_JWT_KEYS"]) == [LEGACY]
    from backend.services.iban_encryption import keyring_from_configuration
    assert keyring_from_configuration(restored).decrypt(encrypted) == IBAN
    assert restored["JWT_SECRET_KEY"] != LEGACY and restored["ENCRYPTION_KEY"] == KEY and restored["ENCRYPTION_INDEX_KEY"] == INDEX
    with sqlite3.connect(database) as db:
        assert db.execute("SELECT iban FROM accounts").fetchone()[0] == encrypted


def test_partial_security_schema_refuses_restore_before_any_family_or_field_mutation(tmp_path):
    database = tmp_path / "incomplete.sqlite"
    with sqlite3.connect(database) as db:
        db.execute("CREATE TABLE auth_sessions(id TEXT)")
        db.execute("INSERT INTO auth_sessions VALUES ('retained')")
    with pytest.raises(SessionRestoreError, match="schema_incomplete"):
        secure_sqlite_restore(database, {"JWT_SECRET_KEY": LEGACY}, deadline=time.monotonic()+30)
    with sqlite3.connect(database) as db:
        assert db.execute("SELECT * FROM auth_sessions").fetchall() == [("retained",)]


def session_database(database, cipher=None):
    from backend.db.session_models import ensure_session_schema
    engine = create_engine("sqlite:///" + database.as_posix())
    try:
        with engine.begin() as db:
            ensure_session_schema(db)
            db.exec_driver_sql("INSERT INTO auth_sessions (id, user_id, device_label, created_at, last_used_at, expires_at, generation, current_refresh_hash) "
                "VALUES ('family', 'synthetic-user', 'Synthetic', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, '2099-01-01', 1, 'current')")
            db.exec_driver_sql("INSERT INTO auth_refresh_tokens (token_hash, session_id, generation, expires_at, consumed_at) "
                "VALUES ('consumed', 'family', 0, '2099-01-01', CURRENT_TIMESTAMP)")
            db.exec_driver_sql("CREATE TABLE accounts(id TEXT PRIMARY KEY, iban TEXT)")
            if cipher:
                db.exec_driver_sql("INSERT INTO accounts VALUES (?,?)", ("account", cipher))
    finally:
        engine.dispose()


def test_failure_after_family_update_rolls_back_revocation_and_preserves_receipts(tmp_path):
    database = tmp_path / "rollback.sqlite"
    session_database(database)
    with sqlite3.connect(database) as db:
        before = db.execute("SELECT * FROM auth_refresh_tokens").fetchall()
    # Keyring parsing runs after UPDATE in the same transaction, before commit.
    with pytest.raises(SessionRestoreError, match="legacy_keyring_invalid"):
        secure_sqlite_restore(database, {"JWT_SECRET_KEY": LEGACY, "ENCRYPTION_LEGACY_JWT_KEYS": "not-json"}, deadline=time.monotonic()+30)
    with sqlite3.connect(database) as db:
        assert db.execute("SELECT revoked_at, revoke_reason FROM auth_sessions").fetchall() == [(None, None)]
        assert db.execute("SELECT * FROM auth_refresh_tokens").fetchall() == before


def test_full_pre_session_schema_backup_keeps_legacy_data_and_rotates_signer_without_precreating_migration_tables(plan, tmp_path):
    with sqlite3.connect(plan.database) as db:
        db.execute("DROP TABLE auth_refresh_tokens")
        db.execute("DROP TABLE auth_sessions")
        users_before = db.execute("SELECT * FROM users ORDER BY id").fetchall()
    archive, destination = tmp_path / "pre-session.immobak", tmp_path / "pre-session-restored"
    recovery.create_full_backup(plan, archive, PASSPHRASE, offline=True)
    result = recovery.restore_full_backup(archive, destination, PASSPHRASE)
    assert result["sessions_revoked"] == 0 and result["signing_key_rotated"] is True
    values = json.loads((destination / "configuration.json").read_text(encoding="utf-8"))
    assert values["JWT_SECRET_KEY"] != plan.configuration["JWT_SECRET_KEY"]
    with sqlite3.connect(destination / "database.sqlite3") as db:
        assert db.execute("SELECT * FROM users ORDER BY id").fetchall() == users_before
        tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        assert not tables & {"auth_sessions", "auth_refresh_tokens"}


@pytest.mark.parametrize("problem", [None, "wrong-key", "malformed-json", "misplaced-secret"])
def test_real_offline_cli_uses_private_pipe_preserves_receipts_and_reports_no_secrets(tmp_path, problem):
    from backend.services.iban_encryption import keyring_from_configuration
    values = dict(JWT_SECRET_KEY=LEGACY, ENCRYPTION_KEY=KEY, ENCRYPTION_INDEX_KEY=INDEX)
    database = tmp_path / "offline-cli.sqlite"
    cipher = keyring_from_configuration(values).encrypt(IBAN)
    session_database(database, cipher)
    if problem == "wrong-key":
        values["ENCRYPTION_KEY"] = OTHER
    args = [sys.executable, "-m", "scripts.restore_session_security", "--configuration-stdin"]
    if problem == "misplaced-secret":
        args.extend(["--secret", "SYNTHETIC-MISPLACED-SECRET"])
    env = os.environ | {"DATABASE_URL": "sqlite:///" + database.as_posix(), "JWT_SECRET_KEY": "fresh-restored-signer-" + "f"*48}
    process = subprocess.run(args, cwd=ROOT, env=env, input="malformed" if problem == "malformed-json" else json.dumps(values),
        capture_output=True, text=True, timeout=30)
    for secret in (LEGACY, KEY, INDEX, OTHER, IBAN, "SYNTHETIC-MISPLACED-SECRET"):
        assert secret not in process.stdout + process.stderr
    with sqlite3.connect(database) as db:
        assert db.execute("SELECT COUNT(*) FROM auth_refresh_tokens WHERE consumed_at IS NOT NULL").fetchone()[0] == 1
        assert db.execute("SELECT iban FROM accounts").fetchone()[0] == cipher
        if problem is None:
            assert process.returncode == 0
            assert json.loads(process.stdout) == {"revoked_session_count": 1, "legacy_iban_present": False}
            assert db.execute("SELECT revoke_reason FROM auth_sessions").fetchone()[0] == "database_restore"
        else:
            assert process.returncode != 0
            assert db.execute("SELECT revoked_at FROM auth_sessions").fetchone()[0] is None


def test_pg_offline_restore_streams_ciphertexts_rolls_back_then_revokes_without_dropping_receipts(postgres_database, monkeypatch):  # noqa: F811
    from fastapi import HTTPException
    from sqlalchemy.orm import Session

    from backend.db.session_models import AuthRefreshORM, AuthSessionORM
    from backend.models import PortfolioCreate
    from backend.repositories.sql_store import SQLAlchemyStore
    from backend.tests.test_account_encryption import configure, payload
    configure(monkeypatch)
    engine, factory, *_ = postgres_database
    monkeypatch.setattr(auth, "_user_store", auth.SQLUserStore(factory))
    monkeypatch.setattr(auth, "_auth_session_factory", factory)
    monkeypatch.setattr(auth, "SECRET_KEY", LEGACY)
    monkeypatch.setattr(auth, "_token_blacklist", set())
    monkeypatch.setattr(auth, "_blacklist_expiry", {})
    owner = auth.register_user("restore-owner", "restore@example.test", "Synthetic", "Synthetic restore passphrase123!", "eigentuemer")
    with Session(engine) as db:
        store = SQLAlchemyStore(db)
        portfolio = store.create_portfolio(PortfolioCreate(name="Synthetic restore"))
        account = store.create_account(payload(portfolio.id))
    original = auth_sessions.login_pair(owner.id)
    current = auth_sessions.rotate(original.refresh_token)
    legacy_access = auth.create_access_token(owner.id)
    values = dict(JWT_SECRET_KEY=LEGACY, ENCRYPTION_KEY=KEY, ENCRYPTION_INDEX_KEY=INDEX)
    with engine.connect() as db:
        before = db.execute(select(AuthRefreshORM.__table__)).fetchall()
    with pytest.raises(RuntimeError, match="Synthetic late failure"):
        with engine.begin() as db:
            assert invalidate_and_inspect(db, values, deadline=time.monotonic()+30)["revoked_session_count"] == 1
            raise RuntimeError("Synthetic late failure")
    with engine.connect() as db:
        assert db.execute(select(AuthSessionORM.revoked_at)).scalar_one() is None
        assert db.execute(select(AuthRefreshORM.__table__)).fetchall() == before
    with engine.begin() as db:
        assert invalidate_and_inspect(db, values, deadline=time.monotonic()+30) == {"revoked_session_count": 1, "legacy_iban_present": False}
        assert invalidate_and_inspect(db, values, deadline=time.monotonic()+30)["revoked_session_count"] == 0
    monkeypatch.setattr(auth, "SECRET_KEY", rotated_configuration(values)["JWT_SECRET_KEY"])
    for token in (original.access_token, current.access_token, legacy_access):
        with pytest.raises(HTTPException) as denial:
            auth.decode_token(token)
        assert denial.value.status_code == 401
    with Session(engine) as db:
        assert SQLAlchemyStore(db).get_account(account.id).iban == IBAN
        assert db.execute(select(AuthRefreshORM.__table__)).fetchall() == before
    assert engine.pool.checkedout() == 0
