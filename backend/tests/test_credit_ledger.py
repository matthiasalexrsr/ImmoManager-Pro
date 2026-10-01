"""Credit consumption uses real posted billing revisions and both actual stores."""

from concurrent.futures import ThreadPoolExecutor
from datetime import date
from decimal import Decimal
from threading import Barrier
from uuid import uuid4

import pytest
from pydantic import ValidationError as ModelValidationError
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from backend.db.credit_models import CreditReceiptORM, CreditReversalORM
from backend.db.orm_models import Base, PaymentORM, PaymentReversalORM
from backend.models import BillingSettlement, BookingPatch, CostItemPatch, ReceivableCreate
from backend.repositories.sql_store import SQLAlchemyStore
from backend.routers import billing
from backend.services import billing_settlement as settlements
from backend.services import credit_ledger as service
from backend.services.credit_types import CreditOffsetCreate, CreditPayoutCreate, CreditReversalCreate
from backend.services.data_transfer import TransferError, import_store_data
from backend.services.payments import FinancialConsistencyError, PaymentCreate, PaymentReversalCreate
from backend.storage import InMemoryStore, ValidationError
from backend.tests.test_bank_payments import bank_booking
from backend.tests.test_billing_integrity import scenario


@pytest.fixture(params=["memory", "sqlite"])
def credit_store(request, tmp_path, monkeypatch):
    if request.param == "memory":
        active = InMemoryStore()
        monkeypatch.setattr(billing, "store", active)
        yield active
    else:
        engine = create_engine(f"sqlite:///{tmp_path / 'credits.db'}", connect_args={"timeout": 20})
        Base.metadata.create_all(engine)
        with Session(engine) as db:
            active = SQLAlchemyStore(db)
            monkeypatch.setattr(billing, "store", active)
            yield active
        engine.dispose()


def credit_scenario(active, monkeypatch, count=1):
    monkeypatch.setattr(billing, "store", active)
    period, contracts, charges, cost = scenario(active, cost=50 * count, count=count)
    for charge in charges:
        active.record_payment("rent_charge", charge.id, PaymentCreate(idempotency_key=str(uuid4()),
            amount="700", payment_date=date(2025, 1, 10)))
    billing.generate_utility_statements(period.id)
    billing.finalize_billing_period(period.id)
    source = BillingSettlement.model_validate(settlements.post_settlements(active, period.id)["settlements"][0])
    assert Decimal(str(source.signed_amount)) == Decimal("-100")
    return source, contracts[0], period, charges[0]


def correct(active, period, new_cost, *, post=True):
    result = settlements.create_revision(active, period.id, "Synthetic correction")
    new_id = result["new_period_id"]
    cost = next(c for c in active.list_cost_items() if c.billing_period_id == new_id)
    billing.patch_cost_item(cost.id, CostItemPatch(amount=new_cost))
    billing.generate_utility_statements(new_id)
    billing.finalize_billing_period(new_id)
    if not post:
        return active.get_billing_period(new_id), None
    posted = BillingSettlement.model_validate(settlements.post_settlements(active, new_id)["settlements"][0])
    return active.get_billing_period(new_id), posted


def payout(source, amount="60", key=None, **kwargs):
    return CreditPayoutCreate(source_settlement_id=source.id, idempotency_key=key or str(uuid4()),
        amount=amount, transaction_date=date(2026, 9, 5), method=kwargs.pop("method", "cash"),
        confirmed_payment=True, **kwargs)


def reversal(key=None):
    return CreditReversalCreate(idempotency_key=key or str(uuid4()), reason="Synthetic correction",
        reversal_date=date(2026, 10, 1))


def offset(source, target, amount="40", key=None, target_type="receivable"):
    return CreditOffsetCreate(source_settlement_id=source.id, idempotency_key=key or str(uuid4()),
        amount=amount, transaction_date=date(2026, 9, 5), target_type=target_type, target_id=target.id)


