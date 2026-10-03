"""Real memory/SQL operations: recurrence identity, rollback, payments and alerts."""
import multiprocessing
from datetime import date
from threading import Event
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session

from backend.db.operational_models import OperationalOccurrenceORM, OperationalTickORM
from backend.db.orm_models import Base, NotificationORM
from backend.models import CalendarEventCreate, EscalationRuleCreate, NotificationPatch, TaskCreate, TaskPatch
from backend.repositories.sql_store import SQLAlchemyStore
from backend.services.operational_schedule import (
    CalendarScheduleInput,
    OperationalScheduler,
    TickRequest,
    configure_calendar,
    generate_tasks,
    list_schedules,
    notification_visible,
    operational_tick,
    recent_ticks,
    scheduler_status,
    validate_escalation,
    validate_task_recurrence,
)
from backend.services.payments import PaymentReversalCreate
from backend.services.recurrence import CatchUpLimit
from backend.storage import InMemoryStore, ValidationError
from backend.tests.test_payments import payload, seed


def _engine(path):
    engine = create_engine(f"sqlite:///{path}", connect_args={"check_same_thread": False, "timeout": 10})
    @event.listens_for(engine, "connect")
    def sqlite_settings(connection, record):
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA journal_mode=WAL")
    return engine


@pytest.fixture(params=["memory", "sql"])
def operations(request, tmp_path):
    if request.param == "memory":
        yield InMemoryStore()
    else:
        engine = _engine(tmp_path / "operations.db")
        Base.metadata.create_all(engine)
        with Session(engine) as db:
            yield SQLAlchemyStore(db)
        engine.dispose()


def template(store, **changes):
    return store.create_task(TaskCreate(**{"title": "Monatskontrolle", "due_date": date(2026, 1, 31),
        "recurrence_rule": "FREQ=MONTHLY;COUNT=3", **changes}))


def rule(store, kind="task", **changes):
    return store.create_escalation_rule(EscalationRuleCreate(**{"name": "Überfällig", "entity_type": kind,
        "condition_field": "due_date", "days_overdue": 7, "action": "notify", **changes}))


def test_month_anchor_survives_clamp_move_completion_and_template_edit(operations):
    original = template(operations)
    first, = generate_tasks(operations, date(2026, 2, 28))
    assert first.due_date == date(2026, 2, 28)
    assert generate_tasks(operations, date(2026, 3, 31)) == []  # one open child
    operations._patch_entity("task", first.id, TaskPatch(due_date=date(2026, 2, 10), status="completed"))
    operations._patch_entity("task", original.id, TaskPatch(due_date=date(2027, 1, 1)))
    second, = generate_tasks(operations, date(2026, 3, 31))
    assert second.due_date == date(2026, 3, 31)
    operations._patch_entity("task", second.id, TaskPatch(status="completed"))
    third, = generate_tasks(operations, date(2026, 4, 30))
    assert third.due_date == date(2026, 4, 30)
    operations._patch_entity("task", third.id, TaskPatch(status="completed"))
    assert generate_tasks(operations, date(2026, 7, 31)) == []  # legacy COUNT is child count
    assert list_schedules(operations, "task")[0]["anchor_date"] == date(2026, 1, 31)


def test_deleted_instance_is_not_recreated_and_legacy_child_is_adopted(operations):
    original = template(operations)
    legacy = operations.create_task(TaskCreate(title=original.title, parent_task_id=original.id,
        due_date=date(2026, 2, 28), status="completed"))
    second, = generate_tasks(operations, date(2026, 3, 31))
    operations.delete_task(legacy.id)
    operations.delete_task(second.id)
    third, = generate_tasks(operations, date(2026, 4, 30))
    assert third.due_date == date(2026, 4, 30)


