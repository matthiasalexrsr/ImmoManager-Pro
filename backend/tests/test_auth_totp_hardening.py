"""Account-bound factor throttling uses only an isolated synthetic account."""

import base64
import hashlib
import hmac
import os
import struct
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import cast
from unittest.mock import MagicMock

import jwt
import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import Table, create_engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import sessionmaker

from backend import auth
from backend.routers.auth import router
from backend.services import auth_factor

SECRET = "JBSWY3DPEHPK3PXP"
PASSWORD = "Birke7Fenster"


def code_at(counter):
    digest = hmac.new(base64.b32decode(SECRET), struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 15
    return str((struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7fffffff) % 1_000_000).zfill(6)


def wrong_code():
    counter = int(time.time()) // 30
    valid = {code_at(counter + offset) for offset in (-1, 0, 1)}
    return next(str(value).zfill(6) for value in range(10) if str(value).zfill(6) not in valid)


@pytest.fixture
def factor():
    auth.clear_users()
    user = auth.register_user("factor-check", "factor@example.invalid", "Factor Check", PASSWORD, "eigentuemer")
    auth.update_totp(user.id, expected_secret=None, expected_enabled=False, secret=SECRET, enabled=True)
    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    with TestClient(app) as client:
        yield client, user
    auth.clear_users()


def test_correct_password_does_not_reset_failed_second_factor_budget(factor):
    client, _ = factor
    for attempt in range(auth.MAX_LOGIN_ATTEMPTS):
        # Username/e-mail are the same account, not independent OTP budgets.
        name = "factor-check" if attempt % 2 else "FACTOR@example.invalid"
        response = client.post("/api/v1/auth/login", json={
            "username": name, "password": PASSWORD, "totp_code": wrong_code(),
        })
        assert response.status_code == 401
    response = client.post("/api/v1/auth/login", json={
        "username": "factor-check", "password": PASSWORD,
        "totp_code": code_at(int(time.time()) // 30),
    })
    assert response.status_code == 429
    assert "access_token" not in response.json()


def test_email_alias_case_does_not_multiply_password_budget(factor):
    client, _ = factor
    names = ["factor-check", "factor@example.invalid", "Factor@example.invalid",
             "FACTOR@example.invalid", "fAcToR@example.invalid"]
    for name in names:
        response = client.post("/api/v1/auth/login", json={"username": name, "password": "Wrong7Guess"})
        assert response.status_code == 401
    response = client.post("/api/v1/auth/login", json={"username": "factor-check", "password": PASSWORD})
    assert response.status_code == 429


@pytest.mark.parametrize("action", ["verify", "disable"])
def test_second_factor_management_is_rate_limited_per_account(factor, action):
    client, user = factor
    if action == "verify":
        auth.update_totp(user.id, expected_secret=SECRET, expected_enabled=True, secret=SECRET, enabled=False)
    headers = {"Authorization": "Bearer " + auth.create_access_token(user.id)}
    for _ in range(auth.MAX_LOGIN_ATTEMPTS):
        response = client.post(f"/api/v1/auth/2fa/{action}", headers=headers, json={"code": wrong_code()})
        assert response.status_code == 400
    response = client.post(f"/api/v1/auth/2fa/{action}", headers=headers,
                           json={"code": code_at(int(time.time()) // 30)})
    assert response.status_code == 429
    account = auth.get_user_by_id(user.id)
    assert account is not None
    assert account["totp_enabled"] is (action == "disable")


def test_success_resets_only_its_account_factor_budget(factor):
    client, user = factor
    for _ in range(2):
        assert client.post("/api/v1/auth/login", json={"username": "factor-check", "password": PASSWORD,
                                                     "totp_code": wrong_code()}).status_code == 401
    assert client.post("/api/v1/auth/login", json={"username": "factor-check", "password": PASSWORD,
                                                 "totp_code": code_at(int(time.time()) // 30)}).status_code == 200
    assert auth_factor._key(user.id) not in auth_factor._memory
    headers = {"Authorization": "Bearer " + auth.create_access_token(user.id)}
    for _ in range(auth_factor.MAX_ATTEMPTS):
        assert client.post("/api/v1/auth/2fa/disable", headers=headers, json={"code": wrong_code()}).status_code == 400
    assert client.post("/api/v1/auth/login", json={"username": "factor-check", "password": PASSWORD,
                                                 "totp_code": code_at(int(time.time()) // 30)}).status_code == 429


def test_successful_login_code_cannot_open_a_second_session(factor):
    client, _ = factor
    payload = {"username": "factor-check", "password": PASSWORD, "totp_code": code_at(int(time.time()) // 30)}
    assert client.post("/api/v1/auth/login", json=payload).status_code == 200
    repeated = client.post("/api/v1/auth/login", json=payload)
    assert repeated.status_code == 401
    assert "access_token" not in repeated.json()


@pytest.mark.parametrize("secret", [None, "PRIVATE-INVALID-BASE32-SECRET"])
def test_enabled_but_missing_or_invalid_secret_fails_closed(factor, secret):
    client, user = factor
    auth.update_totp(user.id, expected_secret=SECRET, expected_enabled=True, secret=secret, enabled=True)
    response = client.post("/api/v1/auth/login", json={"username": "factor-check", "password": PASSWORD,
                                                     "totp_code": "123456"})
    assert response.status_code == 503
    assert "access_token" not in response.json()
    assert "PRIVATE-INVALID" not in response.text


@pytest.mark.parametrize("token_type", ["expired", "refresh"])
def test_invalid_management_session_cannot_consume_factor_attempts(factor, token_type):
    client, user = factor
    token = auth.create_refresh_token(user.id)
    if token_type == "expired":
        token = jwt.encode({"sub": user.id, "type": "access", "jti": "synthetic-expired-factor-test",
                            "exp": datetime.now(timezone.utc) - timedelta(seconds=1)}, auth.SECRET_KEY, algorithm=auth.ALGORITHM)
    response = client.post("/api/v1/auth/2fa/disable", headers={"Authorization": "Bearer " + token},
                           json={"code": wrong_code()})
    assert response.status_code == 401
    assert auth_factor._key(user.id) not in auth_factor._memory


@pytest.fixture(params=["memory", "sqlite"])
def quota(request, tmp_path, monkeypatch):
    auth_factor.clear_memory()
    engine = None
    factory = None
    if request.param == "sqlite":
        engine = create_engine("sqlite:///" + (tmp_path / "own-factor-quota.db").as_posix())
        from backend.db.access_models import RegistrationQuotaORM
        cast(Table, RegistrationQuotaORM.__table__).create(engine)
        factory = sessionmaker(bind=engine)
    monkeypatch.setattr(auth, "_auth_session_factory", factory)
    yield request.param
    if engine is not None:
        engine.dispose()
    auth_factor.clear_memory()


def test_factor_quota_serializes_competing_attempts(quota):
    def attempt(_):
        try:
            auth_factor.reserve("own-synthetic-account")
            return 200
        except HTTPException as error:
            return error.status_code

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(attempt, range(16)))
    assert results.count(200) == 5
    assert results.count(429) == 11


def test_factor_quota_expires_resets_and_is_account_bound(quota, monkeypatch):
    monkeypatch.setattr(auth_factor, "_now", lambda: 2000.0)
    for _ in range(5):
        auth_factor.reserve("own-first-account")
    with pytest.raises(HTTPException) as failure:
        auth_factor.reserve("own-first-account")
    assert failure.value.status_code == 429
    auth_factor.reserve("own-other-account")
    monkeypatch.setattr(auth_factor, "_now", lambda: 2901.0)
    auth_factor.reserve("own-first-account")
    auth_factor.complete("own-first-account", secret=SECRET, counter=96)
    for _ in range(5):
        auth_factor.reserve("own-first-account")


@pytest.mark.parametrize("operation", ["open", "read", "commit", "rollback"])
@pytest.mark.parametrize("action", ["reserve", "complete"])
def test_factor_quota_storage_failure_is_controlled_and_private(monkeypatch, caplog, operation, action):
    failure = SQLAlchemyError("PRIVATE-FACTOR-STORAGE-SECRET")
    session = MagicMock()
    session.get_bind.return_value.dialect.name = "sqlite"
    session.execute.return_value.scalar_one.return_value.attempts = []
    factory = MagicMock(return_value=session)
    if operation == "open":
        factory.side_effect = failure
    elif operation == "commit":
        session.commit.side_effect = failure
    else:
        session.execute.side_effect = failure
        if operation == "rollback":
            session.rollback.side_effect = failure
    monkeypatch.setattr(auth, "_auth_session_factory", factory)
    with pytest.raises(HTTPException) as error:
        if action == "complete":
            auth_factor.complete("own-synthetic-account", secret=SECRET, counter=1)
        else:
            auth_factor.reserve("own-synthetic-account")
    assert error.value.status_code == 503
    assert "PRIVATE-FACTOR" not in str(error.value.detail)
    assert "PRIVATE-FACTOR" not in caplog.text


def test_consumed_code_is_shared_by_management_and_login(factor, monkeypatch):
    client, user = factor
    counter = int(time.time()) // 30
    monkeypatch.setattr(auth, "_totp_now", lambda: counter * 30 + 5)
    headers = {"Authorization": "Bearer " + auth.create_access_token(user.id)}
    auth.update_totp(user.id, expected_secret=SECRET, expected_enabled=True, secret=SECRET, enabled=False)
    assert client.post("/api/v1/auth/2fa/verify", headers=headers, json={"code": code_at(counter)}).status_code == 200
    assert client.post("/api/v1/auth/login", json={"username": "factor-check", "password": PASSWORD,
                                                 "totp_code": code_at(counter)}).status_code == 401
    assert client.post("/api/v1/auth/2fa/disable", headers=headers,
                       json={"code": code_at(counter)}).status_code == 400
    # The subsequent real step is usable; a previous/future-window replay is not.
    monkeypatch.setattr(auth, "_totp_now", lambda: (counter + 1) * 30 + 5)
    assert client.post("/api/v1/auth/2fa/disable", headers=headers,
                       json={"code": code_at(counter + 1)}).status_code == 200


def test_expired_factor_code_does_not_authenticate(factor, monkeypatch):
    client, _ = factor
    counter = int(time.time()) // 30
    monkeypatch.setattr(auth, "_totp_now", lambda: counter * 30 + 5)
    response = client.post("/api/v1/auth/login", json={"username": "factor-check", "password": PASSWORD,
                                                     "totp_code": code_at(counter - 2)})
    assert response.status_code == 401
    assert "access_token" not in response.json()


def test_counter_claim_is_atomic_and_cannot_move_backwards(quota):
    def claim(_):
        try:
            auth_factor.complete("own-synthetic-account", secret=SECRET, counter=100)
            return "claimed"
        except auth_factor.FactorReplay:
            return "replay"

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(claim, range(16)))
    assert results.count("claimed") == 1
    assert results.count("replay") == 15
    for step in [99, 100]:
        with pytest.raises(auth_factor.FactorReplay):
            auth_factor.complete("own-synthetic-account", secret=SECRET.lower(), counter=step)
    auth_factor.complete("own-synthetic-account", secret=SECRET, counter=101)
    auth_factor.complete("own-other-account", secret=SECRET, counter=100)
    auth_factor.complete("own-synthetic-account", secret="KRSXG5DSNFXGOIDB", counter=100)


def test_quota_and_replay_claim_survive_competing_independent_processes(tmp_path):
    """Real own Python children, a fresh SQLite table and bounded start gates."""
    import json

    from backend.db.access_models import RegistrationQuotaORM

    path = tmp_path / "process-quota.db"
    engine = create_engine("sqlite:///" + path.as_posix())
    cast(Table, RegistrationQuotaORM.__table__).create(engine)
    engine.dispose()
    script = tmp_path / "quota-child.py"
    script.write_text('''import json,sys,time
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from fastapi import HTTPException
from backend import auth
from backend.services import auth_factor
engine=create_engine('sqlite:///'+sys.argv[1])
auth._auth_session_factory=sessionmaker(engine)
Path(sys.argv[3]).write_text('ready',encoding='ascii')
deadline=time.monotonic()+15
while not Path(sys.argv[2]).exists():
 if time.monotonic()>deadline: raise TimeoutError('Own start gate expired')
 time.sleep(.01)
out=[]
for _ in range(8):
 try:
  if sys.argv[4]=='reserve': auth_factor.reserve('synthetic-process-account')
  else: auth_factor.complete('synthetic-process-account',secret='JBSWY3DPEHPK3PXP',counter=100)
  out.append(200)
 except auth_factor.FactorReplay: out.append(401)
 except HTTPException as error: out.append(error.status_code)
print(json.dumps(out),flush=True)
engine.dispose()
''', encoding="utf-8")
    for mode, successful, rejected in [("reserve", 5, 429), ("claim", 1, 401)]:
        gate = tmp_path / (mode + "-start")
        ready = [tmp_path / (mode + f"-ready-{i}") for i in range(2)]
        children = [subprocess.Popen([sys.executable, str(script), path.as_posix(), str(gate), str(mark), mode],
                                    cwd=Path(__file__).resolve().parents[2], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                    stdin=subprocess.DEVNULL, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                                    env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[2])})
                    for mark in ready]
        try:
            deadline = time.monotonic() + 20
            while not all(mark.exists() for mark in ready):
                assert all(child.poll() is None for child in children), "An owned quota child stopped before its gate"
                assert time.monotonic() < deadline, "Owned quota children did not reach their start gate"
                time.sleep(.02)
            gate.write_text("start", encoding="ascii")
            outcomes: list[int] = []
            for child in children:
                stdout, _ = child.communicate(timeout=20)
                assert child.returncode == 0, "An owned quota child failed"
                outcomes.extend(json.loads(stdout))
            assert outcomes.count(200) == successful
            assert outcomes.count(rejected) == 16 - successful
        finally:
            for child in children:
                if child.poll() is None:
                    child.kill()
                child.communicate(timeout=5)