def test_revision_reserves_own_chain_and_offset_has_real_payment_then_double_sided_reversal(credit_store, monkeypatch):
    source, contract, period, _ = credit_scenario(credit_store, monkeypatch)
    _, revised = correct(credit_store, period, 90)
    summary = service.summary(credit_store, contract.id)
    assert (summary["remaining_amount"], summary["reserved_amount"], summary["available_amount"]) == ("100.00", "40.00", "60.00")
    with pytest.raises(FinancialConsistencyError):
        service.create_receipt(credit_store, payout(source, "60.01"))
    claim = credit_store.get_receivable(revised.receivable_id)
    command = offset(source, claim)
    receipt = service.create_receipt(credit_store, command)
    assert service.create_receipt(credit_store, command).id == receipt.id
    assert service.create_receipt(credit_store, command).model_dump(mode="json") == receipt.model_dump(mode="json")
    payment = credit_store.list_payments("receivable", claim.id)[0]
    assert payment.credit_receipt_id == receipt.id and payment.amount == Decimal("40")
    assert credit_store.get_receivable(claim.id).status == "paid"
    assert service.summary(credit_store, contract.id)["available_amount"] == "60.00"
    request = reversal()
    payment_reversal = credit_store.reverse_payment("receivable", claim.id, payment.id,
        PaymentReversalCreate(**request.model_dump()))
    assert service.reverse_receipt(credit_store, receipt.id, request).payment_reversal_id == payment_reversal.id
    assert credit_store.get_receivable(claim.id).amount_paid == 0
    assert service.summary(credit_store, contract.id)["available_amount"] == "60.00"
    assert len(service.journal(credit_store, contract.id)["receipts"]) == 1
    with pytest.raises(FinancialConsistencyError):
        service.reverse_receipt(credit_store, receipt.id, reversal())
    assert service.create_receipt(credit_store, command).reversal is not None


def test_payout_before_revision_leaves_legitimate_debt_and_storno_restores_reserved_credit(credit_store, monkeypatch):
    source, contract, period, _ = credit_scenario(credit_store, monkeypatch)
    receipt = service.create_receipt(credit_store, payout(source, "100"))
    second, revised = correct(credit_store, period, 90)
    assert credit_store.get_receivable(revised.receivable_id).amount_due == 40
    assert service.summary(credit_store, contract.id)["available_amount"] == "0.00"
    service.reverse_receipt(credit_store, receipt.id, reversal())
    assert service.summary(credit_store, contract.id)["available_amount"] == "60.00"
    _, third = correct(credit_store, second, 70)
    assert Decimal(str(third.signed_amount)) == Decimal("-20")
    state = service.summary(credit_store, contract.id)
    assert state["remaining_amount"] == "120.00" and state["available_amount"] == "80.00"


def test_cash_then_reserved_offset_and_followup_revision_keep_historical_receipts(credit_store, monkeypatch):
    source, contract, period, _ = credit_scenario(credit_store, monkeypatch)
    second, revised = correct(credit_store, period, 90)
    cash = service.create_receipt(credit_store, payout(source))
    assert service.summary(credit_store, contract.id)["available_amount"] == "0.00"
    receipt = service.create_receipt(credit_store, offset(source, credit_store.get_receivable(revised.receivable_id)))
    assert service.summary(credit_store, contract.id)["remaining_amount"] == "0.00"
    _, third = correct(credit_store, second, 70)
    assert service.summary(credit_store, contract.id)["available_amount"] == "20.00"
    service.reverse_receipt(credit_store, receipt.id, reversal())
    assert service.summary(credit_store, contract.id)["available_amount"] == "20.00"
    service.reverse_receipt(credit_store, cash.id, reversal())
    assert service.summary(credit_store, contract.id)["available_amount"] == "80.00"
    assert service.receipt_by_id(credit_store, receipt.id).amount == Decimal("40")
    assert Decimal(str(third.signed_amount)) == Decimal("-20")


