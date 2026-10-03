"""Real runtime, archive, retained-subset and caller-transaction boundaries."""

import json
import os
import sqlite3
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
from threading import Event, RLock, current_thread
from types import SimpleNamespace

import pytest
from pydantic import ValidationError as ConfigurationError
from sqlalchemy import event, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session, sessionmaker

from backend import auth
from backend.db.bank_import_models import BANK_IMPORT_TABLES  # noqa: F401 — register reset sidecars before create_all
from backend.db.integration_history_models import HISTORY_MODELS, TABLES
from backend.db.integration_history_schema import install_history_guards
from backend.db.measurement_history_schema import install_measurement_guards
from backend.db.orm_models import Base
from backend.db.rent_batch_models import RENT_BATCH_TABLES  # noqa: F401 — register reset sidecars before create_all
from backend.db.session_models import (  # noqa: F401 — register restore security tables before create_all
    AuthRefreshORM,
    AuthSessionORM,
)
from backend.models import PortfolioCreate
from backend.repositories.sql_store import SQLAlchemyStore
from backend.services import data_transfer, full_recovery, recovery_history, recovery_sessions
from backend.services.iban_encryption import IBANKeyring, generate_key, keyring_from_configuration
from backend.services.integrations import history_store
from backend.services.integrations.history_store import HEAD, SQLIntegrationHistoryStore
from backend.services.integrations.history_types import HistoryError, HistoryLimits
from backend.services.integrations.history_validation import validate_history_journal
from backend.services.portfolio_scope import scope_context
from backend.services.recovery_archive import RecoveryError
from backend.services.recovery_retained import guard_operational_history
from backend.settings import Settings
from backend.storage import InMemoryStore, ValidationError
from backend.tests.test_full_recovery import PASSPHRASE
from backend.tests.test_full_recovery import plan as plan
from backend.tests.test_full_recovery import runtime_template as runtime_template
from backend.tests.test_integration_history_core import ACTOR, completed, journal_engine

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(params=["memory", "sqlite", pytest.param("pg", id="postgres")])
def active(request, tmp_path, monkeypatch):
    with journal_engine(tmp_path, "pg" if request.param == "pg" else "sqlite", create_family=False) as engine:
        Base.metadata.create_all(engine)
        with engine.begin() as connection:
            install_history_guards(connection)
            # Explicit native fixture construction must install the same
            # original guards as Alembic; restore never repairs them.
            install_measurement_guards(connection)
        factory = sessionmaker(engine)
        ring = IBANKeyring("synthetic", {"synthetic": generate_key()})
        journal = SQLIntegrationHistoryStore(factory, keyring=ring)
        monkeypatch.setattr(history_store, "_configured_store", journal)
        monkeypatch.setattr(auth, "_user_store", auth.InMemoryUserStore())
        configuration = {"JWT_SECRET_KEY": "synthetic-offline-history-signing-key",
                         "ENCRYPTION_KEYRING": json.dumps(dict(ring.keys)), "ENCRYPTION_ACTIVE_KEY_ID": ring.active_key_id}
        with Session(engine) as session, scope_context(None):
            store = InMemoryStore() if request.param == "memory" else SQLAlchemyStore(session)
            yield SimpleNamespace(store=store, engine=engine, journal=journal, ring=ring,
                                  configuration=configuration, mode=request.param, factory=factory)


def table_rows(engine):
    with engine.connect() as connection:
        return {table: tuple(connection.execute(text('SELECT * FROM "' + table + '" ORDER BY 1'))) for table in TABLES}


def test_actual_facts_block_reset_export_and_both_import_modes(active):
    active.store.create_portfolio(PortfolioCreate(name="must survive"))
    empty = {"version": "synthetic"}
    ticket = completed(active.journal, "retained full result")
    before = table_rows(active.engine)
    for operation in (active.store.clear_all,
                      lambda: data_transfer.export_store_data(active.store, "synthetic"),
                      lambda: data_transfer.import_store_data(active.store, empty, replace_existing=False),
                      lambda: data_transfer.import_store_data(active.store, empty, replace_existing=True)):
        with pytest.raises(ValueError, match="Integrations"):
            operation()
        assert active.store.list_portfolios()[0].name == "must survive"
        assert table_rows(active.engine) == before
    assert active.journal.detail("contract-wizard", ticket.run_id, ACTOR)["details"]["late"] == "retained full result"


