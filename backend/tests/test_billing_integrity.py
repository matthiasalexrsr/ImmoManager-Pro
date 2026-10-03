"""Financial billing invariants, actual receipt cutoffs and correction history."""

import base64
import re
import zlib
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from datetime import date
from decimal import Decimal
from threading import Barrier
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from backend.db.orm_models import Base, BillingSettlementORM, ContractORM, ReceivableORM
from backend.dependencies import store
from backend.models import (
    AllocationKeyCreate,
    BillingPeriodCreate,
    BillingPeriodPatch,
    Contract,
    ContractCreate,
    CostItemCreate,
    CostItemPatch,
    PortfolioCreate,
    PropertyCreate,
    Receivable,
    ReceivablePatch,
    RentChargeCreate,
    TenantCreate,
    UnitCreate,
    UtilityStatementPatch,
)
from backend.repositories.sql_store import SQLAlchemyStore
from backend.routers import billing, receivables
from backend.services import billing_settlement as service
from backend.services.payments import FinancialConsistencyError, PaymentCreate, PaymentReversalCreate


@pytest.fixture(autouse=True)
def empty_store():
    store.clear_all()
    yield
    store.clear_all()


def scenario(target=store, count=1, cost=100):
    portfolio = target.create_portfolio(PortfolioCreate(name="Billing integrity"))
    prop = target.create_property(PropertyCreate(portfolio_id=portfolio.id, name="Haus", property_type="MFH"))
    period = target.create_billing_period(BillingPeriodCreate(property_id=prop.id, label="Januar 2025",
        start_date=date(2025, 1, 1), end_date=date(2025, 1, 31)))
    key = target.create_allocation_key(AllocationKeyCreate(property_id=prop.id, name="Einheiten", key_type="unit_count"))
    contracts, charges = [], []
    for index in range(count):
        unit = target.create_unit(UnitCreate(property_id=prop.id, label=f"WE {index}", unit_type="Wohnung",
            area_sqm=50, cold_rent=999, service_charge_advance=888, heating_advance=777))
        tenant = target.create_tenant(TenantCreate(full_name=f"Mieter {index}"))
        contract = target.create_contract(ContractCreate(contract_number=f"V-{index}", property_id=prop.id,
            unit_id=unit.id, tenant_id=tenant.id, start_date=date(2025, 1, 1)))
        contracts.append(contract)
        charges.append(target.create_rent_charge(RentChargeCreate(contract_id=contract.id, month="2025-01",
            cold_rent=500, service_charge=100, heating_charge=50, other_charges=50)))
    item = target.create_cost_item(CostItemCreate(billing_period_id=period.id, description="Wasser",
        amount=cost, allocation_key_id=key.id, cost_category="water", source_document_id="invoice-1"))
    return period, contracts, charges, item


def pay(charge, amount, reference="rent-1", payment_date=date(2025, 1, 10), target=store):
    return target.record_payment("rent_charge", charge.id, PaymentCreate(amount=Decimal(str(amount)),
        payment_date=payment_date, idempotency_key=reference, reference=reference, method="bank_transfer"))


def generated_finalized():
    period, contracts, charges, cost = scenario()
    statement = billing.generate_utility_statements(period.id)[0]
    billing.finalize_billing_period(period.id)
    return period, contracts[0], charges[0], cost, statement


def correct(period, amount):
    revision = billing.create_period_revision(period.id, "Beleg korrigiert")
    new_id = revision["new_period_id"]
    cost = next(c for c in store.list_cost_items() if c.billing_period_id == new_id)
    billing.patch_cost_item(cost.id, CostItemPatch(amount=amount))
    statement = billing.generate_utility_statements(new_id)[0]
    billing.finalize_billing_period(new_id)
    return store.get_billing_period(new_id), statement


def test_actual_paid_advance_uses_monthly_snapshot_including_other_charges():
    period, _, charges, _ = scenario()
    receipt = pay(charges[0], 350)
    statement = billing.generate_utility_statements(period.id)[0]
    assert statement.advance_details[0]["receipt_ids"] == [receipt.id]
    assert statement.advance_details[0]["receipt_paid_at_cutoff"] == 350
    assert statement.advance_paid == 75
    assert statement.balance == 25
    assert statement.advance_details[0]["split"] == {
        "cold_rent": 250, "service_charge": 50, "heating_charge": 25, "other_charges": 25}
    assert sum(statement.advance_details[0]["split"].values()) == 350
    assert statement.advance_details[0]["policy"] == "proportional_largest_remainder"


