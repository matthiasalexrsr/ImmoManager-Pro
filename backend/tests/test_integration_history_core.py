"""Actual independent SQLite/PG connections, encrypted full observations."""

import os
import sqlite3
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event, func, insert, select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import sessionmaker

from backend.db.integration_history_models import HISTORY_MODELS
from backend.db.integration_history_schema import ensure_history_schema, install_history_guards
from backend.services.iban_encryption import IBANKeyring, generate_key
from backend.services.integrations.history_restore import mark_restored_unconfirmed
from backend.services.integrations.history_store import CHUNK, EVENT, HEAD, RUN, SQLIntegrationHistoryStore
from backend.services.integrations.history_types import HistoryActor, HistoryError, HistoryLimits, RunTicket
from backend.services.integrations.history_validation import validate_history_journal


@contextmanager
def journal_engine(tmp_path, dialect, *, create_family=True):
    schema, admin = None, None
    if dialect == "pg":
        url = os.environ.get("TEST_SERVER_DATABASE_URL")
        if not url:
            pytest.skip("Disposable PostgreSQL service URL not configured")
        schema = "integration_history_" + uuid4().hex
        admin = create_engine(url)
        with admin.begin() as db:
            db.execute(text(f'CREATE SCHEMA "{schema}"'))
        engine = create_engine(url, connect_args={"options": "-csearch_path=" + schema})
    else:
        engine = create_engine("sqlite:///" + (tmp_path / (uuid4().hex + ".db")).as_posix(), connect_args={"timeout": 15})
        @event.listens_for(engine, "connect")
        def foreign_keys(connection, _record):
            connection.execute("PRAGMA foreign_keys=ON")
    try:
        if create_family:
            with engine.begin() as db:
                for model in HISTORY_MODELS:
                    model.__table__.create(db)
                install_history_guards(db)
        yield engine
    finally:
        engine.dispose()
        if admin is not None:
            with admin.begin() as db:
                db.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
            admin.dispose()


@pytest.fixture(params=["sqlite", pytest.param("pg", id="postgres")])
def journal(request, tmp_path):
    with journal_engine(tmp_path, request.param) as engine:
        ring = IBANKeyring("synthetic", {"synthetic": generate_key()})
        yield SQLIntegrationHistoryStore(sessionmaker(engine), keyring=ring), engine, ring


ACTOR = HistoryActor.internal("synthetic:history-tests")


def completed(journal, value="LATE_VALUE", *, integration_id="contract-wizard"):
    ticket = journal.accept(integration_id, ACTOR, {"payload": {"values": ["first", value]}, "policy": {"version": 1}}, {"all": True})
    journal.append(ticket, "execution_started", actor=ACTOR)
    journal.append(ticket, "completed", {"response": {"success": True, "message": "finished", "details": {"late": value}}, "schema": {"all": True}})
    return ticket


def test_full_roundtrip_raw_ciphertext_and_explicit_keys(journal):
    store, engine, ring = journal
    ticket = completed(store, "PRIVATE_AFTER_200")
    detail = store.detail("contract-wizard", ticket.run_id, ACTOR)
    assert detail["payload"]["values"][-1] == "PRIVATE_AFTER_200"
    assert detail["details"]["late"] == "PRIVATE_AFTER_200"
    with engine.connect() as db:
        assert "PRIVATE_AFTER_200" not in repr(db.execute(select(CHUNK)).all())
        assert validate_history_journal(db, ring)
        with pytest.raises(HistoryError, match="HISTORY_KEY_UNAVAILABLE"):
            validate_history_journal(db, IBANKeyring("wrong", {"wrong": generate_key()}))
    assert SQLIntegrationHistoryStore(sessionmaker(engine), keyring=ring).detail("contract-wizard", ticket.run_id, ACTOR) == detail


