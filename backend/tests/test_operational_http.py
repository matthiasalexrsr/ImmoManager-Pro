"""Actual authentication/RBAC and operational API routes on synthetic data."""
from datetime import date

import pytest
from fastapi.testclient import TestClient

from backend import auth
from backend.app import app
from backend.models import CalendarEventCreate, TaskCreate
from backend.routers import calendar, escalation, notifications, tasks
from backend.services.operational_schedule import TickRequest, operational_tick
from backend.storage import InMemoryStore
from backend.tests.test_operational_schedule import rule


@pytest.fixture
def installation(monkeypatch):
    monkeypatch.setattr(auth, "_user_store", auth.InMemoryUserStore())
    monkeypatch.setattr(auth, "_auth_session_factory", None)
    active = InMemoryStore()
    for module in (calendar, escalation, notifications, tasks):
        monkeypatch.setattr(module, "store", active)
    with TestClient(app) as client:
        yield client, active


def credentials(role):
    user = auth.register_user(role, f"{role}@example.invalid", "Synthetic", "Strong123", role)
    return {"Authorization": "Bearer " + auth.create_access_token(user.id)}


@pytest.mark.parametrize("role,allowed", [("eigentuemer", True), ("verwalter", True), ("techniker", True), ("buchhaltung", False), ("readonly", False)])
def test_tick_and_calendar_schedule_follow_actual_operation_grants(installation, role, allowed):
    client, active = installation
    headers = credentials(role)
    original = active.create_calendar_event(CalendarEventCreate(title="Synthetic deadline", event_type="deadline", event_date=date(2026, 1, 31)))
    plan = client.put(f"/api/v1/calendar/{original.id}/schedule", headers=headers, json={"recurrence_rule": "FREQ=MONTHLY;COUNT=3"})
    assert plan.status_code == (200 if allowed else 403)
    tick = client.post("/api/v1/tasks/operational-tick", headers=headers, json={"as_of": "2026-03-31"})
    assert tick.status_code == (200 if allowed else 403)
    assert len(active.list_calendar_events()) == (3 if allowed else 1)
    assert client.get("/api/v1/tasks/operational-status", headers=headers).status_code == 200
    assert client.get("/api/v1/tasks/operational-ticks", headers=headers).status_code == 200


def test_anonymous_requests_and_invalid_rules_leave_no_changes(installation):
    client, active = installation
    assert client.post("/api/v1/tasks/operational-tick", json={}).status_code == 401
    headers = credentials("eigentuemer")
    missing_anchor = client.post("/api/v1/tasks", headers=headers, json={"title": "Synthetic", "recurrence_rule": "FREQ=MONTHLY"})
    assert missing_anchor.status_code == 400
    invalid = client.post("/api/v1/tasks", headers=headers, json={"title": "Synthetic", "due_date": "2026-01-31", "recurrence_rule": "FREQ=SECONDLY"})
    assert invalid.status_code == 400
    assert not active.list_tasks()
    assert client.post("/api/v1/tasks/operational-tick", headers=headers, json={"max_items": 0}).status_code == 422
    assert client.get("/api/v1/tasks/operational-ticks", headers=headers).json() == []


def test_manual_tick_result_persists_and_repeat_creates_nothing(installation):
    client, active = installation
    headers = credentials("eigentuemer")
    active.create_task(TaskCreate(title="Kontrolle", due_date=date(2026, 1, 31), recurrence_rule="FREQ=MONTHLY;COUNT=2"))
    payload = {"as_of": "2026-03-31", "full_catch_up": True}
    first = client.post("/api/v1/tasks/operational-tick", headers=headers, json=payload)
    assert first.status_code == 200
    assert first.json()["tasks_created"] == 2
    second = client.post("/api/v1/tasks/operational-tick", headers=headers, json=payload)
    assert second.status_code == 200
    assert second.json()["tasks_created"] == second.json()["notifications_generated"] == 0
    assert len(client.get("/api/v1/tasks/operational-ticks", headers=headers).json()) == 2


def test_editing_child_with_legacy_full_form_keeps_series_identity(installation):
    client, active = installation
    headers = credentials("eigentuemer")
    parent = active.create_task(TaskCreate(title="Monthly", due_date=date(2026, 1, 31), recurrence_rule="FREQ=MONTHLY"))
    created = client.post("/api/v1/tasks/generate-recurring?as_of=2026-02-28", headers=headers).json()[0]
    edited = client.put(f'/api/v1/tasks/{created["id"]}', headers=headers,
        json={"title": "Completed child", "due_date": "2026-02-28", "status": "completed"})
    assert edited.status_code == 200
    assert edited.json()["parent_task_id"] == parent.id
    second = client.post("/api/v1/tasks/generate-recurring?as_of=2026-03-31", headers=headers)
    assert second.status_code == 200
    assert second.json()[0]["due_date"] == "2026-03-31"


def test_targeted_notifications_are_filtered_on_list_get_and_mutation(installation):
    client, active = installation
    owner, manager, reader = credentials("eigentuemer"), credentials("verwalter"), credentials("readonly")
    active.create_task(TaskCreate(title="Overdue synthetic", due_date=date(2026, 9, 1)))
    rule(active, target_role="verwalter")
    alert_id, = operational_tick(active, TickRequest(as_of=date(2026, 9, 30)), kinds={"escalation"})["notification_ids"]
    for headers in (owner, manager):
        assert client.get("/api/v1/notifications", headers=headers).json()[0]["id"] == alert_id
        assert client.get(f"/api/v1/notifications/{alert_id}", headers=headers).status_code == 200
    assert client.get("/api/v1/notifications", headers=reader).json() == []
    assert client.get(f"/api/v1/notifications/{alert_id}", headers=reader).status_code == 404
    accountant = credentials("buchhaltung")
    assert client.post(f"/api/v1/notifications/{alert_id}/read", headers=accountant).status_code == 404
    assert client.patch(f"/api/v1/notifications/{alert_id}", headers=accountant, json={"content": "Forbidden"}).status_code == 404
    assert client.delete(f"/api/v1/notifications/{alert_id}", headers=accountant).status_code == 404
    assert active.get_notification(alert_id).status == "unread"
