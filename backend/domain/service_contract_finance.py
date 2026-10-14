"""Money of property service contracts: tariff history, planned instalments, bills, payments.

Three things are kept apart and each counts once (docs/SERVICE_CONTRACTS_20261008.md):

* Expectation (Soll): instalments (Abschläge, Raten) the tariff in force plans; they
  are payment obligations, not costs.
* Invoice (Rechnung): the provider's bill for a service period. Its gross amount is
  the cost of that period. A settlement credits the advances already demanded, so
  only ``gross - advances_credited`` is still owed (negative: a credit).
* Payment (Zahlung): a booking allocated to the contract (positive: paid to the
  provider, negative: refunded). One booking is allocated at most once per contract.

Obligations are instalments plus invoice balances; open = obligations - payments.
Costs are invoices only, never instalments, so an advance is not counted again as
a cost and a settlement is not counted again as a payment obligation.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from .billing_engine import allocate_cents
from .money import ZERO, cents, money
from .service_contract_terms import add_months, days_in_month

INTERVAL_MONTHS = {"monthly": 1, "bimonthly": 2, "quarterly": 3, "semiannual": 6, "annual": 12}
# planned instalments of one request: 50 years of monthly instalments per tariff
MAX_INSTALMENTS = 600


def tariff_at(tariffs: Iterable[Any], day: date) -> Any | None:
    """The tariff in force on `day`: the latest one valid from that day or before."""
    best = None
    for tariff in tariffs:
        if tariff.valid_from <= day and (best is None or tariff.valid_from > best.valid_from):
            best = tariff
    return best


def tariff_spans(tariffs: Iterable[Any]) -> list[tuple[Any, date, date | None]]:
    """(tariff, first day, last day or None) in order; a tariff runs until the next one starts."""
    ordered = sorted(tariffs, key=lambda t: t.valid_from)
    spans = []
    for index, tariff in enumerate(ordered):
        following = ordered[index + 1].valid_from if index + 1 < len(ordered) else None
        spans.append((tariff, tariff.valid_from, following - timedelta(days=1) if following else None))
    return spans


def due_day(year: int, month: int, day: int) -> date:
    return date(year, month, min(day, days_in_month(year, month)))


def due_dates(first: date, last: date, interval_months: int, day: int) -> list[date]:
    """Due dates on `day` (clamped to the month) every `interval_months`, from the first one on or after `first`."""
    if last < first:
        return []
    current = due_day(first.year, first.month, day)
    if current < first:
        following = add_months(date(first.year, first.month, 1), 1)
        current = due_day(following.year, following.month, day)
    anchor = date(current.year, current.month, 1)
    found: list[date] = []
    step = 0
    while current <= last and len(found) < MAX_INSTALMENTS:
        found.append(current)
        step += interval_months
        month = add_months(anchor, step)
        current = due_day(month.year, month.month, day)
    return found


@dataclass(frozen=True)
class Instalment:
    due_date: date
    amount: Decimal
    tariff_id: str


def planned_instalments(tariffs: Sequence[Any], contract_start: date, contract_end: date | None,
                        window_from: date, window_to: date) -> list[Instalment]:
    """Instalments the tariffs plan, due within the contract and the window (both inclusive)."""
    found: list[Instalment] = []
    for tariff, span_from, span_to in tariff_spans(tariffs):
        interval = INTERVAL_MONTHS.get(tariff.advance_interval or "")
        amount = money(tariff.advance_amount)
        if not interval or amount == 0:
            continue
        first = max(span_from, contract_start)
        last_candidates = [d for d in (span_to, contract_end, window_to) if d is not None]
        last = min(last_candidates)
        for due in due_dates(first, last, interval, tariff.advance_day or 1):
            if due >= window_from:
                found.append(Instalment(due, amount, tariff.id))
    return sorted(found, key=lambda i: i.due_date)


def overlap_days(a_from: date, a_to: date, b_from: date, b_to: date) -> int:
    start, end = max(a_from, b_from), min(a_to, b_to)
    return (end - start).days + 1 if end >= start else 0


def prorated(amount: Decimal, service_from: date, service_to: date, window_from: date, window_to: date) -> Decimal:
    """The share of `amount` for the days of the service period inside the window, rounded once."""
    total = (service_to - service_from).days + 1
    inside = overlap_days(service_from, service_to, window_from, window_to)
    if total <= 0 or inside <= 0:
        return ZERO
    if inside >= total:
        return amount
    return cents(amount * inside / total)


@dataclass
class InvoiceFigures:
    link_id: str
    invoice_id: str
    invoice_date: date
    period_start: date
    period_end: date
    gross: Decimal
    credited: Decimal
    planned_advances: Decimal          # instalments due in the service period (for settlements)
    paid: Decimal                      # payments allocated to this bill

    @property
    def balance(self) -> Decimal:
        return self.gross - self.credited


@dataclass
class Reconciliation:
    window_from: date
    window_to: date
    instalments: list[Instalment] = field(default_factory=list)
    invoices: list[InvoiceFigures] = field(default_factory=list)     # invoice date in the window
    expected: Decimal = ZERO          # instalments due in the window
    invoiced: Decimal = ZERO          # gross of the bills dated in the window
    credited: Decimal = ZERO          # advances those bills credit
    paid: Decimal = ZERO              # payments booked in the window
    costs: Decimal = ZERO             # bills' gross, prorated to the service days in the window

    @property
    def invoice_balance(self) -> Decimal:
        return self.invoiced - self.credited

    @property
    def obligations(self) -> Decimal:
        return self.expected + self.invoice_balance

    @property
    def open(self) -> Decimal:
        return self.obligations - self.paid


def reconcile(*, tariffs: Sequence[Any], contract_start: date, contract_end: date | None,
              invoices: Sequence[tuple[Any, Any]], payments: Sequence[tuple[Any, Any]],
              window_from: date, window_to: date) -> Reconciliation:
    """Expectation, invoices and payments of a window, each counted once.

    invoices: (link, invoice) pairs; payments: (allocation, booking) pairs.
    """
    result = Reconciliation(window_from, window_to)
    result.instalments = planned_instalments(tariffs, contract_start, contract_end, window_from, window_to)
    result.expected = sum((i.amount for i in result.instalments), ZERO)
    paid_by_link: dict[str, Decimal] = {}
    for allocation, booking in payments:
        amount = money(allocation.amount)
        if allocation.service_contract_invoice_id:
            paid_by_link[allocation.service_contract_invoice_id] = (
                paid_by_link.get(allocation.service_contract_invoice_id, ZERO) + amount)
        if window_from <= booking.booking_date <= window_to:
            result.paid += amount
    for link, invoice in invoices:
        gross = money(invoice.gross_amount)
        result.costs += prorated(gross, link.period_start, link.period_end, window_from, window_to)
        if not window_from <= invoice.invoice_date <= window_to:
            continue
        planned = sum((i.amount for i in planned_instalments(tariffs, contract_start, contract_end,
                                                              link.period_start, link.period_end)), ZERO)
        figures = InvoiceFigures(link.id, invoice.id, invoice.invoice_date, link.period_start, link.period_end,
                                 gross, money(link.advances_credited), planned, paid_by_link.get(link.id, ZERO))
        result.invoices.append(figures)
        result.invoiced += figures.gross
        result.credited += figures.credited
    result.invoices.sort(key=lambda f: (f.invoice_date, f.link_id))
    return result


def active_in(location: Any, period_from: date, period_to: date) -> bool:
    start = location.valid_from or date.min
    end = location.valid_to or date.max
    return start <= period_to and end >= period_from


def property_weights(locations: Iterable[Any], period_from: date, period_to: date) -> dict[str, Decimal]:
    """Cost weights per property of the locations active in the period (unweighted rows count 1)."""
    weights: dict[str, Decimal] = {}
    for location in locations:
        if not active_in(location, period_from, period_to):
            continue
        weight = Decimal(str(location.share_weight if location.share_weight is not None else 1))
        weights[location.property_id] = weights.get(location.property_id, ZERO) + weight
    return weights


def property_share(amount: Decimal, weights: dict[str, Decimal], property_id: str) -> Decimal:
    """The property's cents of `amount`; the parts of all properties add up exactly (largest remainder)."""
    if property_id not in weights:
        return ZERO
    ordered = sorted(weights)
    parts = allocate_cents(amount, [weights[key] for key in ordered])
    return parts[ordered.index(property_id)]


def recoverable_part(amount: Decimal, percent: Any) -> Decimal:
    share = Decimal(str(percent if percent is not None else 100))
    if share >= 100:
        return amount
    return cents(amount * share / 100)
