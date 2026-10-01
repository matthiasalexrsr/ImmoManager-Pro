"""Invoice payments and rental credit payouts share the same actual cash budget."""
from datetime import date
from uuid import uuid4

import pytest

from backend.models import InvoiceCreate
from backend.services import credit_ledger
from backend.services.bank_matching import MatchError, SuggestionQuery, confirm_match, suggestions
from backend.services.payments import Payment, PaymentReversalCreate
from backend.storage import ValidationError
from backend.tests.test_bank_matching import command
from backend.tests.test_bank_payments import bank_booking
from backend.tests.test_credit_ledger import credit_scenario, credit_store, payout, reversal  # noqa: F401


@pytest.mark.parametrize("first", ["invoice", "credit"])
def test_invoice_and_credit_cannot_spend_same_outgoing_bank_budget_twice(credit_store, monkeypatch, first):  # noqa: F811
    source, contract, _, charge = credit_scenario(credit_store, monkeypatch)
    booking = bank_booking(credit_store, charge, amount=-100)
    invoice = credit_store.create_invoice(InvoiceCreate(property_id=contract.property_id, supplier="Synthetic repairs",
        invoice_number="CASH-1", invoice_date=date(2026, 9, 1), net_amount=100, gross_amount=100, vat_rate=0))
    page = suggestions(credit_store, booking.id, SuggestionQuery(kind="invoice"))
    paid = credit_ledger.create_receipt(credit_store, payout(source, "60", method="bank", booking_id=booking.id)) if first == "credit" else None
    if paid:
        with pytest.raises(MatchError, match="geändert"):
            confirm_match(credit_store, booking.id, command(page, amount="100"))
        page = suggestions(credit_store, booking.id, SuggestionQuery(kind="invoice"))
        receipt = confirm_match(credit_store, booking.id, command(page, amount="40"))
    else:
        receipt = confirm_match(credit_store, booking.id, command(page, amount="40"))
        paid = credit_ledger.create_receipt(credit_store, payout(source, "60", method="bank", booking_id=booking.id))
    assert credit_store.get_booking(booking.id).allocated_amount == 100
    with pytest.raises(ValidationError):
        credit_ledger.create_receipt(credit_store, payout(source, ".01", method="bank", booking_id=booking.id))
    assert suggestions(credit_store, booking.id, SuggestionQuery(kind="invoice"))["items"] == []
    credit_ledger.reverse_receipt(credit_store, paid.id, reversal())
    assert credit_store.get_booking(booking.id).allocated_amount == 40
    credit_store.reverse_payment("invoice", invoice.id, receipt.id, PaymentReversalCreate(idempotency_key=str(uuid4()),
        reversal_date=date(2026, 10, 1), reason="Reviewed invoice correction"))
    assert credit_store.get_booking(booking.id).allocated_amount == 0
    assert credit_store.get_invoice(invoice.id).amount_paid == 0 and len(credit_store.list_bookings()) == 1


def test_direct_invoice_receipt_restore_preserves_existing_credit_payout_budget(credit_store, monkeypatch):  # noqa: F811
    source, contract, _, charge = credit_scenario(credit_store, monkeypatch)
    booking = bank_booking(credit_store, charge, amount=-100)
    credit_ledger.create_receipt(credit_store, payout(source, "60", method="bank", booking_id=booking.id))
    invoice = credit_store.create_invoice(InvoiceCreate(property_id=contract.property_id, supplier="Synthetic repairs",
        invoice_date=date(2026, 9, 1), net_amount=100, gross_amount=100, vat_rate=0))
    receipt = Payment(id=str(uuid4()), idempotency_key=str(uuid4()), entity_type="invoice", entity_id=invoice.id,
        amount="40", booking_id=booking.id, payment_date=booking.booking_date)
    credit_store.import_payment(receipt)
    assert credit_store.get_booking(booking.id).allocated_amount == 100
    with pytest.raises(ValidationError):
        credit_store.import_payment(receipt.model_copy(update={"id": str(uuid4()), "idempotency_key": str(uuid4()), "amount": receipt.amount / 40}))
    assert credit_store.get_booking(booking.id).allocated_amount == 100


def test_credit_offset_target_remains_rental_obligation_not_supplier_invoice():
    from pydantic import ValidationError as PayloadError

    from backend.services.credit_types import CreditOffsetCreate
    with pytest.raises(PayloadError):
        CreditOffsetCreate(source_settlement_id="source", idempotency_key="key", amount="1", transaction_date=date(2026, 9, 5),
            target_type="invoice", target_id="supplier-invoice")