def test_unpaid_advance_is_zero_not_current_unit_price():
    period, *_ = scenario()
    statement = billing.generate_utility_statements(period.id)[0]
    assert statement.advance_paid == 0
    assert statement.balance == 100


def test_partial_cent_largest_remainders_are_exact():
    period, _, charges, _ = scenario()
    pay(charges[0], "0.03")
    statement = billing.generate_utility_statements(period.id)[0]
    split = statement.advance_details[0]["split"]
    assert split == {"cold_rent": .02, "service_charge": .01, "heating_charge": 0, "other_charges": 0}
    assert statement.advance_paid == .01


def test_legacy_paid_balance_is_explicit_and_preserved():
    period, contracts, charges, _ = scenario()
    store.delete_rent_charge(charges[0].id)
    legacy = store.create_rent_charge(RentChargeCreate(contract_id=contracts[0].id, month="2025-01",
        cold_rent=500, service_charge=100, heating_charge=50, other_charges=50, amount_paid=70, status="partial"))
    receipt = pay(legacy, 70)
    statement = billing.generate_utility_statements(period.id)[0]
    assert statement.advance_details[0]["receipt_ids"] == [receipt.id]
    assert statement.advance_details[0]["receipt_paid_at_cutoff"] == 70
    assert statement.advance_paid == 30
    assert statement.advance_details[0]["legacy_undated_paid"] == 70
    assert statement.advance_details[0]["paid_at_cutoff"] == 140


def test_late_receipt_is_excluded_but_later_reversal_does_not_rewrite_period_cutoff():
    period, _, charges, _ = scenario()
    first = pay(charges[0], 350)
    late = pay(charges[0], 70, "late", date(2025, 2, 5))
    store.reverse_payment("rent_charge", charges[0].id, first.id, PaymentReversalCreate(
        reversal_date=date(2025, 2, 10), reason="Spätere Rücklastschrift", idempotency_key="later-reversal"))
    statement = billing.generate_utility_statements(period.id)[0]
    assert statement.advance_paid == 75
    assert statement.advance_details[0]["receipt_ids"] == [first.id]
    assert statement.advance_details[0]["reversals_after_cutoff"][0]["receipt_id"] == first.id
    assert statement.advance_details[0]["excluded_receipts"][0]["receipt_id"] == late.id
    billing.finalize_billing_period(period.id)
    assert store.get_utility_statement(statement.id).advance_paid == 75


def test_reversal_within_period_removes_actual_advance():
    period, _, charges, _ = scenario()
    payment = pay(charges[0], 350)
    store.reverse_payment("rent_charge", charges[0].id, payment.id, PaymentReversalCreate(
        reversal_date=date(2025, 1, 20), reason="Rücklastschrift", idempotency_key="in-period"))
    assert billing.generate_utility_statements(period.id)[0].advance_paid == 0


def test_final_snapshot_stays_unchanged_after_new_payment_and_unit_price():
    period, contract, charge, _, statement = generated_finalized()
    snapshot = store.get_utility_statement(statement.id).model_dump()
    pay(charge, 350)
    unit = store.get_unit(contract.unit_id)
    store.update_unit(unit.id, UnitCreate(**{**unit.model_dump(include=set(UnitCreate.model_fields)), "service_charge_advance": 9999}))
    assert store.get_utility_statement(statement.id).model_dump() == snapshot
    assert billing.finalize_billing_period(period.id).status == "finalized"


@pytest.mark.parametrize("status", ["terminated", "expired"])
def test_ended_historic_contracts_remain_billable(status):
    period, contracts, charges, _ = scenario()
    contract = contracts[0]
    store.update_contract(contract.id, ContractCreate(**{**contract.model_dump(include=set(ContractCreate.model_fields)),
        "status": status, "end_date": date(2025, 1, 31)}))
    pay(charges[0], 350)
    statement = billing.generate_utility_statements(period.id)[0]
    assert statement.contract_id == contract.id
    assert statement.advance_paid == 75


