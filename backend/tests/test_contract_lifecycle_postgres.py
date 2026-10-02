"""Actual dedicated PostgreSQL schema and independent sessions when configured."""

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from threading import Barrier
from types import SimpleNamespace
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi import HTTPException
from sqlalchemy import create_engine, inspect, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from backend import auth
from backend.db.contract_lifecycle_models import LIFECYCLE_MODELS, ContractLifecycleCommandORM
from backend.models import ContractCreate, PortfolioCreate, PropertyCreate, TenantCreate, UnitCreate
from backend.repositories.sql_store import SQLAlchemyStore
from backend.services import contract_lifecycle as service
from backend.services.contract_lifecycle_validation import validate_lifecycle_journal
from backend.tests.test_contract_lifecycle import confirmation, prepare
from backend.tests.test_contract_lifecycle import (
    test_late_journal_failure_rolls_back_business_change_and_can_retry as rollback_case,
)
from backend.tests.test_contract_lifecycle import (
    test_normal_create_competes_with_successor_using_shared_occupancy_lock as normal_competition,
)
from backend.tests.test_contract_lifecycle import (
    test_parallel_confirm_lost_response_and_only_one_successor as replay_case,
)
from backend.tests.test_contract_lifecycle import (
    test_parallel_distinct_termination_drafts_cannot_silently_overwrite_accepted_end as distinct_case,
)
from backend.tests.test_contract_lifecycle import (
    test_parallel_supersessions_have_one_current_leaf_and_stale_review_is_recoverable as supersession_case,
)
from backend.tests.test_contract_lifecycle import (
    test_supersession_failure_rolls_back_both_journals_and_parent_before_retry as supersession_rollback,
)


@pytest.fixture
def postgres(monkeypatch):
    source = os.getenv("TEST_SERVER_DATABASE_URL")
    if not source:
        pytest.skip("TEST_SERVER_DATABASE_URL disposable PostgreSQL is not configured")
    url = make_url(source)
    if url.get_backend_name() != "postgresql":
        pytest.fail("TEST_SERVER_DATABASE_URL must be a dedicated disposable PostgreSQL")
    schema = "lifecycle_" + uuid4().hex
    admin = create_engine(url, hide_parameters=True)
    with admin.begin() as connection:
        connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
    scoped = url.update_query_dict({"options": "-csearch_path=" + schema})
    engine = create_engine(scoped, hide_parameters=True)
    db = None
    try:
        config = Config("alembic.ini")
        monkeypatch.setenv("DATABASE_URL", scoped.render_as_string(hide_password=False))
        config.set_main_option("sqlalchemy.url", scoped.render_as_string(hide_password=False).replace("%", "%%"))
        command.upgrade(config, "z1a2b3c4d5e6")
        for model in LIFECYCLE_MODELS:
            assert set(model.__table__.c.keys()) == {col["name"] for col in inspect(engine).get_columns(model.__tablename__)}
        db = Session(engine)
        store = SQLAlchemyStore(db)
        p = store.create_portfolio(PortfolioCreate(name="Synthetic PG local"))
        property = store.create_property(PropertyCreate(portfolio_id=p.id, name="Synthetic", property_type="residential"))
        unit = store.create_unit(UnitCreate(property_id=property.id, label="A", unit_type="apartment"))
        tenant = store.create_tenant(TenantCreate(full_name="Synthetic PG tenant"))
        contract = store.create_contract(ContractCreate(contract_number="Synthetic-parent", property_id=property.id,
            unit_id=unit.id, tenant_id=tenant.id, start_date=date(2026, 1, 1), end_date=date(2026, 12, 31)))
        users = {"actor": dict(id="actor", role="verwalter", is_active=True, portfolio_access="all"),
                 "readonly": dict(id="readonly", role="readonly", is_active=True, portfolio_access="all")}
        monkeypatch.setattr(auth, "get_user_by_id", lambda identifier: users.get(identifier))
        monkeypatch.setattr(service, "today", lambda: date(2026, 10, 2))
        yield SimpleNamespace(store=store, engine=engine, db=db, users=users, p=p, property=property,
                              unit=unit, tenant=tenant, contract=contract)
    finally:
        if db:
            db.close()
        engine.dispose()
        with admin.begin() as connection:
            connection.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
        admin.dispose()


def test_postgres_parallel_confirmation_replays_one_successor(postgres):
    replay_case(postgres)


def test_postgres_distinct_cas_confirmations_have_one_winner(postgres):
    distinct_case(postgres)


def test_postgres_normal_create_and_confirm_share_native_occupancy_lock(postgres):
    normal_competition(postgres)


def test_postgres_supersession_serializes_parent_and_keeps_stale_private_review(postgres):
    supersession_case(postgres)
    with postgres.engine.connect() as connection:
        assert validate_lifecycle_journal(connection)


def test_postgres_supersession_failure_restores_both_sides_before_retry(postgres, monkeypatch):
    supersession_rollback(postgres, monkeypatch)


@pytest.mark.parametrize("operation", ["termination", "renewal"])
def test_postgres_late_failure_rolls_back_and_retries(postgres, monkeypatch, operation):
    rollback_case(postgres, monkeypatch, operation)


def test_postgres_journal_validation_and_stale_different_command(postgres):
    row = prepare(postgres)
    done = service.confirm_draft(postgres.store, postgres.contract.id, row["id"], confirmation(row), "actor")
    with postgres.engine.connect() as connection:
        assert validate_lifecycle_journal(connection)
    gate = Barrier(2)
    def execute():
        with Session(postgres.engine) as db:
            gate.wait(10)
            try:
                return service.confirm_draft(SQLAlchemyStore(db), postgres.contract.id, row["id"], confirmation(row, "different-key"), "actor")
            except HTTPException as error:
                return error.status_code
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = [future.result(20) for future in [pool.submit(execute), pool.submit(execute)]]
    assert results == [409, 409] and done["state"] == "pending_effective"
    with Session(postgres.engine) as db:
        assert len(list(db.scalars(select(ContractLifecycleCommandORM).where(ContractLifecycleCommandORM.operation == "confirm")))) == 1
