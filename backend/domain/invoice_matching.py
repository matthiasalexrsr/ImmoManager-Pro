from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Iterable

CENT = Decimal("0.01")


def _to_money(value: Decimal | float | int | str) -> Decimal:
    amount = Decimal(str(value)).quantize(CENT, rounding=ROUND_HALF_UP)
    if amount < 0:
        raise ValueError("Betrag darf nicht negativ sein")
    return amount


@dataclass(frozen=True)
class InvoiceToMatch:
    invoice_id: str
    gross_amount: Decimal
    invoice_date: date

    def __post_init__(self) -> None:
        if not self.invoice_id:
            raise ValueError("invoice_id ist erforderlich")
        object.__setattr__(self, "gross_amount", _to_money(self.gross_amount))


@dataclass(frozen=True)
class BookingCandidate:
    booking_id: str
    open_amount: Decimal
    booking_date: date

    def __post_init__(self) -> None:
        if not self.booking_id:
            raise ValueError("booking_id ist erforderlich")
        object.__setattr__(self, "open_amount", _to_money(self.open_amount))


@dataclass(frozen=True)
class AllocationLine:
    invoice_id: str
    booking_id: str
    allocated_amount: Decimal


@dataclass(frozen=True)
class AllocationResult:
    allocations: list[AllocationLine]
    allocated_total: Decimal
    unmatched_amount: Decimal


class InvoiceMatcher:
    """Domänenlogik zur Rechnungszuordnung (Rechnungsbetrag -> offene Buchungen)."""

    @staticmethod
    def allocate_fifo(invoice: InvoiceToMatch, candidates: Iterable[BookingCandidate]) -> AllocationResult:
        remaining = invoice.gross_amount
        allocations: list[AllocationLine] = []

        for candidate in sorted(candidates, key=lambda item: item.booking_date):
            if remaining == Decimal("0.00"):
                break
            if candidate.open_amount == Decimal("0.00"):
                continue

            amount = min(remaining, candidate.open_amount)
            if amount <= Decimal("0.00"):
                continue

            allocations.append(
                AllocationLine(
                    invoice_id=invoice.invoice_id,
                    booking_id=candidate.booking_id,
                    allocated_amount=amount.quantize(CENT, rounding=ROUND_HALF_UP),
                )
            )
            remaining = (remaining - amount).quantize(CENT, rounding=ROUND_HALF_UP)

        allocated_total = (invoice.gross_amount - remaining).quantize(CENT, rounding=ROUND_HALF_UP)
        return AllocationResult(
            allocations=allocations,
            allocated_total=allocated_total,
            unmatched_amount=remaining,
        )