def test_technical_heads_and_clear_audit_survive_reset_and_subset_replace(active):
    completed(active.journal)
    active.journal.clear("contract-wizard", ACTOR)
    before = table_rows(active.engine)
    assert before[TABLES[0]] and before[TABLES[4]] and not before[TABLES[1]]
    active.store.create_portfolio(PortfolioCreate(name="business subset"))
    data = data_transfer.export_store_data(active.store, "synthetic")
    data_transfer.import_store_data(active.store, data, replace_existing=True)
    assert active.store.list_portfolios()[0].name == "business subset"
    for _ in range(2):
        active.store.clear_all()
        assert table_rows(active.engine) == before
    assert active.store.list_portfolios() == []
    with active.engine.connect() as connection:
        assert validate_history_journal(connection, active.ring)


def test_pending_history_is_not_flushed_or_committed_by_retention(active):
    if active.mode == "memory":
        pytest.skip("Caller-owned pending ORM state is a SQL-store boundary")
    db = active.store.db
    head = HISTORY_MODELS[0](integration_id="pending", run_sequence=0, event_sequence=0,
                            clear_epoch=0, active_runs=0, history_started_at=history_store.now())
    db.add(head)
    with pytest.raises(ValidationError, match="Ungespeicherte"):
        guard_operational_history(active.store)
    assert head in db.new
    with active.engine.connect() as other:
        assert other.execute(select(HEAD)).first() is None
    db.rollback()


def test_offline_restore_proof_no_auth_or_factory_and_later_failure_rolls_back(active, monkeypatch):
    ticket = active.journal.accept("email", ACTOR, {"payload": {}}, {})
    active.journal.append(ticket, "execution_started", actor=ACTOR)
    before = table_rows(active.engine)
    monkeypatch.setattr(auth, "get_user_by_id", lambda *_: pytest.fail("offline proof called live auth"))
    monkeypatch.setattr(recovery_history, "configured_history", lambda: pytest.fail("offline proof used runtime factory"))
    from backend.db import session_models
    original = session_models.invalidate_restored_sessions
    monkeypatch.setattr(session_models, "invalidate_restored_sessions", lambda *_: (_ for _ in ()).throw(RuntimeError("synthetic later security failure")))
    with pytest.raises(RuntimeError, match="later security"):
        with active.engine.begin() as connection:
            recovery_sessions.invalidate_and_inspect(connection, active.configuration, deadline=time.monotonic() + 45)
    assert table_rows(active.engine) == before
    monkeypatch.setattr(session_models, "invalidate_restored_sessions", original)
    with active.engine.begin() as connection:
        assert recovery_sessions.invalidate_and_inspect(connection, active.configuration, deadline=time.monotonic() + 45) == {
            "revoked_session_count": 0, "legacy_iban_present": False}
        assert validate_history_journal(connection, active.ring)
    detail = active.journal.detail("email", ticket.run_id, ACTOR)
    assert detail["history_status"] == "outcome_uncertain"
    assert detail["details"]["retry_automatically"] is False
    after = table_rows(active.engine)
    with active.engine.begin() as connection:
        recovery_sessions.invalidate_and_inspect(connection, active.configuration, deadline=time.monotonic() + 45)
    assert table_rows(active.engine) == after


