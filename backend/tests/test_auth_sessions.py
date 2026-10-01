"""Actual refresh replay, independent SQL sessions and own-account boundaries."""

import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta, timezone
from pathlib import Path
from threading import Barrier
from types import SimpleNamespace

import jwt
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session, sessionmaker

from backend import auth, dependencies
from backend.app import app
from backend.db.orm_models import Base, PortfolioORM
from backend.db.session_models import AuthRefreshORM, AuthSessionORM
from backend.models import LoginRequest, Portfolio
from backend.repositories.sql_store import SQLAlchemyStore
from backend.routers.auth import login
from backend.services import auth_sessions as service
from backend.services.portfolio_scope import scope_context, scope_from_user
from backend.storage import InMemoryStore


@pytest.fixture(params=["memory", "sql"])
def security_state(request, tmp_path, monkeypatch):
    monkeypatch.setattr(auth, "_token_blacklist", set())
    monkeypatch.setattr(auth, "_blacklist_expiry", {})
    monkeypatch.setattr(auth, "_login_attempts", {})
    engine = None
    factory = None
    if request.param == "sql":
        engine = create_engine("sqlite:///" + (tmp_path / "private auth.sqlite").as_posix(),
            connect_args={"check_same_thread": False, "timeout": 20})
        @event.listens_for(engine, "connect")
        def pragmas(db, _):
            db.execute("PRAGMA foreign_keys=ON")
            db.execute("PRAGMA journal_mode=WAL")
        Base.metadata.create_all(engine)
        with engine.begin() as db:
            db.execute(PortfolioORM.__table__.insert(), dict(id="selected", name="Synthetic"))
        factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
        monkeypatch.setattr(auth, "_user_store", auth.SQLUserStore(factory))
        monkeypatch.setattr(auth, "_auth_session_factory", factory)
        monkeypatch.setattr(dependencies, "store", SQLAlchemyStore(factory()))
    else:
        monkeypatch.setattr(auth, "_user_store", auth.InMemoryUserStore())
        monkeypatch.setattr(auth, "_auth_session_factory", None)
        monkeypatch.setattr(dependencies, "store", InMemoryStore())
        dependencies.store.portfolios["selected"] = Portfolio(id="selected", name="Synthetic")
    business_store = dependencies.store
    owner = auth.register_user("owner", "owner@example.test", "Synthetic owner", "Strong123", "eigentuemer")
    viewer = auth.register_user("viewer", "viewer@example.test", "Synthetic viewer", "Strong123", "readonly",
        portfolio_access="selected", portfolio_ids=["selected"])
    yield SimpleNamespace(owner=owner, viewer=viewer, factory=factory, engine=engine)
    if factory:
        business_store.db.close()
        engine.dispose()


def status(operation):
    try:
        return operation()
    except HTTPException as error:
        return error.status_code


def race(operation):
    barrier = Barrier(2)
    def run(_):
        barrier.wait(timeout=10)
        return status(operation)
    with ThreadPoolExecutor(2) as pool:
        return list(pool.map(run, range(2)))


def test_rotation_replay_revokes_original_and_rotated_access_but_other_device_survives(security_state):
    user = security_state.viewer.id
    first = service.login_pair(user, "Mozilla Chrome/120 Windows secret-unique-user-agent")
    other_device = service.login_pair(user, "Firefox/130 Linux")
    rotated = service.rotate(first.refresh_token)
    assert auth.decode_token(first.access_token).sub == user
    assert auth.decode_token(rotated.access_token).sub == user
    assert first.refresh_token != rotated.refresh_token
    assert status(lambda: service.rotate(first.refresh_token)) == 401
    for token in (first.access_token, rotated.access_token, rotated.refresh_token):
        assert status(lambda: auth.decode_token(token)) == 401
    assert auth.decode_token(other_device.access_token).sub == user
    assert service.rotate(other_device.refresh_token).access_token
    listed = service.list_sessions(user, auth.decode_token(other_device.access_token).sid)
    assert {row["status"] for row in listed["items"]} == {"active", "revoked"}
    assert next(row for row in listed["items"] if row["status"] == "revoked")["revoke_reason"] == "refresh_reuse"
    assert "secret-unique-user-agent" not in str(listed)