def test_full_catchup_and_limit_are_atomic_across_multiple_series(operations):
    template(operations)
    template(operations, title="Weitere Kontrolle")
    with pytest.raises(CatchUpLimit):
        operational_tick(operations, TickRequest(as_of=date(2026, 4, 30), full_catch_up=True, max_items=5), kinds={"tasks"})
    assert len(operations.list_tasks()) == 2
    assert list_schedules(operations) == []
    assert recent_ticks(operations) == []
    result = operational_tick(operations, TickRequest(as_of=date(2026, 4, 30), full_catch_up=True, max_items=6), kinds={"tasks"})
    assert result["tasks_created"] == 6
    assert operational_tick(operations, TickRequest(as_of=date(2026, 4, 30), full_catch_up=True, max_items=1), kinds={"tasks"})["tasks_created"] == 0


def test_bounded_window_does_not_silently_expand_daily_catchup(operations):
    template(operations, due_date=date(2020, 1, 1), recurrence_rule="FREQ=DAILY")
    result = operational_tick(operations, TickRequest(as_of=date(2026, 9, 30), full_catch_up=True, lookback_days=7, max_items=8), kinds={"tasks"})
    assert result["tasks_created"] == 8
    assert min(task.due_date for task in operations.list_tasks() if task.parent_task_id) == date(2026, 9, 23)
    assert result["lookback_days"] == 7


def test_calendar_plan_uses_original_anchor_and_retains_deleted_occurrences(operations):
    original = operations.create_calendar_event(CalendarEventCreate(title="Wartung", event_type="maintenance", event_date=date(2026, 1, 31)))
    configured = configure_calendar(operations, original.id, CalendarScheduleInput(recurrence_rule="FREQ=MONTHLY;COUNT=3"))
    assert configured["anchor_date"] == original.event_date
    first = operational_tick(operations, TickRequest(as_of=date(2026, 2, 28)), kinds={"calendar"})
    generated = operations.get_calendar_event(first["calendar_event_ids"][0])
    assert generated.event_date == date(2026, 2, 28)
    operations.delete_calendar_event(generated.id)
    second = operational_tick(operations, TickRequest(as_of=date(2026, 3, 31)), kinds={"calendar"})
    assert second["calendar_events_created"] == 1
    assert operations.get_calendar_event(second["calendar_event_ids"][0]).event_date == date(2026, 3, 31)
    assert operational_tick(operations, TickRequest(as_of=date(2026, 4, 30)), kinds={"calendar"})["calendar_events_created"] == 0
    configure_calendar(operations, original.id, CalendarScheduleInput(recurrence_rule="FREQ=MONTHLY", active=False))
    assert operational_tick(operations, TickRequest(as_of=date(2026, 5, 31)), kinds={"calendar"})["calendar_events_created"] == 0


def test_task_deadline_is_projected_once_and_manual_deletion_is_respected(operations):
    operations.create_task(TaskCreate(title="Betriebskosten prüfen", due_date=date(2026, 10, 15)))
    first = operational_tick(operations, TickRequest(as_of=date(2026, 9, 30)), kinds={"calendar"})
    assert first["calendar_events_created"] == 1
    event = operations.get_calendar_event(first["calendar_event_ids"][0])
    assert event.event_date == date(2026, 10, 15)
    assert event.event_type == "deadline"
    operations.delete_calendar_event(event.id)
    assert operational_tick(operations, TickRequest(as_of=date(2026, 10, 1)), kinds={"calendar"})["calendar_events_created"] == 0


