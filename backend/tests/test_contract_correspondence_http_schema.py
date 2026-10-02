"""JWT/scope HTTP, bounded history, real immutable SQL and fresh migrations."""

import pytest
from alembic import command as migration
from alembic.script import ScriptDirectory
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, select
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from backend import auth, dependencies
from backend.db.contract_correspondence_models import (
    CORRESPONDENCE_MODELS,
    CorrespondenceDraftORM,
    ensure_contract_correspondence_schema,
)
from backend.middleware import DBSessionMiddleware
from backend.routers import contract_correspondence
from backend.routing import build_api_v1
from backend.services import contract_correspondence as service
from backend.services.portfolio_http import PortfolioScopeMiddleware
from backend.tests import test_billing_migration_guards as migration_tests
from backend.tests.test_contract_correspondence import approval, command, data, prepare
from backend.tests.test_contract_correspondence import letter as letter
from backend.tests.test_contract_lifecycle import active as active

migration_database = migration_tests.migration_database


def test_full_actual_api_with_jwt_scope_explicit_approval_readonly_download_and_revocation(letter, monkeypatch):
    monkeypatch.setattr(auth, "_user_store", auth.InMemoryUserStore())
    monkeypatch.setattr(auth, "_auth_session_factory", None)
    monkeypatch.setattr(auth, "get_user_by_id", auth._user_store.get_by_id)
    monkeypatch.setattr(dependencies, "store", letter.store)
    user = auth.register_user("local-correspondence", "member@example.test", "Synthetic", "Strong123", "verwalter",
        portfolio_access="selected", portfolio_ids=[letter.p.id])
    headers = {"Authorization": "Bearer " + auth.create_access_token(user.id)}
    # The production route builder plus this not-yet-Root-registered extension,
    # with the actual authoritative portfolio middleware and actual JWT auth.
    router = build_api_v1()
    router.include_router(contract_correspondence.router)
    app = FastAPI()
    app.include_router(router)
    base = "/api/v1/contracts/" + letter.contract.id + "/correspondence"
    payload = {"idempotency_key": "http-create", "expected_contract_etag": service.lifecycle.contract_etag(letter.contract), "data": data().model_dump(mode="json")}
    with TestClient(DBSessionMiddleware(PortfolioScopeMiddleware(app))) as client:
        assert client.post(base + "/drafts", json=payload).status_code == 401
        assert client.get(base + "/history").status_code == 401
        created = client.post(base + "/drafts", json=payload, headers=headers)
        assert created.status_code == 201, created.text
        found = created.json()
        reviewed = client.post(base + "/drafts/" + found["id"] + "/review", json=command(found).model_dump(mode="json"), headers=headers)
        assert reviewed.status_code == 200, reviewed.text
        path = base + "/drafts/" + found["id"]
        preview = client.get(path + "/review-pdf", headers=headers)
        assert preview.status_code == 200 and preview.content.startswith(b"%PDF-")
        confirmed = approval(reviewed.json()).model_dump(mode="json")
        for invalid in (False, 1, "true", None):
            assert client.post(path + "/approve", json={**confirmed, "confirmed": invalid}, headers=headers).status_code == 422
        response = client.post(path + "/approve", json=confirmed, headers=headers)
        assert response.status_code == 200, response.text
        assert client.post(path + "/approve", json=confirmed, headers=headers).json() == response.json()
        auth._user_store.update(user.id, {"role": "readonly"})
        assert client.get(path + "/download", headers=headers).content == preview.content
        assert client.get(base + "/history", headers=headers).json()["items"][0]["id"] == found["id"]
        assert client.post(base + "/drafts", json={**payload, "idempotency_key": "readonly"}, headers=headers).status_code == 403
        auth._user_store.update(user.id, {"portfolio_ids": []})
        assert client.get(path + "/download", headers=headers).status_code == 404
        assert client.get(base + "/history", headers=headers).status_code == 404


def test_fresh_frozen_migration_matches_declared_columns_indexes_and_empty_down_up(migration_database):
    config, path = migration_database
    assert ScriptDirectory.from_config(config).get_revision("a2a2b3c4d5e6").down_revision == "z1a2b3c4d5e6"
    migration.upgrade(config, "a2a2b3c4d5e6")
    engine = create_engine("sqlite:///" + path.as_posix())
    try:
        structure = migration_tests._structure(path)
        for model in CORRESPONDENCE_MODELS:
            schema = inspect(engine)
            assert set(model.__table__.c.keys()) == {value["name"] for value in schema.get_columns(model.__tablename__)}
            assert {value.name for value in model.__table__.indexes} == {value["name"] for value in schema.get_indexes(model.__tablename__)}
            assert schema.get_foreign_keys(model.__tablename__)
        with engine.begin() as connection:
            ensure_contract_correspondence_schema(connection)
            ensure_contract_correspondence_schema(connection)
        assert migration_tests._structure(path) == structure
        migration.downgrade(config, "z1a2b3c4d5e6")
        migration.upgrade(config, "a2a2b3c4d5e6")
        assert migration_tests._structure(path) == structure
    finally:
        engine.dispose()


