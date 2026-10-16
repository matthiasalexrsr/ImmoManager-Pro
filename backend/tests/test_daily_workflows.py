"""Independent daily workflows: owner isolation, complete counts, replay and rollback."""
from datetime import datetime
from importlib import import_module
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, text

from backend import auth
from backend.dependencies import store
from backend.models import NotificationCreate, NotificationPatch, PortfolioCreate, PropertyCreate, TaskCreate
from backend.routers import auth as auth_router
from backend.routers import notifications
from backend.services import daily_state, settings_catalogue

app = FastAPI()
app.include_router(notifications.router, prefix="/api/v1")
app.include_router(auth_router.router, prefix="/api/v1")
API = "/api/v1/notifications"


@pytest.fixture(autouse=True)
def clean():
    from backend.audit import clear_audit_logs
    clear_audit_logs()
    auth.clear_users()
    store.clear_all()
    for key in ("_daily_state", "_daily_commands", "_daily_preferences", "_daily_rules", "_daily_audit"):
        store.__dict__.pop(key, None)
    yield
    auth.clear_users()
    store.clear_all()


def client(name, role="eigentuemer", **kwargs):
    user = auth.register_user(name, name + "@example.test", name, "Secret123", role, **kwargs)
    return user, TestClient(app, headers={"Authorization": "Bearer " + auth.create_access_token(user.id)})


def notice(**kwargs):
    return store.create_notification(NotificationCreate(notification_type="task_due", title="Umbenannter deutscher Vorgang", content="Beleg", **kwargs))


def command(**kwargs):
    return {"base_revision": 0, "idempotency_key": str(uuid4()), **kwargs}


def landed(client, item):
    source = client.get(f"{API}/{item.id}/source").json()["source"]
    return command(action="landed", source_kind=source["kind"], source_id=source["entity_id"], source_revision=source["revision"])


def test_personal_receipts_replay_cas_reopen_and_legacy_adoption():
    task = store.create_task(TaskCreate(title="Aktenname unabhängig vom Hinweis"))
    item = notice(entity_type="task", entity_id=task.id, status="archived", read_at=datetime(2020, 1, 2))
    store._patch_entity("notification", item.id, NotificationPatch(read_at=datetime(2020, 1, 2)))
    a, ca = client("alpha")
    _, cb = client("beta")
    rows = ca.get(API + "/inbox").json()
    assert rows["unread_count"] == 1
    assert rows["items"][0]["read_at"] is None
    assert rows["items"][0]["legacy_read_at"].startswith("2020-01-02")
    body = landed(ca, item)
    response = ca.post(f"{API}/{item.id}/receipt", json=body)
    assert response.status_code == 200, response.text
    assert ca.post(f"{API}/{item.id}/receipt", json=body).json() == response.json()
    assert ca.post(f"{API}/{item.id}/receipt", json={**body, "base_revision": 5}).status_code == 409
    assert ca.post(f"{API}/{item.id}/receipt", json={**body, "idempotency_key": str(uuid4())}).status_code == 409
    assert ca.get(API + "/inbox").json()["unread_count"] == 0
    assert cb.get(API + "/inbox").json()["unread_count"] == 1
    assert store.get_notification(item.id).read_at == datetime(2020, 1, 2)
    assert ca.post(f"{API}/{item.id}/receipt", json=command(action="reopen", base_revision=1)).status_code == 200
    assert ca.get(API + "/inbox").json()["unread_count"] == 1
    assert ca.patch(f"{API}/{item.id}", json={"status": "read"}).status_code == 409


def test_all_read_is_complete_and_atomic_across_pages_and_tabs():
    _, ca = client("complete")
    _, cb = client("independent")
    for _ in range(27):
        notice()
    initial = ca.get(API + "/inbox?limit=10").json()
    assert len(initial["items"]) == 10
    assert initial["total"] == initial["unread_count"] == 27
    notice()
    stale = command(action="read_all", snapshot=initial["snapshot"])
    assert ca.post(API + "/all/receipt", json=stale).status_code == 409
    fresh = ca.get(API + "/inbox?limit=10").json()
    body = command(action="read_all", snapshot=fresh["snapshot"])
    response = ca.post(API + "/all/receipt", json=body)
    assert response.json() == {"acknowledged": 28, "unread_count": 0}
    assert ca.post(API + "/all/receipt", json=body).json() == response.json()
    assert ca.post(API + "/all/receipt", json={**body, "idempotency_key": str(uuid4())}).status_code == 409
    assert cb.get(API + "/inbox").json()["unread_count"] == 28


