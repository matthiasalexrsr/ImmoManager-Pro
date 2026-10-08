"""Utility statement regression on a real PostgreSQL server: migration, JSON round trip, portfolio scope.

Opt in with IMMO_TEST_POSTGRES_ADMIN_URL (see test_document_versions_postgres.py).
"""

from datetime import date

import pytest
import sqlalchemy as sa
from alembic import command
from sqlalchemy.orm import Session
from test_document_versions_postgres import postgres  # noqa: F401  (fixture: own database per test)

from backend import auth
from backend.models import (
    AllocationKeyCreate,
    BillingObjectionRequest,
    BillingPeriodCreate,
    ContractCreate,
    ContractOccupancyCreate,
    CostItemCreate,
    MeterCreate,
    PortfolioCreate,
    PropertyCreate,
    StandaloneMeterReadingCreate,
    TenantCreate,
    UnitCreate,
)
from backend.repositories import SQLAlchemyStore
from backend.routers import billing, contracts
from backend.services.data_snapshot import export_snapshot, import_snapshot
from backend.services.final_statements import final_version_problems
from backend.services.portfolio_scope import scope_context, scope_from_user

PARENT = "b8e3d5f7a2c4"


def _house(store, name):
    portfolio = store.create_portfolio(PortfolioCreate(name=name))
    prop = store.create_property(PropertyCreate(portfolio_id=portfolio.id, name=name, property_type="residential"))
    flats = [store.create_unit(UnitCreate(property_id=prop.id, label=f"WE 0{i}", unit_type="residential",
                                          area_sqm=50, service_charge_advance=30)) for i in (1, 2)]
    leases = []
    for flat in flats:
        tenant = store.create_tenant(TenantCreate(full_name=f"Mieter {name} {flat.label}"))
        leases.append(store.create_contract(ContractCreate(
            contract_number=f"{name}-{flat.label}", property_id=prop.id, unit_id=flat.id, tenant_id=tenant.id,
            start_date=date(2020, 1, 1), persons=2)))
    old = store.create_meter(MeterCreate(unit_id=flats[0].id, meter_type="heating", measure_unit="MWh",
                                         removal_date=date(2025, 6, 30), is_active=False))
    new = store.create_meter(MeterCreate(unit_id=flats[0].id, meter_type="heating", measure_unit="kWh",
                                         installation_date=date(2025, 6, 30)))
    other = store.create_meter(MeterCreate(unit_id=flats[1].id, meter_type="heating", measure_unit="kWh"))
    for meter, readings in ((old, [(date(2025, 1, 1), 1.0), (date(2025, 6, 30), 1.5)]),
                            (new, [(date(2025, 6, 30), 0), (date(2025, 12, 31), 500)]),
                            (other, [(date(2025, 1, 1), 0), (date(2025, 12, 31), 1000)])):
        for day, value in readings:
            store.create_standalone_meter_reading(StandaloneMeterReadingCreate(
                meter_id=meter.id, reading_date=day, value=value))
    heat = store.create_allocation_key(AllocationKeyCreate(property_id=prop.id, name="Heizung", key_type="consumption",
                                                           meter_type="heating", measure_unit="kWh"))
    people = store.create_allocation_key(AllocationKeyCreate(property_id=prop.id, name="Personen",
                                                             key_type="person_count"))
    period = store.create_billing_period(BillingPeriodCreate(property_id=prop.id, label="BK 2025",
                                                             start_date=date(2025, 1, 1), end_date=date(2025, 12, 31)))
    for description, amount, key in (("Heizung", 2000, heat), ("Müll", 1000, people)):
        store.create_cost_item(CostItemCreate(billing_period_id=period.id, description=description, amount=amount,
                                              allocation_key_id=key.id))
    return {"portfolio": portfolio, "period": period, "leases": leases, "flats": flats}


@pytest.fixture
def pg_store(postgres, monkeypatch):  # noqa: F811
    engine, config = postgres
    store = SQLAlchemyStore(Session(engine))
    monkeypatch.setattr(billing, "store", store)
    monkeypatch.setattr(contracts, "store", store)
    yield engine, config, store
    store.db.close()


