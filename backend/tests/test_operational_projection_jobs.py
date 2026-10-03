"""Actual complete legacy-family behavior through durable bounded packets."""
# ruff: noqa: F811

from datetime import date, datetime

import pytest
from sqlalchemy import func, insert, select

from backend.db.operational_models import OperationalOccurrenceORM
from backend.db.orm_models import TaskORM
from backend.models import EscalationRuleCreate, MaintenanceCaseCreate, TaskCreate, TaskPatch
from backend.services import operational_jobs as jobs
from backend.services.operational_job_types import FAMILIES, JobContinue, JobCreate, PacketPolicy
from backend.services.operational_job_validation import validate_job_journal
from backend.services.tenant_privacy import export_tenant_metadata
from backend.tests.test_durable_scheduler import active as active
from backend.tests.test_durable_scheduler import finish
from backend.tests.test_durable_scheduler import installation as installation
from backend.tests.test_durable_scheduler import letter as letter
from backend.tests.test_operational_recovery_guards import complete_domain_test_schema


def test_all_projection_families_publish_deduped_effects_and_resolution(installation):
    box = installation
    if box.engine is not None:
        complete_domain_test_schema(box)
    task = box.store.create_task(TaskCreate(title="Inspect", due_date=date(2026, 10, 1), property_id=box.property.id))
    box.store.create_maintenance_case(MaintenanceCaseCreate(title="Repair", property_id=box.property.id,
        due_date=date(2026, 10, 2), appointment_at=datetime(2026, 10, 4, 11, 30)))
    box.store.create_escalation_rule(EscalationRuleCreate(name="Follow up", entity_type="task", condition_field="due_date",
        days_overdue=1, action="notify", target_role="verwalter", notification_severity="critical"))
    job = jobs.create_job(box.store, JobCreate(idempotency_key="all-projections", as_of=date(2026, 10, 3), families=FAMILIES), "actor")
    done = finish(box, job, width=1)
    assert done["state"] == "completed", done
    assert {row.event_type for row in box.store.list_calendar_events()} == {"deadline", "maintenance"}
    assert len(box.store.list_calendar_events()) == 4
    notices = box.store.list_notifications()
    assert {row.notification_type for row in notices} == {"task_due", "escalation", "contract_expiry"}
    assert len(notices) == 3
    exported = export_tenant_metadata(box.store, box.tenant.id)
    own = exported["operational_work_items"]
    assert len(own) == 1 and own[0]["source_id"] == box.contract.id
    assert own[0]["result"]["effect_key"]
    box.store._patch_entity("task", task.id, TaskPatch(status="completed"))
    again = jobs.create_job(box.store, JobCreate(idempotency_key="resolve", as_of=date(2026, 10, 3), families=FAMILIES), "actor")
    assert finish(box, again, width=2)["state"] == "completed"
    assert len(box.store.list_notifications()) == 3 and len(box.store.list_calendar_events()) == 4
    assert all(row.status == "archived" for row in box.store.list_notifications() if row.entity_id == task.id)
    if box.engine is not None:
        with box.engine.connect() as connection:
            assert validate_job_journal(connection)


def test_ten_thousand_escalation_sources_resume_without_legacy_tick_limit(installation):
    box = installation
    if box.engine is None:
        pytest.skip("Large actual SQLite workset")
    stamp = datetime(2026, 1, 1)
    with box.engine.begin() as connection:
        connection.execute(insert(TaskORM), [{"id": f"escalate-{index:05}", "title": "Task", "due_date": date(2026, 1, 1),
            "priority": "medium", "status": "open", "created_at": stamp, "updated_at": stamp} for index in range(10003)])
    box.store.create_escalation_rule(EscalationRuleCreate(name="Large backlog", entity_type="task", condition_field="due_date",
        days_overdue=1, action="notify", target_role="verwalter"))
    job = jobs.create_job(box.store, JobCreate(idempotency_key="large-escalation", as_of=date(2026, 10, 3),
        families=("escalation", "task_deadline")), "actor")
    policy = PacketPolicy(page_size=256, packet_seconds=2, lease_seconds=20)
    for index in range(200):
        current = jobs.continue_job(box.store, job["id"], JobContinue(max_items=256), "actor", policy=policy)
        if index == 1:
            assert len(box.store.list_calendar_events()) > 0  # Other family progresses before escalation finishes.
            box.db.close()
        if current["state"] == "completed":
            break
        assert current["state"] == "running", current
    else:
        pytest.fail("Large escalation did not make bounded progress")
    from backend.db.orm_models import NotificationORM
    assert box.db.scalar(select(func.count()).select_from(NotificationORM)) == 10003
    assert box.db.scalar(select(func.count()).select_from(OperationalOccurrenceORM)) == 10003
    with box.engine.connect() as connection:
        assert validate_job_journal(connection)