@pytest.mark.parametrize("legacy", [False, True])
def test_parallel_rotation_or_legacy_adoption_has_one_winner_then_revokes_that_family(security_state, legacy):
    first = service.login_pair(security_state.viewer.id)
    token = auth.create_refresh_token(security_state.viewer.id) if legacy else first.refresh_token
    results = race(lambda: service.rotate(token))
    winners = [value for value in results if not isinstance(value, int)]
    assert len(winners) == 1 and results.count(401) == 1
    assert status(lambda: auth.decode_token(winners[0].access_token)) == 401
    assert status(lambda: service.rotate(winners[0].refresh_token)) == 401


def test_legacy_access_keeps_original_expiry_legacy_refresh_is_adopted_once_without_extension(security_state):
    user = security_state.viewer.id
    original_access = auth.create_access_token(user)
    original_refresh = auth.create_refresh_token(user)
    old_exp = auth.decode_token(original_refresh).exp
    adopted = service.rotate(original_refresh, "Edg/124 Windows")
    assert auth.decode_token(adopted.refresh_token).exp == old_exp
    assert auth.decode_token(original_access).sid is None
    assert status(lambda: service.rotate(original_refresh)) == 401
    assert status(lambda: auth.decode_token(adopted.access_token)) == 401
    assert auth.decode_token(original_access).sub == user  # Legacy access cannot be retrospectively grouped.
    bad = jwt.encode({"sub": user, "exp": service.now().replace(tzinfo=timezone.utc) - timedelta(seconds=1),
        "type": "access"}, auth.SECRET_KEY, algorithm=auth.ALGORITHM)
    assert status(lambda: auth.decode_token(bad)) == 401


def test_already_revoked_legacy_refresh_cannot_be_upgraded(security_state):
    token = auth.create_refresh_token(security_state.viewer.id)
    auth.revoke_token(token)
    assert status(lambda: service.rotate(token)) == 401
    assert service.list_sessions(security_state.viewer.id, None)["items"] == []


def test_token_claim_confusion_fails_before_family_lookup(security_state):
    for extra in ({"sid": None, "session_version": None}, {"sid": "fake", "session_version": "1"},
                  {"sid": "fake", "session_version": True}, {"sid": "fake", "session_version": 2},
                  {"sid": "fake"}, {"session_version": 1}):
        token = jwt.encode({"sub": security_state.viewer.id, "exp": service.now().replace(tzinfo=timezone.utc) + timedelta(minutes=1),
            "type": "access", **extra}, auth.SECRET_KEY, algorithm=auth.ALGORITHM)
        assert status(lambda: auth.decode_token(token)) == 401
    assert service.list_sessions(security_state.viewer.id, None)["items"] == []


def test_own_readonly_http_revocation_foreign_404_unauth_401_and_current_token_stops(security_state):
    viewer = service.login_pair(security_state.viewer.id)
    owner = service.login_pair(security_state.owner.id)
    viewer_id, owner_id = auth.decode_token(viewer.access_token).sid, auth.decode_token(owner.access_token).sid
    headers = {"Authorization": "Bearer " + viewer.access_token}
    with TestClient(app) as client:
        assert client.get("/api/v1/auth/sessions").status_code == 401
        assert client.post("/api/v1/auth/sessions/" + viewer_id + "/revoke", json={"confirmed": True}).status_code == 401
        response = client.get("/api/v1/auth/sessions", headers=headers)
        assert response.status_code == 200, response.text
        listed = response.json()
        assert listed["current_session_id"] == viewer_id and listed["items"][0]["current"]
        assert [row["id"] for row in listed["items"]] == [viewer_id]
        assert not {"current_refresh_hash", "legacy_refresh_hash", "user_id"} & listed["items"][0].keys()
        foreign = "/api/v1/auth/sessions/" + owner_id + "/revoke"
        assert client.post(foreign, headers=headers, json={"confirmed": True}).status_code == 404
        path = "/api/v1/auth/sessions/" + viewer_id + "/revoke"
        for payload in ({"confirmed": False}, {"confirmed": "true"}, {"confirmed": True, "user_id": security_state.owner.id}):
            assert client.post(path, headers=headers, json=payload).status_code == 422
        result = client.post(path, headers=headers, json={"confirmed": True})
        assert result.status_code == 200 and result.json()["status"] == "revoked", result.text
        assert client.get("/api/v1/auth/me", headers=headers).status_code == 401
    assert status(lambda: service.rotate(viewer.refresh_token)) == 401
    assert auth.decode_token(owner.access_token).sub == security_state.owner.id


