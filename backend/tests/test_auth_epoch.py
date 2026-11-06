"""Only fresh own profile fences and synthetic JWTs; no existing profiles."""

import hashlib
import json
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from backend import auth, paths
from backend.routers import auth as routes
from backend.services import auth_epoch
from backend.services.secret_box import SecretBox


@pytest.fixture
def profile(tmp_path, monkeypatch):
    monkeypatch.setattr(paths, "get_data_dir", lambda: tmp_path)
    auth.clear_users()
    user = auth.register_user("epoch-own", "epoch@example.invalid", "Own epoch fixture", "Birke7Fenster", "eigentuemer")
    app = FastAPI()
    app.include_router(routes.router, prefix="/api/v1")
    with TestClient(app) as client:
        yield tmp_path, user, client
    auth.clear_users()


@pytest.mark.parametrize("family", [False, True])
@pytest.mark.parametrize("kind", ["access", "refresh"])
def test_restore_fence_rejects_pre_restore_and_legacy_tokens(profile, family, kind):
    root, user, _ = profile
    issue = getattr(auth, "create_" + kind + "_token")
    token = issue(user.id, "own-epoch-family" if family else None)
    assert auth.decode_token(token).sub == user.id
    auth_epoch.rotate_for_restore(root)
    with pytest.raises(HTTPException) as failure:
        auth.decode_token(token)
    assert failure.value.status_code == 401
    current = issue(user.id, "own-fresh-epoch-family" if family else None)
    assert auth.decode_token(current).sub == user.id
    auth_epoch.rotate_for_restore(root)
    with pytest.raises(HTTPException) as failure:
        auth.decode_token(current)
    assert failure.value.status_code == 401


@pytest.mark.parametrize("body", [b"", b"not-json", b"[]", b'{"version":true,"epoch":"' + b'a' * 64 + b'"}',
                                  b'{"version":1,"epoch":7}', b'{"version":1,"epoch":"not-an-epoch"}', b'x' * 513])
def test_corrupt_or_oversized_profile_fence_never_falls_back_to_legacy(profile, body):
    root, user, _ = profile
    token = auth.create_access_token(user.id)
    path = auth_epoch.path_for(root)
    path.parent.mkdir()
    path.write_bytes(body)
    for action in [lambda: auth.decode_token(token), lambda: auth.create_access_token(user.id)]:
        with pytest.raises(HTTPException) as failure:
            action()
        assert failure.value.status_code == 503
        assert "not-an-epoch" not in str(failure.value.detail)


def test_fenced_token_is_not_accepted_by_an_unfenced_other_profile(profile, tmp_path, monkeypatch):
    root, user, _ = profile
    auth_epoch.rotate_for_restore(root)
    token = auth.create_access_token(user.id)
    other = tmp_path / "other-profile"
    other.mkdir()
    monkeypatch.setattr(paths, "get_data_dir", lambda: other)
    with pytest.raises(HTTPException) as failure:
        auth.decode_token(token)
    assert failure.value.status_code == 401


@pytest.mark.parametrize("operation", ["login", "refresh"])
def test_inflight_login_or_refresh_cannot_cross_profile_rotation(profile, monkeypatch, operation):
    root, user, client = profile
    auth_epoch.rotate_for_restore(root)
    old_refresh = auth.create_refresh_token(user.id, "own-inflight-family")
    reached, resume = Event(), Event()
    issue = routes.create_access_token

    def paused(*args, **kwargs):
        reached.set()
        assert resume.wait(10), "Own issuing gate expired"
        return issue(*args, **kwargs)

    monkeypatch.setattr(routes, "create_access_token", paused)
    with ThreadPoolExecutor(max_workers=1) as pool:
        if operation == "login":
            pending = pool.submit(client.post, "/api/v1/auth/login", json={"username": user.username, "password": "Birke7Fenster"})
        else:
            pending = pool.submit(client.post, "/api/v1/auth/refresh", json={"refresh_token": old_refresh})
        try:
            assert reached.wait(10), "Own login/refresh did not reach its issuing gate"
            auth_epoch.rotate_for_restore(root)
        finally:
            resume.set()
        result = pending.result(timeout=15)
    assert result.status_code == 401
    assert "access_token" not in result.json() and "set-cookie" not in result.headers


def test_profile_rotation_preserves_aes_keyring_and_sealed_data(profile):
    root, _, _ = profile
    keyring = root / "own-keyring.json"
    box = SecretBox(keyring)
    sealed = box.seal("Own private fixture", "own-context")
    previous = hashlib.sha256(keyring.read_bytes()).hexdigest()
    result = auth_epoch.rotate_for_restore(root)
    assert result["status"] == "rotated"
    assert hashlib.sha256(keyring.read_bytes()).hexdigest() == previous
    assert box.open(sealed, "own-context") == "Own private fixture"
    record = json.loads(auth_epoch.path_for(root).read_bytes())
    assert set(record) == {"version", "epoch"} and len(record["epoch"]) == 64


def test_profile_fence_read_failure_is_private_and_fail_closed(profile, monkeypatch, caplog):
    root, user, _ = profile
    token = auth.create_access_token(user.id)
    auth_epoch.rotate_for_restore(root)
    monkeypatch.setattr(auth_epoch, "filesystem_path", lambda _: (_ for _ in ()).throw(PermissionError("PRIVATE-EPOCH-PATH")))
    with pytest.raises(HTTPException) as failure:
        auth.decode_token(token)
    assert failure.value.status_code == 503
    assert "PRIVATE-EPOCH" not in str(failure.value.detail) + caplog.text


def test_restored_session_inventory_closes_in_caller_transaction():
    with sqlite3.connect(":memory:") as connection:
        assert auth_epoch.close_restored_sessions(connection) == 0
        connection.execute("CREATE TABLE daily_auth_sessions(id TEXT,revision INTEGER,revoked_at TEXT)")
        connection.execute("INSERT INTO daily_auth_sessions VALUES('own-active',1,NULL)")
        connection.execute("INSERT INTO daily_auth_sessions VALUES('own-revoked',2,'previous')")
        connection.commit()
        assert auth_epoch.close_restored_sessions(connection) == 1
        assert connection.execute("SELECT revision FROM daily_auth_sessions WHERE id='own-active'").fetchone() == (2,)
        assert connection.execute("SELECT revoked_at FROM daily_auth_sessions WHERE id='own-revoked'").fetchone() == ('previous',)
        connection.rollback()
        assert connection.execute("SELECT revoked_at FROM daily_auth_sessions WHERE id='own-active'").fetchone() == (None,)


def test_unknown_restored_session_shape_is_refused():
    with sqlite3.connect(":memory:") as connection:
        connection.execute("CREATE TABLE daily_auth_sessions(id TEXT)")
        with pytest.raises(auth_epoch.EpochUnavailable):
            auth_epoch.close_restored_sessions(connection)
