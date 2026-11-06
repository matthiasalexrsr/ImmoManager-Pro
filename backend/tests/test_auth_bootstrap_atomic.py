"""Competing own SQL workers may create only one public bootstrap owner."""

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import cast
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import Table, create_engine
from sqlalchemy.exc import SQLAlchemyError

from backend import auth
from backend.db.access_models import RegistrationQuotaORM, UserAccessORM, UserPortfolioORM
from backend.db.orm_models import UserORM
from backend.routers import auth as routes


def test_public_followup_signup_needs_owner_activation_and_assignment(monkeypatch):
    auth.clear_users()
    try:
        auth.register_user("own-first", "first@example.invalid", "Own first fixture", "Birke7Fenster", "eigentuemer")
        monkeypatch.setattr(routes.settings, "allow_self_registration", True)
        app = FastAPI()
        app.include_router(routes.router, prefix="/api/v1")
        with TestClient(app) as client:
            response = client.post("/api/v1/auth/register", json={
                "username": "own-pending", "email": "pending@example.invalid", "full_name": "Own pending fixture",
                "password": "Birke7Fenster", "role": "eigentuemer", "portfolio_access": "all", "is_active": True,
            })
            assert response.status_code == 201
            account = response.json()
            assert account["is_active"] is False
            assert account["approval_required"] is True
            assert account["role"] == "readonly"
            assert account["portfolio_access"] == "selected" and account["portfolio_ids"] == []
            assert client.post("/api/v1/auth/login", json={"username": "own-pending", "password": "Birke7Fenster"}).status_code == 401
            assert client.get("/api/v1/auth/me", headers={"Authorization": "Bearer " + auth.create_access_token(account["id"])}).status_code == 403
            auth.update_user(account["id"], {"is_active": True})
            assert client.post("/api/v1/auth/login", json={"username": "own-pending", "password": "Birke7Fenster"}).status_code == 200
    finally:
        auth.clear_users()


@pytest.mark.parametrize("operation", ["open", "read", "commit", "rollback"])
def test_public_registration_storage_failure_cannot_confirm_account(monkeypatch, caplog, operation):
    failure = SQLAlchemyError("PRIVATE-BOOTSTRAP-STORAGE-SECRET")
    session = MagicMock()
    session.get_bind.return_value.dialect.name = "sqlite"
    session.scalar.return_value = None
    factory = MagicMock(return_value=session)
    if operation == "open":
        factory.side_effect = failure
    elif operation == "commit":
        session.commit.side_effect = failure
    else:
        session.scalar.side_effect = failure
        if operation == "rollback":
            session.rollback.side_effect = failure
    monkeypatch.setattr(auth, "_user_store", auth.SQLUserStore(factory))
    with pytest.raises(HTTPException) as rejected:
        auth.register_public_user("own-public", "own-public@example.invalid", "Own fixture", "Birke7Fenster",
                                  allow_self_registration=False)
    assert rejected.value.status_code == 503
    assert "PRIVATE-BOOTSTRAP" not in str(rejected.value.detail) + caplog.text

CHILD = '''import json,sys,time
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from fastapi import FastAPI
from fastapi.testclient import TestClient
from backend import auth
from backend.routers import auth as routes
engine=create_engine('sqlite:///'+sys.argv[1])
auth.enable_sql_users(sessionmaker(engine))
routes.settings.allow_self_registration=sys.argv[5]=='1'
app=FastAPI()
app.include_router(routes.router,prefix='/api/v1')
with TestClient(app) as client:
 Path(sys.argv[3]).write_text('ready',encoding='ascii')
 deadline=time.monotonic()+15
 while not Path(sys.argv[2]).exists():
  if time.monotonic()>deadline: raise TimeoutError('Own bootstrap gate expired')
  time.sleep(.01)
 response=client.post('/api/v1/auth/register',json={'username':'worker-'+sys.argv[4],
  'email':'worker'+sys.argv[4]+'@example.invalid','full_name':'Own bootstrap fixture','password':'Birke7Fenster'})
 print(json.dumps({'status':response.status_code,'role':response.json().get('role'),
  'is_active':response.json().get('is_active'),'approval_required':response.json().get('approval_required')}),flush=True)
engine.dispose()
'''


@pytest.mark.parametrize("self_registration", [False, True])
def test_public_bootstrap_is_serialized_across_workers(tmp_path, self_registration):
    database = tmp_path / "own-bootstrap.db"
    engine = create_engine("sqlite:///" + database.as_posix())
    for model in [UserORM, UserAccessORM, UserPortfolioORM, RegistrationQuotaORM]:
        cast(Table, model.__table__).create(engine)
    engine.dispose()
    child_file = tmp_path / "bootstrap-child.py"
    child_file.write_text(CHILD, encoding="utf-8")
    gate = tmp_path / "start"
    ready = [tmp_path / f"ready-{number}" for number in range(2)]
    children = [subprocess.Popen([sys.executable, str(child_file), database.as_posix(), str(gate), str(mark),
                                  str(number), "1" if self_registration else "0"],
                                 cwd=Path(__file__).resolve().parents[2], stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                 stdin=subprocess.DEVNULL, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                                 env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[2])})
                for number, mark in enumerate(ready)]
    try:
        deadline = time.monotonic() + 20
        while not all(mark.exists() for mark in ready):
            assert all(child.poll() is None for child in children), "An owned bootstrap child stopped before its gate"
            assert time.monotonic() < deadline, "Owned bootstrap children did not reach their start gate"
            time.sleep(.02)
        gate.write_text("start", encoding="ascii")
        outcomes = []
        for child in children:
            stdout, _ = child.communicate(timeout=25)
            assert child.returncode == 0, "An owned bootstrap child failed"
            outcomes.append(json.loads(stdout.splitlines()[-1]))
        assert sum(item["role"] == "eigentuemer" for item in outcomes) == 1, outcomes
        assert sorted(item["status"] for item in outcomes) == ([201, 201] if self_registration else [201, 403]), outcomes
        if self_registration:
            assert sum(item["role"] == "readonly" for item in outcomes) == 1
            assert all(item['is_active'] is False and item['approval_required'] is True for item in outcomes if item['role'] == 'readonly')
        assert all(item['is_active'] is True and item['approval_required'] is False for item in outcomes if item['role'] == 'eigentuemer')
    finally:
        for child in children:
            if child.poll() is None:
                child.kill()
            child.communicate(timeout=5)