@pytest.mark.parametrize("fault", ["key", "aad", "budget"])
def test_bad_history_refuses_before_normalization_or_security_dml(active, monkeypatch, fault):
    ticket = active.journal.accept("email", ACTOR, {"payload": {"private": "value"}}, {})
    active.journal.append(ticket, "execution_started", actor=ACTOR)
    configuration = dict(active.configuration)
    if fault == "key":
        configuration["ENCRYPTION_KEYRING"] = json.dumps({"synthetic": generate_key()})
    elif fault == "budget":
        configuration["INTEGRATION_HISTORY_ARTIFACT_BYTES"] = "1"
    else:
        with active.engine.begin() as connection:
            connection.exec_driver_sql("DROP TRIGGER preserve_integration_runs_update" + (" ON integration_runs" if active.mode == "pg" else ""))
            connection.execute(text("UPDATE integration_runs SET actor_id='forged' WHERE id=:id"), {"id": ticket.run_id})
    before = table_rows(active.engine)
    from backend.db import session_models
    monkeypatch.setattr(session_models, "invalidate_restored_sessions", lambda *_: pytest.fail("security DML before proof"))
    with pytest.raises(recovery_sessions.SessionRestoreError, match="restore_integration_history_invalid"):
        with active.engine.begin() as connection:
            recovery_sessions.invalidate_and_inspect(connection, configuration, deadline=time.monotonic() + 45)
    assert table_rows(active.engine) == before


@pytest.mark.parametrize("mode", ["memory", "sql"])
def test_real_startup_initializes_same_database_and_explicit_settings(tmp_path, mode):
    database = tmp_path / "owned-runtime.db"
    environment = dict(os.environ, DATABASE_URL="sqlite:///" + database.as_posix(),
                       SQLITE_PERSISTENT_STORE=str(mode == "sql").lower(), ALLOW_INMEMORY_FALLBACK="true",
                       DATA_DIR=str(tmp_path), INTEGRATION_HISTORY_ARTIFACT_BYTES="67108865",
                       INTEGRATION_HISTORY_PAGE_BYTES="134217729", INTEGRATION_HISTORY_TEMP_BYTES="2147483649",
                       INTEGRATION_HISTORY_TIMEOUT_SECONDS="91.5")
    script = """
from backend import dependencies
from backend.services.integrations.history_store import configured_history
from backend.db.session import engine
from sqlalchemy import inspect
store=configured_history()
assert store.factory.kw['bind'] is engine
assert store.limits.artifact_bytes == 67108865 and store.limits.page_bytes == 134217729
assert store.limits.temp_bytes == 2147483649 and store.limits.timeout_seconds == 91.5
names=set(inspect(engine).get_table_names())
assert 'integration_runs' in names and 'integration_history_clears' in names
assert ('portfolios' in names) == (dependencies.store.__class__.__name__ == 'SQLAlchemyStore')
print('OWNED_RUNTIME_OK')
"""
    result = subprocess.run([sys.executable, "-c", script], cwd=ROOT, env=environment,
                            capture_output=True, text=True, timeout=45)
    assert result.returncode == 0, result.stderr
    assert "OWNED_RUNTIME_OK" in result.stdout and database.exists()


@pytest.mark.parametrize("mode", ["memory", "sql"])
def test_partial_family_cannot_be_repaired_by_startup_or_domain_fallback(tmp_path, mode):
    database = tmp_path / "partial.db"
    with closing(sqlite3.connect(database)) as connection:
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("CREATE TABLE integration_runs(id TEXT)")
        connection.commit()
    before = database.read_bytes()
    environment = dict(os.environ, DATABASE_URL="sqlite:///" + database.as_posix(),
                       SQLITE_PERSISTENT_STORE=str(mode == "sql").lower(), ALLOW_INMEMORY_FALLBACK="true")
    result = subprocess.run([sys.executable, "-c", "from backend import dependencies"], cwd=ROOT,
                            env=environment, capture_output=True, text=True, timeout=45)
    assert result.returncode != 0 and "HISTORY_CORRUPT" in result.stderr
    with sqlite3.connect(database) as connection:
        assert connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall() == [("integration_runs",)]
        assert connection.execute("SELECT * FROM integration_runs").fetchall() == []
    assert database.read_bytes() == before


@pytest.mark.parametrize("field", ["integration_history_artifact_bytes", "integration_history_page_bytes", "integration_history_temp_bytes", "integration_history_timeout_seconds"])
@pytest.mark.parametrize("value", [0, -1, True, float("inf"), float("nan")])
def test_settings_refuse_invalid_resource_budgets(field, value):
    with pytest.raises(ConfigurationError):
        Settings(_env_file=None, **{field: value})


