"""Deposit file on a real PostgreSQL server: migration, finalization, triggers, concurrency, downgrade.

Opt in with IMMO_TEST_POSTGRES_ADMIN_URL pointing at a disposable loopback PostgreSQL
server with CREATE DATABASE permission. Each test owns a new immoqa_deposit_<uuid>
database and drops only that database afterwards.
"""

import os
import threading
import uuid
from datetime import date
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config
from fastapi import HTTPException
from sqlalchemy.orm import Session, sessionmaker

import backend.models  # noqa: F401 (register the UI contract columns)
from backend import auth
from backend.models import (
    AccountCreate,
    BookingCreate,
    ContractCreate,
    PortfolioCreate,
    PropertyCreate,
    TenantCreate,
    UnitCreate,
)
from backend.models_deposits import (
    AgreementRequest,
    FinalizeRequest,
    ReceiptRequest,
    SettlementContent,
    SettlementCreate,
)
from backend.repositories import SQLAlchemyStore
from backend.services import deposits as service
from backend.services.document_version_validation import verify_document_versions

MIGRATIONS = Path(__file__).resolve().parents[1] / "db" / "migrations"
DEPOSIT_PARENT = "c9e4a7d2f1b6"
TRIGGERS = {"immo_deposit_settlements_final", "immo_deposit_settlement_items_final", "immo_deposit_instalments_settled",
            "immo_deposit_interest_rates_settled", "immo_deposit_payments_settled", "immo_deposits_settled"}


@pytest.fixture
def postgres(monkeypatch):
    admin_url = os.getenv("IMMO_TEST_POSTGRES_ADMIN_URL")
    if not admin_url:
        pytest.skip("set IMMO_TEST_POSTGRES_ADMIN_URL for real PostgreSQL deposit tests")
    url = sa.engine.make_url(admin_url)
    if url.get_backend_name() != "postgresql" or url.host not in {"localhost", "127.0.0.1", "::1"}:
        pytest.fail("PostgreSQL deposit tests require an explicitly configured loopback server")
    name = f"immoqa_deposit_{uuid.uuid4().hex}"
    admin = sa.create_engine(url, isolation_level="AUTOCOMMIT")
    test_url = url.set(database=name)
    engine = sa.create_engine(test_url)
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS))
    monkeypatch.setenv("DATABASE_URL", test_url.render_as_string(hide_password=False))
    created = False
    try:
        with admin.connect() as connection:
            connection.exec_driver_sql(f'CREATE DATABASE "{name}"')
        created = True
        command.upgrade(config, "head")
        monkeypatch.setattr(auth, "_user_store", auth.SQLUserStore(sessionmaker(engine)))
        yield engine, config
    finally:
        engine.dispose()
        if created:
            with admin.connect() as connection:
                connection.exec_driver_sql(f'DROP DATABASE "{name}" WITH (FORCE)')
        admin.dispose()


def _store(engine):
    return SQLAlchemyStore(Session(engine))


def _draft(engine, owner):
    """A paid deposit of 1500 € with a settlement draft: claim 200, payout 1300."""
    target = _store(engine)
    portfolio = target.create_portfolio(PortfolioCreate(name="Bestand", owner_name="Linda Reiser"))
    prop = target.create_property(PropertyCreate(portfolio_id=portfolio.id, name="Bautzner Straße 61",
                                                 property_type="residential"))
    unit = target.create_unit(UnitCreate(property_id=prop.id, label="WE 3", unit_type="residential", cold_rent=500))
    tenant = target.create_tenant(TenantCreate(full_name="Mia Muster"))
    contract = target.create_contract(ContractCreate(contract_number="V-1", property_id=prop.id, unit_id=unit.id,
                                                     tenant_id=tenant.id, start_date=date(2024, 1, 1),
                                                     end_date=date(2026, 6, 30), status="terminated"))
    account = target.create_account(AccountCreate(portfolio_id=portfolio.id, name="Kautionskonto",
                                                  account_type="deposit"))
    booking = target.create_booking(BookingCreate(account_id=account.id, tenant_id=tenant.id, property_id=prop.id,
                                                  unit_id=unit.id, booking_date=date(2024, 1, 1), amount=1500))
    detail = service.create(_store(engine), AgreementRequest.model_validate(
        {"contract_id": contract.id, "amount": 1500, "account_id": account.id}), owner.id)
    deposit_id = detail["deposit"]["id"]
    service.add_receipt(_store(engine), deposit_id, ReceiptRequest.model_validate({"booking_id": booking.id}), owner.id)
    detail = service.create_settlement(_store(engine), deposit_id, SettlementCreate(), owner.id)
    settlement = detail["settlements"][0]
    service.save_settlement(_store(engine), deposit_id, settlement["id"], SettlementContent.model_validate({
        "base_revision": settlement["revision"], "settlement_date": "2026-06-30",
        "items": [{"kind": "other", "description": "Reinigung", "amount": 200, "reason": "Rechnung 12"}]}), owner.id)
    preview = service.preview(_store(engine), deposit_id, settlement["id"], owner.id)
    assert preview["ready"], preview["problems"]
    return deposit_id, settlement["id"], preview


