"""One booking's available amount across invoice and service-contract payments.

Amounts use the provider convention: outgoing payments positive, refunds negative.
Reversals reduce their original booking and never provide a second payment. Existing
allocations consume the residual in creation order, including other portfolios;
only amounts are returned, never the identities of hidden invoice/contract rows.
"""

from dataclasses import dataclass, field
from datetime import date, timezone
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


def booking_payment_capacity(rows: Rows, booking_ids: Iterable[str], *, as_of: date | None = None) -> BookingPaymentCapacity:
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
        if as_of is not None and reversal.booking_date > as_of:
            continue
        key = reversal.reverses_booking_id
        reversed_by[key] = reversed_by.get(key, ZERO) + money(reversal.amount)
    sign = {key: Decimal(1) if money(booking.amount) < 0 else Decimal(-1)
            for key, booking in bookings.items()}
    left = {key: (ZERO if booking.reverses_booking_id or (as_of is not None and booking.booking_date > as_of) else
                  max(-(money(booking.amount) + reversed_by.get(key, ZERO)) * sign[key], ZERO))
            for key, booking in bookings.items()}
    reserved = {key: ZERO for key in bookings}
    # Explicit tenant/deposit uses reserve the same cash before supplier refunds.
    from .payment_allocations import non_rent_shares
    with scope_context(None):
        tenant_reserved = non_rent_shares(rows.store, ids)
        rent_reserved = rows.store.list_payment_allocations(booking_ids=ids)
    for allocation in rent_reserved:
        if allocation.source == "manual":
            tenant_reserved[allocation.booking_id] = tenant_reserved.get(allocation.booking_id, ZERO) + money(allocation.amount)
    # The claim shares of each original's returns, read for all originals at once.
    from .receivable_residuals import cash_reserved
    original_of = {b.id: b.reverses_booking_id for b in reversals
                   if b.reverses_booking_id in bookings and not bookings[b.reverses_booking_id].reverses_booking_id
                   and (as_of is None or b.booking_date <= as_of)}
    returned: dict[str, Decimal] = {}
    for reversal_id, amount in (cash_reserved(rows.store, set(original_of)) if original_of else {}).items():
        returned[original_of[reversal_id]] = returned.get(original_of[reversal_id], ZERO) + amount
    for key in left:
        reserved[key] = abs(tenant_reserved.get(key, ZERO))
        if key in returned:
            reserved[key] = max(reserved[key] + returned[key], ZERO)
        left[key] = max(left[key] - reserved[key], ZERO)

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
        capacity = ZERO if booking.reverses_booking_id or (as_of is not None and booking.booking_date > as_of) else max(
            -(money(booking.amount) + reversed_by.get(key, ZERO)) * sign[key], ZERO)
        result.available[key] = max(capacity - reserved[key], ZERO) * sign[key]
    return result