def test_other_claims_do_not_implicitly_consume_or_reserve_credit(credit_store, monkeypatch):
    source, contract, _, _ = credit_scenario(credit_store, monkeypatch)
    unrelated = credit_store.create_receivable(ReceivableCreate(contract_id=contract.id,
        due_date=date(2026, 9, 1), amount_due=75))
    assert service.summary(credit_store, contract.id)["available_amount"] == "100.00"
    receipt = service.create_receipt(credit_store, offset(source, unrelated, "25"))
    assert credit_store.get_receivable(unrelated.id).amount_paid == 25
    assert service.summary(credit_store, contract.id)["available_amount"] == "75.00"
    with pytest.raises(FinancialConsistencyError):
        service.create_receipt(credit_store, offset(source, unrelated, "26", key=receipt.idempotency_key))


def test_negative_bank_shared_budget_reversal_and_history_guards(credit_store, monkeypatch):
    source, contract, _, charge = credit_scenario(credit_store, monkeypatch)
    booking = bank_booking(credit_store, charge, -75, tenant_id=contract.tenant_id,
        unit_id=contract.unit_id, property_id=contract.property_id)
    first = service.create_receipt(credit_store, payout(source, "50", method="bank", booking_id=booking.id))
    with pytest.raises(FinancialConsistencyError):
        service.create_receipt(credit_store, payout(source, "26", method="bank", booking_id=booking.id))
    second = service.create_receipt(credit_store, payout(source, "25", method="bank", booking_id=booking.id))
    assert credit_store.get_booking(booking.id).allocated_amount == 75
    service.reverse_receipt(credit_store, first.id, reversal())
    service.reverse_receipt(credit_store, second.id, reversal())
    assert credit_store.get_booking(booking.id).allocated_amount == 0
    with pytest.raises(ValidationError):
        credit_store._patch_entity("booking", booking.id, BookingPatch(amount=-80)) if isinstance(credit_store, InMemoryStore) else credit_store.finance._bookings.patch(booking.id, BookingPatch(amount=-80))
    with pytest.raises(ValidationError):
        credit_store.delete_booking(booking.id)


@pytest.mark.parametrize("bad", ["positive", "foreign_tenant", "foreign_account", "date"])
def test_bank_scope_failures_do_not_allocate_or_consume_credit(credit_store, monkeypatch, bad):
    from backend.models import AccountCreate, BookingCreate, PortfolioCreate, TenantCreate
    source, contract, _, charge = credit_scenario(credit_store, monkeypatch)
    booking = bank_booking(credit_store, charge, 100 if bad == "positive" else -100,
        tenant_id=credit_store.create_tenant(TenantCreate(full_name="Foreign")).id if bad == "foreign_tenant" else contract.tenant_id)
    if bad == "foreign_account":
        portfolio = credit_store.create_portfolio(PortfolioCreate(name="Foreign"))
        account = credit_store.create_account(AccountCreate(portfolio_id=portfolio.id, name="Other", account_type="bank"))
        booking = credit_store.create_booking(BookingCreate(account_id=account.id, booking_date=booking.booking_date, amount=-100))
    command = payout(source, "50", method="bank", booking_id=booking.id)
    if bad == "date":
        command = command.model_copy(update={"transaction_date": date(2026, 9, 6)})
    with pytest.raises(FinancialConsistencyError):
        service.create_receipt(credit_store, command)
    assert credit_store.get_booking(booking.id).allocated_amount == 0
    assert service.summary(credit_store, contract.id)["available_amount"] == "100.00"
    assert service.journal(credit_store, contract.id)["total"] == 0


def test_subset_restore_is_rejected_before_mutating_existing_data(credit_store, monkeypatch):
    source, contract, _, _ = credit_scenario(credit_store, monkeypatch)
    service.create_receipt(credit_store, payout(source))
    original = credit_store.get_contract(contract.id)
    for replace in (False, True):
        with pytest.raises(TransferError, match="Guthabenjournal"):
            import_store_data(credit_store, {"metadata": {"version": "1.0"}, "tenants": []}, replace_existing=replace)
    assert credit_store.get_contract(contract.id) == original
    assert service.journal(credit_store, contract.id)["total"] == 1