def test_failed_source_and_failed_transaction_preserve_inbox(monkeypatch):
    _, ca = client("failures")
    task = store.create_task(TaskCreate(title="Vorhanden"))
    item = notice(entity_type="task", entity_id=task.id)
    body = landed(ca, item)
    original = daily_state.remember
    def crash(*args):
        raise RuntimeError("injected crash before commit")
    monkeypatch.setattr(daily_state, "remember", crash)
    with pytest.raises(RuntimeError):
        ca.post(f"{API}/{item.id}/receipt", json=body)
    assert ca.get(API + "/inbox").json()["unread_count"] == 1
    monkeypatch.setattr(daily_state, "remember", original)
    store.delete_task(task.id)
    assert ca.get(f"{API}/{item.id}/source").status_code == 404
    assert ca.post(f"{API}/{item.id}/receipt", json=body).status_code == 404
    assert ca.get(API + "/inbox").json()["unread_count"] == 1


def test_reader_receipts_do_not_grant_business_writes_or_foreign_receipts():
    from backend.permissions import may_write
    assert may_write("readonly", "/notifications/abc/receipt")
    assert not may_write("readonly", "/notifications/abc")
    assert not may_write("readonly", "/notifications/templates")
    _, ca = client("reader", "readonly")
    notice()
    body = command(action="read_all", snapshot=ca.get(API + "/inbox").json()["snapshot"], owner_id="foreign")
    assert ca.post(API + "/all/receipt", json=body).status_code == 422
    assert ca.get(API + "/inbox").json()["unread_count"] == 1


def test_settings_cas_validation_replay_and_independent_users():
    a, ca = client("preferences", "readonly")
    _, cb = client("otherprefs")
    url = "/api/v1/auth/users/me/settings"
    body = command(values={"date_format": "YYYY-MM-DD", "email_notifications": "none", "reminder_days": "14", "default_due_day": 15})
    saved = ca.put(url, json=body)
    assert saved.status_code == 200, saved.text
    assert ca.put(url, json=body).json() == saved.json()
    assert ca.put(url, json={**body, "values": {"reminder_days": "30"}}).status_code == 409
    assert ca.put(url, json=command(values={"default_due_day": 0}, base_revision=1)).status_code == 422
    assert ca.put(url, json=command(values={"default_due_day": 9})).status_code == 409
    assert cb.get("/api/v1/auth/users/me/preferences").json()["default_due_day"] == 1
    assert not settings_catalogue.email_allowed(store, a.id, "error")
    assert ca.put(url, json=command(values={"backup_daily_at": "00:00"}, base_revision=1)).status_code == 422
    assert ca.put(url, json=command(values={"default_due_day": 7}, scope="global")).status_code == 403
    assert all(n["scope"] == "personal" for n in ca.get(url).json()["items"])


def test_settings_scope_precedence_and_env_are_actual_sources():
    a, ca = client("rules")
    prop = store.create_property(PropertyCreate(portfolio_id=store.create_portfolio(PortfolioCreate(name="Nord")).id,
                                               name="Haus", property_type="residential"))
    url = "/api/v1/auth/users/me/settings"
    assert ca.put(url, json=command(values={"default_due_day": 5}, scope="global")).status_code == 200
    assert ca.put(url, json=command(values={"default_due_day": 9}, scope="object:" + prop.id)).status_code == 200
    rows = ca.get(url + "?property_id=" + prop.id).json()["items"]
    own = next(n for n in rows if n["key"] == "default_due_day" and n["scope"] == "personal")
    assert (own["value"], own["origin"]) == (9, "object:" + prop.id)
    assert ca.put(url, json=command(values={"default_due_day": 15})).status_code == 200
    rows = ca.get(url + "?property_id=" + prop.id).json()["items"]
    assert next(n for n in rows if n["key"] == "default_due_day" and n["scope"] == "personal")["value"] == 15
    backup = next(n for n in rows if n["key"] == "backup_daily_at")
    assert backup["value"] == settings_catalogue.settings.backup_daily_at
    assert not backup["editable"] and backup["restart_required"]
    assert next(n for n in rows if n["secret"])["value"] == "••••••"