def test_logout_with_only_access_revokes_whole_family(security_state):
    tokens = service.login_pair(security_state.viewer.id)
    auth.revoke_token(tokens.access_token)
    assert auth.is_token_revoked(tokens.access_token)
    assert auth.is_token_revoked(tokens.refresh_token)
    assert status(lambda: service.rotate(tokens.refresh_token)) == 401


def test_disabled_account_cannot_refresh_and_reactivation_does_not_undo_replay_revoke(security_state):
    tokens = service.login_pair(security_state.viewer.id)
    auth.update_user(security_state.viewer.id, {"is_active": False}, actor_id=security_state.owner.id)
    assert status(lambda: service.rotate(tokens.refresh_token)) == 401
    auth.update_user(security_state.viewer.id, {"is_active": True}, actor_id=security_state.owner.id)
    rotated = service.rotate(tokens.refresh_token)
    assert status(lambda: service.rotate(tokens.refresh_token)) == 401
    assert status(lambda: auth.decode_token(rotated.access_token)) == 401


def test_selected_scope_can_read_and_revoke_only_own_security_data(security_state):
    tokens = service.login_pair(security_state.viewer.id)
    own = auth.decode_token(tokens.access_token).sid
    with scope_context(scope_from_user(auth.get_user_by_id(security_state.viewer.id))):
        assert service.list_sessions(security_state.viewer.id, own)["total"] == 1
        assert service.revoke_own(security_state.viewer.id, own, own)["status"] == "revoked"


def test_totp_login_does_not_create_family_before_success(security_state, monkeypatch):
    auth.update_user(security_state.viewer.id, {"totp_secret": auth.generate_totp_secret(), "totp_enabled": True})
    attempt = LoginRequest(username="viewer", password="Strong123")
    assert status(lambda: login(attempt)) == 401
    monkeypatch.setattr("backend.routers.auth.verify_totp", lambda secret, code: code == "123456")
    assert status(lambda: login(attempt.model_copy(update={"totp_code": "999999"}))) == 401
    assert service.list_sessions(security_state.viewer.id, None)["total"] == 0
    tokens = login(attempt.model_copy(update={"totp_code": "123456"}))
    assert auth.decode_token(tokens.access_token).sid
    assert service.rotate(tokens.refresh_token).access_token


def test_sql_durable_fingerprints_restart_and_separate_factory_identity(security_state, tmp_path, monkeypatch):
    if security_state.factory is None:
        pytest.skip("Requires actual SQLite sessions; memory semantics covered separately")
    tokens = service.login_pair(security_state.viewer.id, "Chrome/120 Linux UNIQUE_RAW_AGENT")
    rotated = service.rotate(tokens.refresh_token)
    security_state.engine.dispose()
    replacement = sessionmaker(bind=security_state.engine, autoflush=False, expire_on_commit=False)
    monkeypatch.setattr(auth, "_auth_session_factory", replacement)
    monkeypatch.setattr(auth, "_user_store", auth.SQLUserStore(replacement))
    # A different business database must not become the auth source.
    other = create_engine("sqlite:///" + (tmp_path / "wrong-business.sqlite").as_posix())
    monkeypatch.setattr(dependencies, "store", SimpleNamespace(db=Session(other)))
    try:
        assert auth.decode_token(rotated.access_token).sub == security_state.viewer.id
        assert status(lambda: service.rotate(tokens.refresh_token)) == 401
        with replacement() as db:
            rows = str(db.execute(select(AuthSessionORM.__table__)).all()) + str(db.execute(select(AuthRefreshORM.__table__)).all())
            assert tokens.refresh_token not in rows and rotated.access_token not in rows and "UNIQUE_RAW_AGENT" not in rows
            assert db.scalar(select(AuthSessionORM.revoke_reason)) == "refresh_reuse"
    finally:
        dependencies.store.db.close()
        other.dispose()


def test_unavailable_database_cannot_mint_rotate_or_validate_managed_tokens(security_state, monkeypatch):
    tokens = service.login_pair(security_state.viewer.id)
    def broken():
        raise RuntimeError("synthetic secret database URL must not leak")
    monkeypatch.setattr(auth, "_auth_session_factory", broken)
    for operation in (lambda: service.login_pair(security_state.viewer.id), lambda: service.rotate(tokens.refresh_token),
                      lambda: auth.decode_token(tokens.access_token)):
        with pytest.raises(HTTPException) as error:
            operation()
        assert error.value.status_code == 503 and "secret" not in error.value.detail


