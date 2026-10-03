"""Composed HTTP, startup and late credential failure on real transactions."""

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from jwt import api_jwt
from sqlalchemy import create_engine, inspect, select

from backend import auth
from backend.db import session as runtime
from backend.db.operational_job_models import JOB_MODELS
from backend.db.tenancy_workflow_models import TENANCY_WORKFLOW_MODELS, WorkflowTemplateORM
from backend.db.tenancy_workflow_schema import ensure_tenancy_workflow_schema
from backend.services import auth_sessions
from backend.services import tenancy_workflow as service
from backend.tests.test_portfolio_access_http import access_http as _access_http
from backend.tests.test_workflow_references_postgres import postgres as _postgres
from backend.tests.test_workflow_references_postgres import postgres_http as _postgres_http

access_http = _access_http
postgres, postgres_http = _postgres, _postgres_http


def template_body(property_id, key="http-template"):
    return {"idempotency_key": key, "expected_revision": "new", "property_id": property_id,
            "direction": "move_out", "steps": [{"stable_key": "handover", "position": 0,
                "title": "Wohnungsübergabe organisieren", "default_requirement": "required",
                "anchor": "move_out_handover", "offset_days": -7, "assignee_role": "techniker",
                "depends_on_step_keys": [], "evidence_requirement": "none"}]}


def prepare_guarded_sql(store):
    if hasattr(store, "db"):
        with store.db.get_bind().begin() as connection:
            ensure_tenancy_workflow_schema(connection)


def test_real_http_template_to_task_and_completion_obeys_roles_and_parent_cas(access_http):
    client, store, owner, manager, _, portfolios, properties, contracts, *_ = access_http
    prepare_guarded_sql(store)
    technician = auth.register_user("workflow-http-tech", "workflow-http-tech@example.test", "Assigned technician",
        "StrongPass123!", "techniker", portfolio_access="selected", portfolio_ids=[portfolios[0].id])
    tech = {"Authorization": "Bearer " + auth.create_access_token(technician.id)}
    body = template_body(properties[0].id)
    assert client.post("/api/v1/workflow-templates", headers=tech, json=body).status_code == 403
    assert client.post("/api/v1/workflow-templates", headers=manager,
                       json=template_body(properties[1].id, "hidden-template")).status_code == 404
    response = client.post("/api/v1/workflow-templates", headers=manager, json=body)
    assert response.status_code == 201, response.text
    draft = response.json()
    assert client.post("/api/v1/workflow-templates", headers=manager, json=body).json() == draft
    published_response = client.post(f"/api/v1/workflow-template-versions/{draft['id']}/publish", headers=manager,
        json={"idempotency_key": "publish-http", "expected_revision": draft["revision"]})
    assert published_response.status_code == 200, published_response.text
    published = published_response.json()
    selection = {"property_id": properties[0].id, "unit_id": contracts[0].unit_id,
        "previous_contract_id": contracts[0].id, "mode": "move_out", "move_out_handover_date": "2026-10-31",
        "move_out_template_version_id": published["id"]}
    preview_response = client.post("/api/v1/tenancy-changes/preview", headers=manager, json=selection)
    assert preview_response.status_code == 200, preview_response.text
    preview = preview_response.json()
    start = {**selection, "idempotency_key": "start-http", "expected_revision": "new",
             "preview_hash": preview["preview_hash"], "source_etags": preview["source_etags"]}
    started = client.post("/api/v1/tenancy-changes", headers=manager, json=start)
    assert started.status_code == 201, started.text
    change = started.json()
    assert client.post("/api/v1/tenancy-changes", headers=manager, json=start).json() == change
    step = change["steps"][0]
    path = f"/api/v1/tenancy-changes/{change['id']}/steps/{step['id']}"
    projected = client.post(path + "/task", headers=tech, json={"idempotency_key": "task-http",
        "expected_revision": step["revision"], "expected_change_revision": change["revision"]})
    assert projected.status_code == 201, projected.text
    task_step = projected.json()
    assert task_step["task_id"]
    ordinary = client.patch(f"/api/v1/tasks/{task_step['task_id']}", headers=owner, json={"status": "completed"})
    assert ordinary.status_code == 400, ordinary.text
    assert "Mieterwechselakte" in ordinary.text and "Workflowschritt" in ordinary.text
    assert client.get(f"/api/v1/tasks/{task_step['task_id']}", headers=owner).json()["status"] != "completed"
    current = client.get(f"/api/v1/tenancy-changes/{change['id']}", headers=manager).json()
    stale = client.patch(path, headers=tech, json={"idempotency_key": "stale-parent",
        "expected_revision": task_step["revision"], "expected_change_revision": change["revision"], "state": "completed"})
    assert stale.status_code == 409, stale.text
    finished_step = client.patch(path, headers=tech, json={"idempotency_key": "finish-http",
        "expected_revision": task_step["revision"], "expected_change_revision": current["revision"], "state": "completed"})
    assert finished_step.status_code == 200, finished_step.text
    current = client.get(f"/api/v1/tenancy-changes/{change['id']}", headers=manager).json()
    completed = client.post(f"/api/v1/tenancy-changes/{change['id']}/complete", headers=manager,
        json={"idempotency_key": "complete-http", "expected_revision": current["revision"]})
    assert completed.status_code == 200 and completed.json()["state"] == "completed", completed.text