def test_additive_migration_preserves_legacy_original_values(tmp_path):
    engine = create_engine("sqlite:///" + str(tmp_path / "migration.db"))
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE users (id VARCHAR PRIMARY KEY)"))
        conn.execute(text("CREATE TABLE notifications (id VARCHAR PRIMARY KEY, status TEXT, read_at TEXT)"))
        conn.execute(text("INSERT INTO notifications VALUES ('old', 'archived', '2020-01-02')"))
        module = import_module("backend.db.migrations.versions.e160a1b2c305_daily_receipts_settings")
        with Operations.context(MigrationContext.configure(conn)):
            module.upgrade()
        assert tuple(conn.execute(text("SELECT * FROM notifications")).one()) == ("old", "archived", "2020-01-02")
        assert conn.execute(text("SELECT count(*) FROM daily_user_state")).scalar() == 0
        assert {"daily_user_state", "daily_commands", "daily_setting_rules"} <= set(inspect(conn).get_table_names())
    engine.dispose()

@pytest.mark.parametrize("role", ["readonly", "buchhaltung", "verwalter"])
def test_current_grants_and_source_changes_fence_receipts(role):
    north = store.create_portfolio(PortfolioCreate(name="Sichtbar"))
    south = store.create_portfolio(PortfolioCreate(name="Nicht erlaubt"))
    prop = store.create_property(PropertyCreate(portfolio_id=north.id, name="Haus", property_type="residential"))
    task = store.create_task(TaskCreate(property_id=prop.id, title="Alt"))
    item = notice(entity_type="task", entity_id=task.id)
    actor, ca = client("scoped-" + role, role, portfolio_access="selected", portfolio_ids=[north.id])
    body = landed(ca, item)
    store.update_task(task.id, TaskCreate(property_id=prop.id, title="Neu"))
    assert ca.post(f"{API}/{item.id}/receipt", json=body).status_code == 409
    fresh = landed(ca, item)
    assert ca.post(f"{API}/{item.id}/receipt", json=fresh).status_code == 200
    auth.update_user(actor.id, {"portfolio_access": "selected", "portfolio_ids": [south.id]})
    assert ca.get(f"{API}/{item.id}/source").status_code == 404
    assert ca.post(f"{API}/{item.id}/receipt", json=fresh).status_code == 404
    assert ca.get(API + "/inbox").json()["total"] == 0
    auth.update_user(actor.id, {"portfolio_access": "selected", "portfolio_ids": [north.id]})
    assert ca.get(API + "/inbox").json()["items"][0]["status"] == "archived"


def test_settings_commit_failure_keeps_values_revision_and_audit_atomic(monkeypatch):
    actor, ca = client("settings-crash")
    url = "/api/v1/auth/users/me/settings"
    body = command(values={"date_format": "MM/DD/YYYY"})
    original = daily_state.remember
    def fail(*args):
        raise RuntimeError("injected audit failure")
    monkeypatch.setattr(daily_state, "remember", fail)
    with pytest.raises(RuntimeError):
        ca.put(url, json=body)
    result = ca.get("/api/v1/auth/users/me/preferences").json()
    assert result["date_format"] == "DD.MM.YYYY" and result["_revision"] == 0
    monkeypatch.setattr(daily_state, "remember", original)
    assert ca.put(url, json=body).status_code == 200
    assert ca.get("/api/v1/auth/users/me/preferences").json()["_revision"] == 1


def test_personal_reset_restores_actual_global_rule_and_legacy_route_remains_authoritative():
    _, ca = client("inheritance")
    url = "/api/v1/auth/users/me/settings"
    assert ca.put(url, json=command(values={"reminder_days": "30"}, scope="global")).status_code == 200
    assert ca.put(url, json=command(values={"reminder_days": "3"})).status_code == 200
    assert ca.get("/api/v1/auth/users/me/settings/effective").json()["reminder_days"] == "3"
    reset = command(values={"reminder_days": "3"}, reset=True, base_revision=1)
    assert ca.put(url, json=reset).json()["response"]["reminder_days"] == "30"
    saved = ca.put("/api/v1/auth/users/me/preferences", json={"reminder_days": "14", "_revision": 2})
    assert saved.status_code == 200
    assert saved.json()["reminder_days"] == "14"
    assert next(n for n in ca.get(url).json()["items"] if n["key"] == "reminder_days" and n["scope"] == "personal")["value"] == "14"
    assert ca.put("/api/v1/auth/users/me/preferences", json={"reminder_days": "7", "_revision": 2}).status_code == 409