@pytest.mark.parametrize("kind", ["receivable", "rent_charge"])
def test_partial_paid_reversed_balance_refreshes_one_alert_and_role_visibility(operations, kind):
    target = seed(operations, kind)
    rule(operations, kind, target_role="verwalter")
    first = operations.record_payment(kind, target.id, payload("40.10"))
    result = operational_tick(operations, TickRequest(as_of=date(2026, 9, 30)), kinds={"escalation"})
    alert_id, = result["notification_ids"]
    assert "60.20 EUR" in operations.get_notification(alert_id).content
    assert notification_visible(operations, alert_id, "verwalter")
    assert notification_visible(operations, alert_id, "eigentuemer")
    assert not notification_visible(operations, alert_id, "readonly")
    assert operational_tick(operations, TickRequest(as_of=date(2026, 10, 1)), kinds={"escalation"})["notifications_generated"] == 0
    second = operations.record_payment(kind, target.id, payload("60.20"))
    operational_tick(operations, TickRequest(as_of=date(2026, 10, 1)), kinds={"escalation"})
    assert operations.get_notification(alert_id).status == "archived"
    operations.reverse_payment(kind, target.id, second.id, PaymentReversalCreate(idempotency_key=str(uuid4()), reversal_date=date(2026, 10, 2), reason="Fehlerhafte Zahlung"))
    result = operational_tick(operations, TickRequest(as_of=date(2026, 10, 3)), kinds={"escalation"})
    assert result["notifications_generated"] == 0
    assert operations.get_notification(alert_id).status == "unread"
    assert "60.20 EUR" in operations.get_notification(alert_id).content
    operations.reverse_payment(kind, target.id, first.id, PaymentReversalCreate(idempotency_key=str(uuid4()), reversal_date=date(2026, 10, 3), reason="Zweite Korrektur"))
    operational_tick(operations, TickRequest(as_of=date(2026, 10, 3)), kinds={"escalation"})
    assert "100.30 EUR" in operations.get_notification(alert_id).content
    assert len(operations.list_notifications()) == 1


def test_deleted_alert_stays_deleted(operations):
    task = operations.create_task(TaskCreate(title="Prüfung", due_date=date(2026, 9, 1)))
    rule(operations)
    result = operational_tick(operations, TickRequest(as_of=date(2026, 9, 30)), kinds={"escalation"})
    alert_id, = result["notification_ids"]
    operations.delete_notification(alert_id)
    assert operational_tick(operations, TickRequest(as_of=date(2026, 10, 1)), kinds={"escalation"})["notifications_generated"] == 0
    assert operations.list_notifications() == []
    operations._patch_entity("task", task.id, TaskPatch(status="completed"))
    operational_tick(operations, TickRequest(as_of=date(2026, 10, 1)), kinds={"escalation"})


def test_reader_archive_survives_payment_and_reversal(operations):
    target = seed(operations, "receivable")
    rule(operations, "receivable")
    result = operational_tick(operations, TickRequest(as_of=date(2026, 9, 30)), kinds={"escalation"})
    alert_id, = result["notification_ids"]
    operations._patch_entity("notification", alert_id, NotificationPatch(status="archived"))
    payment = operations.record_payment("receivable", target.id, payload("100.30"))
    operational_tick(operations, TickRequest(as_of=date(2026, 10, 1)), kinds={"escalation"})
    operations.reverse_payment("receivable", target.id, payment.id,
        PaymentReversalCreate(idempotency_key=str(uuid4()), reversal_date=date(2026, 10, 2), reason="Korrektur"))
    result = operational_tick(operations, TickRequest(as_of=date(2026, 10, 3)), kinds={"escalation"})
    assert result["notifications_generated"] == 0
    assert operations.get_notification(alert_id).status == "archived"
    assert "100.30 EUR" in operations.get_notification(alert_id).content
    assert len(operations.list_notifications()) == 1


def test_monthly_and_receivable_overdue_both_use_net_amount(operations):
    monthly = seed(operations, "rent_charge")
    operations.record_payment("rent_charge", monthly.id, payload("40.10"))
    result = operational_tick(operations, TickRequest(as_of=date(2026, 9, 30)), kinds={"overdue"})
    alert_id, = result["notification_ids"]
    assert "60.20 EUR" in operations.get_notification(alert_id).content
    assert operations.get_notification(alert_id).entity_type == "rent_charge"


@pytest.mark.parametrize("changes", [{"action": "reassign"}, {"condition_field": "title"}, {"days_overdue": -1}, {"target_role": "unknown"}])
def test_unsupported_rules_fail_truthfully(changes):
    with pytest.raises(ValidationError):
        validate_escalation(EscalationRuleCreate(**{"name": "Rule", "entity_type": "task", "condition_field": "due_date", "action": "notify", "days_overdue": 7, **changes}))