def test_unchanged_access_subject_uses_fresh_role_and_grants_after_refresh(security_state):
    tokens = service.login_pair(security_state.viewer.id)
    auth.update_user(security_state.viewer.id, {"role": "techniker"}, actor_id=security_state.owner.id)
    refreshed = service.rotate(tokens.refresh_token)
    with TestClient(app) as client:
        headers = {"Authorization": "Bearer " + refreshed.access_token}
        response = client.get("/api/v1/auth/me", headers=headers)
        assert response.status_code == 200 and response.json()["role"] == "techniker"
        assert response.json()["portfolio_ids"] == ["selected"]
        assert client.post("/api/v1/accounts", json={"name": "Denied"}, headers=headers).status_code == 403


def test_failed_sql_commit_returns_no_pair_and_does_not_consume_previous_refresh(security_state, monkeypatch):
    if security_state.factory is None:
        pytest.skip("Requires an actual SQL commit failure")
    tokens = service.login_pair(security_state.viewer.id)
    class BrokenCommit(Session):
        def commit(self):
            raise RuntimeError("Synthetic private failure")
    broken = sessionmaker(bind=security_state.engine, class_=BrokenCommit)
    with monkeypatch.context() as patch:
        patch.setattr(auth, "_auth_session_factory", broken)
        assert status(lambda: service.rotate(tokens.refresh_token)) == 503
        assert status(lambda: service.login_pair(security_state.viewer.id)) == 503
    listed = service.list_sessions(security_state.viewer.id, None)
    assert listed["total"] == 1
    assert service.rotate(tokens.refresh_token).access_token


def test_access_activity_updates_only_own_family_and_monotonically_after_throttle(security_state, monkeypatch):
    current = service.login_pair(security_state.viewer.id)
    service.login_pair(security_state.owner.id)
    created = service.now()
    monkeypatch.setattr(service, "now", lambda: created + timedelta(seconds=90))
    assert auth.decode_token(current.access_token).sub == security_state.viewer.id
    own = service.list_sessions(security_state.viewer.id, None)["items"][0]
    foreign = service.list_sessions(security_state.owner.id, None)["items"][0]
    assert own["last_used_at"] > foreign["last_used_at"]


def test_real_new_process_uses_persisted_consumption_and_revokes_existing_access(security_state, tmp_path, monkeypatch):
    if security_state.factory is None:
        pytest.skip("Requires persisted SQL state across a real process restart")
    monkeypatch.setattr(auth, "SECRET_KEY", "synthetic-restart-session-key-" + "0" * 32)
    original = service.login_pair(security_state.viewer.id)
    rotated = service.rotate(original.refresh_token)
    security_state.engine.dispose()
    environment = {key: value for key, value in os.environ.items()
        if key.upper() in {"SYSTEMROOT", "WINDIR", "COMSPEC", "PATH", "PATHEXT"}}
    environment.update({"PYTHONPATH": str(Path(__file__).resolve().parents[2]), "PYTHONUTF8": "1",
        "JWT_SECRET_KEY": auth.SECRET_KEY, "PRIVATE_AUTH_DATABASE": str(security_state.engine.url),
        "ENVIRONMENT": "development", "SQLITE_PERSISTENT_STORE": "false", "ALLOW_INMEMORY_FALLBACK": "true"})
    child = r'''
import json, os, sys
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from backend import auth
from backend.services import auth_sessions as service
engine = create_engine(os.environ["PRIVATE_AUTH_DATABASE"])
factory = sessionmaker(bind=engine)
auth._auth_session_factory = factory
auth._user_store = auth.SQLUserStore(factory)
tokens = json.load(sys.stdin)
assert auth.decode_token(tokens["current_access"]).sid
try:
    service.rotate(tokens["consumed_refresh"])
except HTTPException as error:
    assert error.status_code == 401
else:
    raise AssertionError("Consumed refresh accepted")
engine.dispose()
print("SESSION_RESTART_OK")
'''
    completed = subprocess.run([sys.executable, "-c", child], cwd=tmp_path, env=environment,
        input=json.dumps({"current_access": rotated.access_token, "consumed_refresh": original.refresh_token}),
        text=True, encoding="utf-8", capture_output=True, timeout=30, check=False)
    assert completed.returncode == 0, "Synthetic restart failed; private subprocess output suppressed"
    assert completed.stdout.strip() == "SESSION_RESTART_OK"
    assert status(lambda: auth.decode_token(rotated.access_token)) == 401