def test_email_policy_is_per_account_and_does_not_hide_in_app_notices():
    first, ca = client("email-first")
    second, cb = client("email-second")
    for severity in ("info", "warning", "error"):
        notice(severity=severity)
    ca.put("/api/v1/auth/users/me/settings", json=command(values={"email_notifications": "none"}))
    assert ca.get(API + "/inbox").json()["unread_count"] == 3
    assert not any(n["email_eligible"] for n in ca.get(API + "/inbox").json()["items"])
    assert sum(n["email_eligible"] for n in cb.get(API + "/inbox").json()["items"]) == 2
    assert not settings_catalogue.email_allowed(store, first.id, "error")
    assert settings_catalogue.email_allowed(store, second.id, "warning")
    assert not settings_catalogue.email_allowed(store, second.id, "info")


def test_full_backup_restore_reopens_personal_state_audit_and_original_bytes(tmp_path):
    from sqlalchemy.orm import Session

    from backend.db.daily_models import DailyCommandORM, DailyStateORM, SettingRuleORM
    from backend.db.orm_models import Base, UserORM, UserPreferencesORM
    from backend.services.full_backup import Sources, create_full_backup, restore_archive
    data = tmp_path / "synthetic"
    uploads = data / "uploads"
    uploads.mkdir(parents=True)
    original = bytes(range(256)) * 53 + b"original-not-editable"
    (uploads / "original.bin").write_bytes(original)
    database = data / "immo_manager.db"
    engine = create_engine("sqlite:///" + database.as_posix())
    Base.metadata.create_all(engine)
    stamp = datetime(2026, 10, 16, 12)
    with Session(engine) as db:
        db.add(UserORM(id="restore-reader", username="restore-reader", email="restore@example.test", full_name="Leser", hashed_password="synthetic-only", role="readonly"))
        db.flush()
        db.add(UserPreferencesORM(user_id="restore-reader", date_format="YYYY-MM-DD", reminder_days="14"))
        db.add(DailyStateORM(owner_id="restore-reader", key="notice:source-123", revision=3,
                             payload={"read_at": "2026-10-16T12:00:00Z", "archived_at": "2026-10-16T12:00:00Z"}, updated_at=stamp))
        db.add(DailyCommandORM(owner_id="restore-reader", key="lost-response", fingerprint="a" * 64,
                               result={"response": {"revision": 3}}, created_at=stamp))
        db.add(SettingRuleORM(scope="object:house-123", key="default_due_day", revision=4, payload={"value": 9}, updated_at=stamp))
        db.commit()
    engine.dispose()
    sources = Sources(database_url="sqlite:///" + database.as_posix(), data_dir=data, uploads_dir=uploads,
                      root=data / "backups" / "full", integration_state=data / "missing-integrations.json",
                      key_file=data / "missing-key.json", env_file=data / "missing-env")
    event = create_full_backup("manual", sources)
    assert event["ok"]
    target = tmp_path / "restored"
    restore_archive(sources.root / event["archive"], target)
    assert (target / "uploads" / "original.bin").read_bytes() == original
    restored = create_engine("sqlite:///" + (target / "immo_manager.db").as_posix())
    with Session(restored) as db:
        restored_revision = db.get(DailyStateORM, ("restore-reader", "notice:source-123"))
        assert restored_revision is not None
        assert restored_revision.revision == 3
        restored_result = db.get(DailyCommandORM, ("restore-reader", "lost-response"))
        assert restored_result is not None
        assert restored_result.result == {"response": {"revision": 3}}
        restored_payload = db.get(SettingRuleORM, ("object:house-123", "default_due_day"))
        assert restored_payload is not None
        assert restored_payload.payload == {"value": 9}
        assert db.query(UserPreferencesORM).one().date_format == "YYYY-MM-DD"
    restored.dispose()


