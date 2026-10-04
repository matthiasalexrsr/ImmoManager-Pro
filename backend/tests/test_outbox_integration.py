"""Actual startup, additive bootstrap, reset protection, and no memory sidecar."""

import base64
import os
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy import event, inspect, select
from sqlalchemy.orm import Session

from backend.db import session as session_module
from backend.db.orm_models import PortfolioORM
from backend.db.outbox_models import OutboxCommandORM, OutboxEventORM, OutboxMessageORM
from backend.models import PortfolioCreate
from backend.repositories.sql_store import SQLAlchemyStore
from backend.services import outbox as service
from backend.storage import InMemoryStore
from backend.tests.test_outbox_journal import active as active
from backend.tests.test_outbox_journal import command, review

ROOT = Path(__file__).resolve().parents[2]
OUTBOX_TABLES = (OutboxMessageORM.__table__, OutboxEventORM.__table__, OutboxCommandORM.__table__)


def test_real_bootstrap_recreates_missing_journal_tables_and_preserves_live_rows(active, monkeypatch):
    monkeypatch.setattr(session_module, "engine", active.engine)
    active.store.db.rollback()
    with active.engine.begin() as connection:
        for table in reversed(OUTBOX_TABLES):
            table.drop(connection)
    for _ in range(2):
        session_module.create_tables()
    assert {table.name for table in OUTBOX_TABLES} <= set(inspect(active.engine).get_table_names())
    with Session(active.engine) as db:
        assert set(db.scalars(select(PortfolioORM.id))) == {"p", "foreign"}
        for table in OUTBOX_TABLES:
            assert db.execute(select(table)).all() == []


@pytest.mark.parametrize("sent", [False, True])
def test_ordinary_reset_refuses_before_any_dml_and_preserves_review_or_transport_history(active, sent):
    first = service.create_message(active.store, review(), "actor")
    if sent:
        service.send_message(active.store, first["id"], command(first), "actor")
    with Session(active.engine) as db:
        before = {table.name: db.execute(select(table)).all() for table in (*OUTBOX_TABLES, PortfolioORM.__table__)}
    modifications = []
    def record_statement(connection, cursor, statement, parameters, context, many):
        if statement.lstrip().split(None, 1)[0].upper() in {"DELETE", "INSERT", "UPDATE"}:
            modifications.append(statement)
    event.listen(active.engine, "before_cursor_execute", record_statement)
    try:
        with pytest.raises(HTTPException, match="outbox_history_exists") as denied:
            SQLAlchemyStore(active.store.db).clear_all()
        assert denied.value.status_code == 409 and modifications == []
    finally:
        event.remove(active.engine, "before_cursor_execute", record_statement)
    with Session(active.engine) as db:
        after = {table.name: db.execute(select(table)).all() for table in (*OUTBOX_TABLES, PortfolioORM.__table__)}
    assert before == after
    assert len(active.calls) == int(sent)


def test_empty_outbox_does_not_break_existing_sql_reset(active):
    store = SQLAlchemyStore(active.store.db)
    store.clear_all()
    assert store.list_portfolios() == []
    for table in OUTBOX_TABLES:
        assert store.db.execute(select(table)).all() == []


def test_memory_failure_never_allocates_sidecar_and_existing_reset_remains_usable():
    store = InMemoryStore()
    store.create_portfolio(PortfolioCreate(name="Synthetic private portfolio"))
    before = set(store.__dict__)
    with pytest.raises(HTTPException, match="outbox_requires_persistent_sql") as denied:
        service.create_message(store, review(), "actor")
    assert denied.value.status_code == 503 and set(store.__dict__) == before
    store.clear_all()
    assert store.list_portfolios() == []
    assert not any("outbox" in key for key in store.__dict__)


