"""Real SQLUser/Sid HTTP command through the actual readonly RBAC middleware."""

from contextlib import contextmanager

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from backend import auth, dependencies
from backend.db.notification_inbox_models import NotificationReadStateORM
from backend.db.orm_models import NotificationORM
from backend.middleware import RBACWriteGuardMiddleware
from backend.routers import notification_inbox as inbox_router
from backend.routers import notifications as legacy_router
from backend.services import auth_sessions
from backend.services.portfolio_http import PortfolioScopeMiddleware
from backend.tests.test_notification_inbox_commit_authority import (
    _insert,
    _notice,
    _read_rows,
    read_installation,  # noqa: F401 — genuine shared SQLUser/Sid fixture
)

PATH = "/api/v1/notifications/inbox"


@pytest.fixture
def http_writer(read_installation, monkeypatch):
    box = read_installation
    monkeypatch.setattr(dependencies, "store", box.store)
    application = FastAPI()
    application.include_router(inbox_router.router, prefix="/api/v1")
    application.include_router(legacy_router.router, prefix="/api/v1")
    application.add_middleware(RBACWriteGuardMiddleware)
    with TestClient(PortfolioScopeMiddleware(application), base_url="http://127.0.0.1") as client:
        box.client = client
        yield box


def _headers(box, actor="reader-a"):
    return {"Authorization": "Bearer " + box.tokens[actor]}


def _private(response):
    assert response.headers["cache-control"] == "private, no-store"
    assert response.headers["vary"] == "Authorization"


def _post(box, identifier="notice", actor="reader-a", **kwargs):
    return box.client.post(PATH + "/" + identifier + "/read", headers=_headers(box, actor),
                           json=kwargs.pop("json", {}), **kwargs)


def test_http_actual_readonly_sid_can_read_own_notice_once_without_global_mutation(http_writer):
    box = http_writer
    _insert(box, [_notice("notice")])
    page = box.client.get(PATH, headers=_headers(box))
    assert page.status_code == 200 and page.json()["items"][0]["actions"] == {"mark_read": True}
    _private(page)
    first, replay = _post(box), _post(box)
    assert first.status_code == replay.status_code == 200
    assert first.json() == replay.json() and set(first.json()) == {"notification_id", "read_at"}
    _private(first)
    _private(replay)
    assert first.json()["notification_id"] == "notice" and len(_read_rows(box)) == 1
    read = box.client.get(PATH, headers=_headers(box), params={"status": "read"})
    assert read.status_code == 200 and read.json()["full_count"] == 1 and read.json()["unread_count"] == 0
    assert read.json()["items"][0]["actions"] == {"mark_read": False}
    other = box.client.get(PATH, headers=_headers(box, "reader-b"))
    assert other.status_code == 200 and other.json()["unread_count"] == 1
    with box.probe.connect() as connection:
        assert connection.execute(select(NotificationORM.status, NotificationORM.read_at).where(
            NotificationORM.id == "notice")).one() == ("unread", None)


def test_http_forged_actor_unknown_and_foreign_notice_do_not_create_receipts(http_writer):
    box = http_writer
    _insert(box, [_notice("notice"), _notice("foreign", entity_id="unit-two")])
    assert _post(box, json={"actor_id": "owner"}).status_code == 422
    assert _post(box, "foreign").status_code == 404
    assert _post(box, "absent").status_code == 404
    assert _read_rows(box) == []


def test_http_modern_selected_unsupported_task_has_no_action(http_writer):
    box = http_writer
    _insert(box, [_notice("notice"), _notice("task", entity_type="task", entity_id="task-one")])
    page = box.client.get(PATH, headers=_headers(box), params={"status": "all"})
    assert page.status_code == 200
    actions = {item["id"]: item["actions"]["mark_read"] for item in page.json()["items"]}
    assert actions == {"notice": True, "task": False}
    closed = _post(box, "task")
    assert closed.status_code == 503 and _read_rows(box) == []
    _private(closed)


def test_http_legacy_session_requires_reauthentication_and_revoked_sid_is_denied(http_writer):
    box = http_writer
    _insert(box, [_notice("notice")])
    headers = {"Authorization": "Bearer " + auth.create_access_token("reader-a")}
    page = box.client.get(PATH, headers=headers)
    assert page.status_code == 200 and page.json()["items"][0]["actions"] == {"mark_read": False}
    denied = box.client.post(PATH + "/notice/read", headers=headers, json={})
    assert denied.status_code == 401
    _private(denied)
    auth_sessions.revoke_from_token(box.tokens["reader-a"])
    assert _post(box).status_code == 401 and _read_rows(box) == []


def test_http_readonly_personal_command_does_not_allow_domain_writes_or_bulk_commands(http_writer):
    box = http_writer
    _insert(box, [_notice("notice")])
    headers = _headers(box)
    assert box.client.patch("/api/v1/notifications/notice", headers=headers, json={"status": "read"}).status_code == 403
    assert box.client.delete("/api/v1/notifications/notice", headers=headers).status_code == 403
    assert box.client.post(PATH + "/read-all", headers=headers, json={}).status_code == 403
    assert box.client.post(PATH + "/notice/read/more", headers=headers, json={}).status_code == 403
    assert box.client.patch(PATH + "/notice/read", headers=headers, json={}).status_code == 403
    assert _read_rows(box) == []


def test_http_missing_native_family_is_closed_without_ddl_repair(http_writer):
    box = http_writer
    _insert(box, [_notice("notice")])
    with box.probe.begin() as connection:
        NotificationReadStateORM.__table__.drop(connection)
    unavailable = _post(box)
    assert unavailable.status_code == 503 and "read_at" not in unavailable.json()
    _private(unavailable)
    with box.probe.connect() as connection:
        assert connection.exec_driver_sql(
            "SELECT count(*) FROM sqlite_master WHERE name='notification_read_states'"
        ).scalar_one() == 0