def test_issued_version_correction_and_snapshot_on_postgres(pg_store):
    engine, _, store = pg_store
    house = _house(store, "Nord")
    family = house["leases"][0]
    contracts.add_occupancy(family.id, ContractOccupancyCreate(contract_id=family.id, valid_from=date(2025, 7, 1),
                                                               persons=3))
    stmts = {s.unit_id: s for s in billing.generate_utility_statements(house["period"].id)}
    first, second = (stmts[flat.id] for flat in house["flats"])

    # heat: (1.5 - 1.0) MWh = 500 kWh + 500 kWh = 1,000 kWh vs 1,000 kWh -> 1,000 € each
    # waste: 2 × 181 + 3 × 184 = 914 vs 730 person-days -> 555.96 € / 444.04 €
    assert (first.total_cost, second.total_cost) == (1555.96, 1444.04)
    billing.finalize_billing_period(house["period"].id)

    store.db.expire_all()
    stored = [s for s in store.list_utility_statements() if s.billing_period_id == house["period"].id]
    period = store.get_billing_period(house["period"].id)
    assert final_version_problems(period, stored) == []  # JSON (document, sections) survives PostgreSQL
    pdf = billing.download_utility_statement_pdf(first.id).body

    billing.create_billing_objection(period.id, BillingObjectionRequest(statement_id=first.id, reason="Zähler"))
    revision = billing.create_period_revision(period.id, revision_notes="Zählerwechsel geprüft")
    assert store.get_billing_period(revision["new_period_id"]).corrects_period_id == period.id

    snapshot = export_snapshot(store)
    import_snapshot(store, snapshot, replace=True)
    store.db.expire_all()
    restored = [s for s in store.list_utility_statements() if s.billing_period_id == period.id]
    assert final_version_problems(store.get_billing_period(period.id), restored) == []
    assert billing.download_utility_statement_pdf(first.id).body == pdf
    assert [o.status for o in store.list_billing_objections(period.id)] == ["correction"]


def test_objections_and_occupancies_stay_within_the_portfolio_on_postgres(pg_store):
    engine, _, store = pg_store
    north, south = _house(store, "Nord"), _house(store, "Sued")
    for house in (north, south):
        billing.generate_utility_statements(house["period"].id)
        billing.finalize_billing_period(house["period"].id)
        billing.dispute_billing_period(house["period"].id, reason=f"Widerspruch {house['period'].id}")
        lease = house["leases"][1]
        store.create_contract_occupancy(ContractOccupancyCreate(contract_id=lease.id, valid_from=date(2025, 3, 1),
                                                                persons=1))
    staff = auth.register_user("staff", "s@example.com", "Staff", "Secret123", "verwalter",
                               portfolio_access="selected", portfolio_ids=[north["portfolio"].id])
    store.db.close()

    target = SQLAlchemyStore(Session(engine))
    with scope_context(scope_from_user(auth.get_user_by_id(staff.id) or {})):
        assert {o.billing_period_id for o in target.list_billing_objections()} == {north["period"].id}
        assert {o.contract_id for o in target.list_contract_occupancies()} == {north["leases"][1].id}
    target.db.close()


def test_downgrade_is_refused_while_billing_history_exists_on_postgres(pg_store):
    engine, config, store = pg_store
    house = _house(store, "Nord")
    store.create_contract_occupancy(ContractOccupancyCreate(contract_id=house["leases"][0].id,
                                                            valid_from=date(2025, 3, 1), persons=1))
    store.db.close()

    with pytest.raises(RuntimeError, match="Downgrade would discard billing history"):
        command.downgrade(config, PARENT)
    with engine.begin() as connection:
        for table in ("contract_occupancies", "standalone_meter_readings", "meters"):
            connection.execute(sa.text(f"DELETE FROM {table}"))
        connection.execute(sa.text("UPDATE allocation_keys SET measure_unit = NULL"))
    command.downgrade(config, PARENT)
    with engine.connect() as connection:
        columns = {c["name"] for c in sa.inspect(connection).get_columns("billing_periods")}
        assert "corrects_period_id" not in columns
    command.upgrade(config, "head")