def test_finalized_settlements_on_postgres_are_immutable_and_refuse_the_downgrade(postgres):
    engine, config = postgres
    owner = auth.register_user("owner", "owner@example.com", "Owner", "Secret123", "eigentuemer")
    deposit_id, settlement_id, preview = _draft(engine, owner)
    done = service.finalize(_store(engine), deposit_id, settlement_id, FinalizeRequest.model_validate(
        {"idempotency_key": "pg-key-1", "review_hash": preview["review_hash"], "confirmed": True}), owner.id)
    final = done["settlements"][0]
    assert done["stage"] == "settled" and final["result_amount"] == 1300.0
    content, row = service.read_original(_store(engine), deposit_id, settlement_id, owner.id)
    assert row.sha256 == preview["pdf_sha256"] and content.startswith(b"%PDF-")
    with engine.connect() as connection:
        amount = connection.execute(sa.text("SELECT amount FROM bookings WHERE id = :id"),
                                    {"id": final["payout_booking_id"]}).scalar()
        assert float(amount) == -1300.0
        assert verify_document_versions(connection) == 1
    for statement in ("UPDATE deposit_settlements SET notes = 'x' WHERE deposit_id = :id",
                      "DELETE FROM deposit_settlements WHERE deposit_id = :id",
                      "UPDATE deposit_payments SET amount = 1 WHERE deposit_id = :id",
                      "DELETE FROM deposit_instalments WHERE deposit_id = :id",
                      "UPDATE deposits SET amount = 1 WHERE id = :id",
                      "UPDATE deposits SET carried_amount = 1 WHERE id = :id",
                      "DELETE FROM deposits WHERE id = :id"):
        with pytest.raises(sa.exc.DBAPIError, match="immutable"):
            with engine.begin() as connection:
                connection.execute(sa.text(statement), {"id": deposit_id})
    with engine.begin() as connection:      # the status may still change (release of a retention)
        connection.execute(sa.text("UPDATE deposits SET notes = 'geprüft' WHERE id = :id"), {"id": deposit_id})

    with engine.connect() as connection:
        before = connection.exec_driver_sql("SELECT version_num FROM alembic_version").scalar()
    with pytest.raises(RuntimeError, match="deposit file data exists"):
        command.downgrade(config, DEPOSIT_PARENT)
    with engine.connect() as connection:     # the refused downgrade changed nothing
        assert connection.exec_driver_sql("SELECT version_num FROM alembic_version").scalar() == before
        assert connection.exec_driver_sql("SELECT count(*) FROM deposit_settlements").scalar() == 1


def test_three_finalizations_of_one_settlement_serialize_on_postgres(postgres):
    engine, _ = postgres
    owner = auth.register_user("owner", "owner@example.com", "Owner", "Secret123", "eigentuemer")
    deposit_id, settlement_id, preview = _draft(engine, owner)
    outcomes: list = []

    def finalize(key):
        try:
            service.finalize(_store(engine), deposit_id, settlement_id, FinalizeRequest.model_validate(
                {"idempotency_key": key, "review_hash": preview["review_hash"], "confirmed": True}), owner.id)
            outcomes.append("ok")
        except HTTPException as error:
            outcomes.append(error.status_code)

    workers = [threading.Thread(target=finalize, args=(f"pg-key-{index}",)) for index in range(3)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(60)
    assert sorted(outcomes, key=str) == [409, 409, "ok"]
    with engine.connect() as connection:
        assert connection.exec_driver_sql("SELECT count(*) FROM document_versions").scalar() == 1
        assert connection.exec_driver_sql("SELECT count(*) FROM deposit_payments WHERE kind = 'payout'").scalar() == 1
        assert connection.exec_driver_sql("SELECT count(*) FROM bookings WHERE amount < 0").scalar() == 1


def test_the_deposit_migration_goes_down_and_up_without_data_on_postgres(postgres):
    engine, config = postgres
    command.downgrade(config, DEPOSIT_PARENT)
    inspector = sa.inspect(engine)
    assert not {"deposit_payments", "deposit_settlements", "deposit_instalments"} & set(inspector.get_table_names())
    assert "form" not in {c["name"] for c in inspector.get_columns("deposits")}
    command.upgrade(config, "head")
    inspector = sa.inspect(engine)
    assert {"deposit_payments", "deposit_settlements", "deposit_settlement_items", "deposit_interest_rates",
            "deposit_instalments"} <= set(inspector.get_table_names())
    with engine.connect() as connection:
        triggers = {row[0] for row in connection.execute(sa.text(
            "SELECT tgname FROM pg_trigger WHERE NOT tgisinternal AND tgname LIKE 'immo_deposit%'"))}
    assert TRIGGERS <= triggers


def test_the_takeover_migration_guards_its_columns_and_the_downgrade_on_postgres(postgres):
    engine, config = postgres
    owner = auth.register_user("owner", "owner@example.com", "Owner", "Secret123", "eigentuemer")
    deposit_id, _, _ = _draft(engine, owner)
    with engine.begin() as connection:
        connection.execute(sa.text("UPDATE deposits SET carried_on = '2024-01-01', carried_amount = 100 "
                                   "WHERE id = :id"), {"id": deposit_id})
    with pytest.raises(RuntimeError, match="takeover of deposits"):
        command.downgrade(config, "f019a1b2c001")
    with engine.begin() as connection:
        connection.execute(sa.text("UPDATE deposits SET carried_on = NULL, carried_amount = NULL"))
    command.downgrade(config, "f019a1b2c001")
    columns = {c["name"] for c in sa.inspect(engine).get_columns("deposits")}
    assert not {"carried_on", "carried_amount", "carried_interest", "carried_note"} & columns
    with engine.connect() as connection:
        definition = connection.exec_driver_sql(
            "SELECT pg_get_triggerdef(oid) FROM pg_trigger WHERE tgname = 'immo_deposits_settled'").scalar()
    assert "UPDATE OF contract_id, amount, form " in definition
    command.upgrade(config, "head")
    with engine.connect() as connection:
        definition = connection.exec_driver_sql(
            "SELECT pg_get_triggerdef(oid) FROM pg_trigger WHERE tgname = 'immo_deposits_settled'").scalar()
    assert "carried_amount" in definition
