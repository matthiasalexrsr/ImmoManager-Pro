"""A finalization reuses its locked calculation without changing issued content."""

from datetime import date
from functools import wraps

import pytest
from fastapi import HTTPException

from backend.dependencies import store
from backend.models import (
    AllocationKeyCreate,
    BillingPeriodCreate,
    ContractCreate,
    CostItemCreate,
    CostItemPatch,
    PortfolioCreate,
    PropertyCreate,
    TenantCreate,
    UnitCreate,
    UtilityStatementPatch,
)
from backend.routers import billing
from backend.services.data_snapshot import clear_business_data
from backend.services.final_statements import json_safe, statement_snapshot_hash


@pytest.fixture
def period():
    clear_business_data(store)
    portfolio = store.create_portfolio(PortfolioCreate(name="Own NK performance fixture"))
    prop = store.create_property(
        PropertyCreate(portfolio_id=portfolio.id, name="Own NK building", property_type="residential")
    )
    for index in range(3):
        unit = store.create_unit(
            UnitCreate(
                property_id=prop.id,
                label=f"Unit {index}",
                unit_type="residential",
                area_sqm=50 + index,
                person_count=2,
                service_charge_advance=100,
            )
        )
        tenant = store.create_tenant(TenantCreate(full_name=f"Synthetic tenant {index}"))
        store.create_contract(
            ContractCreate(
                property_id=prop.id,
                unit_id=unit.id,
                tenant_id=tenant.id,
                contract_number=f"NK-{index}",
                start_date=date(2025, 1, 1),
                persons=2,
            )
        )
    period = store.create_billing_period(
        BillingPeriodCreate(
            property_id=prop.id, label="Own NK 2025", start_date=date(2025, 1, 1), end_date=date(2025, 12, 31)
        )
    )
    for key_type, amount in (("area_sqm", 1200), ("person_count", 600)):
        key = store.create_allocation_key(AllocationKeyCreate(property_id=prop.id, name=key_type, key_type=key_type))
        store.create_cost_item(
            CostItemCreate(
                billing_period_id=period.id,
                allocation_key_id=key.id,
                description="Synthetic " + key_type,
                amount=amount,
            )
        )
    billing.generate_utility_statements(period.id)
    billing.submit_period_for_review(period.id)
    yield store.get_billing_period(period.id)
    clear_business_data(store)


def counters(monkeypatch):
    counts = {"compute": 0, "statements": 0}
    original_compute = billing.compute_period_billing
    original_statements = store.list_utility_statements

    @wraps(original_compute)
    def compute(*args, **kwargs):
        counts["compute"] += 1
        return original_compute(*args, **kwargs)

    @wraps(original_statements)
    def statements(*args, **kwargs):
        counts["statements"] += 1
        return original_statements(*args, **kwargs)

    monkeypatch.setattr(billing, "compute_period_billing", compute)
    monkeypatch.setattr(store, "list_utility_statements", statements)
    return counts


def test_one_locked_calculation_and_statement_read_preserve_exact_frozen_content(period, monkeypatch):
    original = billing._period_statements(period.id)
    expected = [
        s.model_copy(update={"final_document": json_safe(billing._live_statement_document(s, period))})
        for s in original
    ]
    expected_hash = statement_snapshot_hash(expected)
    counts = counters(monkeypatch)
    finalized = billing.finalize_billing_period(period.id)
    assert finalized.status == "finalized"
    assert counts == {"compute": 1, "statements": 1}
    actual = billing._period_statements(period.id)
    assert len(actual) == 3 and {s.snapshot_hash for s in actual} == {expected_hash}
    assert {s.id: s.final_document for s in actual} == {s.id: s.final_document for s in expected}
    assert all(s.status == "finalized" for s in actual)


def test_stale_statements_still_reject_without_freezing_any_row(period, monkeypatch):
    cost = next(item for item in store.list_cost_items() if item.billing_period_id == period.id)
    store._patch_entity("cost_item", cost.id, CostItemPatch(description="Changed after generation"))
    counts = counters(monkeypatch)
    with pytest.raises(HTTPException) as error:
        billing.finalize_billing_period(period.id)
    assert error.value.status_code == 400 and "veraltet" in str(error.value.detail)
    assert counts == {"compute": 1, "statements": 1}
    assert store.get_billing_period(period.id).status == "review"
    assert all(not s.snapshot_hash and not s.final_document for s in billing._period_statements(period.id))


def test_failure_during_freeze_rolls_back_all_documents_and_status(period, monkeypatch):
    original = store._patch_entity
    frozen = []

    @wraps(original)
    def fail(entity_type, entity_id, patch):
        if entity_type == "utility_statement" and patch.final_document is not None:
            frozen.append(entity_id)
            if len(frozen) == 2:
                raise RuntimeError("controlled second-document failure")
        return original(entity_type, entity_id, patch)

    monkeypatch.setattr(store, "_patch_entity", fail)
    with pytest.raises(RuntimeError, match="controlled"):
        billing.finalize_billing_period(period.id)
    assert len(frozen) == 2 and store.get_billing_period(period.id).status == "review"
    assert all(
        not s.snapshot_hash and not s.final_document and s.status == "draft"
        for s in billing._period_statements(period.id)
    )


@pytest.mark.parametrize("with_document", [False, True])
def test_finalization_preserves_already_sealed_legacy_rows_in_a_mixed_period(period, monkeypatch, with_document):
    before = sorted(billing._period_statements(period.id), key=lambda row: row.id)
    needs_status, already_finalized, fresh = before
    legacy_document = {"title": "Unveränderter historischer Beleg", "facts": [["Einheit", "Alte Bezeichnung"]]} if with_document else None
    archived_document = {"title": "Bereits abgeschlossener Altbeleg"}
    fresh_document = json_safe(billing._live_statement_document(fresh, period))
    expected_hash = statement_snapshot_hash([
        needs_status.model_copy(update={"final_document": legacy_document}),
        already_finalized.model_copy(update={"final_document": archived_document}),
        fresh.model_copy(update={"final_document": fresh_document}),
    ])
    store._patch_entity("utility_statement", needs_status.id, UtilityStatementPatch(
        final_document=legacy_document, snapshot_hash=expected_hash))
    archived = store._patch_entity("utility_statement", already_finalized.id, UtilityStatementPatch(
        final_document=archived_document, snapshot_hash=expected_hash, status="finalized"))
    original = store._patch_entity
    patches = {}

    @wraps(original)
    def track(entity_type, entity_id, patch):
        if entity_type == "utility_statement":
            assert entity_id not in patches
            patches[entity_id] = patch.model_dump(exclude_unset=True)
        return original(entity_type, entity_id, patch)

    monkeypatch.setattr(store, "_patch_entity", track)
    assert billing.finalize_billing_period(period.id).status == "finalized"
    final = {row.id: row for row in billing._period_statements(period.id)}
    assert set(patches) == {needs_status.id, fresh.id}
    assert patches[needs_status.id] == {"status": "finalized"}
    assert patches[fresh.id] == {"status": "finalized", "snapshot_hash": expected_hash,
                                 "final_document": fresh_document}
    assert final[needs_status.id].final_document == legacy_document
    assert final[already_finalized.id] == archived
    assert final[fresh.id].final_document == fresh_document
    assert all(row.status == "finalized" and row.snapshot_hash == expected_hash for row in final.values())
    assert statement_snapshot_hash(final.values()) == expected_hash
