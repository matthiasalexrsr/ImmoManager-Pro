"""Native persistent scheduler coordination and recurrence packet behavior."""
# ruff: noqa: F811

from datetime import date, timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import select, update

from backend.db.operational_job_models import OperationalJobORM, OperationalWorkItemORM
from backend.db.operational_models import OperationalOccurrenceORM
from backend.db.operational_scheduler_models import OperationalSchedulerORM
from backend.models import CalendarEventCreate, TaskCreate, TaskPatch
from backend.services import operational_jobs as jobs
from backend.services import operational_scheduler as scheduler
from backend.services.operational_job_types import FAMILIES, JobContinue, JobCreate, PacketPolicy
from backend.services.operational_job_validation import validate_job_journal
from backend.services.operational_schedule import CalendarScheduleInput, configure_calendar
from backend.tests.test_operational_jobs import active as active
from backend.tests.test_operational_jobs import jobs as installation  # noqa: F401
from backend.tests.test_operational_jobs import letter as letter

PARAMETERS = {"max_items": 7, "lookback_days": 30000, "interval_seconds": 300, "full_catch_up": True}


def finish(box, job, *, maximum=200, width=7):
    for _ in range(maximum):
        value = jobs.continue_job(box.store, job["id"], JobContinue(max_items=width), "actor")
        if value["state"] in {"completed", "attention"}:
            return value
    pytest.fail("Expected bounded packets to progress")


def expire(box):
    if box.db is not None:
        box.db.rollback()
        with box.engine.begin() as connection:
            connection.execute(update(OperationalSchedulerORM).values(lease_expires_at=jobs._clock() - timedelta(seconds=1)))
    else:
        box.store.__dict__[OperationalSchedulerORM.__tablename__]["automatic"].lease_expires_at = jobs._clock() - timedelta(seconds=1)


def test_reserved_generation_replays_created_unattached_job_and_never_adopts_manual(installation):
    box = installation
    manual = jobs.create_job(box.store, JobCreate(idempotency_key="automatic:1", as_of=date.today(), families=FAMILIES), "actor")
    claim = scheduler.reserve(box.store, "actor", PARAMETERS)
    created = jobs.create_job(box.store, JobCreate(idempotency_key="automatic:" + claim.generation_key,
        as_of=claim.as_of, lookback_days=PARAMETERS["lookback_days"], full_catch_up=True, families=FAMILIES), "actor")
    with pytest.raises(HTTPException):
        scheduler.attach(box.store, claim, manual["id"])
    expire(box)
    resumed = scheduler.advance(box.store, "actor", PARAMETERS)
    assert resumed["generation"] == claim.generation and resumed["job_id"] == created["id"]
    assert jobs.read_job(box.store, manual["id"], "actor")["state"] == "queued"
    with pytest.raises(jobs.ClaimLost):
        scheduler.attach(box.store, claim, created["id"])


def test_task_and_calendar_packets_keep_clamping_counts_and_deleted_tombstones(installation):
    box = installation
    template = box.store.create_task(TaskCreate(title="Monthly", due_date=date(2026, 1, 31), recurrence_rule="FREQ=MONTHLY;COUNT=3"))
    event = box.store.create_calendar_event(CalendarEventCreate(title="Monthly", event_date=date(2026, 1, 31), event_type="other"))
    configure_calendar(box.store, event.id, CalendarScheduleInput(recurrence_rule="FREQ=MONTHLY;COUNT=4"))
    values = dict(as_of=date(2026, 4, 30), families=("recurring_task", "recurring_calendar"), full_catch_up=True)
    job = jobs.create_job(box.store, JobCreate(idempotency_key="recurrence", **values), "actor")
    done = finish(box, job, width=1)
    assert done["state"] == "completed"
    children = [row for row in box.store.list_tasks() if row.parent_task_id == template.id]
    assert {row.due_date for row in children} == {date(2026, 2, 28), date(2026, 3, 31), date(2026, 4, 30)}
    assert len(box.store.list_calendar_events()) == 4
    box.store.delete_task(children[0].id)
    box.store._patch_entity("task", children[1].id, TaskPatch(due_date=date(2026, 3, 29)))
    repeated = jobs.create_job(box.store, JobCreate(idempotency_key="recurrence-again", **values), "actor")
    assert finish(box, repeated, width=2)["state"] == "completed"
    assert len(box.store.list_tasks()) == 3 and len(box.store.list_calendar_events()) == 4
    if box.engine is not None:
        with box.engine.connect() as connection:
            assert validate_job_journal(connection)


