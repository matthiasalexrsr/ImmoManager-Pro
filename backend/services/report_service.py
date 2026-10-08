"""Centralised report / analytics computation.

All financial calculations live here so they can be tested in isolation and shared across
routers, scheduled jobs and export pipelines. Three views of money stay apart
(docs/FINANCE_PRECISION_20261008.md):

- cash view (Zahlungsübersicht, compute_cashflow): bookings dated in the period, by side;
- period result (Periodenergebnis, compute_period_result): the rent due for the period's months
  from the contracts' rent history, plus other income and the costs booked in those months;
  tenants' payments settle that rent and are not counted again;
- forecast (Prognose, compute_liquidity_forecast): the rent the contracts will owe, plus the
  average other income and costs of the last complete months (months without bookings count).

Amounts are Decimal cents throughout (domain.money); responses carry them as JSON numbers.
Every report takes the same filter (services.finance_ledger.FinanceFilter).
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from ..domain.lease_engine import LeaseEngine
from ..domain.money import ZERO, as_number, cents, money, money_sum
from ..domain.occupancy import NON_BILLABLE_STATUSES, unit_statuses_on
from ..domain.receivables import is_open_credit, is_overdue_debt, is_unpaid_debt
from .finance_ledger import (
    BookingTotal,
    Dimensions,
    FinanceFilter,
    add_months,
    booking_totals,
    first_booking_date,
    month_end,
    month_key,
    month_start,
    months_between,
)
from .read_cache import CachedReads
from .rent_history import rent_steps

HISTORY_MONTHS = 12   # complete months behind the forecast's averages


# ---------------------------------------------------------------------------
# Shared pieces
# ---------------------------------------------------------------------------

def _income(rows: list[BookingTotal]) -> Decimal:
    return sum((row.amount for row in rows if row.side == "income"), ZERO)


def _expense(rows: list[BookingTotal]) -> Decimal:
    return -sum((row.amount for row in rows if row.side == "expense"), ZERO)


def _other_flows(rows: list[BookingTotal]) -> tuple[Decimal, Decimal, Decimal]:
    """(other income, costs, unassigned income) of bookings that do not settle a tenant's account.

    Tenant payments (and their returns and refunds) pay the rent due and are left out. Incoming
    money counts as other income only with an income category and without a unit: money for a
    unit or without any category may be rent that is not assigned yet (review list), so it is
    reported apart and kept out of the result.
    """
    other = costs = unassigned = ZERO
    for row in rows:
        if row.tenant:
            continue
        if row.side == "expense":
            costs -= row.amount
        elif row.classified and not row.unit:
            other += row.amount
        else:
            unassigned += row.amount
    return other, costs, unassigned


def _by_month(rows: list[BookingTotal]) -> dict[str, list[BookingTotal]]:
    grouped: dict[str, list[BookingTotal]] = defaultdict(list)
    for row in rows:
        grouped[row.month or ""].append(row)
    return grouped


def rent_due_by_month(store: Any, flt: FinanceFilter, first: date, last: date) -> dict[str, Decimal]:
    """Rent the contracts owe in each month from *first* to *last* (their rent history, warm,
    move-in and move-out months by days); drafts owe nothing."""
    reads = CachedReads(store)
    dims = Dimensions(reads, flt)
    first, last_day = month_start(first), month_end(last)
    due: dict[str, Decimal] = defaultdict(lambda: ZERO)
    for contract in reads.list_contracts():
        if contract.status in NON_BILLABLE_STATUSES or not dims.contract_matches(contract):
            continue
        if contract.start_date > last_day or (contract.end_date and contract.end_date < first):
            continue
        if contract.end_date and contract.end_date < contract.start_date:
            continue     # not a valid term; the contract form refuses it
        # months before *first* are not needed; a full month owes the same from either start
        start = max(contract.start_date, first)
        for line in LeaseEngine.build_monthly_receivables(
                contract_start=start, contract_end=contract.end_date,
                rent_steps=rent_steps(reads, contract), until_including=last_day):
            if line.period_start >= first:
                due[month_key(line.period_start)] += line.total_amount
    return due


def _contracts_by_id(store: Any) -> dict[str, Any]:
    return {c.id: c for c in store.list_contracts()}


def _receivables(store: Any, flt: FinanceFilter) -> list:
    """Receivables of the matching contracts, due in the period."""
    dims = Dimensions(store, flt)
    contracts = _contracts_by_id(store)
    selected = []
    for receivable in store.list_receivables():
        contract = contracts.get(receivable.contract_id)
        if contract is None or not dims.contract_matches(contract) or not flt.in_period(receivable.due_date):
            continue
        selected.append(receivable)
    return selected


# ---------------------------------------------------------------------------
# Report computations
# ---------------------------------------------------------------------------

def compute_summary(store: Any, flt: FinanceFilter | None = None, today: date | None = None) -> dict[str, Any]:
    flt = flt or FinanceFilter()
    today = today or date.today()
    dims = Dimensions(store, flt)
    receivables = _receivables(store, flt)
    open_receivables = money_sum(r.amount_due for r in receivables if is_unpaid_debt(r))
    overdue_receivables = money_sum(r.amount_due for r in receivables if is_overdue_debt(r, today))
    open_credits = -money_sum(r.amount_due for r in receivables if is_open_credit(r))
    total_bookings = sum((row.amount for row in booking_totals(store, flt)), ZERO)
    # invoices name a property (or nothing), never a unit
    invoices = [inv for inv in store.list_invoices()
                if not flt.unit_id and dims.matches(inv.property_id) and flt.in_period(inv.invoice_date)]
    maintenance = [c for c in store.list_maintenance_cases() if dims.matches(c.property_id, c.unit_id)]
    return {
        "totals": {
            "properties": sum(1 for p in store.list_properties() if dims.property_record_matches(p)),
            "units": sum(1 for u in store.list_units() if dims.unit_record_matches(u)),
            "contracts": sum(1 for c in store.list_contracts() if dims.contract_matches(c)),
        },
        "finance": {
            "bookingsTotal": as_number(total_bookings),
            "invoicesTotal": as_number(money_sum(inv.gross_amount for inv in invoices)),
            "openReceivables": as_number(open_receivables),
            "overdueReceivables": as_number(overdue_receivables),
            "openCredits": as_number(open_credits),
        },
        "maintenance": {
            "openCases": sum(1 for c in maintenance if c.status in {"open", "in_progress"}),
        },
        "filters": flt.echo(),
    }


def compute_finance(store: Any, flt: FinanceFilter | None = None) -> dict[str, Any]:
    """Bookings per category; a reversal nets the booking it cancels within its category."""
    flt = flt or FinanceFilter()
    categories = {c.id: c for c in store.list_categories()}
    per_category: dict[str, Decimal] = defaultdict(lambda: ZERO)
    uncategorized = total = ZERO
    for row in booking_totals(store, flt, by=("category",)):
        total += row.amount
        if row.category_id is not None and row.category_id in categories:
            per_category[row.category_id] += row.amount
        else:
            uncategorized += row.amount
    totals = sorted(
        ({"categoryId": category_id, "categoryName": categories[category_id].name,
          "categoryType": categories[category_id].category_type, "total": as_number(amount)}
         for category_id, amount in per_category.items()),
        key=lambda item: item["categoryName"])
    return {
        "totalsByCategory": totals,
        "uncategorizedTotal": as_number(uncategorized),
        "bookingsTotal": as_number(total),
        "filters": flt.echo(),
    }


def compute_occupancy(*, units: list, contracts: list, today: date | None = None) -> dict[str, Any]:
    statuses = unit_statuses_on(today or date.today(), units, contracts)
    total = len(units)
    rented = sum(1 for status in statuses.values() if status == "occupied")
    rate = (rented / total) if total else 0.0
    return {
        "totalUnits": total,
        "rentedUnits": rented,
        "occupancyRate": rate,
    }


def compute_receivables_aging(store: Any, flt: FinanceFilter | None = None,
                              today: date | None = None) -> dict[str, Any]:
    """Unpaid receivables by days past due; credits are reported apart, never netted."""
    flt = flt or FinanceFilter()
    today = today or date.today()
    receivables = _receivables(store, flt)
    buckets = {"current": ZERO, "days1to30": ZERO, "days31to60": ZERO, "days61to90": ZERO, "days90plus": ZERO}
    for r in receivables:
        if not is_unpaid_debt(r):
            continue
        days = (today - r.due_date).days
        bucket = ("current" if days <= 0 else "days1to30" if days <= 30 else "days31to60" if days <= 60
                  else "days61to90" if days <= 90 else "days90plus")
        buckets[bucket] += money(r.amount_due)
    open_credits = -money_sum(r.amount_due for r in receivables if is_open_credit(r))
    return {
        "openTotal": as_number(sum(buckets.values(), ZERO)),
        "buckets": {key: as_number(value) for key, value in buckets.items()},
        "openCredits": as_number(open_credits),
        "filters": flt.echo(),
    }


def compute_cashflow(store: Any, flt: FinanceFilter | None = None) -> dict[str, Any]:
    """Cash view: what came in and went out in the period, with a row for every month.

    A bounded period lists each of its months, months without bookings as zero rows; an open
    period runs from the first to the last booking.
    """
    flt = flt or FinanceFilter()
    rows = booking_totals(store, flt, by=("month",))
    by_month = _by_month(rows)
    if rows or (flt.date_from and flt.date_to):
        known = sorted(by_month)
        first = flt.date_from or date.fromisoformat(known[0] + "-01")
        last = flt.date_to or date.fromisoformat(known[-1] + "-01")
        months = [month_key(m) for m in months_between(first, last)]
    else:
        months = []
    monthly = []
    for key in months:
        income, expense = _income(by_month.get(key, [])), _expense(by_month.get(key, []))
        monthly.append({"month": key, "income": as_number(income), "expense": as_number(expense),
                        "net": as_number(income - expense)})
    income, expense = _income(rows), _expense(rows)
    return {
        "incomeTotal": as_number(income),
        "expenseTotal": as_number(expense),
        "netTotal": as_number(income - expense),
        "monthly": monthly,
        "basis": "cash",
        "filters": flt.echo(),
    }


def period_months(flt: FinanceFilter, today: date) -> tuple[date, date]:
    """Whole calendar months of the filter's period; without one the twelve months up to this one."""
    last = month_start(flt.date_to or today)
    first = month_start(flt.date_from) if flt.date_from else add_months(last, -11)
    return first, last