def test_offline_limits_ignore_ambient_values_and_have_no_configuration_ceiling(monkeypatch, tmp_path):
    monkeypatch.setenv("INTEGRATION_HISTORY_ARTIFACT_BYTES", "1")
    values = {"INTEGRATION_HISTORY_ARTIFACT_BYTES": "67108865", "INTEGRATION_HISTORY_PAGE_BYTES": "134217729",
              "INTEGRATION_HISTORY_TEMP_BYTES": "2147483649", "INTEGRATION_HISTORY_TIMEOUT_SECONDS": "172800.5"}
    assert recovery_history.history_limits_from_configuration(values) == HistoryLimits(
        artifact_bytes=67108865, page_bytes=134217729, temp_bytes=2147483649, timeout_seconds=172800.5)
    with sqlite3.connect(tmp_path / "entirely-old.db") as connection:
        assert recovery_history.validate_configured_history(connection, {"INTEGRATION_HISTORY_ARTIFACT_BYTES": "invalid"}) is False
    assert recovery_history.verify_history(tmp_path / "entirely-old.db", {}) is False


def seed_archive_history(plan, *, started=False):
    from sqlalchemy import create_engine
    engine = create_engine("sqlite:///" + plan.database.as_posix())
    journal = SQLIntegrationHistoryStore(sessionmaker(engine), keyring=keyring_from_configuration(plan.configuration))
    if started:
        ticket = journal.accept("email", ACTOR, {"payload": {}}, {})
        journal.append(ticket, "execution_started", actor=ACTOR)
    else:
        ticket = completed(journal, "完整尾部-" + "private chunk value " * 5000)
    return journal, engine, ticket


@pytest.mark.parametrize("started", [False, True])
def test_actual_encrypted_archive_source_gone_restores_full_chunks_or_unconfirmed(plan, tmp_path, started):
    journal, engine, ticket = seed_archive_history(plan, started=started)
    before = journal.detail("email" if started else "contract-wizard", ticket.run_id, ACTOR)
    engine.dispose()
    archive = tmp_path / "with-history.immobak"
    full_recovery.create_full_backup(plan, archive, PASSPHRASE, offline=True)
    assert b"private chunk value" not in archive.read_bytes()
    assert plan.database.parent.resolve().parent == tmp_path.resolve()
    plan.database.parent.rename(tmp_path / "source-offline")
    target = tmp_path / "restored"
    full_recovery.restore_full_backup(archive, target, PASSPHRASE)
    from sqlalchemy import create_engine
    restored_engine = create_engine("sqlite:///" + (target / "database.sqlite3").as_posix())
    try:
        recovered = SQLIntegrationHistoryStore(sessionmaker(restored_engine), keyring=keyring_from_configuration(plan.configuration))
        detail = recovered.detail("email" if started else "contract-wizard", ticket.run_id, ACTOR)
        if started:
            assert detail["history_status"] == "outcome_uncertain"
            assert detail["details"]["retry_automatically"] is False
            with pytest.raises(HistoryError, match="HISTORY_BUSY"):
                recovered.append(ticket, "execution_started", actor=ACTOR)
        else:
            assert detail == before
        assert recovery_history.verify_history(target / "database.sqlite3", plan.configuration)
    finally:
        restored_engine.dispose()


def test_entire_old_archive_and_partial_history_have_real_image_proofs(plan, tmp_path):
    with closing(sqlite3.connect(plan.database)) as connection:
        for model in reversed(HISTORY_MODELS):
            assert connection.execute('SELECT COUNT(*) FROM "' + model.__tablename__ + '"').fetchone()[0] == 0
            connection.execute('DROP TABLE "' + model.__tablename__ + '"')
        connection.commit()
    before = full_recovery._database_info(plan.database)
    archive, target = tmp_path / "fully-old.immobak", tmp_path / "old-restored"
    full_recovery.create_full_backup(plan, archive, PASSPHRASE, offline=True)
    full_recovery.restore_full_backup(archive, target, PASSPHRASE)
    assert full_recovery._database_info(target / "database.sqlite3") == before
    with sqlite3.connect(plan.database) as connection:
        connection.execute("CREATE TABLE integration_runs(id TEXT)")
    with pytest.raises(RecoveryError, match="Integrationshistorie"):
        full_recovery._database_info(plan.database)


