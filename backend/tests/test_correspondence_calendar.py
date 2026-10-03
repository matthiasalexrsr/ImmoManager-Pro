"""Real approved sources, bounded resumable sweeps and one calendar transaction."""

from datetime import date
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import event, select

from backend.db.operational_models import OperationalOccurrenceORM, OperationalTickORM
from backend.models import ContractPatch
from backend.services import correspondence_calendar as projection
from backend.services import operational_schedule as operations
from backend.services.portfolio_scope import scope_context, scope_from_user
from backend.tests.test_contract_correspondence import approved, create
from backend.tests.test_contract_correspondence import letter as letter
from backend.tests.test_contract_lifecycle import active as active


@pytest.fixture
def calendar(letter):
    if letter.engine:
        with letter.engine.begin() as connection:
            operations.ensure_operational_schema(connection)
    return letter


def tick(box, actor="actor", **changes):
    with scope_context(scope_from_user(box.users[actor])):
        return operations.operational_tick(box.store, operations.TickRequest(as_of=date(2026, 11, 5), **changes), kinds={"calendar"})


def test_explicit_approved_date_is_projected_once_without_cash_or_legal_delivery_claims(calendar):
    original = approved(calendar)
    create(calendar, key="private-open", deadline_date="2026-11-05")
    before = calendar.store.get_contract(calendar.contract.id).model_dump(mode="json")
    first = tick(calendar)
    assert first["correspondence"]["created"] == first["calendar_events_created"] == 1
    item = calendar.store.get_calendar_event(first["calendar_event_ids"][0])
    assert item.event_date == date(2026, 11, 5)
    assert item.description.startswith("Bewusst bestätigter Verwaltungstermin, keine berechnete Rechtsfrist.")
    assert original["data"]["deadline_basis"] in item.description
    assert original["data"]["recipient_address"] not in item.description
    assert tick(calendar)["calendar_events_created"] == 0
    assert calendar.store.get_contract(calendar.contract.id).model_dump(mode="json") == before
    assert calendar.store.list_payments() == []


def test_changed_source_marks_the_existing_calendar_evidence_stale_without_moving_it_or_recreating_a_tombstone(calendar):
    original = approved(calendar)
    first = tick(calendar)
    identifier = first["calendar_event_ids"][0]
    before = calendar.store.get_calendar_event(identifier)
    calendar.store._patch_entity("contract", calendar.contract.id, ContractPatch(contract_number="Synthetic changed source"))
    result = tick(calendar)
    assert result["calendar_events_created"] == 0 and result["correspondence"]["stale_marked"] == 1
    current = calendar.store.get_calendar_event(identifier)
    assert current.event_date == before.event_date and current.title == before.title
    assert current.description == before.description + projection.STALE_MARKER
    assert tick(calendar)["correspondence"]["stale_marked"] == 0
    calendar.store.delete_calendar_event(identifier)
    assert tick(calendar)["calendar_events_created"] == 0
    assert calendar.store.get_document(original["document_id"]).file_url


def test_page_budget_one_and_tick_budget_one_resume_across_rows_with_sql_limits_before_materialization(calendar, monkeypatch):
    sources = [approved(calendar, key="source-" + str(index)) for index in range(4)]
    monkeypatch.setattr(projection, "settings", SimpleNamespace(contract_correspondence_page_max_size=1))
    selected = []
    if calendar.engine:
        def observe(connection, cursor, statement, parameters, context, executemany):
            if "ORDER BY contract_correspondence_drafts.deadline_date" in statement:
                selected.append((statement, parameters))
        event.listen(calendar.engine, "before_cursor_execute", observe)
    try:
        identifiers = []
        for index in range(4):
            result = tick(calendar, max_items=1)
            assert result["correspondence"]["scanned"] == result["calendar_events_created"] == 1
            assert result["correspondence"]["has_more"] is (index < 3)
            identifiers.extend(result["calendar_event_ids"])
        assert len(set(identifiers)) == len(sources)
        assert tick(calendar, max_items=1)["calendar_events_created"] == 0
        if calendar.engine:
            assert selected and all("LIMIT" in statement and parameters[-2] == 2 for statement, parameters in selected)
    finally:
        if calendar.engine:
            event.remove(calendar.engine, "before_cursor_execute", observe)


def test_no_explicit_actor_never_queries_correspondence_and_foreign_or_revoked_roles_publish_nothing(calendar, monkeypatch):
    approved(calendar)
    with monkeypatch.context() as patch:
        patch.setattr(projection, "_page", lambda *args: pytest.fail("Private journal read without explicit actor"))
        result = operations.operational_tick(calendar.store, operations.TickRequest(as_of=date(2026, 11, 5)), kinds={"calendar"})
    assert result["correspondence"] == {"enabled": False, "scanned": 0, "created": 0, "stale_marked": 0, "has_more": False, "reason": "explicit_actor_required"}


def test_foreign_and_readonly_actors_do_not_publish_another_portfolio_deadline(calendar):
    approved(calendar)
    assert tick(calendar, "foreign")["calendar_events_created"] == 0
    with pytest.raises(HTTPException) as failure:
        tick(calendar, "readonly")
    assert failure.value.status_code == 403


@pytest.mark.parametrize("failure", ["occurrence", "role"])
def test_failure_after_calendar_insert_rolls_back_calendar_occurrence_cursor_and_tick_together(calendar, monkeypatch, failure):
    approved(calendar)
    original = operations._Transaction.create
    def after_insert(tx, kind, payload):
        value = original(tx, kind, payload)
        if failure == "role":
            calendar.users["actor"]["role"] = "readonly"
        return value
    monkeypatch.setattr(operations._Transaction, "create", after_insert)
    if failure == "occurrence":
        monkeypatch.setattr(operations._Transaction, "record", lambda *args: (_ for _ in ()).throw(RuntimeError("Synthetic late occurrence failure")))
    with pytest.raises((HTTPException, RuntimeError)):
        tick(calendar)
    calendar.users["actor"]["role"] = "verwalter"
    assert calendar.store.list_calendar_events() == []
    if calendar.engine:
        with calendar.engine.connect() as connection:
            assert connection.scalar(select(OperationalOccurrenceORM.key).limit(1)) is None
            assert connection.scalar(select(OperationalTickORM.id).limit(1)) is None
    else:
        assert calendar.store._operational_state["occurrences"] == {} and calendar.store._operational_state["ticks"] == []


def test_scheduler_requires_an_explicit_trimmed_actor_but_does_not_impose_user_id_length_limits(calendar):
    scheduler = operations.OperationalScheduler(calendar.store, actor_id="  actor  ")
    assert scheduler.actor_id == "actor"
    assert operations.OperationalScheduler(calendar.store, actor_id="  ").actor_id is None
    assert operations.OperationalScheduler(calendar.store, actor_id="a" * 1000).actor_id == "a" * 1000


def test_internal_resume_cursor_is_not_published_as_a_user_recurrence_rule(calendar):
    approved(calendar)
    tick(calendar)
    for actor in ("actor", "foreign", "readonly"):
        with scope_context(scope_from_user(calendar.users[actor])):
            assert operations.list_schedules(calendar.store) == []
            assert operations.list_schedules(calendar.store, projection.CURSOR_KIND) == []
