"""Explicit owner cost allocation and blockers for unsupported vacant-unit bases."""

from datetime import date
from decimal import Decimal

import pytest
from fastapi import HTTPException

from backend.dependencies import store
from backend.domain.billing_engine import BillingEngine, CostEntry, UnitShare
from backend.models import (
    AllocationKeyCreate,
    BillingPeriodCreate,
    ContractCreate,
    CostItemCreate,
    TenantCreate,
    UnitCreate,
)
from backend.routers import billing
from backend.tests.test_billing_integrity import pay, scenario


@pytest.fixture(autouse=True)
def clear_store():
    store.clear_all()
    yield
    store.clear_all()


def vacant_unit(period, area=50):
    return store.create_unit(UnitCreate(property_id=period.property_id, label="Leerstand",
        unit_type="Wohnung", area_sqm=area, rooms=2, person_count=2))


def change_key(cost, key_type):
    key = store.get_allocation_key(cost.allocation_key_id)
    return store.update_allocation_key(key.id, AllocationKeyCreate(
        **{**key.model_dump(include=set(AllocationKeyCreate.model_fields)), "key_type": key_type}))


@pytest.mark.parametrize("key_type, owner_area, tenant_expected", [
    ("unit_count", 50, 50), ("area_sqm", 50, 50), ("area_sqm", 150, 25)])
def test_empty_unit_cost_share_is_borne_by_owner(key_type, owner_area, tenant_expected):
    period, _, _, cost = scenario()
    empty = vacant_unit(period, owner_area)
    change_key(cost, key_type)
    statement = billing.generate_utility_statements(period.id)[0]
    owner = store.get_billing_period(period.id).owner_cost_share
    assert statement.total_cost == tenant_expected
    assert owner["total_amount"] == 100 - tenant_expected
    assert owner["property_cost_total"] == owner["tenant_cost_total"] + owner["total_amount"] == 100
    assert owner["vacant_unit_days"] == {empty.id: 31}
    assert owner["line_items"][0]["reason"] == "vacancy"
    assert owner["line_items"][0]["cost_item_id"] == cost.id
    assert owner["line_items"][0]["unit_id"] == empty.id
    billing.finalize_billing_period(period.id)
    result = billing.create_receivables_from_period(period.id)
    assert result["debts_total"] == tenant_expected
    assert len(store.list_receivables()) == 1


@pytest.mark.parametrize("key_type", ["unit_count", "area_sqm"])
def test_partial_month_vacancy_keeps_time_share_with_owner(key_type):
    period, contracts, _, cost = scenario()
    contract = contracts[0]
    store.update_contract(contract.id, ContractCreate(**{**contract.model_dump(include=set(ContractCreate.model_fields)),
        "start_date": date(2025, 1, 16)}))
    change_key(cost, key_type)
    statement = billing.generate_utility_statements(period.id)[0]
    owner = store.get_billing_period(period.id).owner_cost_share
    assert statement.total_cost == 51.61
    assert owner["total_amount"] == 48.39
    assert owner["vacant_unit_days"] == {contract.unit_id: 15}
    assert statement.total_cost + owner["total_amount"] == 100
    billing.finalize_billing_period(period.id)


def test_under_year_vacancy_is_explicit_even_if_unit_currently_rented():
    period, contracts, _, _ = scenario(cost=365)
    period = store.update_billing_period(period.id, BillingPeriodCreate(
        **{**period.model_dump(include=set(BillingPeriodCreate.model_fields)), "end_date": date(2025, 12, 31)}))
    contract = contracts[0]
    store.update_contract(contract.id, ContractCreate(**{**contract.model_dump(include=set(ContractCreate.model_fields)),
        "end_date": date(2025, 6, 30), "status": "terminated"}))
    tenant = store.create_tenant(TenantCreate(full_name="Neu"))
    second = store.create_contract(ContractCreate(contract_number="V-next", property_id=period.property_id,
        unit_id=contract.unit_id, tenant_id=tenant.id, start_date=date(2025, 7, 16)))
    unit = store.get_unit(contract.unit_id)
    store.update_unit(unit.id, UnitCreate(**{**unit.model_dump(include=set(UnitCreate.model_fields)), "status": "rented"}))
    generated = {s.contract_id: s for s in billing.generate_utility_statements(period.id)}
    owner = store.get_billing_period(period.id).owner_cost_share
    assert generated[contract.id].total_cost == 181
    assert generated[second.id].total_cost == 169
    assert owner["total_amount"] == 15
    assert owner["vacant_unit_days"] == {contract.unit_id: 15}
    assert sum(s.total_cost for s in generated.values()) + owner["total_amount"] == 365


