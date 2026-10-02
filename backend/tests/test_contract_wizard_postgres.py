"""Dedicated disposable PostgreSQL gates; no implicit production URL fallback."""

import os
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from types import SimpleNamespace
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from backend import auth
from backend.db.contract_wizard_models import WIZARD_MODELS
from backend.models import PortfolioCreate, PropertyCreate, TenantCreate, UnitCreate
from backend.repositories.sql_store import SQLAlchemyStore
from backend.services import contract_wizard as service
from backend.services.contract_wizard_types import DraftCreate
from backend.tests.test_contract_wizard_workflow import (
    data,
    publish,
)
from backend.tests.test_contract_wizard_workflow import (
    test_failed_publication_rolls_back_new_tenant_contract_chunks_and_commands as check_rollback,
)
from backend.tests.test_contract_wizard_workflow import (
    test_normal_create_and_wizard_publication_compete_for_same_unit as check_occupancy,
)


@pytest.fixture
def postgres(tmp_path, monkeypatch):
    source = os.getenv("TEST_SERVER_DATABASE_URL")
    if not source:
        pytest.skip("TEST_SERVER_DATABASE_URL disposable PostgreSQL service is not configured")
    url = make_url(source)
    if url.get_backend_name() != "postgresql":
        pytest.fail("TEST_SERVER_DATABASE_URL must be disposable PostgreSQL")
    schema = "wizard_" + uuid4().hex
    admin = create_engine(url, hide_parameters=True)
    with admin.begin() as connection:
        connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
    scoped_url = url.update_query_dict({"options": "-csearch_path=" + schema})
    engine = create_engine(scoped_url, hide_parameters=True)
    try:
        config = Config("alembic.ini")
        monkeypatch.setenv("DATABASE_URL", scoped_url.render_as_string(hide_password=False))
        config.set_main_option("sqlalchemy.url", scoped_url.render_as_string(hide_password=False).replace("%", "%%"))
        command.upgrade(config, "v1a2b3c4d5e6")
        for model in WIZARD_MODELS:
            assert {c["name"] for c in inspect(engine).get_columns(model.__tablename__)} == set(model.__table__.c.keys())
        with Session(engine) as db:
            store = SQLAlchemyStore(db)
            p = store.create_portfolio(PortfolioCreate(name="Synthetic PG portfolio"))
            property = store.create_property(PropertyCreate(portfolio_id=p.id, name="Synthetic PG property", property_type="residential"))
            unit = store.create_unit(UnitCreate(property_id=property.id, label="PG A", unit_type="apartment", cold_rent=600))
            tenant = store.create_tenant(TenantCreate(full_name="Synthetic PG tenant"))
            users = {"actor": dict(id="actor", role="verwalter", is_active=True, portfolio_access="all", portfolio_ids=[])}
            monkeypatch.setattr(auth, "get_user_by_id", users.get)
            yield SimpleNamespace(store=store, engine=engine, p=p, property=property, unit=unit, tenant=tenant, users=users)
    finally:
        engine.dispose()
        # Exactly the newly owned UUID namespace; never another schema/database.
        assert schema.startswith("wizard_") and len(schema) == 39
        with admin.begin() as connection:
            connection.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
        admin.dispose()


def test_pg_identical_draft_and_publish_commands_across_two_sessions(postgres):
    request = DraftCreate(idempotency_key="pg-create", data=data(postgres))
    barrier = Barrier(2)
    def create(_):
        with Session(postgres.engine) as db:
            barrier.wait(timeout=10)
            return service.create_draft(SQLAlchemyStore(db), request, "actor")
    with ThreadPoolExecutor(max_workers=2) as pool:
        drafts = list(pool.map(create, range(2)))
    assert drafts[0] == drafts[1]
    from backend.services.contract_wizard_types import RevisionCommand
    reviewed = service.review_draft(postgres.store, drafts[0]["id"],
        RevisionCommand(idempotency_key="pg-review", expected_revision=drafts[0]["revision"]), "actor")
    barrier = Barrier(2)
    def save(_):
        with Session(postgres.engine) as db:
            barrier.wait(timeout=10)
            return service.publish_draft(SQLAlchemyStore(db), reviewed["id"], publish(reviewed), "actor")
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(save, range(2)))
    assert results[0] == results[1]
    with Session(postgres.engine) as db:
        store = SQLAlchemyStore(db)
        assert len(store.list_contracts()) == 1 and len(store.list_tenants()) == 2
        assert service.read_pdf(store, reviewed["id"], "actor").startswith(b"%PDF-")


def test_pg_normal_and_wizard_unit_lock_are_shared(postgres):
    check_occupancy(postgres)


def test_pg_failed_publication_is_atomic_and_same_reference_can_retry(postgres, monkeypatch):
    check_rollback(postgres, monkeypatch)