def test_changed_actor_blocks_coordinator_and_prepared_recurrence(installation):
    box = installation
    box.store.create_task(TaskCreate(title="Series", due_date=date(2026, 1, 1), recurrence_rule="FREQ=DAILY;COUNT=9"))
    initial = scheduler.advance(box.store, "actor", PARAMETERS)
    box.users["actor"]["is_active"] = False
    with pytest.raises(HTTPException):
        scheduler.advance(box.store, "actor", PARAMETERS)
    box.users["actor"]["is_active"] = True
    assert scheduler.status(box.store, "actor")["job_id"] == initial["job_id"]


def test_scheduler_progress_is_compatible_with_memory_privacy_snapshot(installation):
    from backend.services.tenant_privacy import _memory_copy, _memory_state
    box = installation
    if box.engine is not None:
        pytest.skip("Memory snapshot semantics")
    scheduler.advance(box.store, "actor", PARAMETERS)
    assert _memory_state(_memory_copy(box.store).__dict__) == _memory_state(_memory_copy(box.store).__dict__)


def test_real_ten_thousand_occurrences_continue_without_global_overflow(installation):
    box = installation
    if box.engine is None:
        pytest.skip("Large native SQL acceptance")
    template = box.store.create_task(TaskCreate(title="Long history", due_date=date(1990, 1, 1), recurrence_rule="FREQ=DAILY;COUNT=10003"))
    job = jobs.create_job(box.store, JobCreate(idempotency_key="large-series", as_of=date(2020, 1, 1),
        lookback_days=1, families=("recurring_task",), full_catch_up=True), "actor")
    policy = PacketPolicy(page_size=256, packet_seconds=2, lease_seconds=20)
    first_count = None
    for _ in range(250):
        value = jobs.continue_job(box.store, job["id"], JobContinue(max_items=256), "actor", policy=policy)
        if first_count is None:
            first_count = box.db.scalar(select(OperationalOccurrenceORM.key).where(OperationalOccurrenceORM.schedule_id == "task:" + template.id).limit(1))
            assert first_count is not None and value["state"] == "running"
            box.db.close()  # Real connection/session restart between packets.
        if value["state"] == "completed":
            break
        assert value["state"] == "running"
    else:
        pytest.fail("Large recurrence did not finish")
    from sqlalchemy import func
    assert box.db.scalar(select(func.count()).select_from(OperationalOccurrenceORM).where(
        OperationalOccurrenceORM.schedule_id == "task:" + template.id)) == 10003
    with box.engine.connect() as connection:
        assert validate_job_journal(connection)
    assert box.db.get(OperationalJobORM, job["id"]).state == "completed"


