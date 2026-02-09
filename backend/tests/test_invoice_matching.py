import datetime
from decimal import Decimal

import pytest

from backend.domain.invoice_matching import BookingCandidate, InvoiceMatcher, InvoiceToMatch


def test_allocate_fifo_full_match() -> None:
    invoice = InvoiceToMatch(
        invoice_id="inv-1",
        gross_amount=Decimal("500.00"),
        invoice_date=datetime.date(2024, 4, 20),
    )
    candidates = [
        BookingCandidate("b-2", Decimal("200.00"), datetime.date(2024, 4, 2)),
        BookingCandidate("b-1", Decimal("300.00"), datetime.date(2024, 4, 1)),
    ]

    result = InvoiceMatcher.allocate_fifo(invoice, candidates)

    assert result.allocated_total == Decimal("500.00")
    assert result.unmatched_amount == Decimal("0.00")
    assert [line.booking_id for line in result.allocations] == ["b-1", "b-2"]
    assert [line.allocated_amount for line in result.allocations] == [Decimal("300.00"), Decimal("200.00")]


def test_allocate_fifo_partial_match() -> None:
    invoice = InvoiceToMatch(
        invoice_id="inv-2",
        gross_amount=Decimal("800.00"),
        invoice_date=datetime.date(2024, 4, 20),
    )
    candidates = [
        BookingCandidate("b-1", Decimal("100.00"), datetime.date(2024, 4, 1)),
        BookingCandidate("b-2", Decimal("200.00"), datetime.date(2024, 4, 2)),
    ]

    result = InvoiceMatcher.allocate_fifo(invoice, candidates)

    assert result.allocated_total == Decimal("300.00")
    assert result.unmatched_amount == Decimal("500.00")
    assert len(result.allocations) == 2


def test_reject_negative_amounts() -> None:
    with pytest.raises(ValueError):
        InvoiceToMatch(
            invoice_id="inv-3",
            gross_amount=Decimal("-10.00"),
            invoice_date=datetime.date(2024, 4, 20),
        )

    with pytest.raises(ValueError):
        BookingCandidate("b-1", Decimal("-2.00"), datetime.date(2024, 4, 1))