@pytest.mark.parametrize("key_type", ["person_count", "consumption"])
@pytest.mark.parametrize("partial", [False, True])
def test_vacancy_missing_resident_or_consumption_basis_blocks_without_mutating_costs(key_type, partial):
    period, contracts, _, cost = scenario()
    original = billing.generate_utility_statements(period.id)[0]
    if partial:
        contract = contracts[0]
        store.update_contract(contract.id, ContractCreate(**{**contract.model_dump(include=set(ContractCreate.model_fields)),
            "start_date": date(2025, 1, 16)}))
    else:
        vacant_unit(period)
    change_key(cost, key_type)
    costs_before = [c.model_dump() for c in store.list_cost_items()]
    result = billing.get_billing_period_preflight(period.id)
    assert "VACANCY_ALLOCATION_BASIS_MISSING" in {i.code for i in result.blockers}
    with pytest.raises(HTTPException) as error:
        billing.generate_utility_statements(period.id)
    assert error.value.status_code == 400
    assert [c.model_dump() for c in store.list_cost_items()] == costs_before
    assert store.get_utility_statement(original.id).total_cost == 100
    assert store.get_billing_period(period.id).status == "draft"


def test_owner_area_missing_blocks_instead_of_distributing_to_remaining_tenants():
    period, _, _, cost = scenario()
    vacant_unit(period, area=None)
    change_key(cost, "area_sqm")
    assert "MISSING_OWNER_AREA" in {i.code for i in billing.get_billing_period_preflight(period.id).blockers}
    with pytest.raises(HTTPException):
        billing.generate_utility_statements(period.id)
    assert store.list_utility_statements() == []


def test_unknown_key_cannot_silently_fall_back_to_equal_tenant_allocation():
    period, _, _, cost = scenario()
    change_key(cost, "custom_missing_basis")
    assert "UNKNOWN_ALLOCATION_TYPE" in {i.code for i in billing.get_billing_period_preflight(period.id).blockers}
    with pytest.raises(HTTPException):
        billing.generate_utility_statements(period.id)


def test_non_recoverable_costs_and_vacancy_together_preserve_all_property_costs():
    period, _, _, cost = scenario()
    vacant_unit(period)
    store.create_cost_item(CostItemCreate(billing_period_id=period.id, description="Eigentümer", amount=70,
        allocation_key_id=cost.allocation_key_id, is_recoverable=False))
    statement = billing.generate_utility_statements(period.id)[0]
    owner = store.get_billing_period(period.id).owner_cost_share
    assert statement.total_cost == 50
    assert owner["recoverable_vacancy_amount"] == 50
    assert owner["non_recoverable_amount"] == 70
    assert owner["total_amount"] == 120
    assert statement.total_cost + owner["total_amount"] == 170
    billing.finalize_billing_period(period.id)


def test_owner_only_costs_still_refund_actual_tenant_advances():
    period, _, charges, cost = scenario()
    store.update_cost_item(cost.id, CostItemCreate(**{**cost.model_dump(include=set(CostItemCreate.model_fields)),
        "is_recoverable": False}))
    pay(charges[0], 700)
    statement = billing.generate_utility_statements(period.id)[0]
    assert statement.total_cost == 0
    assert statement.advance_paid == 150
    assert statement.balance == -150
    assert store.get_billing_period(period.id).owner_cost_share["total_amount"] == 100
    billing.finalize_billing_period(period.id)
    assert billing.create_receivables_from_period(period.id)["credits_total"] == 150


def test_new_vacant_unit_changes_basis_and_prevents_finalizing_stale_allocation():
    period, *_ = scenario()
    billing.generate_utility_statements(period.id)
    vacant_unit(period)
    with pytest.raises(HTTPException) as error:
        billing.finalize_billing_period(period.id)
    assert error.value.status_code == 409


def test_finalized_owner_share_is_immutable_under_later_unit_and_payment_changes():
    period, _, charges, _ = scenario()
    empty = vacant_unit(period)
    billing.generate_utility_statements(period.id)
    before = billing.finalize_billing_period(period.id).owner_cost_share
    store.update_unit(empty.id, UnitCreate(**{**empty.model_dump(include=set(UnitCreate.model_fields)), "area_sqm": 999}))
    pay(charges[0], 350)
    assert store.get_billing_period(period.id).owner_cost_share == before


@pytest.mark.parametrize("amount", ["0.01", "-0.01"])
def test_tiny_invoice_cents_never_create_negative_owner_share_by_rounding(amount):
    engine = BillingEngine()
    for index in range(10):
        engine.add_unit_share("units", UnitShare(unit_id=f"u{index}", contract_id=f"c{index}", share_value=Decimal("1")))
    engine.add_unit_share("units", UnitShare(unit_id="vacant", contract_id="owner", share_value=Decimal(".1")))
    engine.add_cost(CostEntry(description="Cent invoice", amount=Decimal(amount), allocation_key_id="units"))
    statements = engine.generate()
    assert sum(s.total_cost for s in statements) == Decimal(amount)
    assert all(s.total_cost >= 0 for s in statements) if Decimal(amount) > 0 else all(s.total_cost <= 0 for s in statements)