@pytest.mark.parametrize("fault", ["key", "aad", "budget"])
def test_full_backup_rejects_history_before_publication_with_exact_archive_config(plan, tmp_path, fault):
    _, engine, ticket = seed_archive_history(plan)
    engine.dispose()
    configuration = dict(plan.configuration)
    if fault == "key":
        configuration.update(ENCRYPTION_KEY=generate_key(), ENCRYPTION_KEYRING="")
    elif fault == "budget":
        configuration["INTEGRATION_HISTORY_ARTIFACT_BYTES"] = "4096"
    else:
        with sqlite3.connect(plan.database) as connection:
            connection.execute("DROP TRIGGER preserve_integration_runs_update")
            connection.execute("UPDATE integration_runs SET actor_id='tampered' WHERE id=?", (ticket.run_id,))
    from dataclasses import replace
    archive = tmp_path / "refused.immobak"
    with pytest.raises(RecoveryError):
        full_recovery.create_full_backup(replace(plan, configuration=configuration), archive, PASSPHRASE, offline=True)
    assert not archive.exists()


def test_native_sqlite_memory_reset_waits_writer_before_auth_and_keeps_auth_through_commit(active):
    if active.mode != "memory":
        pytest.skip("Memory reset with an actual shared SQLite journal")
    active.store.create_portfolio(PortfolioCreate(name="clear me"))
    writer_attempt, account_attempt, commit_checked = Event(), Event(), Event()
    actual = RLock()
    class ObservedLock:
        def __enter__(self):
            if current_thread().name.startswith("history-reset"):
                account_attempt.set()
            actual.acquire()
            return self
        def __exit__(self, *_):
            actual.release()
    active_auth = auth._user_store
    active_auth._lock = ObservedLock()
    @event.listens_for(active.engine, "before_cursor_execute")
    def before(_connection, _cursor, statement, _parameters, _context, _many):
        if current_thread().name.startswith("history-reset") and statement.strip().upper() == "BEGIN IMMEDIATE":
            writer_attempt.set()
    @event.listens_for(active.engine, "commit")
    def at_commit(_connection):
        if current_thread().name.startswith("history-reset"):
            assert actual._is_owned()
            commit_checked.set()
    with active.engine.connect() as blocker, ThreadPoolExecutor(max_workers=1, thread_name_prefix="history-reset") as pool:
        blocker.exec_driver_sql("BEGIN IMMEDIATE")
        reset = pool.submit(active.store.clear_all)
        try:
            assert writer_attempt.wait(10), "reset never reached actual SQLite writer boundary"
            assert not account_attempt.is_set(), "memory auth was acquired while waiting for the existing SQLite writer"
            # This actual older writer must still obtain the real MemoryAuth
            # mutex before its own commit; no sleep or raised timeout hides it.
            with active_auth._lock:
                blocker.commit()
            reset.result(timeout=15)
        finally:
            blocker.rollback()
    assert commit_checked.is_set() and active.store.list_portfolios() == []


def test_actual_postgres_reset_fence_blocks_new_journal_dml_and_preserves_caller_state(active):
    if active.mode != "pg":
        pytest.skip("Actual PostgreSQL table-lock boundary")
    from backend.services.contract_occupancy import begin_writer
    db = active.store.db
    begin_writer(db)
    guard_operational_history(active.store, serialized=True)
    with active.engine.begin() as other:
        with pytest.raises(DBAPIError) as denial:
            other.exec_driver_sql("LOCK TABLE integration_runs IN ROW EXCLUSIVE MODE NOWAIT")
        assert denial.value.orig.pgcode == "55P03"
    assert db.in_transaction()
    db.rollback()
    with active.engine.begin() as other:
        other.exec_driver_sql("LOCK TABLE integration_runs IN ROW EXCLUSIVE MODE NOWAIT")