def compute_period_result(store: Any, flt: FinanceFilter | None = None,
                          today: date | None = None) -> dict[str, Any]:
    """Period result (accrual) in whole months: rent due + other income - costs."""
    flt = flt or FinanceFilter()
    today = today or date.today()
    first, last = period_months(flt, today)
    months = months_between(first, last)
    applied = flt.with_period(first, month_end(last))
    rent = rent_due_by_month(store, applied, first, last)
    by_month = _by_month(booking_totals(store, applied, by=("month",)))
    monthly = []
    totals = {"rent_due": ZERO, "other_income": ZERO, "costs": ZERO, "result": ZERO, "unassigned_income": ZERO}
    for month in months:
        key = month_key(month)
        other, costs, unassigned = _other_flows(by_month.get(key, []))
        values = {"rent_due": rent.get(key, ZERO), "other_income": other, "costs": costs,
                  "result": rent.get(key, ZERO) + other - costs, "unassigned_income": unassigned}
        for name, value in values.items():
            totals[name] += value
        monthly.append({"month": key, **{name: as_number(value) for name, value in values.items()}})
    return {
        "monthly": monthly,
        "totals": {name: as_number(value) for name, value in totals.items()},
        "basis": "accrual",
        "filters": applied.echo(),
    }


def compute_contracts_expiring(
    *,
    contracts: list,
    days: int = 90,
    today: date | None = None,
) -> dict[str, Any]:
    today = today or date.today()
    threshold = today + timedelta(days=days)
    expiring = []
    for c in contracts:
        if c.end_date is None:
            continue
        if today <= c.end_date <= threshold:
            expiring.append({
                "contractId": c.id,
                "contractNumber": c.contract_number,
                "propertyId": c.property_id,
                "unitId": c.unit_id,
                "tenantId": c.tenant_id,
                "endDate": c.end_date.isoformat(),
                "daysRemaining": (c.end_date - today).days,
            })
    expiring.sort(key=lambda i: i["daysRemaining"])
    return {"windowDays": days, "count": len(expiring), "contracts": expiring}