@pytest.mark.parametrize("status", ["draft"])
def test_draft_and_cancelled_contracts_are_not_billed(status):
    period, contracts, _, _ = scenario()
    contract = contracts[0]
    store.update_contract(contract.id, ContractCreate(**{**contract.model_dump(include=set(ContractCreate.model_fields)), "status": status}))
    with pytest.raises(HTTPException) as error:
        billing.generate_utility_statements(period.id)
    assert error.value.status_code == 400


def test_non_recoverable_cost_does_not_charge_tenant():
    period, _, _, cost = scenario()
    store.create_cost_item(CostItemCreate(billing_period_id=period.id, description="Eigentümerkosten",
        amount=500, allocation_key_id=cost.allocation_key_id, is_recoverable=False))
    assert billing.generate_utility_statements(period.id)[0].total_cost == 100
    billing.finalize_billing_period(period.id)


def test_partial_period_uses_paid_occupied_day_share():
    period, contracts, charges, _ = scenario()
    store.update_billing_period(period.id, BillingPeriodCreate(**{**period.model_dump(include=set(BillingPeriodCreate.model_fields)),
        "start_date": date(2025, 1, 16)}))
    pay(charges[0], 700)
    actual, details = service.actual_paid_advances(store, contracts[0], store.get_billing_period(period.id))
    assert actual == Decimal("77.42")
    assert details[0]["overlap_days"] == 16


def test_posting_positive_balance_is_idempotent_and_source_protected():
    period, _, _, _, statement = generated_finalized()
    first = billing.create_receivables_from_period(period.id)
    replay = billing.create_receivables_from_period(period.id)
    assert first["created_receivables"] == 1
    assert replay["created_receivables"] == replay["created_settlements"] == 0
    assert replay["existing_count"] == 1
    claim = store.list_receivables()[0]
    assert claim.statement_id == statement.id
    assert first["settlements"][0]["receivable_id"] == claim.id
    with pytest.raises(HTTPException) as error:
        receivables.patch_receivable(claim.id, ReceivablePatch(amount_due=1))
    assert error.value.status_code == 409
    with pytest.raises(HTTPException) as error:
        receivables.delete_receivable(claim.id)
    assert error.value.status_code == 409


def test_credit_is_available_with_no_negative_open_receivable_or_claimed_payout():
    period, _, charges, _ = scenario()
    pay(charges[0], 700)
    billing.generate_utility_statements(period.id)
    billing.finalize_billing_period(period.id)
    result = billing.create_receivables_from_period(period.id)
    assert result["created_receivables"] == 0
    assert result["created_credits"] == 1
    assert result["credits_total"] == 50
    assert result["settlements"][0]["status"] == "credit_available"
    assert result["settlements"][0]["receivable_id"] is None
    assert store.list_receivables() == []
    assert billing.list_period_settlements(period.id)["net_amount"] == -50


def legacy_credit_fixture():
    period, contracts, charges, _ = scenario()
    pay(charges[0], 700)
    statement = billing.generate_utility_statements(period.id)[0]
    billing.finalize_billing_period(period.id)
    legacy = Receivable(id="old-negative-source", contract_id=contracts[0].id, statement_id=statement.id,
        due_date=period.end_date, amount_due=-50, amount_paid=0, status="open")
    with service.atomic_billing(store, period.id):
        service._write(store, "receivables", legacy)
    return period, legacy


def test_legacy_negative_source_is_retained_as_available_credit():
    period, legacy = legacy_credit_fixture()
    result = billing.create_receivables_from_period(period.id)
    assert result["credits_total"] == 50
    assert result["created_receivables"] == 0
    assert store.get_receivable(legacy.id).status == "credit_available"
    assert store.get_receivable(legacy.id).amount_due == -50
    assert result["settlements"][0]["receivable_id"] == legacy.id
    assert billing.create_receivables_from_period(period.id)["created_settlements"] == 0


