"""Tests for the full billing workflow: generate, finalize, receivables, revisions, delivery."""

import datetime

from backend.dependencies import store
from backend.models import (
    AllocationKeyCreate,
    BillingPeriodCreate,
    ContractCreate,
    CostItemCreate,
    MeterCreate,
    PortfolioCreate,
    PropertyCreate,
    StandaloneMeterReadingCreate,
    TenantCreate,
    UnitCreate,
)
from backend.routers import billing


def _clear_store() -> None:
    for collection in (
        store.portfolios, store.properties, store.units, store.tenants,
        store.contracts, store.billing_periods, store.allocation_keys,
        store.cost_items, store.utility_statements, store.receivables,
    ):
        collection.clear()


def _setup_full_scenario():
    """Create a complete scenario: 2 units, area_sqm key, 2 cost items."""
    _clear_store()
    portfolio = store.create_portfolio(PortfolioCreate(name="Test"))
    prop = store.create_property(PropertyCreate(portfolio_id=portfolio.id, name="Haus A", property_type="MFH"))

    u1 = store.create_unit(UnitCreate(
        property_id=prop.id, label="EG links", unit_type="Wohnung",
        area_sqm=60.0, rooms=3.0, service_charge_advance=150.0, heating_advance=50.0,
    ))
    u2 = store.create_unit(UnitCreate(
        property_id=prop.id, label="EG rechts", unit_type="Wohnung",
        area_sqm=40.0, rooms=2.0, service_charge_advance=100.0, heating_advance=30.0,
    ))

    t1 = store.create_tenant(TenantCreate(full_name="Müller"))
    t2 = store.create_tenant(TenantCreate(full_name="Schmidt"))

    c1 = store.create_contract(ContractCreate(
        contract_number="C-1", property_id=prop.id, unit_id=u1.id,
        tenant_id=t1.id, start_date=datetime.date(2025, 1, 1),
    ))
    c2 = store.create_contract(ContractCreate(
        contract_number="C-2", property_id=prop.id, unit_id=u2.id,
        tenant_id=t2.id, start_date=datetime.date(2025, 1, 1),
    ))

    period = store.create_billing_period(BillingPeriodCreate(
        property_id=prop.id, label="NK 2025",
        start_date=datetime.date(2025, 1, 1), end_date=datetime.date(2025, 12, 31),
    ))

    key_area = store.create_allocation_key(AllocationKeyCreate(
        property_id=prop.id, name="Fläche", key_type="area_sqm",
    ))

    store.create_cost_item(CostItemCreate(
        billing_period_id=period.id, description="Wasser",
        amount=500.0, allocation_key_id=key_area.id,
    ))
    store.create_cost_item(CostItemCreate(
        billing_period_id=period.id, description="Müllabfuhr",
        amount=300.0, allocation_key_id=key_area.id,
    ))

    return period, prop, u1, u2, c1, c2, key_area


# ---------------------------------------------------------------------------
# Generate + line_items
# ---------------------------------------------------------------------------

def test_generate_stores_line_items():
    period, *_ = _setup_full_scenario()
    stmts = billing.generate_utility_statements(period.id)
    assert len(stmts) == 2
    for stmt in stmts:
        assert stmt.line_items is not None
        assert len(stmt.line_items) == 2  # Wasser + Müllabfuhr
        for li in stmt.line_items:
            assert "description" in li
            assert "allocated_amount" in li


# ---------------------------------------------------------------------------
# Finalize
# ---------------------------------------------------------------------------

def test_finalize_period_updates_all_statements():
    period, *_ = _setup_full_scenario()
    billing.generate_utility_statements(period.id)

    result = billing.finalize_billing_period(period.id)
    assert result.status == "finalized"

    stmts = [s for s in store.list_utility_statements() if s.billing_period_id == period.id]
    for s in stmts:
        assert s.status == "finalized"


def test_finalize_already_finalized_is_idempotent():
    period, *_ = _setup_full_scenario()
    billing.generate_utility_statements(period.id)
    billing.finalize_billing_period(period.id)
    result = billing.finalize_billing_period(period.id)
    assert result.status == "finalized"


# ---------------------------------------------------------------------------
# CSV Export
# ---------------------------------------------------------------------------

def test_export_period_csv():
    period, *_ = _setup_full_scenario()
    billing.generate_utility_statements(period.id)

    response = billing.export_billing_period(period.id)
    assert response.media_type == "text/csv"
    body = response.body.decode("utf-8")
    assert "statement_id" in body
    assert "Wasser" not in body  # CSV has IDs, not cost descriptions
    lines = body.strip().split("\n")
    assert len(lines) == 3  # header + 2 statements


# ---------------------------------------------------------------------------
# Mark Delivered
# ---------------------------------------------------------------------------

def test_mark_statement_delivered():
    period, *_ = _setup_full_scenario()
    stmts = billing.generate_utility_statements(period.id)

    updated = billing.mark_statement_delivered(stmts[0].id)
    assert updated.delivery_status == "delivered"
    assert updated.delivered_at is not None
    assert updated.status == "delivered"


# ---------------------------------------------------------------------------
# Create Receivables
# ---------------------------------------------------------------------------

