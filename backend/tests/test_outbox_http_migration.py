"""Authenticated HTTP and actual frozen Alembic chain, rather than create_all."""

import pytest
from alembic import command as migration
from alembic.script import ScriptDirectory
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect

from backend import auth, dependencies
from backend.db.outbox_models import OutboxCommandORM, OutboxEventORM, OutboxMessageORM, ensure_outbox_schema
from backend.routers import outbox
from backend.services import outbox as service
from backend.tests import test_billing_migration_guards as migration_tests
from backend.tests.test_outbox_journal import active as active
from backend.tests.test_outbox_journal import command, review

migration_database = migration_tests.migration_database


@pytest.mark.parametrize("role", ["eigentuemer", "verwalter", "buchhaltung", "techniker", "readonly"])
def test_real_http_roles_explicit_confirmation_and_stale_command(active, monkeypatch, role):
    monkeypatch.setattr(auth, "_user_store", auth.InMemoryUserStore())
    monkeypatch.setattr(auth, "_auth_session_factory", None)
    monkeypatch.setattr(auth, "get_user_by_id", auth._user_store.get_by_id)
    monkeypatch.setattr(outbox, "store", active.store)
    from backend.repositories.sql_store import SQLAlchemyStore
    monkeypatch.setattr(dependencies, "store", SQLAlchemyStore(active.store.db))
    user = auth.register_user("synthetic-outbox", "outbox@example.test", "Synthetic", "Strong123", role,
        portfolio_access="selected", portfolio_ids=["p"])
    headers = {"Authorization": "Bearer " + auth.create_access_token(user.id)}
    app = FastAPI()
    app.include_router(outbox.router, prefix="/api/v1")
    base = "/api/v1/messages/outbox"
    with TestClient(app) as client:
        assert client.post(base, json=review().model_dump()).status_code == 401
        assert client.get(base + "?portfolio_id=foreign", headers=headers).status_code == (200 if role == "eigentuemer" else 404)
        response = client.post(base, json=review().model_dump(), headers=headers)
        if role == "readonly":
            assert response.status_code == 403 and active.calls == []
            return
        assert response.status_code == 201, response.text
        first = response.json()
        path = base + "/" + first["id"]
        assert client.post(path + "/send", json=command(first).model_dump() | {"confirmed": False}, headers=headers).status_code == 422
        assert client.post(path + "/send", json=command(first).model_dump() | {"expected_revision": 1}, headers=headers).status_code == 412
        sent = client.post(path + "/send", json=command(first).model_dump(), headers=headers)
        assert sent.status_code == 200 and sent.json()["state"] == "sent", sent.text
        assert client.post(path + "/send", json=command(first).model_dump(), headers=headers).json() == sent.json()
        assert len(active.calls) == 1
        history = client.get(path + "/events?limit=2", headers=headers).json()
        assert history["total"] == 4 and len(history["items"]) == 2
        assert client.get(path + "/events?offset=2&limit=2", headers=headers).json()["items"][-1]["kind"] == "reviewed"


def test_fresh_alembic_outbox_schema_and_repeatable_additive_helper(migration_database):
    config, path = migration_database
    directory = ScriptDirectory.from_config(config)
    assert directory.get_revision("r1a2b3c4d5e6").down_revision == "q1a2b3c4d5e6"
    migration.upgrade(config, "r1a2b3c4d5e6")
    engine = create_engine("sqlite:///" + path.as_posix())
    try:
        schema = inspect(engine)
        for model in (OutboxMessageORM, OutboxEventORM, OutboxCommandORM):
            assert {column["name"] for column in schema.get_columns(model.__tablename__)} == set(model.__table__.c.keys())
            assert schema.get_foreign_keys(model.__tablename__)
        structure = migration_tests._structure(path)
        with engine.begin() as connection:
            ensure_outbox_schema(connection)
            ensure_outbox_schema(connection)
        assert migration_tests._structure(path) == structure
        migration.downgrade(config, "q1a2b3c4d5e6")
        migration.upgrade(config, "r1a2b3c4d5e6")
        assert migration_tests._structure(path) == structure
    finally:
        engine.dispose()


def test_populated_outbox_downgrade_refuses_before_any_ddl(migration_database, active):
    config, path = migration_database
    migration.upgrade(config, "r1a2b3c4d5e6")
    engine = create_engine("sqlite:///" + path.as_posix())
    from types import SimpleNamespace

    from sqlalchemy.orm import Session

    from backend.db.orm_models import PortfolioORM
    try:
        with engine.begin() as db:
            db.execute(PortfolioORM.__table__.insert(), dict(id="p", name="Synthetic"))
        with Session(engine) as db:
            service.create_message(SimpleNamespace(db=db), review(), "actor")
        before = migration_tests._state(path)
        with pytest.raises(RuntimeError, match="downgrade would erase communication history"):
            migration.downgrade(config, "q1a2b3c4d5e6")
        assert migration_tests._state(path) == before
    finally:
        engine.dispose()


def test_real_scoped_http_revocation_after_data_keeps_factual_result_and_returns_403(active, monkeypatch):
    monkeypatch.setattr(auth, "_user_store", auth.InMemoryUserStore())
    monkeypatch.setattr(auth, "_auth_session_factory", None)
    monkeypatch.setattr(auth, "get_user_by_id", auth._user_store.get_by_id)
    from sqlalchemy import select
    from sqlalchemy.orm import Session

    from backend.repositories.sql_store import SQLAlchemyStore
    from backend.services.email_service import EmailResult
    from backend.services.portfolio_http import PortfolioScopeMiddleware
    from backend.services.portfolio_scope import scope_context
    monkeypatch.setattr(dependencies, "store", SQLAlchemyStore(active.store.db))
    monkeypatch.setattr(outbox, "store", active.store)
    owner = auth.register_user("outbox-owner", "owner@example.test", "Synthetic", "Strong123", "eigentuemer")
    member = auth.register_user("outbox-member", "member@example.test", "Synthetic", "Strong123", "buchhaltung",
        portfolio_access="selected", portfolio_ids=["p"])
    headers = {"Authorization": "Bearer " + auth.create_access_token(member.id)}
    calls = []
    def revoke_after_data(recipient, wire, *, config, before_data):
        before_data()
        calls.append(wire)
        auth._user_store.update(member.id, {"portfolio_access": "selected", "portfolio_ids": []}, actor_id=owner.id)
        return EmailResult("accepted", "smtp_accepted")
    monkeypatch.setattr(service.mail, "submit_prepared_email", revoke_after_data)
    app = FastAPI()
    app.include_router(outbox.router, prefix="/api/v1")
    with TestClient(PortfolioScopeMiddleware(app)) as client:
        response = client.post("/api/v1/messages/outbox", json=review().model_dump(), headers=headers)
        assert response.status_code == 201, response.text
        first = response.json()
        path = "/api/v1/messages/outbox/" + first["id"]
        assert client.post(path + "/send", json=command(first).model_dump(), headers=headers).status_code == 403
        assert client.post(path + "/send", json=command(first).model_dump(), headers=headers).status_code in (403, 404)
        assert client.get(path, headers=headers).status_code == 404
    with Session(active.engine) as db, scope_context(None):
        assert service.decode_state(db.get(OutboxMessageORM, first["id"])).state == "sent"
        result_event = db.scalar(select(OutboxEventORM).where(OutboxEventORM.kind == "transport_result"))
        assert result_event.actor_id == member.id and result_event.code == "smtp_accepted"
    assert len(calls) == 1