def test_transaction_failure_after_payment_rolls_back_both_journals(credit_store, monkeypatch):
    source, contract, _, _ = credit_scenario(credit_store, monkeypatch)
    target = credit_store.create_receivable(ReceivableCreate(contract_id=contract.id,
        due_date=date(2026, 9, 1), amount_due=50))
    if hasattr(credit_store, "db"):
        original = credit_store.db.flush
        def fail_credit(*args, **kwargs):
            if any(isinstance(row, CreditReceiptORM) for row in credit_store.db.new):
                raise RuntimeError("synthetic journal failure")
            return original(*args, **kwargs)
        monkeypatch.setattr(credit_store.db, "flush", fail_credit)
    else:
        class FailingDict(dict):
            def __setitem__(self, key, value):
                raise RuntimeError("synthetic journal failure")
        credit_store.credit_receipts = FailingDict()
    with pytest.raises(RuntimeError, match="synthetic journal failure"):
        service.create_receipt(credit_store, offset(source, target))
    assert credit_store.get_receivable(target.id).amount_paid == 0
    assert credit_store.list_payments("receivable", target.id) == []
    assert service.summary(credit_store, contract.id)["available_amount"] == "100.00"


def test_reversal_failure_restores_payment_and_credit_consumption(credit_store, monkeypatch):
    source, contract, _, _ = credit_scenario(credit_store, monkeypatch)
    target = credit_store.create_receivable(ReceivableCreate(contract_id=contract.id, due_date=date(2026, 9, 1), amount_due=50))
    receipt = service.create_receipt(credit_store, offset(source, target))
    if hasattr(credit_store, "db"):
        original = credit_store.db.flush
        def fail_reversal(*args, **kwargs):
            if any(isinstance(row, CreditReversalORM) for row in credit_store.db.new):
                raise RuntimeError("synthetic reversal failure")
            return original(*args, **kwargs)
        monkeypatch.setattr(credit_store.db, "flush", fail_reversal)
    else:
        class FailingDict(dict):
            def __setitem__(self, key, value):
                raise RuntimeError("synthetic reversal failure")
        credit_store.credit_reversals = FailingDict()
    with pytest.raises(RuntimeError, match="synthetic reversal failure"):
        service.reverse_receipt(credit_store, receipt.id, reversal())
    assert credit_store.get_receivable(target.id).amount_paid == 40
    assert credit_store.list_payments("receivable", target.id)[0].reversal is None
    assert service.receipt_by_id(credit_store, receipt.id).reversal is None
    assert service.summary(credit_store, contract.id)["available_amount"] == "60.00"


@pytest.mark.parametrize("amount", ["NaN", "Infinity", "0", "-1", "1.001", True])
def test_cent_domain_rejects_invalid_currency(amount):
    with pytest.raises(ModelValidationError):
        CreditPayoutCreate(source_settlement_id="synthetic", idempotency_key="test", amount=amount,
            transaction_date=date(2026, 9, 1), method="cash", confirmed_payment=True)


def test_cent_domain_has_no_invented_maximum_and_huge_input_is_budget_checked(credit_store, monkeypatch):
    source, _, _, _ = credit_scenario(credit_store, monkeypatch)
    command = payout(source, "1e1000000")
    assert command.amount == Decimal("1e1000000")
    with pytest.raises(FinancialConsistencyError, match="Guthaben"):
        service.create_receipt(credit_store, command)


def test_independent_sql_sessions_cannot_double_spend_credit(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'parallel.db'}", connect_args={"timeout": 20})
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        source, contract, _, _ = credit_scenario(SQLAlchemyStore(db), monkeypatch)
    barrier = Barrier(2)
    def spend(index):
        with Session(engine) as db:
            barrier.wait(timeout=10)
            try:
                return service.create_receipt(SQLAlchemyStore(db), payout(source, "60", key=f"parallel-{index}")).id
            except FinancialConsistencyError:
                return None
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(spend, range(2)))
    assert sum(value is not None for value in results) == 1
    with Session(engine) as db:
        assert service.summary(SQLAlchemyStore(db), contract.id)["remaining_amount"] == "40.00"
        assert len(list(db.scalars(select(CreditReceiptORM)))) == 1
        assert list(db.scalars(select(CreditReversalORM))) == []
        assert list(db.scalars(select(PaymentReversalORM))) == []
        assert len(list(db.scalars(select(PaymentORM)))) == 1  # original rent receipt only
    engine.dispose()