def test_create_receivables_from_finalized_period():
    period, *_ = _setup_full_scenario()
    billing.generate_utility_statements(period.id)
    billing.finalize_billing_period(period.id)

    result = billing.create_receivables_from_period(period.id)
    assert result["created_receivables"] >= 1

    receivables = store.list_receivables()
    assert len(receivables) >= 1


def test_create_receivables_rejects_draft_period():
    period, *_ = _setup_full_scenario()
    billing.generate_utility_statements(period.id)

    import pytest
    from fastapi import HTTPException
    with pytest.raises(HTTPException) as exc_info:
        billing.create_receivables_from_period(period.id)
    assert exc_info.value.status_code == 400


# ---------------------------------------------------------------------------
# Revisions
# ---------------------------------------------------------------------------

def test_create_revision_creates_new_period():
    period, *_ = _setup_full_scenario()
    billing.generate_utility_statements(period.id)

    result = billing.create_period_revision(period.id)
    assert result["source_period_id"] == period.id
    assert result["revision"] == 2

    new_period = store.get_billing_period(result["new_period_id"])
    assert new_period.status == "draft"
    assert "Korrektur" in new_period.label

    # Cost items should be copied
    new_costs = [ci for ci in store.list_cost_items() if ci.billing_period_id == new_period.id]
    old_costs = [ci for ci in store.list_cost_items() if ci.billing_period_id == period.id]
    assert len(new_costs) == len(old_costs)


# ---------------------------------------------------------------------------
# PDF Generation
# ---------------------------------------------------------------------------

def test_statement_pdf_generation():
    period, *_ = _setup_full_scenario()
    stmts = billing.generate_utility_statements(period.id)

    response = billing.download_utility_statement_pdf(stmts[0].id)
    assert response.media_type in {"application/pdf", "text/plain"}
    assert "statement_" in response.headers.get("content-disposition", "")


# ---------------------------------------------------------------------------
# Consumption-based allocation via meter readings
# ---------------------------------------------------------------------------

def test_consumption_based_generation():
    _clear_store()
    portfolio = store.create_portfolio(PortfolioCreate(name="P"))
    prop = store.create_property(PropertyCreate(portfolio_id=portfolio.id, name="H", property_type="MFH"))

    u1 = store.create_unit(UnitCreate(
        property_id=prop.id, label="W1", unit_type="Wohnung",
        area_sqm=50.0, service_charge_advance=100.0, heating_advance=50.0,
    ))
    u2 = store.create_unit(UnitCreate(
        property_id=prop.id, label="W2", unit_type="Wohnung",
        area_sqm=50.0, service_charge_advance=100.0, heating_advance=50.0,
    ))

    t1 = store.create_tenant(TenantCreate(full_name="A"))
    t2 = store.create_tenant(TenantCreate(full_name="B"))
    store.create_contract(ContractCreate(
        contract_number="C1", property_id=prop.id, unit_id=u1.id,
        tenant_id=t1.id, start_date=datetime.date(2025, 1, 1),
    ))
    store.create_contract(ContractCreate(
        contract_number="C2", property_id=prop.id, unit_id=u2.id,
        tenant_id=t2.id, start_date=datetime.date(2025, 1, 1),
    ))

    period = store.create_billing_period(BillingPeriodCreate(
        property_id=prop.id, label="NK 2025",
        start_date=datetime.date(2025, 1, 1), end_date=datetime.date(2025, 12, 31),
    ))

    key = store.create_allocation_key(AllocationKeyCreate(
        property_id=prop.id, name="Verbrauch", key_type="consumption",
    ))
    store.create_cost_item(CostItemCreate(
        billing_period_id=period.id, description="Heizung",
        amount=1000.0, allocation_key_id=key.id,
    ))

    # Create meters and readings: u1 consumes 300, u2 consumes 100
    m1 = store.create_meter(MeterCreate(unit_id=u1.id, meter_type="heating"))
    m2 = store.create_meter(MeterCreate(unit_id=u2.id, meter_type="heating"))
    store.create_standalone_meter_reading(StandaloneMeterReadingCreate(
        meter_id=m1.id, reading_date=datetime.date(2025, 1, 1), value=1000.0,
    ))
    store.create_standalone_meter_reading(StandaloneMeterReadingCreate(
        meter_id=m1.id, reading_date=datetime.date(2025, 12, 31), value=1300.0,
    ))
    store.create_standalone_meter_reading(StandaloneMeterReadingCreate(
        meter_id=m2.id, reading_date=datetime.date(2025, 1, 1), value=500.0,
    ))
    store.create_standalone_meter_reading(StandaloneMeterReadingCreate(
        meter_id=m2.id, reading_date=datetime.date(2025, 12, 31), value=600.0,
    ))

    stmts = billing.generate_utility_statements(period.id)
    assert len(stmts) == 2

    # u1: 300/(300+100) * 1000 = 750
    # u2: 100/(300+100) * 1000 = 250
    costs_by_unit = {s.unit_id: s.total_cost for s in stmts}
    assert costs_by_unit[u1.id] == 750.0
    assert costs_by_unit[u2.id] == 250.0
