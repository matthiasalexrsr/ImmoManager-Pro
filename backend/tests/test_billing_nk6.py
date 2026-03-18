"""Sprint-3 / NK-6 billing tests: OCR import, disputed status, statement_id traceability, delivery_channel."""

import datetime

import pytest
from fastapi import HTTPException

from backend.dependencies import store
from backend.models import (
    AllocationKeyCreate,
    BillingPeriodCreate,
    ContractCreate,
    CostItemCreate,
    PortfolioCreate,
    PropertyCreate,
    TenantCreate,
    UnitCreate,
)
from backend.routers import billing
from backend.services.ocr_service import _extract_invoice_fields, _infer_cost_category


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
# OCR field extraction
# ---------------------------------------------------------------------------


def test_extract_invoice_fields_basic():
    text = "Rechnungsnr.: R-2025-001\nDatum: 15.03.2025\nGesamtbetrag: € 1.234,56"
    fields = _extract_invoice_fields(text)
    assert fields["invoice_number"] == "R-2025-001"
    assert fields["invoice_date"] == "15.03.2025"
    assert abs(fields["total_amount"] - 1234.56) < 0.01


def test_extract_supplier():
    text = "Lieferant: Stadtwerke München GmbH\nRechnungsnr.: 42"
    fields = _extract_invoice_fields(text)
    assert fields["supplier"] == "Stadtwerke München GmbH"


def test_extract_supplier_firma():
    text = "Firma: ABC Entsorgung\nSumme: 500,00"
    fields = _extract_invoice_fields(text)
    assert fields["supplier"] == "ABC Entsorgung"


# ---------------------------------------------------------------------------
# Cost category inference
# ---------------------------------------------------------------------------


def test_infer_water_category():
    assert _infer_cost_category("Rechnung für Trinkwasser und Abwasser") == "water"


def test_infer_heating_category():
    assert _infer_cost_category("Fernwärme Abrechnung Heizkosten") == "heating"


def test_infer_garbage_category():
    assert _infer_cost_category("Müllabfuhr Restmüll Entsorgung") == "garbage"


def test_infer_electricity_category():
    assert _infer_cost_category("Allgemeinstrom Beleuchtung Treppenhaus") == "electricity"


def test_infer_insurance_category():
    assert _infer_cost_category("Gebäudeversicherung Haftpflicht") == "insurance"


def test_infer_cleaning_category():
    assert _infer_cost_category("Treppenhausreinigung Gebäudereinigung") == "cleaning"


def test_infer_no_category():
    assert _infer_cost_category("Lorem ipsum dolor sit amet") is None


# ---------------------------------------------------------------------------
# Disputed status
# ---------------------------------------------------------------------------


def test_dispute_finalized_period():
    period, *_ = _setup_full_scenario()
    billing.generate_utility_statements(period.id)
    billing.finalize_billing_period(period.id)

    result = billing.dispute_billing_period(period.id)
    assert result.status == "disputed"


def test_dispute_delivered_period():
    period, *_ = _setup_full_scenario()
    billing.generate_utility_statements(period.id)
    billing.finalize_billing_period(period.id)

    # Mark all as delivered, then patch period to delivered
    stmts = [s for s in store.list_utility_statements() if s.billing_period_id == period.id]
    for stmt in stmts:
        billing.mark_statement_delivered(stmt.id)

    from backend.models import BillingPeriodPatch
    store._patch_entity("billing_period", period.id, BillingPeriodPatch(status="delivered"))

    result = billing.dispute_billing_period(period.id)
    assert result.status == "disputed"


def test_dispute_rejects_draft():
    period, *_ = _setup_full_scenario()
    with pytest.raises(HTTPException) as exc_info:
        billing.dispute_billing_period(period.id)
    assert exc_info.value.status_code == 400


# ---------------------------------------------------------------------------
# Delivery channel
# ---------------------------------------------------------------------------


def test_mark_delivered_sets_channel():
    period, *_ = _setup_full_scenario()
    billing.generate_utility_statements(period.id)
    billing.finalize_billing_period(period.id)

    stmts = [s for s in store.list_utility_statements() if s.billing_period_id == period.id]
    updated = billing.mark_statement_delivered(stmts[0].id, channel="post")
    assert updated.delivery_channel == "post"


def test_mark_delivered_default_channel():
    period, *_ = _setup_full_scenario()
    billing.generate_utility_statements(period.id)
    billing.finalize_billing_period(period.id)

    stmts = [s for s in store.list_utility_statements() if s.billing_period_id == period.id]
    updated = billing.mark_statement_delivered(stmts[0].id)
    assert updated.delivery_channel == "email"


# ---------------------------------------------------------------------------
# Statement -> Receivable traceability
# ---------------------------------------------------------------------------


def test_receivables_include_statement_id():
    period, *_ = _setup_full_scenario()
    billing.generate_utility_statements(period.id)
    billing.finalize_billing_period(period.id)

    result = billing.create_receivables_from_period(period.id)
    assert result["created_receivables"] > 0

    receivables = store.list_receivables()
    period_stmts = [s for s in store.list_utility_statements() if s.billing_period_id == period.id]
    stmt_ids = {s.id for s in period_stmts}

    for r in receivables:
        if r.statement_id:
            assert r.statement_id in stmt_ids