def test_native_approved_draft_commands_and_events_are_immutable_and_populated_downgrade_refuses(letter, monkeypatch):
    if not letter.engine:
        pytest.skip("SQL native immutability/downgrade")
    found = prepare(letter)
    approved = service.approve_draft(letter.store, letter.contract.id, found["id"], approval(found), "actor")
    from backend.tests.test_contract_correspondence import event_payload
    service.record_event(letter.store, letter.contract.id, found["id"], event_payload(approved), "actor")
    for table, field in (("contract_correspondence_drafts", "state"), ("contract_correspondence_commands", "actor_id"), ("contract_correspondence_events", "actor_id")):
        for statement in (f"UPDATE {table} SET {field}={field}", f"DELETE FROM {table}"):
            with letter.engine.connect() as connection, pytest.raises(DBAPIError):
                connection.exec_driver_sql(statement)
    from alembic import op

    from backend.db.migrations.versions import a2a2b3c4d5e6_contract_correspondence as version
    with letter.engine.begin() as connection:
        monkeypatch.setattr(op, "get_bind", lambda: connection)
        with pytest.raises(RuntimeError, match="erase retained"):
            version.downgrade()
        assert connection.scalar(select(CorrespondenceDraftORM.state).where(CorrespondenceDraftORM.id == found["id"])) == "approved"


def test_runtime_half_schema_refuses_without_creating_other_tables(tmp_path):
    engine = create_engine("sqlite:///" + (tmp_path / "partial.sqlite").as_posix())
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql("CREATE TABLE contract_correspondence_drafts(id TEXT PRIMARY KEY)")
            with pytest.raises(RuntimeError, match="Incomplete"):
                ensure_contract_correspondence_schema(connection)
            assert inspect(connection).get_table_names() == ["contract_correspondence_drafts"]
    finally:
        engine.dispose()


def test_history_keyset_has_stable_ties_and_no_cross_actor_open_drafts(letter, monkeypatch):
    from backend.tests.test_contract_correspondence import create
    stamp = service.lifecycle.now()
    monkeypatch.setattr(service.lifecycle, "now", lambda: stamp)
    found = [create(letter, key="page-" + str(index))[0] for index in range(7)]
    # No global materialization in a Memory reference path; SQL uses LIMIT p+1.
    seen, cursor = [], None
    for _ in range(4):
        page = service.listing(letter.store, letter.contract.id, "actor", limit=2, before=cursor)
        seen.extend(value["id"] for value in page["items"])
        cursor = page["next_before"]
        if not cursor:
            break
    assert seen == sorted((value["id"] for value in found), reverse=True)
    assert service.listing(letter.store, letter.contract.id, "other")["items"] == []


def test_actual_sql_auth_factory_uses_account_marker_before_domain_and_keeps_approved_owner_scope(letter, monkeypatch):
    if not letter.engine:
        pytest.skip("Actual SQL auth factory and writer marker")
    accounts = auth.SQLUserStore(lambda: Session(letter.engine))
    monkeypatch.setattr(dependencies, "store", letter.store)
    monkeypatch.setattr(auth, "_user_store", accounts)
    monkeypatch.setattr(auth, "get_user_by_id", accounts.get_by_id)
    actor = auth.register_user("correspondence-sql-member", "sql@example.test", "Synthetic", "Strong123", "verwalter",
        portfolio_access="selected", portfolio_ids=[letter.p.id])
    from backend.tests.test_contract_correspondence import create
    found, _ = create(letter, actor=actor.id)
    reviewed = service.review_draft(letter.store, letter.contract.id, found["id"], command(found), actor.id)
    published = service.approve_draft(letter.store, letter.contract.id, found["id"], approval(reviewed), actor.id)
    assert published["state"] == "approved"
    accounts.update(actor.id, {"portfolio_ids": []})
    with pytest.raises(Exception):
        service.get_draft(letter.store, letter.contract.id, found["id"], actor.id)
