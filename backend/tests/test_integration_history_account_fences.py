"""Real Memory-account/SQLite-writer and SQL-auth management carrier races."""

import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from threading import Event, current_thread

import pytest
from sqlalchemy import event, text
from sqlalchemy.orm import sessionmaker

from backend import auth, dependencies  # noqa: F401 — initialize the real factory before replacing it
from backend.db.orm_models import Base
from backend.services.integrations.history_types import HistoryActor, HistoryError
from backend.services.portfolio_scope import scope_context, scope_from_user
from backend.tests.test_integration_history_core import journal as journal  # noqa: F401


def test_actual_sqlite_writer_precedes_memory_account_mutex(tmp_path):
    script = r'''
import os
from threading import Event, Thread
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from backend import auth, dependencies
from backend.db.integration_history_models import HISTORY_MODELS
from backend.db.integration_history_schema import install_history_guards
from backend.services.iban_encryption import IBANKeyring, generate_key
from backend.services.integrations.history_store import SQLIntegrationHistoryStore
from backend.services.integrations.history_types import HistoryActor
engine = create_engine(os.environ['HISTORY_TEST_URL'])
with engine.begin() as db:
    for model in HISTORY_MODELS: model.__table__.create(db)
    install_history_guards(db)
auth._user_store = auth.InMemoryUserStore()
auth._auth_session_factory = None
owner = auth.register_user('owner', 'owner@example.invalid', 'Owner', 'SyntheticPassword123!', 'eigentuemer')
store = SQLIntegrationHistoryStore(sessionmaker(engine), keyring=IBANKeyring('test', {'test': generate_key()}))
held, attempted, finished, saved = Event(), Event(), Event(), Event()
def observed(conn, cursor, statement, parameters, context, many):
    from threading import current_thread
    if current_thread().name == 'history' and statement == 'BEGIN IMMEDIATE': attempted.set()
event.listen(engine, 'before_cursor_execute', observed)
def writer():
    with engine.connect() as db, db.begin():
        db.exec_driver_sql('BEGIN IMMEDIATE')
        held.set()
        if not attempted.wait(10): os._exit(3)
        if auth.get_user_by_id(owner.id) is None: os._exit(5)
    finished.set()
def history():
    if not held.wait(10): os._exit(3)
    store.accept('email', HistoryActor.internal('synthetic:fence'), {'payload': {}}, {})
    saved.set()
Thread(target=writer, daemon=True, name='writer').start()
Thread(target=history, daemon=True, name='history').start()
if not finished.wait(5) or not saved.wait(10):
    print('actual writer/account deadlock', flush=True)
    os._exit(4)
print('both real writers completed', flush=True)
engine.dispose()
'''
    result = subprocess.run([sys.executable, "-c", script], env={**os.environ, "HISTORY_TEST_URL": "sqlite:///" + (tmp_path / "fence.db").as_posix()}, capture_output=True, text=True, timeout=35)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "both real writers completed" in result.stdout


def test_real_sqlauth_management_revoke_waits_through_history_commit(journal, monkeypatch):
    store, engine, _ = journal
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine)
    monkeypatch.setattr(auth, "_user_store", auth.SQLUserStore(factory))
    monkeypatch.setattr(auth, "_auth_session_factory", None)
    auth.register_user("owner", "owner@example.invalid", "Owner", "SyntheticPassword123!", "eigentuemer")
    user = auth.register_user("manager", "manager@example.invalid", "Manager", "SyntheticPassword123!", "verwalter", portfolio_access="all")
    captured = scope_from_user(auth.get_user_by_id(user.id))
    paused, release, revoke_attempted, revoked = Event(), Event(), Event(), Event()
    connections = {}

    def observed(connection, cursor, statement, parameters, context, many):
        if statement.startswith("INSERT INTO integration_runs"):
            connections["history"] = connection.scalar(text("SELECT pg_backend_pid()")) if engine.dialect.name == "postgresql" else id(connection.connection.dbapi_connection)
            paused.set()
            assert release.wait(15)
        elif current_thread().name.startswith("revoke") and statement.startswith("UPDATE auth_setup"):
            connections["revoke"] = connection.scalar(text("SELECT pg_backend_pid()")) if engine.dialect.name == "postgresql" else id(connection.connection.dbapi_connection)
            revoke_attempted.set()

    def accept():
        with scope_context(captured):
            return store.accept("email", HistoryActor.authenticated(), {"payload": {}}, {})

    def revoke():
        auth.update_user(user.id, {"role": "readonly"})
        revoked.set()

    event.listen(engine, "before_cursor_execute", observed)
    try:
        with ThreadPoolExecutor(max_workers=1, thread_name_prefix="history") as history_pool, ThreadPoolExecutor(max_workers=1, thread_name_prefix="revoke") as revoke_pool:
            first = history_pool.submit(accept)
            try:
                assert paused.wait(10)
                second = revoke_pool.submit(revoke)
                assert revoke_attempted.wait(10)
                revoked_before_commit = revoked.wait(0.5)
            finally:
                release.set()
            ticket = first.result(timeout=15)
            second.result(timeout=15)
    finally:
        release.set()
        event.remove(engine, "before_cursor_execute", observed)
    assert not revoked_before_commit
    assert connections["history"] != connections["revoke"]
    assert auth.get_user_by_id(user.id)["role"] == "readonly"
    assert store.detail("email", ticket.run_id, HistoryActor.internal("synthetic:read"))["actor_id"] == user.id


def test_missing_sqlauth_carrier_is_not_repaired(journal, monkeypatch):
    store, engine, _ = journal
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine)
    monkeypatch.setattr(auth, "_user_store", auth.SQLUserStore(factory))
    monkeypatch.setattr(auth, "_auth_session_factory", None)
    user = auth.register_user("missing-owner", "missing@example.invalid", "Owner", "SyntheticPassword123!", "eigentuemer")
    captured = scope_from_user(auth.get_user_by_id(user.id))
    with engine.begin() as db:
        db.execute(text("DELETE FROM auth_setup"))
    with scope_context(captured), pytest.raises(HistoryError, match="HISTORY_NOT_CONFIGURED"):
        store.accept("email", HistoryActor.authenticated(), {"payload": {}}, {})
    with engine.connect() as db:
        assert db.execute(text("SELECT 1 FROM auth_setup")).first() is None
        assert db.execute(text("SELECT 1 FROM integration_runs")).first() is None