def test_actual_jwt_expiry_after_workflow_dml_rolls_back_and_exact_retry_succeeds(access_http, monkeypatch):
    client, store, _, _, actor, _, properties, *_ = access_http
    prepare_guarded_sql(store)
    token = auth_sessions.login_pair(actor.id).access_token
    headers = {"Authorization": "Bearer " + token}
    body = template_body(properties[0].id, "expired-after-dml")
    added: list[service.Work] = []
    original_add, original_touch = service.Work.add, auth_sessions.touch

    class ExpiredClock:
        @staticmethod
        def now(tz=None):
            value = datetime.now(timezone.utc) + timedelta(days=2)
            return value.astimezone(tz) if tz else value.replace(tzinfo=None)

    def fail_if_second_writer(claims):
        assert not any(unit.db is not None and unit.db.in_transaction() for unit in added), "session touch inside business writer"
        return original_touch(claims)

    def expire_after_insert(unit, row):
        original_add(unit, row)
        added.append(unit)
        patch.setattr(api_jwt, "datetime", ExpiredClock)

    with monkeypatch.context() as patch:
        patch.setattr(auth_sessions, "touch", fail_if_second_writer)
        patch.setattr(service.Work, "add", expire_after_insert)
        response = client.post("/api/v1/workflow-templates", headers=headers, json=body)
    assert response.status_code == 401, response.text
    assert added
    if hasattr(store, "db"):
        assert store.db.scalar(select(WorkflowTemplateORM.id)) is None
    else:
        assert store.__dict__.get("tenancy_workflow_templates", {}) == {}
        assert store.__dict__.get("tenancy_workflow_commands", {}) == {}
    fresh = {"Authorization": "Bearer " + auth_sessions.login_pair(actor.id).access_token}
    retry = client.post("/api/v1/workflow-templates", headers=fresh, json=body)
    assert retry.status_code == 201, retry.text
    assert client.post("/api/v1/workflow-templates", headers=fresh, json=body).json() == retry.json()


