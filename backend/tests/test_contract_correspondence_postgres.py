"""Real PostgreSQL head, separate transactions and immutable approval journal."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from alembic import command as migration
from alembic.config import Config
from fastapi import HTTPException
from sqlalchemy import inspect, text

from backend import auth
from backend.db.contract_correspondence_models import CORRESPONDENCE_MODELS
from backend.services import contract_correspondence as service
from backend.services.contract_correspondence_validation import validate_correspondence_journal
from backend.tests.test_contract_correspondence import approval, approved, event_payload, prepare
from backend.tests.test_contract_correspondence import (
    test_late_failure_publishes_no_document_version_or_command_and_exact_retry_succeeds as failure_case,
)
from backend.tests.test_contract_lifecycle_postgres import postgres as postgres


@pytest.fixture
def letter_pg(postgres, monkeypatch):
    # The reused fixture owns a UUID-only schema and migrates to z1. Upgrade
    # the actual frozen continuation, never create_all over an absent migration.
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", postgres.engine.url.render_as_string(hide_password=False).replace("%", "%%"))
    migration.upgrade(config, "a2a2b3c4d5e6")
    # The parent fixture supplies synthetic identity dictionaries rather than
    # a SQL user factory. Do not accidentally use ambient SQLite auth marker
    # ownership for the isolated PostgreSQL business-lock probe.
    monkeypatch.setattr(auth, "_user_store", auth.InMemoryUserStore())
    for model in CORRESPONDENCE_MODELS:
        assert {column["name"] for column in inspect(postgres.engine).get_columns(model.__tablename__)} == set(model.__table__.c.keys())
    return postgres


def test_postgres_independent_native_transactions_exact_approval_replays_one_original(letter_pg, monkeypatch):
    found = prepare(letter_pg)
    original = service.parents
    gate, pids = Barrier(2), []
    def observe(unit, contract_id, *, lock=False):
        if lock:
            pids.append(unit.db.scalar(text("SELECT pg_backend_pid()")))
            gate.wait(10)
        return original(unit, contract_id, lock=lock)
    monkeypatch.setattr(service, "parents", observe)
    def publish():
        return service.approve_draft(letter_pg.store, letter_pg.contract.id, found["id"], approval(found), "actor")
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = [future.result(30) for future in [pool.submit(publish), pool.submit(publish)]]
    assert results[0] == results[1] and len(set(pids)) == 2
    assert len(letter_pg.store.list_documents()) == 1
    with letter_pg.engine.connect() as connection:
        assert validate_correspondence_journal(connection)


def test_postgres_late_command_failure_preserves_review_and_rolls_back_all_generated_bytes(letter_pg, monkeypatch):
    failure_case(letter_pg, monkeypatch, "journal")
    with letter_pg.engine.connect() as connection:
        assert validate_correspondence_journal(connection)


def test_postgres_scope_revocation_before_commit_publishes_no_original_or_approval(letter_pg, monkeypatch):
    failure_case(letter_pg, monkeypatch, "role")


def test_postgres_competing_manual_event_cas_keeps_exact_winner_receipt(letter_pg):
    found = approved(letter_pg)
    gate = Barrier(2)
    def append(key):
        gate.wait(10)
        try:
            return service.record_event(letter_pg.store, letter_pg.contract.id, found["id"], event_payload(found, key), "actor")
        except HTTPException as error:
            return error.status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = [future.result(30) for future in [pool.submit(append, "pg-a"), pool.submit(append, "pg-b")]]
    assert len([value for value in results if isinstance(value, dict)]) == 1 and 409 in results
    winner = next(value for value in results if isinstance(value, dict))
    payload = event_payload(found, winner["event"]["data"]["idempotency_key"])
    assert service.record_event(letter_pg.store, letter_pg.contract.id, found["id"], payload, "actor") == winner
    with letter_pg.engine.connect() as connection:
        assert validate_correspondence_journal(connection)