def test_sql_legacy_credit_upgrade_is_idempotent_and_keeps_source_row():
    if not hasattr(store, "db"):
        pytest.skip("Legacy additive upgrade applies to SQL only")
    period, legacy = legacy_credit_fixture()
    engine = store.db.get_bind()
    with engine.begin() as connection:
        service.ensure_billing_schema(connection)
        service.ensure_billing_schema(connection)
    store.db.expire_all()
    assert store.get_receivable(legacy.id).status == "credit_available"
    summary = billing.list_period_settlements(period.id)
    assert summary["credits_total"] == 50
    assert len(summary["settlements"]) == 1


def test_legacy_credit_with_ambiguous_paid_balance_refuses_destructive_repair():
    period, legacy = legacy_credit_fixture()
    with service.atomic_billing(store, period.id):
        service._write(store, "receivables", legacy.model_copy(update={"amount_paid": 1}))
    with pytest.raises(HTTPException) as error:
        billing.create_receivables_from_period(period.id)
    assert error.value.status_code == 409
    assert service.settlements(store) == []
    assert store.get_receivable(legacy.id).status == "open"


def test_revision_posts_only_delta_and_keeps_original_paid_history():
    period, _, _, _, original = generated_finalized()
    billing.create_receivables_from_period(period.id)
    claim = store.list_receivables()[0]
    store.record_payment("receivable", claim.id, PaymentCreate(amount=Decimal("100"), payment_date=date(2025, 2, 1),
        idempotency_key="utility-paid", reference="BK", method="bank_transfer"))
    revised_period, revised = correct(period, 80)
    credit = billing.create_receivables_from_period(revised_period.id)
    assert credit["credits_total"] == 20
    assert revised.revision == revised_period.revision_number == 2
    assert revised.source_statement_id == original.id
    assert store.get_receivable(claim.id).amount_due == store.get_receivable(claim.id).amount_paid == 100
    assert len(store.list_payments("receivable", claim.id)) == 1
    third_period, third = correct(revised_period, 130)
    adjustment = billing.create_receivables_from_period(third_period.id)
    assert adjustment["debts_total"] == 50
    assert third.revision == 3
    assert sum(s.signed_amount for s in service.settlements(store)) == 130
    assert len(store.list_receivables()) == 2
    with pytest.raises(HTTPException):
        billing.create_receivables_from_period(period.id)


def test_unposted_original_correction_claims_only_latest_full_balance():
    period, _, _, _, _ = generated_finalized()
    new_period, _ = correct(period, 80)
    result = billing.create_receivables_from_period(new_period.id)
    assert result["debts_total"] == 80
    assert len(store.list_receivables()) == 1


def test_revision_preserves_cost_metadata_and_cannot_branch_or_change_obligation():
    period, *_ = generated_finalized()
    revised = billing.create_period_revision(period.id, "Begründung")
    new = store.get_billing_period(revised["new_period_id"])
    copied = next(c for c in store.list_cost_items() if c.billing_period_id == new.id)
    assert copied.cost_category == "water"
    assert copied.source_document_id == "invoice-1"
    assert new.revision_notes == "Begründung"
    with pytest.raises(HTTPException) as error:
        billing.create_period_revision(period.id)
    assert error.value.status_code == 409
    with pytest.raises(HTTPException):
        billing.patch_billing_period(new.id, BillingPeriodPatch(start_date=date(2025, 1, 2)))


def test_revision_requires_finalized_source_and_pdf_contains_persisted_revision():
    period, *_ = scenario()
    with pytest.raises(HTTPException) as error:
        billing.create_period_revision(period.id)
    assert error.value.status_code == 400
    billing.generate_utility_statements(period.id)
    billing.finalize_billing_period(period.id)
    _, statement = correct(period, 90)
    response = billing.get_utility_statement_pdf(statement.id)
    assert response.media_type == "application/pdf"
    # Verify the actual PDF text stream using only the declared Python runtime.
    streams = re.findall(rb"stream\r?\n(.*?)endstream", response.body, re.DOTALL)
    decoded = [zlib.decompress(base64.a85decode(stream.strip(), adobe=True)) for stream in streams]
    assert any(b"Revision: 2" in stream for stream in decoded)