@pytest.mark.parametrize("models,label", [(TENANCY_WORKFLOW_MODELS, "tenancy workflow"), (JOB_MODELS, "operational job")])
@pytest.mark.parametrize("damage", ["partial", "columns"])
def test_startup_rejects_incomplete_new_family_before_schema_dml(tmp_path, monkeypatch, models, label, damage):
    engine = create_engine("sqlite:///" + (tmp_path / "damaged.db").as_posix())
    try:
        with engine.begin() as connection:
            for model in models if damage == "columns" else models[:1]:
                connection.exec_driver_sql(f'CREATE TABLE "{model.__tablename__}" (id TEXT PRIMARY KEY)')
        before = set(inspect(engine).get_table_names())
        monkeypatch.setattr(runtime, "engine", engine)
        with pytest.raises(RuntimeError, match="Incomplete " + label):
            runtime.create_tables()
        assert set(inspect(engine).get_table_names()) == before
    finally:
        engine.dispose()


def test_fresh_startup_registers_both_families_and_shared_frozen_guards(tmp_path, monkeypatch):
    engine = create_engine("sqlite:///" + (tmp_path / "fresh.db").as_posix())
    try:
        monkeypatch.setattr(runtime, "engine", engine)
        runtime.create_tables()
        tables = set(inspect(engine).get_table_names())
        assert {model.__tablename__ for model in (*TENANCY_WORKFLOW_MODELS, *JOB_MODELS)} <= tables
        with engine.connect() as connection:
            triggers = set(connection.exec_driver_sql("SELECT name FROM sqlite_master WHERE type='trigger'").scalars())
        assert {"immo_tenancy_commands_update", "immo_tenancy_commands_delete", "immo_operational_command_update"} <= triggers
    finally:
        engine.dispose()


def test_postgres_persistent_session_revoke_after_insert_rolls_back_and_allows_exact_retry(postgres, postgres_http, monkeypatch):
    client, store, _, _, actor, *_ = postgres_http
    prepare_guarded_sql(store)
    token = auth_sessions.login_pair(actor.id).access_token
    headers = {"Authorization": "Bearer " + token}
    body = template_body(postgres.property.id, "pg-real-revoke-after-dml")
    original, inserted = service.Work.add, []

    def revoke_after_insert(unit, row):
        original(unit, row)
        inserted.append(row.id)
        auth.revoke_token(token)

    with monkeypatch.context() as patch:
        patch.setattr(service.Work, "add", revoke_after_insert)
        response = client.post("/api/v1/workflow-templates", headers=headers, json=body)
    assert response.status_code == 401, response.text
    assert inserted
    with postgres.engine.connect() as connection:
        assert connection.scalar(select(WorkflowTemplateORM.id)) is None
    assert client.get("/api/v1/workflow-templates", headers=headers).status_code == 401
    fresh = {"Authorization": "Bearer " + auth_sessions.login_pair(actor.id).access_token}
    retry = client.post("/api/v1/workflow-templates", headers=fresh, json=body)
    assert retry.status_code == 201, retry.text
    assert client.post("/api/v1/workflow-templates", headers=fresh, json=body).json() == retry.json()


def test_actual_postgres_composed_migration_chain_is_linear_and_preserves_old_property(postgres, monkeypatch):
    root = Path(__file__).resolve().parents[2]
    monkeypatch.setenv("DATABASE_URL", postgres.engine.url.render_as_string(hide_password=False))
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "backend/db/migrations"))
    expected_head = ScriptDirectory.from_config(config).get_current_head()
    command.upgrade(config, "head")
    with postgres.engine.connect() as connection:
        assert connection.exec_driver_sql("SELECT version_num FROM alembic_version").scalar_one() == expected_head
        assert {model.__tablename__ for model in (*TENANCY_WORKFLOW_MODELS, *JOB_MODELS)} <= set(inspect(connection).get_table_names())
    command.downgrade(config, "a2a2b3c4d5e6")
    with postgres.engine.connect() as connection:
        assert not {model.__tablename__ for model in (*TENANCY_WORKFLOW_MODELS, *JOB_MODELS)} & set(inspect(connection).get_table_names())
        assert connection.exec_driver_sql("SELECT id FROM properties WHERE id=%s", (postgres.property.id,)).scalar_one() == postgres.property.id
