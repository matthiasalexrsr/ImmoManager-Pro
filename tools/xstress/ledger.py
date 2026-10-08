"""Independent bookkeeping of what the app should show: rent due, payments, advances.

Written from the business rules, not from the app's code:
- rent is due per calendar month; a month the tenancy covers only partly is charged
  by days (cents rounded half up per part: cold, service, heating);
- a rent change applies from its valid-from date (always the 1st);
- a tenant's payments count for the tenant; how they split across contracts is checked
  where the tenant has a single contract.
"""

from __future__ import annotations

import calendar
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from .world import Tenancy, months

CENT = Decimal("0.01")


def money(value) -> Decimal:
    return Decimal(str(value)).quantize(CENT, rounding=ROUND_HALF_UP)


@dataclass
class Ledger:
    payments: dict = field(default_factory=lambda: defaultdict(Decimal))       # tenant id -> paid
    unassigned: dict = field(default_factory=lambda: defaultdict(Decimal))     # tenant id -> paid without contract
    expenses: dict = field(default_factory=lambda: defaultdict(Decimal))       # property id, year -> recoverable costs
    booked_total: Decimal = Decimal("0")

    def pay(self, tenant_id: str, amount) -> None:
        self.payments[tenant_id] += money(amount)
        self.booked_total += money(amount)

    def book(self, amount) -> None:
        self.booked_total += money(amount)


def step_on(tenancy: Tenancy, day: date):
    current = None
    for valid_from, cold, service, heating in sorted(tenancy.steps, key=lambda s: s[0]):
        if valid_from <= day:
            current = (cold, service, heating)
    return current


def due_until(tenancy: Tenancy, until: date) -> Decimal:
    """Rent the tenancy owes from its start up to and including `until`."""
    total = Decimal("0")
    last_day = min(until, tenancy.end) if tenancy.end else until
    for month in months(tenancy.start, last_day):
        first = max(month, tenancy.start)
        charge = step_on(tenancy, first)
        if charge is None:
            continue
        days = calendar.monthrange(month.year, month.month)[1]
        last = min(month.replace(day=days), tenancy.end or month.replace(day=days))
        share = Decimal((last - first).days + 1) / Decimal(days)
        total += sum((money(Decimal(str(part)) * share) for part in charge), Decimal("0"))
    return total


def advances_between(tenancy: Tenancy, start: date, end: date) -> Decimal:
    """Service and heating advances the tenancy owes for days inside [start, end]."""
    total = Decimal("0")
    begin = max(start, tenancy.start)
    finish = min(end, tenancy.end) if tenancy.end else end
    if finish < begin:
        return total
    for month in months(begin, finish):
        days = calendar.monthrange(month.year, month.month)[1]
        first = max(month, begin)
        last = min(month.replace(day=days), finish)
        charge = step_on(tenancy, first)
        if charge is None:
            continue
        share = Decimal((last - first).days + 1) / Decimal(days)
        total += money(Decimal(str(charge[1])) * share) + money(Decimal(str(charge[2])) * share)
    return total


def monthly_due(tenancy: Tenancy, month: date) -> Decimal:
    """What the tenant should transfer for this month (prorated in the first and last month)."""
    end = month.replace(day=calendar.monthrange(month.year, month.month)[1])
    before = month - timedelta(days=1)
    upto = due_until(tenancy, end)
    return upto - (due_until(tenancy, before) if before >= tenancy.start else Decimal("0"))