@pytest.mark.parametrize("field", ["cost", "advance", "key"])
def test_finalization_rejects_changed_calculation_inputs(field):
    period, _, charges, cost = scenario()
    billing.generate_utility_statements(period.id)
    if field == "cost":
        billing.patch_cost_item(cost.id, CostItemPatch(amount=101))
    elif field == "advance":
        pay(charges[0], 350)
    else:
        key = store.get_allocation_key(cost.allocation_key_id)
        store.update_allocation_key(key.id, AllocationKeyCreate(**{**key.model_dump(include=set(AllocationKeyCreate.model_fields)), "key_type": "area_sqm"}))
    with pytest.raises(HTTPException) as error:
        billing.finalize_billing_period(period.id)
    assert error.value.status_code == 409
    assert store.get_billing_period(period.id).status == "draft"


def test_disputed_financial_records_stay_immutable_but_can_be_revised():
    period, contract, _, cost, statement = generated_finalized()
    # A real pre-journal status remains valid historical input. It cannot be
    # manufactured by the now-incomplete legacy action for a new dispute.
    from backend.services import billing_settlement
    billing_settlement._write(store, "billing_periods", period.model_copy(update={"status": "disputed"}))
    for mutation in (lambda: billing.patch_billing_period(period.id, BillingPeriodPatch(status="draft")),
        lambda: billing.patch_cost_item(cost.id, CostItemPatch(amount=1)),
        lambda: billing.patch_utility_statement(statement.id, UtilityStatementPatch(balance=1)),
        lambda: store.delete_contract(contract.id)):
        with pytest.raises((HTTPException, FinancialConsistencyError)):
            mutation()
    assert billing.create_period_revision(period.id)["revision"] == 2


@pytest.mark.parametrize("operation", ["post", "generate", "finalize", "revision"])
def test_batch_failure_rolls_back_all_mutations(operation, monkeypatch):
    period, *_ = scenario(count=2)
    billing.generate_utility_statements(period.id)
    if operation in {"post", "revision"}:
        billing.finalize_billing_period(period.id)
    before = {"periods": [p.model_dump() for p in store.list_billing_periods()],
        "statements": [s.model_dump() for s in store.list_utility_statements()],
        "costs": [c.model_dump() for c in store.list_cost_items()]}
    real_write = service._write
    calls = 0
    def fail_second(*args):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("second financial write failed")
        return real_write(*args)
    monkeypatch.setattr(service, "_write", fail_second)
    action = {"post": billing.create_receivables_from_period, "generate": billing.generate_utility_statements,
        "finalize": billing.finalize_billing_period, "revision": billing.create_period_revision}[operation]
    with pytest.raises(RuntimeError):
        action(period.id)
    assert [p.model_dump() for p in store.list_billing_periods()] == before["periods"]
    assert [s.model_dump() for s in store.list_utility_statements()] == before["statements"]
    assert [c.model_dump() for c in store.list_cost_items()] == before["costs"]
    assert service.settlements(store) == store.list_receivables() == []


def test_memory_parallel_posting_creates_one_source_obligation():
    if hasattr(store, "db"):
        pytest.skip("Independent SQL sessions exercised separately")
    period, *_ = generated_finalized()
    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(lambda _: service.post_settlements(store, period.id), range(4)))
    assert sum(r["created_receivables"] for r in results) == 1
    assert sum(r["existing_count"] for r in results) == 3


def test_sql_parallel_posting_and_commit_failure(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'billing-race.db'}", connect_args={"timeout": 15})
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        target = SQLAlchemyStore(db)
        period, contracts, _, _ = scenario(target)
        monkeypatch.setattr(billing, "store", target)
        billing.generate_utility_statements(period.id)
        billing.finalize_billing_period(period.id)
    # Exercise database serialization itself, without the in-process memory lock.
    monkeypatch.setattr(service, "_memory_lock", nullcontext())
    barrier = Barrier(2)
    def post(_):
        with Session(engine) as db:
            barrier.wait()
            return service.post_settlements(SQLAlchemyStore(db), period.id)
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(post, range(2)))
    assert sum(r["created_receivables"] for r in results) == 1
    with Session(engine) as db:
        assert len(list(db.scalars(select(ReceivableORM)))) == 1
        assert len(list(db.scalars(select(BillingSettlementORM)))) == 1
        target = SQLAlchemyStore(db)
        revision = service.create_revision(target, period.id, "Commit failure")
        monkeypatch.setattr(billing, "store", target)
        billing.generate_utility_statements(revision["new_period_id"])
        billing.finalize_billing_period(revision["new_period_id"])
        monkeypatch.setattr(db, "commit", lambda: (_ for _ in ()).throw(RuntimeError("commit failed")))
        with pytest.raises(RuntimeError):
            service.post_settlements(target, revision["new_period_id"])
    with Session(engine) as db:
        assert len(list(db.scalars(select(BillingSettlementORM)))) == 1
    engine.dispose()


