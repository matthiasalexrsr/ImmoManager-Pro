"""Real PostgreSQL letter races; included by the mandatory no-skip native gate."""
import threading
from datetime import date
from typing import cast

import pytest
from archive_helpers import lease_with_document
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session, scoped_session, sessionmaker
from test_document_versions_postgres import postgres  # noqa: F401

from backend import auth
from backend.db.document_version_models import DocumentVersionORM
from backend.models import AllocationKeyCreate, BillingPeriodCreate, CostItemCreate
from backend.repositories import SQLAlchemyStore
from backend.routers import billing
from backend.services import billing_letters as letters
from backend.services.billing_letter_types import LetterPreview, LetterPublish


def _issued(target, number):
    lease = lease_with_document(target, number=number)
    period = target.create_billing_period(BillingPeriodCreate(property_id=lease["property"].id,
        label="BK 2025 " + number, start_date=date(2025, 1, 1), end_date=date(2025, 12, 31)))
    key = target.create_allocation_key(AllocationKeyCreate(property_id=lease["property"].id,
        name="Einheiten", key_type="unit_count"))
    target.create_cost_item(CostItemCreate(billing_period_id=period.id,
        description="Wasser", amount=1200, allocation_key_id=key.id))
    statement = billing.generate_utility_statements(period.id)[0]
    billing.finalize_billing_period(period.id)
    return period, statement


def _command(target, statement, actor_id, key):
    context = letters.context(target, statement.id, actor_id)
    payload = LetterPreview.model_validate({"source_revision": context["source_revision"], "data": {
        **context["defaults"], "sender_address": "Verwaltung 1\n01099 Dresden"}})
    shown = letters.preview(target, statement.id, payload, actor_id)
    return LetterPublish(**payload.model_dump(), review_hash=shown["review_hash"], idempotency_key=key)


@pytest.mark.parametrize("same_key", [True, False])
def test_cross_period_commands_serialize_only_the_same_actor_key(postgres, monkeypatch, same_key):  # noqa: F811
    engine, _ = postgres
    sessions = scoped_session(sessionmaker(engine))
    target = SQLAlchemyStore(cast(Session, sessions))
    monkeypatch.setattr(billing, "store", target)
    owner = auth.register_user("letters", "letters@example.test", "Verwaltung", "Secret123", "eigentuemer")
    _, first = _issued(target, "LETTER-A")
    _, second = _issued(target, "LETTER-B")
    commands = [_command(target, first, owner.id, "parallel-letter-command"),
                _command(target, second, owner.id, "parallel-letter-command" if same_key else "another-letter-command")]
    sessions.remove()
    locked, resume, started, entered, finished = (threading.Event() for _ in range(5))
    outcomes = {}
    original = letters._source

    def pause(unit, statement_id, *, lock=False):
        if lock and threading.current_thread().name == "letter-second":
            entered.set()
        result = original(unit, statement_id, lock=lock)
        if lock and threading.current_thread().name == "letter-first" and not locked.is_set():
            locked.set()
            assert resume.wait(15)
        return result

    monkeypatch.setattr(letters, "_source", pause)

    def publish(index):
        if index == 1:
            started.set()
        try:
            outcomes[index] = letters.publish(target, (first, second)[index].id, commands[index], owner.id)
        except HTTPException as error:
            outcomes[index] = error.status_code
        except BaseException as error:
            outcomes[index] = error
        finally:
            if index == 1:
                finished.set()
            sessions.remove()

    first_writer = threading.Thread(target=publish, args=(0,), name="letter-first")
    second_writer = threading.Thread(target=publish, args=(1,), name="letter-second")
    try:
        first_writer.start()
        assert locked.wait(15), outcomes
        second_writer.start()
        assert started.wait(5)
        if same_key:
            assert not entered.wait(0.5), "The same command entered parent locks before its predecessor committed"
        else:
            assert finished.wait(15), "Unrelated command keys must remain independent"
    finally:
        resume.set()
        first_writer.join(20)
        if second_writer.ident is not None:
            second_writer.join(20)
        sessions.remove()
    assert not first_writer.is_alive() and not second_writer.is_alive(), outcomes
    assert isinstance(outcomes.get(0), dict), outcomes
    assert outcomes.get(1) == 409 if same_key else isinstance(outcomes.get(1), dict), outcomes
    with Session(engine) as check:
        assert check.scalar(select(func.count()).select_from(DocumentVersionORM)) == (1 if same_key else 2)


def test_correction_finalization_waits_for_letter_publication_and_replay_still_works(postgres, monkeypatch):  # noqa: F811
    engine, _ = postgres
    sessions = scoped_session(sessionmaker(engine))
    target = SQLAlchemyStore(cast(Session, sessions))
    monkeypatch.setattr(billing, "store", target)
    owner = auth.register_user("letters", "letters@example.test", "Verwaltung", "Secret123", "eigentuemer")
    period, statement = _issued(target, "LETTER-C")
    command = _command(target, statement, owner.id, "letter-before-correction")
    correction = billing.create_period_revision(period.id)["new_period_id"]
    billing.generate_utility_statements(correction)
    sessions.remove()
    locked, resume, finished = (threading.Event() for _ in range(3))
    outcomes = {}
    original = letters._source

    def pause(unit, statement_id, *, lock=False):
        result = original(unit, statement_id, lock=lock)
        if lock and threading.current_thread().name == "letter-first" and not locked.is_set():
            locked.set()
            assert resume.wait(15)
        return result

    monkeypatch.setattr(letters, "_source", pause)

    def publish():
        try:
            outcomes["letter"] = letters.publish(target, statement.id, command, owner.id)
        except BaseException as error:
            outcomes["letter"] = error
        finally:
            sessions.remove()

    def finalize():
        try:
            outcomes["correction"] = billing.finalize_billing_period(correction).status
        except BaseException as error:
            outcomes["correction"] = error
        finally:
            finished.set()
            sessions.remove()

    writer = threading.Thread(target=publish, name="letter-first")
    finalizer = threading.Thread(target=finalize)
    try:
        writer.start()
        assert locked.wait(15), outcomes
        finalizer.start()
        assert not finished.wait(0.5), outcomes
    finally:
        resume.set()
        writer.join(20)
        if finalizer.ident is not None:
            finalizer.join(20)
        sessions.remove()
    assert not writer.is_alive() and not finalizer.is_alive(), outcomes
    assert isinstance(outcomes.get("letter"), dict) and outcomes.get("correction") == "finalized", outcomes
    assert target.get_billing_period(period.id).status == "corrected"
    assert letters.publish(target, statement.id, command, owner.id) == outcomes["letter"]
    with pytest.raises(HTTPException) as stale:
        letters.publish(target, statement.id, command.model_copy(update={"idempotency_key": "new-after-correction"}), owner.id)
    assert stale.value.status_code == 412
    sessions.remove()
