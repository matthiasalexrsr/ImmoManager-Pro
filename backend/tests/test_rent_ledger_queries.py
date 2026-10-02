"""Bounded contract history reads with exact payment/reversal semantics."""
from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import event

from backend.models import ContractCreate, RentChargeCreate, UnitCreate
from backend.services.payments import PaymentReversalCreate
from backend.services.rent_ledger import contract_ledger_inputs, ungenerated_contract_preview
from backend.tests.test_payments import payload
from backend.tests.test_rent_ledger import ledger_store, setup_contract  # noqa: F401


def other_charge(active, original):
    unit = active.create_unit(UnitCreate(property_id=original.property_id, label="Other synthetic unit", unit_type="apartment"))
    contract = active.create_contract(ContractCreate(**{**original.model_dump(include=set(ContractCreate.model_fields)),
        "contract_number": "Other-" + str(uuid4()), "unit_id": unit.id}))
    return active.create_rent_charge(RentChargeCreate(contract_id=contract.id, month="2026-09", cold_rent=900))


def test_history_stays_contract_and_as_of_scoped_with_a_real_reversal(ledger_store):  # noqa: F811
    contract, charge = setup_contract(ledger_store)
    other = other_charge(ledger_store, contract)
    receipt = ledger_store.record_payment("rent_charge", charge.id, payload("40.10"))
    ledger_store.record_payment("rent_charge", other.id, payload("25.00"))
    ledger_store.create_rent_charge(RentChargeCreate(contract_id=contract.id, month="2046-10", cold_rent=900))
    ledger_store.reverse_payment("rent_charge", charge.id, receipt.id, PaymentReversalCreate(
        idempotency_key=str(uuid4()), reversal_date=date(2026, 10, 10), reason="Synthetic reversal"))
    lines, before = contract_ledger_inputs(ledger_store, contract, date(2026, 10, 1))
    assert len(lines) == 1 and lines[0].total_amount == Decimal("100.30")
    assert sum(item.amount for item in before) == Decimal("40.10")
    _, after = contract_ledger_inputs(ledger_store, contract, date(2026, 10, 20))
    assert after == []


def test_ungenerated_preview_never_reads_global_contract_charge_or_price_lists(ledger_store, monkeypatch):  # noqa: F811
    contract, _ = setup_contract(ledger_store)
    other_charge(ledger_store, contract)
    def forbidden(*_args, **_kwargs):
        raise AssertionError("Global ledger materialization is forbidden for one contract")
    for method in ("list_contracts", "list_rent_charges", "list_rent_adjustments"):
        monkeypatch.setattr(ledger_store, method, forbidden)
    preview = ungenerated_contract_preview(ledger_store, contract, date(2026, 11, 15))
    assert all(row["contract_id"] == contract.id for row in preview["candidates"])
    assert next(row for row in preview["candidates"] if row["month"] == "2026-11")["cold_rent"] == 800


def test_sql_history_has_two_targeted_selects_instead_of_per_receipt_queries(ledger_store):  # noqa: F811
    if not hasattr(ledger_store, "db"):
        pytest.skip("SQL query-shape gate")
    contract, charge = setup_contract(ledger_store)
    for _ in range(8):
        ledger_store.record_payment("rent_charge", charge.id, payload("1.00"))
    other_charge(ledger_store, contract)
    calls = []
    def capture(_connection, _cursor, statement, parameters, _context, _many):
        if statement.lstrip().upper().startswith("SELECT"):
            calls.append((statement, parameters))
    engine = ledger_store.db.get_bind()
    event.listen(engine, "before_cursor_execute", capture)
    try:
        _, receipts = contract_ledger_inputs(ledger_store, contract, date(2026, 10, 1))
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    assert len(receipts) == 8 and len(calls) == 2
    assert all("WHERE" in query and "contract_id" in query and contract.id in parameters for query, parameters in calls)
    assert "LEFT OUTER JOIN payment_reversals" in calls[1][0]
