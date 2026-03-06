"""Sprint-2 billing tests: status guards, immutability, snapshot hash, review workflow, ZIP export."""

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
# Status transition: submit-review, revert-draft
# ---------------------------------------------------------------------------

def test_submit_review_from_draft():
    period, *_ = _setup_full_scenario()
    assert period.status == "draft"
    result = billing.submit_period_for_review(period.id)
    assert result.status == "review"


def test_submit_review_rejects_non_draft():
    period, *_ = _setup_full_scenario()
    billing.generate_utility_statements(period.id)
    billing.finalize_billing_period(period.id)
    with pytest.raises(HTTPException) as exc_info:
        billing.submit_period_for_review(period.id)
    assert exc_info.value.status_code == 400


def test_revert_draft_from_review():
    period, *_ = _setup_full_scenario()
    billing.submit_period_for_review(period.id)
    result = billing.revert_period_to_draft(period.id)
    assert result.status == "draft"


def test_revert_draft_rejects_non_review():
    period, *_ = _setup_full_scenario()
    with pytest.raises(HTTPException) as exc_info:
        billing.revert_period_to_draft(period.id)
    assert exc_info.value.status_code == 400


# ---------------------------------------------------------------------------
# Finalize from review status
# ---------------------------------------------------------------------------

def test_finalize_from_review():
    period, *_ = _setup_full_scenario()
    billing.submit_period_for_review(period.id)
    billing.generate_utility_statements(period.id)
    result = billing.finalize_billing_period(period.id)
    assert result.status == "finalized"


# ---------------------------------------------------------------------------
# Snapshot hash on finalization
# ---------------------------------------------------------------------------

def test_finalize_stores_snapshot_hash():
    period, *_ = _setup_full_scenario()
    billing.generate_utility_statements(period.id)
    billing.finalize_billing_period(period.id)

    stmts = [s for s in store.list_utility_statements() if s.billing_period_id == period.id]
    assert len(stmts) >= 1
    for s in stmts:
        assert s.snapshot_hash is not None
        assert len(s.snapshot_hash) == 64  # SHA-256 hex


def test_snapshot_hash_is_deterministic():
    """Same data should produce the same hash."""
    period, *_ = _setup_full_scenario()
    billing.generate_utility_statements(period.id)

    hash1 = billing._compute_snapshot_hash(period.id)
    hash2 = billing._compute_snapshot_hash(period.id)
    assert hash1 == hash2


# ---------------------------------------------------------------------------
# Immutability: finalized periods cannot be modified
# ---------------------------------------------------------------------------

def test_finalized_period_rejects_update():
    period, prop, u1, u2, c1, c2, key_area = _setup_full_scenario()
    billing.generate_utility_statements(period.id)
    billing.finalize_billing_period(period.id)

    with pytest.raises(HTTPException) as exc_info:
        billing.update_billing_period(period.id, BillingPeriodCreate(
            property_id=prop.id, label="Changed", start_date=period.start_date,
            end_date=period.end_date, status="draft",
        ))
    assert exc_info.value.status_code == 409


def test_finalized_period_rejects_delete():
    period, *_ = _setup_full_scenario()
    billing.generate_utility_statements(period.id)
    billing.finalize_billing_period(period.id)

    with pytest.raises(HTTPException) as exc_info:
        billing.delete_billing_period(period.id)
    assert exc_info.value.status_code == 409


def test_finalized_period_rejects_new_cost_item():
    period, prop, u1, u2, c1, c2, key_area = _setup_full_scenario()
    billing.generate_utility_statements(period.id)
    billing.finalize_billing_period(period.id)

    with pytest.raises(HTTPException) as exc_info:
        billing.create_cost_item(CostItemCreate(
            billing_period_id=period.id, description="Strom",
            amount=200.0, allocation_key_id=key_area.id,
        ))
    assert exc_info.value.status_code == 409


def test_finalized_period_rejects_regeneration():
    period, *_ = _setup_full_scenario()
    billing.generate_utility_statements(period.id)
    billing.finalize_billing_period(period.id)

    with pytest.raises(HTTPException) as exc_info:
        billing.generate_utility_statements(period.id)
    assert exc_info.value.status_code == 409


def test_finalized_period_rejects_statement_patch():
    period, *_ = _setup_full_scenario()
    billing.generate_utility_statements(period.id)
    billing.finalize_billing_period(period.id)

    stmts = [s for s in store.list_utility_statements() if s.billing_period_id == period.id]
    from backend.models import UtilityStatementPatch
    with pytest.raises(HTTPException) as exc_info:
        billing.patch_utility_statement(stmts[0].id, UtilityStatementPatch(notes="test"))
    assert exc_info.value.status_code == 409


# ---------------------------------------------------------------------------
# Mark delivered guard: requires finalized period
# ---------------------------------------------------------------------------

def test_mark_delivered_rejects_draft_period():
    period, *_ = _setup_full_scenario()
    billing.generate_utility_statements(period.id)

    stmts = [s for s in store.list_utility_statements() if s.billing_period_id == period.id]
    with pytest.raises(HTTPException) as exc_info:
        billing.mark_statement_delivered(stmts[0].id)
    assert exc_info.value.status_code == 400


# ---------------------------------------------------------------------------
# Batch ZIP export
# ---------------------------------------------------------------------------

def test_export_zip_returns_zip():
    period, *_ = _setup_full_scenario()
    billing.generate_utility_statements(period.id)

    response = billing.export_billing_period_zip(period.id)
    assert response.media_type == "application/zip"
    assert len(response.body) > 0
    # Verify it's a valid ZIP (magic bytes PK\x03\x04)
    assert response.body[:4] == b"PK\x03\x04"


def test_export_zip_rejects_empty_period():
    period, *_ = _setup_full_scenario()
    # Don't generate statements
    with pytest.raises(HTTPException) as exc_info:
        billing.export_billing_period_zip(period.id)
    assert exc_info.value.status_code == 400


# ---------------------------------------------------------------------------
# Finalize rejects invalid status
# ---------------------------------------------------------------------------

def test_finalize_rejects_delivered_status():
    """Periods already in 'delivered' status cannot be re-finalized."""
    period, *_ = _setup_full_scenario()
    billing.generate_utility_statements(period.id)
    billing.finalize_billing_period(period.id)

    # Manually mark all statements as delivered
    stmts = [s for s in store.list_utility_statements() if s.billing_period_id == period.id]
    for stmt in stmts:
        billing.mark_statement_delivered(stmt.id)

    # Patch period to delivered status
    from backend.models import BillingPeriodPatch
    store._patch_entity(
        None, period.id,
        BillingPeriodPatch(status="delivered"),
        "Abrechnungsperiode nicht gefunden",
    )
    refreshed = store.get_billing_period(period.id)
    assert refreshed.status == "delivered"

    with pytest.raises(HTTPException) as exc_info:
        billing.finalize_billing_period(period.id)
    assert exc_info.value.status_code == 400
