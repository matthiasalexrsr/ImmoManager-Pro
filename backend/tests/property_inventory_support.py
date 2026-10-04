"""Own synthetic native fixtures; real SQLUserStore/Sid, no getter override."""

from contextlib import contextmanager
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from backend import auth
from backend.db.document_version_models import DocumentVersionORM
from backend.db.orm_models import Base, ContractORM, MaintenanceCaseORM, PortfolioORM, PropertyORM, TenantORM, UnitORM
from backend.models import Contract, MaintenanceCase, Portfolio, Property, Tenant, Unit
from backend.repositories.sql_store import SQLAlchemyStore
from backend.services import auth_sessions
from backend.services.portfolio_scope import scope_context, scope_from_user
from backend.services.request_authority import request_authority
from backend.storage import InMemoryStore

STAMP = datetime(2026, 1, 1, tzinfo=timezone.utc)
MODELS = {
    "portfolios": (Portfolio, PortfolioORM), "properties": (Property, PropertyORM),
    "units": (Unit, UnitORM), "tenants": (Tenant, TenantORM),
    "contracts": (Contract, ContractORM), "maintenance_cases": (MaintenanceCase, MaintenanceCaseORM),
}


def native_metadata(engine):
    # Explicit needed metadata registration, not a fake revision/factory claim.
    assert DocumentVersionORM.__tablename__ in Base.metadata.tables
    Base.metadata.create_all(engine)


def sqlite_engine(path):
    engine = create_engine("sqlite:///" + path.as_posix(), connect_args={"check_same_thread": False}, hide_parameters=True)

    @event.listens_for(engine, "connect")
    def setup(driver, _record):
        cursor = driver.cursor()
        try:
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA foreign_keys=ON")
        finally:
            cursor.close()

    return engine


def put(box, collection, rows):
    model, orm = MODELS[collection]
    values = [model(**{"created_at": STAMP, "updated_at": STAMP, **row}) for row in rows]
    with scope_context(None):
        if box.engine is not None:
            with box.engine.begin() as connection:
                connection.execute(orm.__table__.insert(), [row.model_dump() for row in values])
        else:
            box.store.__dict__[collection].update({row.id: row for row in values})
    return values


def make_box(engine, accounts, tokens, *, memory=False):
    db = None if memory else Session(engine)
    return SimpleNamespace(engine=None if memory else engine, account_engine=engine, accounts=accounts,
                           tokens=tokens, db=db, store=InMemoryStore() if memory else SQLAlchemyStore(db))


def install_accounts(monkeypatch, engine, *, sid_engine=None):
    factory = sessionmaker(bind=engine, autoflush=False)
    accounts = auth.SQLUserStore(factory)
    monkeypatch.setattr(auth, "_user_store", accounts)  # Actual owned adapter, no getter/lambda.
    monkeypatch.setattr(auth, "_auth_session_factory", sessionmaker(bind=sid_engine or engine, autoflush=False))
    tokens = {}
    for actor, role, mode, grants in (("owner", "eigentuemer", "all", []),
        ("reader-eur", "readonly", "selected", ["eur"]), ("reader-usd", "readonly", "selected", ["usd"])):
        with scope_context(None):
            accounts.create({"id": actor, "username": actor, "email": actor + "@example.invalid",
                "full_name": "Synthetic " + actor, "hashed_password": "unused-synthetic-hash",
                "role": role, "is_active": True, "portfolio_access": mode,
                "portfolio_ids": grants, "portfolio_access_origin": "owner_assignment"},
                actor_id="owner" if actor != "owner" else None)
            tokens[actor] = auth_sessions.login_pair(actor).access_token
    return accounts, tokens


@contextmanager
def actor(box, name="owner"):
    actual = box.accounts.get_by_id(name)
    assert actual is not None and actual["is_active"]
    with scope_context(scope_from_user(actual)), request_authority(box.tokens[name]):
        yield


@pytest.fixture(params=["memory", "sqlite"])
def property_box(request, tmp_path, monkeypatch):
    engine = sqlite_engine(tmp_path / "synthetic-property-inventory.sqlite")
    box = None
    try:
        native_metadata(engine)
        with scope_context(None), engine.begin() as connection:
            connection.execute(PortfolioORM.__table__.insert(), [
                {"id": "eur", "name": "Synthetic Euro", "currency": "EUR"},
                {"id": "usd", "name": "Synthetic Dollar", "currency": "USD"},
                {"id": "unknown", "name": "Synthetic unknown", "currency": " \t\u3000"},
            ])
        accounts, tokens = install_accounts(monkeypatch, engine)
        box = make_box(engine, accounts, tokens, memory=request.param == "memory")
        if request.param == "memory":
            put(box, "portfolios", [{"id": "eur", "name": "Synthetic Euro", "currency": "EUR"},
                {"id": "usd", "name": "Synthetic Dollar", "currency": "USD"},
                {"id": "unknown", "name": "Synthetic unknown", "currency": " \t\u3000"}])
        yield box
    finally:
        if box is not None and box.db is not None:
            box.db.close()
        assert engine.pool.checkedout() == 0
        engine.dispose()


def properties(box, rows):
    return put(box, "properties", [{"property_type": "residential", "name": row["id"], **row} for row in rows])


def units(box, rows):
    return put(box, "units", [{"unit_type": "apartment", "label": row["id"], **row} for row in rows])
