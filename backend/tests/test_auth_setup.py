import base64
import hashlib
import hmac
import importlib
import os
import struct
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend import auth
from backend.app import app
from backend.db.access_models import UserAccessORM, UserPortfolioORM
from backend.db.auth_models import AuthSetupORM
from backend.db.orm_models import AuditLogORM, Base, LoginAttemptORM, PortfolioORM, RevokedTokenORM, UserORM
from backend.db.session_models import AuthRefreshORM, AuthSessionORM
from scripts.reset_2fa import reset_totp


@pytest.fixture(params=["memory", "sql"])
def user_store(request, monkeypatch, tmp_path):
    engine = None
    if request.param == "memory":
        store = auth.InMemoryUserStore()
        factory = None
    else:
        engine = create_engine(f"sqlite:///{tmp_path / 'immo_manager.db'}", connect_args={"check_same_thread": False})
        Base.metadata.create_all(engine, tables=[UserORM.__table__, AuthSetupORM.__table__, LoginAttemptORM.__table__, RevokedTokenORM.__table__, AuditLogORM.__table__,
                                                PortfolioORM.__table__, UserAccessORM.__table__, UserPortfolioORM.__table__,
                                                AuthSessionORM.__table__, AuthRefreshORM.__table__])
        factory = sessionmaker(bind=engine)
        store = auth.SQLUserStore(factory)
    monkeypatch.setattr(auth, "_user_store", store)
    monkeypatch.setattr(auth, "_auth_session_factory", factory)
    auth._login_attempts.clear()
    yield store
    auth._login_attempts.clear()
    if engine is not None:
        engine.dispose()


@pytest.fixture
def local_client(user_store):
    with TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 50000)) as client:
        yield client


def owner_payload(index=0):
    return {"username": f"owner{index}", "email": f"owner{index}@example.com", "full_name": "Installation Owner", "password": "Strong123"}