def test_full_history_ignores_lookback_and_completed_series_do_not_grow_work_journal(installation):
    box = installation
    box.store.create_task(TaskCreate(title="35 years", due_date=date(1990, 1, 1), recurrence_rule="FREQ=YEARLY;COUNT=35"))
    template = box.store.create_calendar_event(CalendarEventCreate(title="36 years", event_date=date(1990, 1, 1), event_type="other"))
    configure_calendar(box.store, template.id, CalendarScheduleInput(recurrence_rule="FREQ=YEARLY;COUNT=36", full_catch_up=True))
    parameters = dict(as_of=date(2026, 1, 1), lookback_days=1, families=("recurring_task", "recurring_calendar"), full_catch_up=True)
    first = jobs.create_job(box.store, JobCreate(idempotency_key="historic-series", **parameters), "actor")
    assert finish(box, first, width=4)["state"] == "completed"
    assert len(box.store.list_tasks()) == 36 and len(box.store.list_calendar_events()) == 36
    second = jobs.create_job(box.store, JobCreate(idempotency_key="historic-series-repeat", **parameters), "actor")
    assert finish(box, second, width=4)["state"] == "completed"
    if box.db is not None:
        assert box.db.scalar(select(OperationalWorkItemORM.id).where(OperationalWorkItemORM.job_id == second["id"]).limit(1)) is None
    else:
        assert not any(item.job_id == second["id"] for item in box.store.__dict__[OperationalWorkItemORM.__tablename__].values())


def test_automatic_configuration_accepts_long_history_without_legacy_tick_limits():
    from backend.services.operational_schedule import OperationalScheduler
    from backend.settings import Settings
    settings = Settings(operational_scheduler_lookback_days=30000, operational_scheduler_max_items=20000)
    worker = OperationalScheduler(None, lookback_days=settings.operational_scheduler_lookback_days,
                                  max_items=settings.operational_scheduler_max_items)
    assert worker.parameters == {"max_items": 20000, "lookback_days": 30000}


def test_upgrade_recovers_unattached_exact_legacy_receipt_instead_of_replacing_parameters(installation):
    from backend.services.contract_lifecycle import digest
    box = installation
    claim = scheduler.reserve(box.store, "actor", PARAMETERS)
    legacy = jobs.create_job(box.store, JobCreate(idempotency_key="automatic:" + claim.generation_key,
        as_of=claim.as_of, families=("recurring_task",), lookback_days=1, full_catch_up=True), "actor")
    frozen = {**legacy["parameters"], "semantics_version": 2}
    if box.db is not None:
        box.db.rollback()
        with box.engine.begin() as connection:
            connection.execute(update(OperationalJobORM).where(OperationalJobORM.id == legacy["id"])
                .values(parameters=frozen, request_hash=digest(frozen)))
    else:
        original = box.store.__dict__[OperationalJobORM.__tablename__][legacy["id"]]
        original.parameters, original.request_hash = frozen, digest(frozen)
    expire(box)
    resumed = scheduler.advance(box.store, "actor", PARAMETERS)
    assert resumed["job_id"] == legacy["id"] and resumed["families"] == ["recurring_task"]
    assert jobs.read_job(box.store, legacy["id"], "actor")["parameters"] == frozen


def test_late_legacy_child_is_adopted_after_reusing_completed_progress(installation):
    box = installation
    source = box.store.create_task(TaskCreate(title="Legacy continuation", due_date=date(2026, 1, 1), recurrence_rule="FREQ=DAILY"))
    parameters = dict(families=("recurring_task",), full_catch_up=True, lookback_days=1)
    first = jobs.create_job(box.store, JobCreate(idempotency_key="before-manual-child", as_of=date(2026, 1, 3), **parameters), "actor")
    assert finish(box, first, width=2)["state"] == "completed"
    child = box.store.create_task(TaskCreate(title="Imported legacy child", due_date=date(2026, 1, 4), parent_task_id=source.id))
    second = jobs.create_job(box.store, JobCreate(idempotency_key="after-manual-child", as_of=date(2026, 1, 4), **parameters), "actor")
    assert finish(box, second, width=2)["state"] == "completed"
    assert len(box.store.list_tasks()) == 4
    from backend.services.operational_schedule import _key
    if box.db is not None:
        record = box.db.get(OperationalOccurrenceORM, _key("task:" + source.id, date(2026, 1, 4)))
    else:
        record = box.store._operational_state["occurrences"][_key("task:" + source.id, date(2026, 1, 4))]
    assert record.target_id == child.id