def test_memory_parallel_spenders_share_one_atomic_source_budget(monkeypatch):
    active = InMemoryStore()
    source, contract, _, _ = credit_scenario(active, monkeypatch)
    barrier = Barrier(2)
    def spend(index):
        barrier.wait(timeout=10)
        try:
            return service.create_receipt(active, payout(source, "60", key=f"memory-{index}")).id
        except FinancialConsistencyError:
            return None
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(spend, range(2)))
    assert sum(value is not None for value in results) == 1
    assert service.summary(active, contract.id)["remaining_amount"] == "40.00"
    assert service.journal(active, contract.id)["total"] == 1


def test_credit_from_other_statement_chain_cannot_unlock_reserved_source(credit_store, monkeypatch):
    from backend.models import BillingPeriodCreate, CostItemCreate, RentChargeCreate
    source, contract, period, _ = credit_scenario(credit_store, monkeypatch)
    _, revision = correct(credit_store, period, 150)
    next_period = credit_store.create_billing_period(BillingPeriodCreate(property_id=contract.property_id,
        label="February", start_date=date(2025, 2, 1), end_date=date(2025, 2, 28)))
    key = credit_store.list_allocation_keys()[0]
    credit_store.create_cost_item(CostItemCreate(billing_period_id=next_period.id, description="Other statement",
        amount=50, allocation_key_id=key.id))
    charge = credit_store.create_rent_charge(RentChargeCreate(contract_id=contract.id, month="2025-02",
        cold_rent=500, service_charge=100, heating_charge=50, other_charges=50))
    credit_store.record_payment("rent_charge", charge.id, PaymentCreate(idempotency_key="feb-rent", amount="700", payment_date=date(2025, 2, 10)))
    billing.generate_utility_statements(next_period.id)
    billing.finalize_billing_period(next_period.id)
    other_source = BillingSettlement.model_validate(settlements.post_settlements(credit_store, next_period.id)["settlements"][0])
    assert other_source.signed_amount == -100
    state = service.summary(credit_store, contract.id)
    assert state["available_amount"] == "100.00"  # exclusively the February source
    assert next(row for row in state["sources"] if row["id"] == source.id)["available_amount"] == "0.00"
    with pytest.raises(FinancialConsistencyError):
        service.create_receipt(credit_store, payout(source, "1"))
    # Spending February on January is allowed only through this explicit command.
    service.create_receipt(credit_store, offset(other_source, credit_store.get_receivable(revision.receivable_id), "100"))
    assert credit_store.get_receivable(revision.receivable_id).amount_paid == 100
    assert service.summary(credit_store, contract.id)["available_amount"] == "100.00"


def test_persisted_journal_beyond_first_thousand_keeps_every_receipt_and_exact_cents(credit_store, monkeypatch):
    from backend.services.credit_types import CreditReceipt
    source, contract, _, _ = credit_scenario(credit_store, monkeypatch)
    for index in range(1005):
        values = dict(id=f"synthetic-receipt-{index:05}", contract_id=contract.id,
            source_settlement_id=source.id, idempotency_key=f"historical-{index}", transaction_date=date(2026, 9, 5), method="cash")
        if hasattr(credit_store, "db"):
            credit_store.db.add(CreditReceiptORM(**values, amount_cents="1"))
        else:
            credit_store.credit_receipts[values["idempotency_key"]] = CreditReceipt(**values, amount=Decimal("0.01"))
    if hasattr(credit_store, "db"):
        credit_store.db.commit()
    page = service.journal(credit_store, contract.id, offset=1000, limit=50)
    assert page["total"] == 1005 and len(page["receipts"]) == 5
    assert service.summary(credit_store, contract.id)["remaining_amount"] == "89.95"