def login_headers(client, username="owner0"):
    response = client.post("/api/v1/auth/login", json={"username": username, "password": "Strong123"})
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def totp(secret):
    key = base64.b32decode(secret)
    digest = hmac.new(key, struct.pack(">Q", int(time.time()) // 30), hashlib.sha1).digest()
    offset = digest[-1] & 15
    return str((struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF) % 1000000).zfill(6)


def test_local_setup_creates_owner_once_and_registration_is_closed(local_client, user_store):
    assert local_client.get("/api/v1/auth/setup-status").json()["setup_required"] is True
    created = local_client.post("/api/v1/auth/setup", json=owner_payload())
    assert created.status_code == 201
    assert created.json()["role"] == "eigentuemer"
    assert "hashed_password" not in created.json()
    assert local_client.get("/api/v1/auth/setup-status").json()["setup_required"] is False
    assert local_client.post("/api/v1/auth/setup", json=owner_payload(1)).status_code == 409
    assert local_client.post("/api/v1/auth/register", json=owner_payload(2)).status_code == 403
    # The final active owner must survive; setup still stays permanently closed.
    with pytest.raises(HTTPException) as protected:
        user_store.delete(created.json()["id"])
    assert protected.value.status_code == 409
    assert not user_store.setup_required()
    assert local_client.post("/api/v1/auth/setup", json=owner_payload(3)).status_code == 409


def test_concurrent_setup_has_one_successful_initial_owner(local_client, user_store):
    barrier = Barrier(4)

    def setup(index):
        barrier.wait()
        return local_client.post("/api/v1/auth/setup", json=owner_payload(index)).status_code

    with ThreadPoolExecutor(max_workers=4) as pool:
        statuses = list(pool.map(setup, range(4)))
    assert sorted(statuses) == [201, 409, 409, 409]
    assert len(user_store.list_all()) == 1
    assert user_store.list_all()[0]["role"] == "eigentuemer"


def test_remote_peer_and_foreign_host_or_origin_cannot_setup(local_client, user_store):
    with TestClient(app, base_url="http://127.0.0.1", client=("203.0.113.12", 50000)) as remote:
        assert remote.get("/api/v1/auth/setup-status").json()["setup_allowed"] is False
        assert remote.post("/api/v1/auth/setup", json=owner_payload()).status_code == 403
    for headers in [{"Host": "evil.example"}, {"Origin": "https://evil.example"}, {"Origin": "null"}]:
        assert local_client.post("/api/v1/auth/setup", json=owner_payload(), headers=headers).status_code == 403
    assert user_store.setup_required()


def test_only_owner_approves_accounts_and_assigns_roles(local_client):
    assert local_client.post("/api/v1/auth/setup", json=owner_payload()).status_code == 201
    headers = login_headers(local_client)
    assert local_client.post("/api/v1/auth/users", json=owner_payload(1)).status_code == 401
    reader = local_client.post("/api/v1/auth/users", json=owner_payload(1), headers=headers)
    assert reader.status_code == 201
    assert reader.json()["role"] == "readonly"
    reader_headers = login_headers(local_client, "owner1")
    assert local_client.post("/api/v1/auth/users", json=owner_payload(2), headers=reader_headers).status_code == 403
    manager = {**owner_payload(3), "role": "verwalter"}
    assert local_client.post("/api/v1/auth/users", json=manager, headers=headers).status_code == 201
    assert local_client.post("/api/v1/auth/users", json=owner_payload(4), headers=login_headers(local_client, "owner3")).status_code == 403


def test_two_factor_enrollment_preserves_secret_and_disable_clears_it(local_client, user_store):
    owner = local_client.post("/api/v1/auth/setup", json=owner_payload()).json()
    headers = login_headers(local_client)
    pending = local_client.post("/api/v1/auth/2fa/setup", headers=headers).json()
    assert pending["uri"].startswith("otpauth://totp/")
    assert local_client.post("/api/v1/auth/2fa/setup", headers=headers).json()["secret"] == pending["secret"]
    assert local_client.post("/api/v1/auth/2fa/verify", headers=headers, json={"code": "wrong"}).status_code == 400
    assert local_client.get("/api/v1/auth/2fa/status", headers=headers).json() == {"enabled": False}
    assert local_client.post("/api/v1/auth/2fa/verify", headers=headers, json={"code": totp(pending["secret"])}).status_code == 200
    assert local_client.post("/api/v1/auth/2fa/setup", headers=headers).status_code == 409
    assert user_store.get_by_id(owner["id"])["totp_secret"] == pending["secret"]
    required = local_client.post("/api/v1/auth/login", json={"username": "owner0", "password": "Strong123"})
    assert required.status_code == 401
    assert required.headers["X-2FA-Required"] == "true"
    assert local_client.post("/api/v1/auth/2fa/disable", headers=headers, json={"code": "wrong"}).status_code == 400
    assert local_client.post("/api/v1/auth/2fa/disable", headers=headers, json={"code": totp(pending["secret"])}).status_code == 200
    assert user_store.get_by_id(owner["id"])["totp_secret"] is None
    assert local_client.post("/api/v1/auth/login", json={"username": "owner0", "password": "Strong123"}).status_code == 200


def test_bad_totp_codes_trigger_lockout_despite_correct_password(local_client):
    local_client.post("/api/v1/auth/setup", json=owner_payload())
    headers = login_headers(local_client)
    pending = local_client.post("/api/v1/auth/2fa/setup", headers=headers).json()
    local_client.post("/api/v1/auth/2fa/verify", headers=headers, json={"code": totp(pending["secret"])})
    for _ in range(auth.MAX_LOGIN_ATTEMPTS):
        response = local_client.post("/api/v1/auth/login", json={"username": "owner0", "password": "Strong123", "totp_code": "invalid"})
        assert response.status_code == 401
    blocked = local_client.post("/api/v1/auth/login", json={"username": "owner0", "password": "Strong123", "totp_code": totp(pending["secret"])})
    assert blocked.status_code == 429


def test_readonly_can_enroll_own_two_factor_without_business_writes(local_client):
    local_client.post("/api/v1/auth/setup", json=owner_payload())
    headers = login_headers(local_client)
    local_client.post("/api/v1/auth/users", json=owner_payload(1), headers=headers)
    reader_headers = login_headers(local_client, "owner1")
    pending = local_client.post("/api/v1/auth/2fa/setup", headers=reader_headers)
    assert pending.status_code == 200
    assert local_client.post("/api/v1/auth/2fa/verify", headers=reader_headers, json={"code": totp(pending.json()["secret"])}).status_code == 200
    assert local_client.post("/api/v1/portfolios", headers=reader_headers, json={"name": "Forbidden"}).status_code == 403


def test_offline_recovery_changes_only_the_recorded_account_and_audits(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'immo_manager.db'}")
    Base.metadata.create_all(engine, tables=[UserORM.__table__, AuthSetupORM.__table__, AuditLogORM.__table__,
                                            PortfolioORM.__table__, UserAccessORM.__table__, UserPortfolioORM.__table__])
    factory = sessionmaker(bind=engine)
    store = auth.SQLUserStore(factory)
    users = []
    for index in range(2):
        data = {"id": f"account-{index}", "username": f"user{index}", "email": f"u{index}@example.com", "full_name": "User", "hashed_password": "unchanged", "role": "readonly", "totp_secret": "ABCDEF", "totp_enabled": True}
        store.create(data)
        users.append(data)
    reset_totp(tmp_path, "account-0", "Lost device verified locally")
    assert store.get_by_id("account-0")["totp_secret"] is None
    assert store.get_by_id("account-0")["totp_enabled"] is False
    assert store.get_by_id("account-1")["totp_secret"] == "ABCDEF"
    assert store.get_by_id("account-1")["totp_enabled"] is True
    with factory() as session:
        audit = session.query(AuditLogORM).one()
        assert audit.entity_id == "account-0"
        assert "Lost device verified locally" in audit.changes
    with pytest.raises(ValueError):
        reset_totp(tmp_path, "unknown", "Wrong account")
    engine.dispose()


def test_fresh_source_startup_registers_the_auth_table_before_database_creation(tmp_path):
    result = subprocess.run(
        [sys.executable, "-c", "from backend.app import app; from backend.auth import setup_required; from backend.db.session import engine; from sqlalchemy import inspect; assert 'auth_setup' in inspect(engine).get_table_names(); assert setup_required(); print('Fresh owner setup available')"],
        cwd=Path(__file__).resolve().parents[2],
        env={**os.environ, "DATABASE_URL": f"sqlite:///{(tmp_path / 'fresh.db').as_posix()}",
             "DATA_DIR": str(tmp_path), "SQLITE_PERSISTENT_STORE": "true", "ALLOW_INMEMORY_FALLBACK": "false", "AI_ENABLED": "false", "AUTO_SEED_DEMO_DATA": "false", "ENVIRONMENT": "development", "PYTHONUTF8": "1"},
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert "Fresh owner setup available" in result.stdout


@pytest.mark.parametrize("has_existing_user", [False, True])
def test_auth_migration_marks_existing_users_and_keeps_empty_installation_open(tmp_path, has_existing_user):
    engine = create_engine(f"sqlite:///{tmp_path / 'migration.db'}")
    Base.metadata.create_all(engine, tables=[UserORM.__table__])
    with engine.begin() as connection:
        if has_existing_user:
            connection.execute(UserORM.__table__.insert().values(id="legacy", username="legacy", email="legacy@example.com", full_name="Legacy", hashed_password="unchanged", role="readonly"))
        migration = importlib.import_module("backend.db.migrations.versions.e9f0a1b2c3d4_close_initial_owner_setup")
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
    Base.metadata.create_all(engine, tables=[PortfolioORM.__table__, UserAccessORM.__table__, UserPortfolioORM.__table__])
    store = auth.SQLUserStore(sessionmaker(bind=engine))
    assert store.setup_required() is not has_existing_user
    if has_existing_user:
        store.delete("legacy")
        assert store.setup_required() is False
    engine.dispose()