def test_keyset_all_201_and_concurrent_independent_connections(journal):
    store, engine, ring = journal
    def create(index):
        other = SQLIntegrationHistoryStore(sessionmaker(engine), keyring=ring)
        return completed(other, f"value-{index}").run_id
    with ThreadPoolExecutor(max_workers=3) as pool:
        identifiers = set(pool.map(create, range(205)))
    cursor, seen = None, []
    while True:
        page = store.page("contract-wizard", ACTOR, limit=17, cursor=cursor)
        seen.extend(item["id"] for item in page["items"])
        cursor = page["next_cursor"]
        if cursor is None:
            break
    assert len(seen) == 205 and len(set(seen)) == 205 and set(seen) == identifiers
    assert store.metrics(["contract-wizard"], ACTOR)["runs_successful"] == 205
    with engine.connect() as db:
        assert validate_history_journal(db, ring)


def test_frozen_status_cursor_and_explicit_clear_audit(journal):
    store, engine, ring = journal
    older = store.accept("contract-wizard", ACTOR, {"payload": {}}, {})
    newer = store.accept("contract-wizard", ACTOR, {"payload": {}}, {})
    first = store.page("contract-wizard", ACTOR, limit=1, state="pending")
    assert first["items"][0]["id"] == newer.run_id
    for ticket in (older, newer):
        store.append(ticket, "rejected", {"response": {"success": False, "message": "disabled"}, "schema": {}})
    second = store.page("contract-wizard", ACTOR, limit=1, state="pending", cursor=first["next_cursor"])
    assert second["items"][0]["id"] == older.run_id
    assert store.clear("contract-wizard", ACTOR) == {"id": "contract-wizard", "cleared": 2}
    assert store.page("contract-wizard", ACTOR)["items"] == []
    with engine.connect() as db:
        assert validate_history_journal(db, ring)
    with pytest.raises(HistoryError, match="HISTORY_CURSOR_INVALID"):
        store.page("contract-wizard", ACTOR, limit=1, state="pending", cursor=first["next_cursor"])


def test_started_crash_normalization_is_caller_atomic_and_never_provider(journal):
    store, engine, ring = journal
    ticket = store.accept("email", ACTOR, {"payload": {}, "policy": {"mail_payload_omitted": True}}, {})
    store.append(ticket, "execution_started", actor=ACTOR)
    with engine.connect() as db, db.begin() as transaction:
        assert mark_restored_unconfirmed(db, ring) == 1
        transaction.rollback()
    assert store.detail("email", ticket.run_id, ACTOR)["history_status"] == "outcome_unconfirmed"
    with engine.begin() as db:
        assert mark_restored_unconfirmed(db, ring) == 1
    with engine.begin() as db:
        assert mark_restored_unconfirmed(db, ring) == 0
        assert validate_history_journal(db, ring)
    assert store.detail("email", ticket.run_id, ACTOR)["history_status"] == "outcome_uncertain"
    with pytest.raises(HistoryError, match="HISTORY_BUSY"):
        store.append(ticket, "execution_started", actor=ACTOR)


def test_no_partial_run_on_budget_failure_and_forged_ticket(journal):
    store, engine, ring = journal
    small = SQLIntegrationHistoryStore(sessionmaker(engine), keyring=ring, limits=HistoryLimits(artifact_bytes=100))
    with pytest.raises(HistoryError, match="HISTORY_BUDGET_EXCEEDED"):
        small.accept("email", ACTOR, {"payload": "X" * 1000}, {})
    with engine.connect() as db:
        assert db.execute(select(RUN)).first() is None
        assert db.execute(select(HEAD)).first() is None
    ticket = store.accept("email", ACTOR, {"payload": {}}, {})
    with pytest.raises(HistoryError, match="HISTORY_FORBIDDEN"):
        store.append(RunTicket(ticket.run_id, "forged"), "execution_started")
    with pytest.raises(HistoryError, match="HISTORY_BUSY"):
        store.clear("email", ACTOR)


def test_legacy_absence_before_keylookup_and_partial_family(tmp_path):
    with sqlite3.connect(tmp_path / "legacy.db") as db:
        assert ensure_history_schema(db) is False
        assert validate_history_journal(db, {}) is False
        db.execute("CREATE TABLE integration_runs(id TEXT)")
        with pytest.raises(HistoryError, match="HISTORY_CORRUPT"):
            validate_history_journal(db, {})


