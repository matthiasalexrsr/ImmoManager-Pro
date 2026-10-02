"""Independent PG sessions in a UUID schema; no application database is touched."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from threading import Barrier

from sqlalchemy import select

from backend.db.credit_models import CreditReceiptORM, CreditReversalORM
from backend.db.orm_models import BillingSettlementORM, PaymentORM, ReceivableORM
from backend.repositories.sql_store import SQLAlchemyStore
from backend.services import billing_settlement as settlements
from backend.services import credit_ledger as service
from backend.services.payments import FinancialConsistencyError
from backend.tests.test_bank_payments import bank_booking
from backend.tests.test_credit_ledger import correct, credit_scenario, offset, payout, reversal
from backend.tests.test_private_server_concurrency import postgres_database as postgres_database


def parallel(factory, operations):
    barrier = Barrier(len(operations))
    def run(operation):
        with factory() as db:
            barrier.wait(timeout=20)
            try:
                return operation(SQLAlchemyStore(db))
            except FinancialConsistencyError:
                return None
    with ThreadPoolExecutor(max_workers=len(operations)) as pool:
        return list(pool.map(run, operations))


def test_pg_same_key_offset_and_reversal_create_one_receipt_each(postgres_database, monkeypatch):
    engine, factory, _, _ = postgres_database
    with factory() as db:
        active = SQLAlchemyStore(db)
        source, contract, period, _ = credit_scenario(active, monkeypatch)
        _, revision = correct(active, period, 90)
        command = offset(source, active.get_receivable(revision.receivable_id), key="same-offset")
    results = parallel(factory, [lambda active: service.create_receipt(active, command)] * 2)
    assert all(results) and results[0].id == results[1].id
    receipt = results[0]
    request = reversal("same-reversal")
    results = parallel(factory, [lambda active: service.reverse_receipt(active, receipt.id, request)] * 2)
    assert all(results) and results[0].id == results[1].id
    with factory() as db:
        assert len(list(db.scalars(select(CreditReceiptORM)))) == 1
        assert len(list(db.scalars(select(CreditReversalORM)))) == 1
        assert len(list(db.scalars(select(PaymentORM).where(PaymentORM.receivable_id == revision.receivable_id)))) == 1
        assert SQLAlchemyStore(db).get_receivable(revision.receivable_id).amount_paid == 0
        assert service.summary(SQLAlchemyStore(db), contract.id)["available_amount"] == "60.00"
    assert engine.pool.checkedout() == 0


def test_pg_different_contracts_contend_for_shared_negative_bank_budget(postgres_database, monkeypatch):
    _, factory, _, _ = postgres_database
    with factory() as db:
        active = SQLAlchemyStore(db)
        _, _, _, charge = credit_scenario(active, monkeypatch, count=2)
        sources = list(settlements.settlements(active))
        booking = bank_booking(active, charge, -75)
    commands = [payout(source, "60", key=f"bank-{index}", method="bank", booking_id=booking.id)
        for index, source in enumerate(sources)]
    results = parallel(factory, [lambda active, command=command: service.create_receipt(active, command) for command in commands])
    assert sum(row is not None for row in results) == 1
    with factory() as db:
        active = SQLAlchemyStore(db)
        assert active.get_booking(booking.id).allocated_amount == 60
        assert len(list(db.scalars(select(CreditReceiptORM)))) == 1
        states = [service.summary(active, source.contract_id)["available_amount"] for source in sources]
        assert sorted(states) == ["100.00", "40.00"]


def test_pg_revision_posting_and_payout_serialize_financial_order(postgres_database, monkeypatch):
    _, factory, _, _ = postgres_database
    with factory() as db:
        active = SQLAlchemyStore(db)
        source, contract, period, _ = credit_scenario(active, monkeypatch)
        revised, _ = correct(active, period, 90, post=False)
    # SQL serialization, independent of the memory-store coordination lock.
    monkeypatch.setattr(settlements, "_memory_lock", nullcontext())
    results = parallel(factory, [lambda active: service.create_receipt(active, payout(source, "100", key="before-or-after")),
        lambda active: settlements.post_settlements(active, revised.id)])
    assert results[1]["created_receivables"] == 1
    with factory() as db:
        active = SQLAlchemyStore(db)
        state = service.summary(active, contract.id)
        assert len(list(db.scalars(select(BillingSettlementORM)))) == 2
        claim = db.scalar(select(ReceivableORM))
        assert claim.amount_due == 40 and claim.amount_paid == 0
        assert state["available_amount"] == ("0.00" if results[0] else "60.00")
        assert state["remaining_amount"] == ("0.00" if results[0] else "100.00")