def test_tenant_turnover_uses_precise_occupied_days_and_no_double_unit_weight():
    period, contracts, _, _ = scenario()
    first = contracts[0]
    store.update_contract(first.id, ContractCreate(**{**first.model_dump(include=set(ContractCreate.model_fields)),
        "end_date": date(2025, 1, 15), "status": "terminated"}))
    next_tenant = store.create_tenant(TenantCreate(full_name="Nachmieter"))
    second = store.create_contract(ContractCreate(contract_number="V-Nachmieter", property_id=first.property_id,
        unit_id=first.unit_id, tenant_id=next_tenant.id, start_date=date(2025, 1, 16)))
    statements = {s.contract_id: s for s in billing.generate_utility_statements(period.id)}
    assert statements[first.id].total_cost == 48.39
    assert statements[second.id].total_cost == 51.61
    billing.finalize_billing_period(period.id)


def test_overlapping_tenancies_are_blocked_before_any_double_obligation():
    period, contracts, _, _ = scenario()
    first = contracts[0]
    tenant = store.create_tenant(TenantCreate(full_name="Überschneidung"))
    # Simulate corrupt historical data explicitly: normal contract creation now
    # rejects this overlap before it can reach the billing preflight.
    historical_overlap = Contract(id=str(uuid4()), contract_number="V-overlap", property_id=first.property_id,
        unit_id=first.unit_id, tenant_id=tenant.id, start_date=date(2025, 1, 16))
    if hasattr(store, "db"):
        store.db.add(ContractORM(**historical_overlap.model_dump()))
        store.db.commit()
    else:
        store.contracts[historical_overlap.id] = historical_overlap
    assert "OVERLAPPING_CONTRACTS" in {i.code for i in billing.get_billing_period_preflight(period.id).blockers}
    with pytest.raises(HTTPException) as error:
        billing.generate_utility_statements(period.id)
    assert error.value.status_code == 400
    assert store.list_utility_statements() == []


@pytest.mark.parametrize("value", [float("inf"), float("nan"), .001])
def test_invalid_billing_money_is_rejected_at_input(value):
    with pytest.raises(ValueError):
        CostItemCreate(billing_period_id="p", description="Bad", amount=value, allocation_key_id="k")
    with pytest.raises(ValueError):
        CostItemPatch(amount=value)


@pytest.mark.parametrize("duplicate", ["receivable", "statement"])
def test_legacy_duplicate_migration_refuses_to_erase_history(tmp_path, duplicate):
    engine = create_engine(f"sqlite:///{tmp_path / 'legacy.db'}")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE billing_periods (id TEXT PRIMARY KEY)"))
        connection.execute(text("CREATE TABLE utility_statements (id TEXT PRIMARY KEY, billing_period_id TEXT, contract_id TEXT)"))
        connection.execute(text("CREATE TABLE receivables (id TEXT PRIMARY KEY, statement_id TEXT)"))
        if duplicate == "receivable":
            connection.execute(text("INSERT INTO receivables VALUES ('r1', 's1'), ('r2', 's1')"))
        else:
            connection.execute(text("INSERT INTO utility_statements VALUES ('s1', 'p1', 'c1'), ('s2', 'p1', 'c1')"))
        with pytest.raises(RuntimeError, match="Doppelte Abrechnungsquelle"):
            service.ensure_billing_schema(connection)
        table = "receivables" if duplicate == "receivable" else "utility_statements"
        assert connection.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar() == 2
    engine.dispose()
