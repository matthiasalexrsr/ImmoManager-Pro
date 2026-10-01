"""Root wiring, historical startup and resets use actual rental snapshots."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, inspect, select, text
from sqlalchemy.orm import Session

from backend import auth, dependencies
from backend.db import session as session_module
from backend.db.rent_batch_models import RENT_BATCH_TABLES
from backend.repositories.sql_store import SQLAlchemyStore
from backend.routing import build_api_v1
from backend.services.rent_batch import BatchCreate, create_batch
from backend.storage import InMemoryStore
from backend.tests.test_rent_ledger import setup_contract


@pytest.fixture
def integrated_sql_store(tmp_path, monkeypatch):
    engine = create_engine("sqlite:///" + (tmp_path / "integrated.db").as_posix())
    monkeypatch.setattr(session_module, "engine", engine)
    session_module.create_tables()
    session_module.create_tables()
    with Session(engine) as db:
        yield SQLAlchemyStore(db)
    engine.dispose()


def test_actual_startup_registers_all_batch_tables_and_repeatable_revision_triggers(integrated_sql_store):
    store = integrated_sql_store
    connection = store.db.connection()
    assert {table.name for table in RENT_BATCH_TABLES} <= set(inspect(connection).get_table_names())
    triggers = connection.execute(text("SELECT name FROM sqlite_master WHERE type='trigger' AND name LIKE 'immo_rent_revision_%'")).scalars().all()
    assert len(triggers) == len(set(triggers)) == 12
    contract, _ = setup_contract(store)
    connection = store.db.connection()
    revision = connection.execute(text("SELECT revision FROM rent_source_revisions WHERE entity_type='contract' AND entity_id=:id"), {"id": contract.id}).scalar_one()
    assert revision > 0


@pytest.mark.parametrize("kind", ["memory", "sql"])
def test_full_reset_removes_durable_snapshot_and_source_revisions(integrated_sql_store, kind):
    store = integrated_sql_store if kind == "sql" else InMemoryStore()
    contract, _ = setup_contract(store)
    create_batch(store, BatchCreate(start_month="2026-10", end_month="2026-12",
                                   contract_ids=[contract.id], idempotency_key="synthetic-reset"))
    memory_engine = getattr(store, "_rent_batch_engine", None)
    store.clear_all()
    assert store.list_contracts() == []
    if kind == "sql":
        for table in RENT_BATCH_TABLES:
            assert store.db.scalar(select(func.count()).select_from(table)) == 0
    else:
        assert memory_engine is not None and not hasattr(store, "_rent_batch_engine")


def test_root_router_uses_batch_collection_before_parameterized_charge_route(monkeypatch):
    monkeypatch.setattr(auth, "_user_store", auth.InMemoryUserStore())
    monkeypatch.setattr(auth, "_auth_session_factory", None)
    monkeypatch.setattr(dependencies, "store", InMemoryStore())
    owner = auth.register_user("synthetic-batch-root", "root@example.test", "Synthetic", "Strong123", "eigentuemer")
    app = FastAPI()
    app.include_router(build_api_v1())
    with TestClient(app) as client:
        response = client.get("/api/v1/rent-charges/batches", headers={"Authorization": "Bearer " + auth.create_access_token(owner.id)})
        assert response.status_code == 200, response.text
        assert response.json()["items"] == []