def test_extra_foreign_chunk_refuses_before_normalization(journal):
    store, engine, ring = journal
    ticket = completed(store)
    with engine.begin() as db:
        event = db.execute(select(EVENT).where(EVENT.c.run_id == ticket.run_id).limit(1)).mappings().one()
        db.execute(insert(CHUNK).values(event_id=event["id"], kind="foreign", position=0, ciphertext="bad"))
    with engine.begin() as db, pytest.raises(HistoryError, match="HISTORY_CORRUPT"):
        mark_restored_unconfirmed(db, ring)


def test_actual_separate_processes_share_commit_ordered_journal(journal):
    store, engine, ring = journal
    source = engine.url.render_as_string(hide_password=False)
    schema = engine.url.query.get("options") or engine.dialect.create_connect_args(engine.url)[1].get("options", "")
    # Engine connect_args contains the random schema in this fixture.
    with engine.connect() as db:
        if engine.dialect.name == "postgresql":
            schema = "-csearch_path=" + db.scalar(text("SELECT current_schema()"))
    script = """
import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from backend.services.iban_encryption import IBANKeyring
from backend.services.integrations.history_store import SQLIntegrationHistoryStore
from backend.services.integrations.history_types import HistoryActor
args = {'options': os.environ['HISTORY_TEST_SCHEMA']} if os.environ['HISTORY_TEST_SCHEMA'] else {}
engine = create_engine(os.environ['HISTORY_TEST_URL'], connect_args=args)
store = SQLIntegrationHistoryStore(sessionmaker(engine), keyring=IBANKeyring('synthetic', {'synthetic': os.environ['HISTORY_TEST_KEY']}))
actor = HistoryActor.internal('synthetic:separate-process')
ticket = store.accept('email', actor, {'payload': {'process': os.getpid()}}, {})
store.append(ticket, 'rejected', {'response': {'success': False, 'message': 'synthetic rejection'}, 'schema': {}})
print(ticket.run_id)
engine.dispose()
"""
    environment = dict(os.environ, HISTORY_TEST_URL=source, HISTORY_TEST_SCHEMA=schema, HISTORY_TEST_KEY=ring.keys["synthetic"])
    children = [subprocess.Popen([sys.executable, "-c", script], env=environment, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for _ in range(2)]
    outputs = []
    try:
        for child in children:
            output, error = child.communicate(timeout=60)
            assert child.returncode == 0, error
            outputs.append(output.strip())
    finally:
        for child in children:
            if child.poll() is None:
                child.kill()
                child.communicate(timeout=10)
    assert len(set(outputs)) == 2
    assert {row["id"] for row in store.page("email", ACTOR)["items"]} == set(outputs)
    with engine.connect() as db:
        assert validate_history_journal(db, ring)


def test_immutable_sql_values_and_aad_corruption_before_any_restore_dml(journal):
    store, engine, ring = journal
    ticket = completed(store)
    with engine.begin() as db, pytest.raises(DBAPIError):
        db.execute(text("UPDATE integration_runs SET actor_id='changed' WHERE id=:identifier"), {"identifier": ticket.run_id})
    with engine.begin() as db:
        # Synthetic damage is intentionally introduced only after removing its
        # immutable trigger; the original metadata AAD must still reject it.
        suffix = "" if engine.dialect.name == "sqlite" else " ON integration_runs"
        db.exec_driver_sql("DROP TRIGGER preserve_integration_runs_update" + suffix)
        db.execute(text("UPDATE integration_runs SET actor_id='changed' WHERE id=:identifier"), {"identifier": ticket.run_id})
        count = db.scalar(select(func.count()).select_from(EVENT))
    with engine.begin() as db, pytest.raises(HistoryError, match="HISTORY_CORRUPT"):
        mark_restored_unconfirmed(db, ring)
    with engine.connect() as db:
        assert db.scalar(select(func.count()).select_from(EVENT)) == count


def test_expired_proof_budget_does_not_mutate(journal):
    store, engine, ring = journal
    ticket = store.accept("email", ACTOR, {"payload": {}}, {})
    with engine.begin() as db, pytest.raises(HistoryError, match="HISTORY_BUDGET_EXCEEDED"):
        mark_restored_unconfirmed(db, ring, deadline=time.monotonic() - 1)
    assert store.detail("email", ticket.run_id, ACTOR)["history_status"] == "outcome_unconfirmed"