@pytest.mark.parametrize("backend", ["sql", "memory"])
def test_fresh_process_actual_app_start_routes_and_restart_preserve_review_without_sending(tmp_path, backend):
    """No imported ORM fixtures, inherited app config, user database, or network."""
    environment = {name: value for name, value in os.environ.items()
        if name.upper() in {"SYSTEMROOT", "WINDIR", "COMSPEC", "PATH", "PATHEXT", "NUMBER_OF_PROCESSORS"}}
    environment.update({
        "PYTHONPATH": str(ROOT), "PYTHONUTF8": "1", "PYTHONNOUSERSITE": "1",
        "DATABASE_URL": "sqlite:///" + (tmp_path / "fresh.sqlite").as_posix(),
        "DATA_DIR": str(tmp_path), "TEMP": str(tmp_path), "TMP": str(tmp_path),
        "HOME": str(tmp_path), "USERPROFILE": str(tmp_path), "LOCALAPPDATA": str(tmp_path),
        "ENVIRONMENT": "production" if backend == "sql" else "development",
        "SQLITE_PERSISTENT_STORE": str(backend == "sql").lower(),
        "ALLOW_INMEMORY_FALLBACK": str(backend == "memory").lower(),
        "AUTO_MIGRATE": "false", "AUTO_SEED_DEMO_DATA": "false", "AI_ENABLED": "false",
        "OPERATIONAL_SCHEDULER_ENABLED": "false", "PLUGIN_DIRS": "[]", "LOG_LEVEL": "CRITICAL",
        "CORS_ORIGINS": '["http://127.0.0.1"]', "TRUSTED_HOSTS": '["127.0.0.1"]',
        "JWT_SECRET_KEY": "synthetic-only-outbox-startup-" + "0" * 32,
        "ENCRYPTION_KEY": base64.urlsafe_b64encode(b"synthetic-key".ljust(32, b"0")).decode("ascii"),
        "ENCRYPTION_INDEX_KEY": base64.urlsafe_b64encode(b"synthetic-index".ljust(32, b"0")).decode("ascii"),
        "INTEGRATION_STATE_FILE": str(tmp_path / "integrations.json"),
    })
    if backend == "sql":
        # Production starts an explicitly installed database. Startup itself
        # must never install or repair schema, including this subprocess gate.
        installed = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=ROOT,
            env=environment, capture_output=True, timeout=90)
        assert installed.returncode == 0, "Owned outbox startup schema migration failed"
    child = r'''
import multiprocessing
import os
from fastapi.testclient import TestClient
from backend.app import app
from backend.auth import create_access_token
from backend.services.integrations.manager import integration_manager
from backend.dependencies import cleanup_session
from backend.db.session import engine

is_sql = os.environ["SQLITE_PERSISTENT_STORE"] == "true"
integration_manager.update_config("email", {"smtp_host": "127.0.0.1", "smtp_port": 587,
    "smtp_use_tls": True, "smtp_use_ssl": False, "sender_email": "owner@test.invalid",
    "sender_name": "Synthetic owner", "smtp_timeout_seconds": 1})
base = "/api/v1/messages/outbox"
with TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 50000)) as client:
    assert client.get(base + "/configuration").status_code == 401
    assert client.get("/api/v1/auth/setup-status").json()["setup_required"]
    owner = client.post("/api/v1/auth/setup", json={"username": "synthetic-startup-owner",
        "email": "owner@example.test", "full_name": "Synthetic owner", "password": "SyntheticStartup1234"})
    assert owner.status_code == 201
    headers = {"Authorization": "Bearer " + create_access_token(owner.json()["id"])}
    portfolio = client.post("/api/v1/portfolios", json={"name": "Synthetic"}, headers=headers)
    assert portfolio.status_code == 201
    portfolio_id = portfolio.json()["id"]
    assert client.get(base + "/configuration", headers=headers).status_code == 200
    listed = client.get(base, params={"portfolio_id": portfolio_id}, headers=headers)
    assert listed.status_code == (200 if is_sql else 503)
    if is_sql:
        assert listed.json()["items"] == []
    reviewed = client.post(base, headers=headers, json={"portfolio_id": portfolio_id,
        "idempotency_key": "synthetic-startup", "recipient": "tenant@test.invalid",
        "sender_address": "owner@test.invalid", "sender_name": "Synthetic owner",
        "subject": "Synthetic", "body_text": "Synthetic private content", "reviewed_by": "Synthetic",
        "review_confirmed": True})
    assert reviewed.status_code == (201 if is_sql else 503)
    if is_sql:
        original = reviewed.json()
        assert original["state"] == "ready" and original["attempt_no"] == 0
cleanup_session()
engine.dispose()
if is_sql:
    with TestClient(app, base_url="http://127.0.0.1", client=("127.0.0.1", 50001)) as client:
        assert not client.get("/api/v1/auth/setup-status").json()["setup_required"]
        restored = client.get(base + "/" + original["id"], headers=headers)
        assert restored.status_code == 200 and restored.json() == original
        journal = client.get(base + "/" + original["id"] + "/events", headers=headers).json()
        assert journal["total"] == 1 and journal["items"][0]["kind"] == "reviewed"
cleanup_session()
if is_sql:
    assert engine.pool.checkedout() == 0
engine.dispose()
assert multiprocessing.active_children() == []
print("OUTBOX_STARTUP_OK")
'''
    completed = subprocess.run([sys.executable, "-c", child], cwd=tmp_path, env=environment,
        capture_output=True, text=True, encoding="utf-8", timeout=40, check=False)
    assert completed.returncode == 0, "Fresh synthetic outbox app startup failed (private process output suppressed)"
    assert "OUTBOX_STARTUP_OK" in completed.stdout
