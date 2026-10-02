"""Owned synthetic installations for full-router private draft acceptance tests.

SQL schemas come only from Alembic, never from create_all/compatibility helpers.
The application's real authentication, request sessions and scope middleware are
used; no endpoint, permission check or business repository is mocked.
"""

from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select, text
from sqlalchemy.orm import Session, scoped_session, sessionmaker
from sqlalchemy.pool import QueuePool

from backend import auth, dependencies
from backend.db.form_draft_models import FormDraftORM
from backend.middleware import DBSessionMiddleware, RBACWriteGuardMiddleware
from backend.models import PortfolioCreate, PropertyCreate
from backend.repositories.sql_store import SQLAlchemyStore
from backend.routers import form_drafts, invoices, portfolios, properties
from backend.routing import build_api_v1
from backend.services.concurrency import ConcurrencyMiddleware
from backend.services.portfolio_http import PortfolioScopeMiddleware
from backend.services.portfolio_scope import scope_context
from backend.storage import InMemoryStore

ENDPOINT = "/api/v1/auth/users/me/form-drafts"
PASSWORD = "Synthetic-Draft-Passphrase-123!"


def migrate(url, monkeypatch):
    """Run the actual complete chain in one explicitly owned test database."""
    root = Path(__file__).resolve().parents[2]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "backend/db/migrations"))
    script = ScriptDirectory.from_config(config)
    assert script.get_revision("x1a2b3c4d5e6") is not None
    with monkeypatch.context() as environment:
        environment.setenv("DATABASE_URL", url)
        command.upgrade(config, "head")
    return script.get_current_head()


@dataclass
class DraftApplication:
    client: TestClient
    store: Any
    engine: Engine | None
    factory: Any
    owner: Any
    member: Any
    peer: Any
    portfolios: list[Any]
    properties: list[Any]

    def headers(self, user):
        response = self.client.post("/api/v1/auth/login", json={"username": user.username, "password": PASSWORD})
        assert response.status_code == 200, response.text
        return {"Authorization": "Bearer " + response.json()["access_token"]}

    def snapshot(self):
        if self.engine is None:
            return sorted((dict(row) for row in self.store.__dict__.get("_form_drafts", {}).values()), key=lambda row: row["id"])
        with self.engine.connect() as connection:
            return [dict(row) for row in connection.execute(select(FormDraftORM.__table__).order_by(FormDraftORM.id)).mappings()]

    def assert_connections_returned(self):
        if self.engine is not None:
            assert_connections_returned(self.engine)


def assert_connections_returned(engine: Engine):
    assert isinstance(engine.pool, QueuePool)
    assert engine.pool.checkedout() == 0


@contextmanager
def application(monkeypatch, engine=None):
    """Use the production router graph and the production middleware order."""
    factory = sessionmaker(bind=engine, autoflush=False) if engine is not None else None
    registry = scoped_session(factory, scopefunc=dependencies.session_scope_key) if factory else None
    store = SQLAlchemyStore(cast(Session, registry)) if registry is not None else InMemoryStore()
    monkeypatch.setattr(dependencies, "store", store)
    monkeypatch.setattr(dependencies, "_scoped_session", registry)
    monkeypatch.setattr(auth, "_user_store", auth.SQLUserStore(factory) if factory else auth.InMemoryUserStore())
    monkeypatch.setattr(auth, "_auth_session_factory", factory)
    for router in (form_drafts, properties, portfolios, invoices):
        monkeypatch.setattr(router, "store", store)
    with scope_context(None):
        owned_portfolios = [store.create_portfolio(PortfolioCreate(name=f"Synthetic draft portfolio {index}")) for index in range(2)]
        owned_properties = [store.create_property(PropertyCreate(portfolio_id=row.id, name=f"Synthetic building {index}", property_type="residential")) for index, row in enumerate(owned_portfolios)]
        owner = auth.register_user("draftowner", "draftowner@example.test", "Synthetic owner", PASSWORD, "eigentuemer")
        selected = {"portfolio_access": "selected", "portfolio_ids": [owned_portfolios[0].id]}
        member = auth.register_user("draftmember", "draftmember@example.test", "Synthetic member", PASSWORD, "verwalter", **selected)
        peer = auth.register_user("draftpeer", "draftpeer@example.test", "Synthetic peer", PASSWORD, "verwalter", **selected)
    if registry is not None:
        registry.remove()
    app = FastAPI()
    app.include_router(build_api_v1())
    app.add_middleware(RBACWriteGuardMiddleware)
    app.add_middleware(PortfolioScopeMiddleware)
    app.add_middleware(ConcurrencyMiddleware)
    app.add_middleware(DBSessionMiddleware)
    try:
        with TestClient(app) as client:
            yield DraftApplication(client, store, engine, factory, owner, member, peer, owned_portfolios, owned_properties)
    finally:
        if registry is not None:
            registry.remove()
            assert not registry.registry.registry


def draft_query(user, row, **values):
    return {"owner_id": user.id, "collection": "properties", "entity_id": row.id, **values}


def draft_body(user, row, *, name="Private synthetic draft €", revision=None, business_revision=None):
    return {**draft_query(user, row), "schema": "name:text|portfolio_id:select", "expected_revision": revision,
        "values": {"name": name, "portfolio_id": row.portfolio_id},
        "original_values": {"name": row.name, "portfolio_id": row.portfolio_id},
        "edit_revision": business_revision or {"collection": "properties", "id": row.id, "updatedAt": row.updated_at.isoformat()}}


def assert_migrated(engine, head):
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == head
        assert connection.scalar(select(FormDraftORM.id).limit(1)) is None