def compute_maintenance_costs(store: Any, flt: FinanceFilter | None = None) -> dict[str, Any]:
    flt = flt or FinanceFilter()
    dims = Dimensions(store, flt)
    cases = [c for c in store.list_maintenance_cases() if dims.matches(c.property_id, c.unit_id)]
    by_cat: dict[str, Decimal] = defaultdict(lambda: ZERO)
    for c in cases:
        by_cat[c.category or "Unkategorisiert"] += money(c.estimated_cost)
    return {
        "openCases": sum(1 for c in cases if c.status in {"open", "in_progress"}),
        "totalEstimatedCost": as_number(sum(by_cat.values(), ZERO)),
        "categories": [{"category": name, "estimatedCost": as_number(value)} for name, value in sorted(by_cat.items())],
        "filters": flt.echo(),
    }


def current_balance(store: Any, flt: FinanceFilter, today: date) -> Decimal:
    """Opening balances of the accounts in scope plus every booking up to today.

    Opening balances belong to accounts, not to properties or units: below the portfolio the
    balance starts from the bookings alone.
    """
    opening = ZERO
    if not flt.below_portfolio:
        opening = money_sum(a.opening_balance for a in store.list_accounts()
                            if not flt.portfolio_id or a.portfolio_id == flt.portfolio_id)
    moved = sum((row.amount for row in booking_totals(store, flt.with_period(None, today))), ZERO)
    return opening + moved