@pytest.mark.parametrize("changes", [{"due_date": None}, {"recurrence_rule": "FREQ=SECONDLY"}, {"recurrence_rule": "FREQ=MONTHLY;BYDAY=MO"}, {"parent_task_id": "other"}])
def test_invalid_recurrence_never_silently_falls_back(changes):
    with pytest.raises(ValidationError):
        validate_task_recurrence(TaskCreate(**{"title": "Test", "due_date": date(2026, 1, 31), "recurrence_rule": "FREQ=MONTHLY", **changes}))


def _process_tick(database, ready, output):
    engine = _engine(database)
    try:
        with Session(engine) as db:
            ready.wait(timeout=15)
            result = operational_tick(SQLAlchemyStore(db), TickRequest(as_of=date(2026, 3, 31), full_catch_up=True), kinds={"tasks", "due_tasks"})
            output.put({"tasks": result["tasks_created"], "notifications": result["notifications_generated"]})
    except Exception as exc:
        output.put({"error": type(exc).__name__})
    finally:
        engine.dispose()


def test_independent_processes_and_restart_keep_one_persistent_instance(tmp_path):
    path = str(tmp_path / "parallel.db")
    engine = _engine(path)
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        original = template(SQLAlchemyStore(db), recurrence_rule="FREQ=MONTHLY;COUNT=2")
    context = multiprocessing.get_context("spawn")
    ready, output = context.Event(), context.Queue()
    processes = [context.Process(target=_process_tick, args=(path, ready, output)) for _ in range(2)]
    for process in processes:
        process.start()
    ready.set()
    results = [output.get(timeout=35) for _ in processes]
    for process in processes:
        process.join(timeout=35)
        assert process.exitcode == 0
    assert all("error" not in result for result in results), results
    assert sum(result["tasks"] for result in results) == 2
    with Session(engine) as db:
        active = SQLAlchemyStore(db)
        assert len([task for task in active.list_tasks() if task.parent_task_id == original.id]) == 2
        assert len(db.scalars(select(OperationalOccurrenceORM)).all()) == 2
        assert len(db.scalars(select(OperationalTickORM)).all()) == 2
        for task in active.list_tasks():
            if task.parent_task_id:
                active.delete_task(task.id)
    engine.dispose()
    reopened = _engine(path)
    with Session(reopened) as db:
        assert generate_tasks(SQLAlchemyStore(db), date(2026, 4, 30), full_catch_up=True) == []
    reopened.dispose()


def test_sql_failure_rolls_back_business_rows_keys_and_run_history(tmp_path):
    engine = _engine(tmp_path / "rollback.db")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        active = SQLAlchemyStore(db)
        template(active)
        def fail(mapper, connection, target):
            raise RuntimeError("Synthetic notification fault")
        event.listen(NotificationORM, "before_insert", fail)
        try:
            with pytest.raises(RuntimeError, match="Synthetic"):
                operational_tick(active, TickRequest(as_of=date(2026, 2, 28)))
        finally:
            event.remove(NotificationORM, "before_insert", fail)
        assert len(active.list_tasks()) == 1
        assert not active.list_notifications()
        assert not db.scalars(select(OperationalOccurrenceORM)).all()
        assert recent_ticks(active) == []
    engine.dispose()


def test_scheduler_requires_explicit_enable_and_stops_without_second_tick(monkeypatch):
    called = Event()
    from backend.services import operational_scheduler as durable
    def packet(*args):
        called.set()
        return {"state": "running"}
    monkeypatch.setattr(durable, "advance", packet)
    disabled = OperationalScheduler(InMemoryStore())
    disabled.start()
    assert not called.is_set()
    assert not scheduler_status()["automatic_running"]
    enabled = OperationalScheduler(InMemoryStore(), enabled=True, interval_seconds=10, actor_id="explicit-synthetic-actor")
    enabled.start()
    assert called.wait(timeout=2)
    assert scheduler_status()["automatic_running"]
    enabled.stop()
    assert not scheduler_status()["automatic_running"]
    disabled.stop()
