"""Actual JWT/scope HTTP and real fresh Alembic journals, only synthetic data."""

import pytest
from alembic import command as migration
from alembic.script import ScriptDirectory
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, select, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from backend import auth, dependencies
from backend.db.contract_lifecycle_models import (
    LIFECYCLE_MODELS,
    ContractLifecycleDraftORM,
    ensure_contract_lifecycle_schema,
)
from backend.routers import contract_lifecycle
from backend.services import contract_lifecycle as service
from backend.services.portfolio_http import PortfolioScopeMiddleware
from backend.tests import test_billing_migration_guards as migration_tests
from backend.tests.test_contract_lifecycle import active as active
from backend.tests.test_contract_lifecycle import command, confirmation, create, data, prepare

migration_database = migration_tests.migration_database


@pytest.mark.parametrize("role", ["verwalter", "readonly", "buchhaltung", "techniker"])
def test_actual_authenticated_http_readonly_foreign_and_explicit_confirmation(active, monkeypatch, role):
    monkeypatch.setattr(auth, "_user_store", auth.InMemoryUserStore())
    monkeypatch.setattr(auth, "_auth_session_factory", None)
    monkeypatch.setattr(auth, "get_user_by_id", auth._user_store.get_by_id)
    monkeypatch.setattr(dependencies, "store", active.store)
    user = auth.register_user("lifecycle-member", "member@example.test", "Synthetic", "Strong123", role,
        portfolio_access="selected", portfolio_ids=[active.p.id])
    headers = {"Authorization": "Bearer " + auth.create_access_token(user.id)}
    app = FastAPI()
    app.include_router(contract_lifecycle.router, prefix="/api/v1")
    base = "/api/v1/contracts/" + active.contract.id + "/lifecycle"
    payload = {"idempotency_key": "create-http", "expected_contract_etag": service.contract_etag(active.contract), "data": data()}
    with TestClient(PortfolioScopeMiddleware(app)) as client:
        assert client.post(base + "/drafts", json=payload).status_code == 401
        assert client.get(base + "/history").status_code == 401
        assert client.get(base + "/history", headers=headers).status_code == 200
        response = client.post(base + "/drafts", json=payload, headers=headers)
        if role != "verwalter":
            assert response.status_code == 403
            assert active.store.get_contract(active.contract.id).end_date.isoformat() == "2026-12-31"
            return
        assert response.status_code == 201, response.text
        first = response.json()
        assert client.post(base + "/drafts", json=payload, headers=headers).json() == first
        assert client.get(base + "/drafts", headers=headers).json()["items"][0]["id"] == first["id"]
        reviewed = client.post(base + "/drafts/" + first["id"] + "/review", headers=headers,
                               json=command(first, "http-review").model_dump(mode="json")).json()
        confirm_payload = confirmation(reviewed).model_dump(mode="json")
        for invalid in (False, 1, "true", None):
            assert client.post(base + "/drafts/" + first["id"] + "/confirm", headers=headers,
                               json={**confirm_payload, "confirmed": invalid}).status_code == 422
        response = client.post(base + "/drafts/" + first["id"] + "/confirm", headers=headers, json=confirm_payload)
        assert response.status_code == 200, response.text
        assert response.json()["state"] == "pending_effective"
        assert client.post(base + "/drafts/" + first["id"] + "/confirm", headers=headers, json=confirm_payload).json() == response.json()
        auth._user_store.update(user.id, {"role": "readonly"})
        assert client.get(base + "/history", headers=headers).json()["items"][0]["result"] == response.json()
        assert client.get(base + "/drafts/" + first["id"], headers=headers).status_code == 200
        assert client.post(base + "/drafts", json={**payload, "idempotency_key": "readonly"}, headers=headers).status_code == 403
        auth._user_store.update(user.id, {"portfolio_ids": []})
        assert client.get(base + "/history", headers=headers).status_code == 404
        assert client.get(base + "/drafts/" + first["id"], headers=headers).status_code == 404


def test_real_fresh_migration_chain_repeatable_bootstrap_and_empty_down_up(migration_database):
    config, path = migration_database
    assert ScriptDirectory.from_config(config).get_revision("z1a2b3c4d5e6").down_revision == "y1a2b3c4d5e6"
    migration.upgrade(config, "z1a2b3c4d5e6")
    engine = create_engine("sqlite:///" + path.as_posix())
    try:
        schema = inspect(engine)
        for model in LIFECYCLE_MODELS:
            assert set(model.__table__.c.keys()) == {c["name"] for c in schema.get_columns(model.__tablename__)}
            assert schema.get_foreign_keys(model.__tablename__)
        before = migration_tests._structure(path)
        with engine.begin() as connection:
            ensure_contract_lifecycle_schema(connection)
            ensure_contract_lifecycle_schema(connection)
        assert migration_tests._structure(path) == before
        migration.downgrade(config, "y1a2b3c4d5e6")
        migration.upgrade(config, "z1a2b3c4d5e6")
        assert migration_tests._structure(path) == before
    finally:
        engine.dispose()


def test_confirmed_sql_evidence_immutable_and_populated_downgrade_refuses(active, monkeypatch):
    if active.engine is None:
        pytest.skip("SQL-only native immutable evidence")
    reviewed = prepare(active)
    done = service.confirm_draft(active.store, active.contract.id, reviewed["id"], confirmation(reviewed), "actor")
    with Session(active.engine) as db:
        with pytest.raises(DBAPIError, match="immutable"):
            db.execute(update(ContractLifecycleDraftORM).where(ContractLifecycleDraftORM.id == done["id"])
                       .values(data=data(termination_end_date="2026-10-15")))
        db.rollback()
        original = db.scalar(select(ContractLifecycleDraftORM).where(ContractLifecycleDraftORM.id == done["id"]))
        assert original.review_hash == done["review_hash"]
    from alembic import op

    from backend.db.migrations.versions import z1a2b3c4d5e6_contract_lifecycle as version
    with active.engine.begin() as connection:
        monkeypatch.setattr(op, "get_bind", lambda: connection)
        with pytest.raises(RuntimeError, match="would erase"):
            version.downgrade()
        assert set(version.TABLES) <= set(inspect(connection).get_table_names())


def test_open_draft_keyset_has_no_duplicates_and_conflicting_key_never_reuses_other_payload(active):
    rows = [create(active, key="key-" + str(i))[0] for i in range(5)]
    collected, before = [], None
    for _ in range(4):
        page = service.list_drafts(active.store, active.contract.id, "actor", limit=2, before=before)
        collected.extend(row["id"] for row in page["items"])
        before = page["next_before"]
        if before is None:
            break
    assert len(set(collected)) == len(collected) == 5 and set(collected) == {row["id"] for row in rows}
    with pytest.raises(Exception, match="anderen Eingaben"):
        create(active, key="key-0", termination_end_date="2026-10-31")
    assert service.list_drafts(active.store, active.contract.id, "other")["items"] == []
