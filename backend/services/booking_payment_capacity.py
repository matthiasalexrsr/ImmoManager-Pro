"""One booking's available amount across invoice and service-contract payments.

Amounts use the provider convention: outgoing payments positive, refunds negative.
Reversals reduce their original booking and never provide a second payment. Existing
allocations consume the residual in creation order, including other portfolios;
only amounts are returned, never the identities of hidden invoice/contract rows.
"""

from dataclasses import dataclass, field
from datetime import timezone
from decimal import Decimal
from typing import Iterable

from ..domain.money import ZERO, money
from .maintenance_rows import Rows
from .portfolio_scope import scope_context

PAYMENT_TABLES = ("invoice_payments", "service_contract_payments")


@dataclass
class BookingPaymentCapacity:
    available: dict[str, Decimal] = field(default_factory=dict)
    effective: dict[tuple[str, str], Decimal] = field(default_factory=dict)


def booking_payment_capacity(rows: Rows, booking_ids: Iterable[str]) -> BookingPaymentCapacity:
    ids = set(booking_ids)
    result = BookingPaymentCapacity()
    if not ids:
        return result
    # Callers authorize the booking first. Other allocations still consume its money,
    # even when their invoice or contract belongs to another portfolio.
    with scope_context(None):
        bookings = {row.id: row for row in rows.find("bookings", id=ids)}
        reversals = rows.find("bookings", reverses_booking_id=ids)
        allocations = [(table, row) for table in PAYMENT_TABLES
                       for row in rows.find(table, booking_id=ids)]
    reversed_by: dict[str, Decimal] = {}
    for reversal in reversals:
        key = reversal.reverses_booking_id
        reversed_by[key] = reversed_by.get(key, ZERO) + money(reversal.amount)
    sign = {key: Decimal(1) if money(booking.amount) < 0 else Decimal(-1)
            for key, booking in bookings.items()}
    left = {key: (ZERO if booking.reverses_booking_id else
                  max(-(money(booking.amount) + reversed_by.get(key, ZERO)) * sign[key], ZERO))
            for key, booking in bookings.items()}
    reserved = {key: ZERO for key in bookings}

    def ordering(entry):
        table, row = entry
        stamp = row.created_at
        stamp = stamp.replace(tzinfo=timezone.utc) if stamp.tzinfo is None else stamp.astimezone(timezone.utc)
        return stamp, row.id, table

    for table, allocation in sorted(allocations, key=ordering):
        key = allocation.booking_id
        wanted = max(money(allocation.amount) * sign.get(key, ZERO), ZERO)
        effective = min(wanted, left.get(key, ZERO))
        result.effective[table, allocation.id] = effective * sign.get(key, ZERO)
        left[key] = left.get(key, ZERO) - effective
        reserved[key] = reserved.get(key, ZERO) + wanted
    for key, booking in bookings.items():
        capacity = ZERO if booking.reverses_booking_id else max(
            -(money(booking.amount) + reversed_by.get(key, ZERO)) * sign[key], ZERO)
        result.available[key] = max(capacity - reserved[key], ZERO) * sign[key]
    return result
