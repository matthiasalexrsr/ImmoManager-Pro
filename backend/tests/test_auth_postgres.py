"""Native authentication proof: distinct processes, restart and competing refresh claims."""

import os
import secrets
import subprocess
import sys
import time
from pathlib import Path
from typing import cast
from uuid import uuid4

import pytest
from sqlalchemy import Table, create_engine
from sqlalchemy.engine import make_url

from backend import auth
from backend.db.orm_models import RevokedTokenORM
from tools.xstress.processes import start_owned, stop_owned

_CHILD = r'''
import os, sys, time
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from fastapi import HTTPException
from backend import auth
engine = create_engine(os.environ['DATABASE_URL'])
auth._auth_session_factory = sessionmaker(bind=engine)
token = os.environ['IMMO_TEST_AUTH_TOKEN']
mode = os.environ['IMMO_TEST_AUTH_MODE']
try:
    if mode == 'revoke':
        auth.revoke_token(token)
        print('revoked', flush=True)
    elif mode == 'check':
        try:
            auth.decode_token(token)
            print('valid', flush=True)
        except HTTPException as error:
            print('revoked' if error.status_code == 401 else 'unexpected-status', flush=True)
    elif mode == 'claim':
        auth.decode_token(token)
        root = Path(os.environ['IMMO_TEST_BARRIER'])
        (root / ('ready-' + str(os.getpid()))).write_text('ready', encoding='utf-8')
        deadline = time.monotonic() + 30
        while not (root / 'release').exists():
            if time.monotonic() >= deadline:
                raise TimeoutError
            time.sleep(.02)
        try:
            auth.revoke_token(token, require_unrevoked=True)
            print('claimed', flush=True)
        except HTTPException as error:
            print('revoked' if error.status_code == 401 else 'unexpected-status', flush=True)
    else:
        raise ValueError
except Exception as error:
    # Never place token values, connection URLs or SQL parameters into test logs.
    print('failure:' + type(error).__name__, flush=True)
    sys.exit(3)
finally:
    engine.dispose()
'''


@pytest.fixture
def native_auth(tmp_path, monkeypatch):
    configured = os.environ.get("IMMO_TEST_POSTGRES_ADMIN_URL")
    if not configured:
        pytest.skip("set IMMO_TEST_POSTGRES_ADMIN_URL for the native auth gate")
    url = make_url(configured)
    if url.get_backend_name() != "postgresql" or url.host not in {"127.0.0.1", "localhost", "::1"}:
        pytest.fail("Native auth tests require an explicitly configured loopback test server")
    name = "immoqa_auth_" + uuid4().hex
    admin = create_engine(url, isolation_level="AUTOCOMMIT")
    engine = None
    created = False
    root = Path(__file__).resolve().parents[2]
    secret = secrets.token_urlsafe(48)
    monkeypatch.setattr(auth, "SECRET_KEY", secret)
    environment = {**os.environ, "DATABASE_URL": url.set(database=name).render_as_string(hide_password=False),
                   "DATA_DIR": str(tmp_path), "SECRET_KEY_FILE": str(tmp_path / "keyring.json"), "SECRET_KEYS": "",
                   "JWT_SECRET_KEY": secret, "INTEGRATION_STATE_FILE": str(tmp_path / "integrations.json"),
                   "JOB_SCHEDULER_ENABLED": "false", "BACKUP_SCHEDULE_ENABLED": "false", "PYTHONPATH": str(root),
                   "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8", "ENVIRONMENT": "development"}
    try:
        with admin.connect() as connection:
            connection.exec_driver_sql(f'CREATE DATABASE "{name}"')
        created = True
        engine = create_engine(environment["DATABASE_URL"])
        cast(Table, RevokedTokenORM.__table__).create(engine)
        yield environment
    finally:
        if engine is not None:
            engine.dispose()
        if created:
            with admin.connect() as connection:
                connection.exec_driver_sql(f'DROP DATABASE "{name}" WITH (FORCE)')
        admin.dispose()


def run_worker(environment, directory, token, mode):
    result = subprocess.run([sys.executable, "-c", _CHILD], cwd=directory,
                            env={**environment, "IMMO_TEST_AUTH_TOKEN": token, "IMMO_TEST_AUTH_MODE": mode},
                            capture_output=True, text=True, encoding="utf-8", timeout=45)
    assert result.returncode == 0, "The isolated auth worker failed; secrets are not included in this assertion"
    return result.stdout.strip()


def test_revocation_survives_two_new_native_auth_worker_processes(native_auth, tmp_path):
    token = auth.create_access_token("synthetic-native-user")
    assert run_worker(native_auth, tmp_path, token, "check") == "valid"
    assert run_worker(native_auth, tmp_path, token, "revoke") == "revoked"
    assert run_worker(native_auth, tmp_path, token, "check") == "revoked"
    assert run_worker(native_auth, tmp_path, token, "check") == "revoked"
    # A different, valid token must remain usable after the first was revoked.
    other = auth.create_access_token("synthetic-native-user")
    assert run_worker(native_auth, tmp_path, other, "check") == "valid"


def test_native_refresh_claim_is_single_use_after_both_processes_validate_it(native_auth, tmp_path):
    token = auth.create_refresh_token("synthetic-native-user")
    barrier = tmp_path / "barrier"
    barrier.mkdir()
    environment = {**native_auth, "IMMO_TEST_AUTH_TOKEN": token, "IMMO_TEST_AUTH_MODE": "claim",
                   "IMMO_TEST_BARRIER": str(barrier)}
    workers = []
    try:
        for _ in range(2):
            workers.append(start_owned([sys.executable, "-c", _CHILD], cwd=tmp_path, env=environment,
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8"))
        deadline = time.monotonic() + 35
        while len(list(barrier.glob("ready-*"))) != 2:
            assert all(process.poll() is None for process, _job in workers), "A worker exited before the race barrier"
            assert time.monotonic() < deadline, "Both independent workers must validate before the claim"
            time.sleep(.02)
        (barrier / "release").write_text("release", encoding="utf-8")
        states = []
        for process, _job in workers:
            stdout, _stderr = process.communicate(timeout=45)
            assert process.returncode == 0
            states.append(stdout.strip())
        assert sorted(states) == ["claimed", "revoked"]
        assert run_worker(native_auth, tmp_path, token, "check") == "revoked"
    finally:
        for process, job in workers:
            stop_owned(process, job, hard=True)