def compute_liquidity_forecast(store: Any, flt: FinanceFilter | None = None, *, months: int = 12,
                               today: date | None = None) -> dict[str, Any]:
    """Forecast: the balance month by month from the rent the contracts will owe and averages.

    Income of a future month is the rent the matching contracts owe then (rent history, end
    dates, paid in full) plus the average other income; expenses are the average costs. The
    averages cover the last complete calendar months, at most twelve and none before the
    first booking; months without bookings count as zero.
    """
    flt = (flt or FinanceFilter()).with_period(None, None)     # the history and the future set the periods
    today = today or date.today()
    this_month = month_start(today)
    history_end = add_months(this_month, -1)
    history_start = add_months(this_month, -HISTORY_MONTHS)
    first = first_booking_date(store, flt)
    if first is not None:
        history_start = max(history_start, month_start(first))
    history = months_between(history_start, history_end) if history_start <= history_end else []
    other = costs = ZERO
    if history:
        rows = booking_totals(store, flt.with_period(history[0], month_end(history[-1])))
        other, costs, _ = _other_flows(rows)
    avg_other = cents(other / len(history)) if history else ZERO
    avg_costs = cents(costs / len(history)) if history else ZERO

    future_first, future_last = add_months(this_month, 1), add_months(this_month, months)
    rent = rent_due_by_month(store, flt, future_first, future_last)
    balance = start = current_balance(store, flt, today)
    forecast, income_total = [], ZERO
    for month in months_between(future_first, future_last):
        key = month_key(month)
        income = rent.get(key, ZERO) + avg_other
        balance += income - avg_costs
        income_total += income
        forecast.append({
            "month": key,
            "projected_rent": as_number(rent.get(key, ZERO)),
            "projected_other_income": as_number(avg_other),
            "projected_income": as_number(income),
            "projected_expense": as_number(avg_costs),
            "projected_balance": as_number(balance),
        })
    avg_income = cents(income_total / months) if months else ZERO
    return {
        "current_balance": as_number(start),
        "avg_monthly_income": as_number(avg_income),
        "avg_monthly_expense": as_number(avg_costs),
        "avg_monthly_net": as_number(avg_income - avg_costs),
        "forecast_months": months,
        "history_months": len(history),
        "forecast": forecast,
        "basis": "forecast",
        "filters": flt.echo(),
    }
