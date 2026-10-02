"""Isolated PostgreSQL gates for Wohnungsgeberbestätigung publication."""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from threading import Barrier, local
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from backend import auth
from backend.db.access_models import ResourcePortfolioORM
from backend.db.document_version_models import (
    DocumentVersionORM,
    ensure_document_version_schema,
)
from backend.db.orm_models import Base
from backend.models import (
    ContractCreate,
    PortfolioCreate,
    PropertyCreate,
    TenantCreate,
    UnitCreate,
)
from backend.repositories.sql_store import SQLAlchemyStore
from backend.services import housing_confirmation as service
from backend.services.document_version_validation import _verify_document_versions
from backend.tests.test_housing_confirmation import (
    preview_payload,
    save_payload,
)


@pytest.fixture
def postgres_housing(monkeypatch):
    source = os.getenv("TEST_SERVER_DATABASE_URL")
    if not source:
        pytest.skip("TEST_SERVER_DATABASE_URL disposable PostgreSQL is not configured")
    url = make_url(source)
    if url.get_backend_name() != "postgresql":
        pytest.fail("TEST_SERVER_DATABASE_URL must reference PostgreSQL")

    schema = "housing_confirmation_" + uuid4().hex
    admin = create_engine(url, hide_parameters=True, pool_pre_ping=True)
    with admin.begin() as connection:
        connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')

    scoped = url.update_query_dict({"options": "-csearch_path=" + schema})
    engine = create_engine(
        scoped,
        hide_parameters=True,
        pool_pre_ping=True,
        pool_size=6,
        max_overflow=2,
    )
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        ensure_document_version_schema(connection)
        assert connection.scalar(text("select current_schema()")) == schema

    db = Session(engine)
    store = SQLAlchemyStore(db)
    portfolio = store.create_portfolio(PortfolioCreate(name="Synthetic PG"))
    prop = store.create_property(
        PropertyCreate(
            portfolio_id=portfolio.id,
            name="PG property",
            property_type="residential",
            address_line="PG Straße 1",
            postal_code="66111",
            city="Saarbrücken",
            country="Deutschland",
        )
    )
    unit = store.create_unit(
        UnitCreate(
            property_id=prop.id,
            label="PG-A",
            unit_type="apartment",
        )
    )
    tenant = store.create_tenant(TenantCreate(full_name="PG Synthetic Tenant"))
    db.add(
        ResourcePortfolioORM(
            resource_type="tenants",
            resource_id=tenant.id,
            portfolio_id=portfolio.id,
        )
    )
    db.commit()
    contract = store.create_contract(
        ContractCreate(
            contract_number="PG-HOUSING-1",
            property_id=prop.id,
            unit_id=unit.id,
            tenant_id=tenant.id,
            start_date=date(2026, 1, 1),
            end_date=date(2027, 12, 31),
        )
    )
    users = {
        "actor": {
            "id": "actor",
            "role": "verwalter",
            "is_active": True,
            "portfolio_access": "selected",
            "portfolio_ids": [portfolio.id],
        }
    }
    monkeypatch.setattr(auth, "get_user_by_id", lambda identifier: users.get(identifier))
    box = SimpleNamespace(
        store=store,
        engine=engine,
        db=db,
        users=users,
        p=portfolio,
        property=prop,
        unit=unit,
        tenant=tenant,
        contract=contract,
    )
    try:
        yield box
    finally:
        db.close()
        engine.dispose()
        try:
            with admin.begin() as connection:
                connection.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
        finally:
            admin.dispose()


def test_postgres_atomic_publish_replay_and_stale_source_gate(postgres_housing):
    box = postgres_housing
    payload = preview_payload(
        box,
        move_in_date=date(2026, 1, 15),
        apartment_address="PG Straße 1\n66111 Saarbrücken",
        apartment_label="PG-A",
        residents=["PG Synthetic Tenant", "PG Zusatzperson"],
    )
    review = service.preview(box.store, box.contract.id, payload, "actor")
    command = save_payload(payload, review, key="postgres-stable-key")

    first = service.publish(box.store, box.contract.id, command, "actor")
    second = service.publish(box.store, box.contract.id, command, "actor")
    assert second == first

    with Session(box.engine) as db:
        assert db.query(DocumentVersionORM).count() == 1
    page = service.listing(
        box.store, box.contract.id, "actor", limit=1
    )
    assert page["items"][0]["document_id"] == first["document_id"]
    with box.engine.connect() as connection:
        assert _verify_document_versions(connection) == 1

    stale_payload = preview_payload(
        box,
        move_in_date=date(2026, 1, 16),
        apartment_address="PG Straße 1\n66111 Saarbrücken",
        apartment_label="PG-A",
        residents=["PG Synthetic Tenant"],
    )
    stale_review = service.preview(
        box.store, box.contract.id, stale_payload, "actor"
    )
    tenant = box.store.get_tenant(box.tenant.id)
    box.store.update_tenant(
        tenant.id,
        TenantCreate(
            **{
                **tenant.model_dump(
                    exclude={"id", "created_at", "updated_at"}
                ),
                "full_name": "PG Tenant renamed after preview",
            }
        ),
    )
    with pytest.raises(HTTPException) as failure:
        service.publish(
            box.store,
            box.contract.id,
            save_payload(
                stale_payload,
                stale_review,
                key="postgres-stale-source",
            ),
            "actor",
        )
    assert failure.value.status_code == 412

    with Session(box.engine) as db:
        assert db.query(DocumentVersionORM).count() == 1


def test_postgres_parallel_same_key_has_one_original_then_safe_replay(
    postgres_housing, monkeypatch
):
    box = postgres_housing
    payload = preview_payload(
        box,
        move_in_date=date(2026, 1, 20),
        apartment_address="PG Straße 1\n66111 Saarbrücken",
        apartment_label="PG-A",
        residents=["PG Synthetic Tenant", "PG Parallelperson"],
    )
    review = service.preview(box.store, box.contract.id, payload, "actor")
    command = save_payload(payload, review, key="postgres-parallel-key")

    original_fence = service.lock_subject_write_fence
    barrier = Barrier(2, timeout=15)
    state = local()

    def synchronized_fence(store, tenant_id):
        if not getattr(state, "released", False):
            state.released = True
            barrier.wait()
        return original_fence(store, tenant_id)

    monkeypatch.setattr(
        service,
        "lock_subject_write_fence",
        synchronized_fence,
    )

    def worker():
        with Session(box.engine) as outer:
            store = SQLAlchemyStore(outer)
            try:
                return (
                    "ok",
                    service.publish(
                        store, box.contract.id, command, "actor"
                    ),
                )
            except BaseException as error:
                return ("error", error)

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = [
            future.result(timeout=25)
            for future in [executor.submit(worker), executor.submit(worker)]
        ]

    monkeypatch.setattr(
        service,
        "lock_subject_write_fence",
        original_fence,
    )
    winners = [value for status, value in results if status == "ok"]
    losers = [value for status, value in results if status == "error"]
    assert len(winners) == 1
    assert len(losers) == 1
    assert isinstance(losers[0], HTTPException)
    assert losers[0].status_code == 409

    replay = service.publish(
        box.store, box.contract.id, command, "actor"
    )
    assert replay == winners[0]
    with Session(box.engine) as db:
        assert db.query(DocumentVersionORM).count() == 1