def test_additional_personal_controls_are_validated_durable_and_used_by_channel_policy():
    actor, ca = client("new-preferences", "readonly")
    url = "/api/v1/auth/users/me/settings"
    body = command(values={"density": "compact", "start_page": "/tasks", "quiet_start": "22:00", "quiet_end": "07:00", "email_notifications": "all"})
    saved = ca.put(url, json=body)
    assert saved.status_code == 200, saved.text
    current = ca.get("/api/v1/auth/users/me/preferences").json()
    assert {key: current[key] for key in body["values"]} == body["values"]
    assert ca.put(url, json=command(values={"quiet_start": "24:90"}, base_revision=1)).status_code == 422
    assert ca.put(url, json=command(values={"start_page": "https://example.test"}, base_revision=1)).status_code == 422
    assert ca.put(url, json=command(values={"density": "tiny"}, base_revision=1)).status_code == 422
    # January is UTC+1: 21:00 UTC is the start, 06:00 UTC is the end.
    assert settings_catalogue.email_allowed(store, actor.id, "info", datetime.fromisoformat("2026-01-02T20:59:00+00:00"))
    assert not settings_catalogue.email_allowed(store, actor.id, "info", datetime.fromisoformat("2026-01-02T21:00:00+00:00"))
    assert not settings_catalogue.email_allowed(store, actor.id, "info", datetime.fromisoformat("2026-01-03T05:59:00+00:00"))
    assert settings_catalogue.email_allowed(store, actor.id, "info", datetime.fromisoformat("2026-01-03T06:00:00+00:00"))
    if hasattr(store, "db"):
        from sqlalchemy.orm import Session

        from backend.repositories.sql_store import SQLAlchemyStore
        with Session(store.db.get_bind()) as independent:
            reopened = settings_catalogue.prefs(SQLAlchemyStore(independent), actor.id)
            assert {key: reopened[key] for key in body["values"]} == body["values"]
            assert reopened["_revision"] == 1


def test_inbox_page_snapshot_refuses_changed_history_instead_of_skipping_items():
    _, ca = client("page-snapshot")
    for _ in range(12):
        notice()
    initial = ca.get(API + "/inbox?limit=5").json()
    second = ca.get(API + "/inbox", params={"limit": 5, "offset": 5, "expected_snapshot": initial["snapshot"]})
    assert second.status_code == 200
    assert not {n["id"] for n in initial["items"]} & {n["id"] for n in second.json()["items"]}
    notice()
    assert ca.get(API + "/inbox", params={"limit": 5, "offset": 10, "expected_snapshot": initial["snapshot"]}).status_code == 409


def test_complete_inbox_crash_rolls_back_every_receipt_and_the_command(monkeypatch):
    _, ca = client("all-crash")
    for _ in range(4):
        notice()
    page = ca.get(API + "/inbox").json()
    body = command(action="read_all", snapshot=page["snapshot"])
    original = daily_state.put_notice_batch
    calls = []
    def fail_second(*args, **kwargs):
        calls.append(1)
        result = original(*args, **kwargs)
        raise RuntimeError("injected interruption after receipt batch before commit")
        return result
    monkeypatch.setattr(daily_state, "put_notice_batch", fail_second)
    with pytest.raises(RuntimeError):
        ca.post(API + "/all/receipt", json=body)
    assert ca.get(API + "/inbox").json()["unread_count"] == 4
    monkeypatch.setattr(daily_state, "put_notice_batch", original)
    assert ca.post(API + "/all/receipt", json=body).json() == {"acknowledged": 4, "unread_count": 0}


def test_global_rule_audit_is_permanent_and_exactly_once_after_account_deletion():
    actor, ca = client("global-audit")
    body = command(values={"default_due_day": 12}, scope="global")
    assert ca.put("/api/v1/auth/users/me/settings", json=body).status_code == 200
    assert ca.put("/api/v1/auth/users/me/settings", json=body).status_code == 200
    auth.delete_user(actor.id)
    if hasattr(store, "db"):
        from backend.db.orm_models import AuditLogORM
        rows = store.db.query(AuditLogORM).filter(AuditLogORM.user_id == actor.id, AuditLogORM.action == "settings_change").all()
    else:
        from backend.audit import list_audit_logs
        rows = list_audit_logs(user_id=actor.id, action="settings_change")
    assert len(rows) == 1
    import json
    data = json.loads(rows[0].changes if hasattr(rows[0], "changes") else rows[0]["changes"])
    assert data["before"] == {"revision": 0, "payload": {}}
    assert data["after"] == {"revision": 1, "payload": {"value": 12}}
