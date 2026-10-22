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
Every report takes the same filter (services.finance_ledger.FinanceFilter). With an owner in the
filter every amount counts with that owner's part on its day (services.ownership.OwnerView).
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import replace
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from ..domain.clock import local_today
from ..domain.lease_engine import LeaseEngine
from ..domain.money import ZERO, as_number, cents, money, money_sum
from ..domain.occupancy import NON_BILLABLE_STATUSES, unit_statuses_on
from .finance_ledger import (
    PRIVATE_SIDES,
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
from .ownership import OwnerView
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


def _withdrawn(rows: list[BookingTotal]) -> Decimal:
    """What the owners took out (withdrawals, distributions), as a positive amount."""
    return -sum((row.amount for row in rows if row.side == "withdrawal"), ZERO)


def _contributed(rows: list[BookingTotal]) -> Decimal:
    """What the owners put in from private means."""
    return sum((row.amount for row in rows if row.side == "contribution"), ZERO)


def _other_flows(rows: list[BookingTotal]) -> tuple[Decimal, Decimal, Decimal]:
    """(other income, costs, unassigned income) of bookings that do not settle a tenant's account.

    Tenant payments (and their returns and refunds) pay the rent due and are left out. Incoming
    money counts as other income only with an income category and without a unit: money for a
    unit or without any category may be rent that is not assigned yet (review list), so it is
    reported apart and kept out of the result.
    """
    other = costs = unassigned = ZERO
    for row in rows:
        if row.tenant or row.side in PRIVATE_SIDES:
            continue
        if row.side == "expense":
            costs -= row.amount
        elif row.classified and not row.unit:
            other += row.amount
        else:
            unassigned += row.amount
    return other, costs, unassigned


def other_claims_by_month(store: Any, flt: FinanceFilter) -> dict[str, Decimal]:
    """Claims of their own (receivable kind "other": damage, keys, …) per month of their due date.

    They are income the rent does not hold (R12-15). Their payments come from the tenant and are
    left out of the bookings' income, so nothing counts twice. Unmarked receivables may repeat a
    monthly rent and never count.
    """
    claims: dict[str, Decimal] = defaultdict(lambda: ZERO)
    view, contracts = OwnerView(store, flt), _contracts_by_id(store)
    for receivable in _receivables(store, flt):
        if receivable.kind == "other":
            claims[month_key(receivable.due_date)] += view.contract(
                contracts[receivable.contract_id], receivable.amount_due, receivable.due_date)
    return claims


def _by_month(rows: list[BookingTotal]) -> dict[str, list[BookingTotal]]:
    grouped: dict[str, list[BookingTotal]] = defaultdict(list)
    for row in rows:
        grouped[row.month or ""].append(row)
    return grouped


def rent_due_by_month(store: Any, flt: FinanceFilter, first: date, last: date) -> dict[str, Decimal]:
    """Rent the contracts owe in each month from *first* to *last* (their rent history, warm,
    move-in and move-out months by days); drafts owe nothing."""
    reads = CachedReads(store)
    dims, view = Dimensions(reads, flt), OwnerView(store, flt)
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
                # by the owners' days of the month: a sale on the 16th splits the month's rent
                due[month_key(line.period_start)] += view.contract_period(
                    contract, line.total_amount, line.period_start, line.period_end - timedelta(days=1))
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
    today = today or local_today()
    dims, view = Dimensions(store, flt), OwnerView(store, flt)
    contracts = _contracts_by_id(store)
    receivables = _receivables(store, flt)
    from .receivable_residuals import ResidualReader
    residual_reader = ResidualReader(store)
    # an owner's part of what is open, on the day each claim is due
    balances = {r.id: view.contract(contracts[r.contract_id], residual_reader.balance(r, today), r.due_date)
                for r in receivables}
    open_receivables = money_sum(max(balances[r.id], ZERO) for r in receivables)
    overdue_receivables = money_sum(max(balances[r.id], ZERO) for r in receivables if r.due_date < today or r.status == "overdue")
    open_credits = -money_sum(min(balances[r.id], ZERO) for r in receivables)
    total_bookings = sum((row.amount for row in booking_totals(store, flt)), ZERO)
    # invoices name a property (or nothing), never a unit
    invoices = [inv for inv in store.list_invoices()
                if not flt.unit_id and dims.matches(inv.property_id) and flt.in_period(inv.invoice_date)]
    invoices_total = money_sum(view.part(inv.gross_amount, inv.property_id, None, inv.invoice_date) for inv in invoices)
    maintenance = [c for c in store.list_maintenance_cases()
                   if dims.matches(c.property_id, c.unit_id) and view.owns(c.property_id, c.unit_id, today)]
    return {
        "totals": {
            # with an owner: what they hold a part of today
            "properties": sum(1 for p in store.list_properties()
                              if dims.property_record_matches(p) and view.owns(p.id, None, today)),
            "units": sum(1 for u in store.list_units()
                         if dims.unit_record_matches(u) and view.owns(u.property_id, u.id, today)),
            "contracts": sum(1 for c in contracts.values()
                             if dims.contract_matches(c) and view.owns(c.property_id, c.unit_id, today)),
        },
        "finance": {
            "bookingsTotal": as_number(total_bookings),
            "invoicesTotal": as_number(invoices_total),
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
    statuses = unit_statuses_on(today or local_today(), units, contracts)
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
    today = today or local_today()
    receivables = _receivables(store, flt)
    buckets = {"current": ZERO, "days1to30": ZERO, "days31to60": ZERO, "days61to90": ZERO, "days90plus": ZERO}
    from .receivable_residuals import ResidualReader
    residual_reader = ResidualReader(store)
    view, contracts = OwnerView(store, flt), _contracts_by_id(store)
    if view.active:     # only the claims the owner has a part of, each with that part
        receivables = [r for r in receivables if view.owns(contracts[r.contract_id].property_id,
                                                           contracts[r.contract_id].unit_id, r.due_date)]
    states = {r.id: residual_reader.read(r, today) for r in receivables}
    parts = {r.id: view.contract(contracts[r.contract_id], states[r.id]["residual"], r.due_date) for r in receivables}
    for r in receivables:
        amount = parts[r.id]
        if amount <= 0:
            continue
        days = (today - r.due_date).days
        bucket = ("current" if days <= 0 else "days1to30" if days <= 30 else "days31to60" if days <= 60
                  else "days61to90" if days <= 90 else "days90plus")
        buckets[bucket] += amount
    open_credits = -money_sum(min(part, ZERO) for part in parts.values())
    return {
        "openTotal": as_number(sum(buckets.values(), ZERO)),
        "buckets": {key: as_number(value) for key, value in buckets.items()},
        "openCredits": as_number(open_credits),
        "residuals": list(states.values()),
        "as_of": today.isoformat(),
        "filters": flt.echo(),
    }


def compute_cashflow(store: Any, flt: FinanceFilter | None = None, *, decimal_strings: bool = False) -> dict[str, Any]:
    """Cash view: what came in and went out in the period, with a row for every month.

    Income and expenses leave out the owners' own money; withdrawals (distributions) and
    contributions of private means are reported beside them.

    A bounded period lists each of its months, months without bookings as zero rows; an open
    period runs from the first to the last booking.

    Versioned exports request decimal strings, avoiding a float round trip of
    large cent totals. Existing callers retain their JSON-number contract.
    """
    flt = flt or FinanceFilter()
    number = str if decimal_strings else as_number
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
        month_rows = by_month.get(key, [])
        income, expense = _income(month_rows), _expense(month_rows)
        monthly.append({"month": key, "income": number(income), "expense": number(expense),
                        "net": number(income - expense), "withdrawal": number(_withdrawn(month_rows)),
                        "contribution": number(_contributed(month_rows))})
    income, expense = _income(rows), _expense(rows)
    return {
        "incomeTotal": number(income),
        "expenseTotal": number(expense),
        "netTotal": number(income - expense),
        # the owners' own money: it moves the balance, not the result (finance_ledger)
        "withdrawalTotal": number(_withdrawn(rows)),
        "contributionTotal": number(_contributed(rows)),
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
    today = today or local_today()
    first, last = period_months(flt, today)
    months = months_between(first, last)
    applied = flt.with_period(first, month_end(last))
    rent = rent_due_by_month(store, applied, first, last)
    by_month = _by_month(booking_totals(store, applied, by=("month",)))
    claims = other_claims_by_month(store, applied)
    monthly = []
    totals = {"rent_due": ZERO, "other_income": ZERO, "costs": ZERO, "result": ZERO, "unassigned_income": ZERO}
    for month in months:
        key = month_key(month)
        other, costs, unassigned = _other_flows(by_month.get(key, []))
        other += claims.get(key, ZERO)
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
    today = today or local_today()
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
    dims, view, today = Dimensions(store, flt), OwnerView(store, flt), local_today()
    cases = [c for c in store.list_maintenance_cases()
             if dims.matches(c.property_id, c.unit_id) and view.owns(c.property_id, c.unit_id, today)]
    by_cat: dict[str, Decimal] = defaultdict(lambda: ZERO)
    for c in cases:
        by_cat[c.category or "Unkategorisiert"] += view.part(c.estimated_cost, c.property_id, c.unit_id, today)
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
    today = today or local_today()
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


def compute_owner_results(store: Any, flt: FinanceFilter | None = None, today: date | None = None) -> dict[str, Any]:
    """Period result and owners' money per owner; the rows add up to the result of all owners.

    One row per owner (a contact of type owner) with a part in the period, and one for the part
    no owner is recorded for (services.ownership.NOBODY) when there is any.
    """
    from .ownership import NOBODY, owner_name

    flt = (flt or FinanceFilter()).without_owner()
    today = today or local_today()
    keys = ("rent_due", "other_income", "costs", "result", "unassigned_income")

    def figures(owner: str | None) -> dict[str, Decimal]:
        selected = replace(flt, owner_contact_id=owner)
        result = compute_period_result(store, selected, today)
        applied = selected.with_period(date.fromisoformat(result["filters"]["date_from"]),
                                       date.fromisoformat(result["filters"]["date_to"]))
        rows = booking_totals(store, applied)
        values = {key: money(result["totals"][key]) for key in keys}
        values["withdrawal"], values["contribution"] = _withdrawn(rows), _contributed(rows)
        return values

    whole = figures(None)
    # also a contact named by a share or booking whose type was changed since: its money has a row
    named = {s.owner_contact_id for s in store.list_ownership_shares()}
    named |= {b.owner_contact_id for b in store.list_bookings() if getattr(b, "owner_contact_id", None)}
    owners = sorted((c for c in store.list_contacts() if c.contact_type == "owner" or c.id in named),
                    key=lambda c: (owner_name(c).lower(), c.id))
    rows, added = [], {key: ZERO for key in whole}
    for owner, name in [(c.id, owner_name(c)) for c in owners] + [(NOBODY, "Ohne Eigentümer")]:
        values = figures(owner)
        if not any(values.values()):
            continue
        for key, value in values.items():
            added[key] += value
        rows.append({"owner_contact_id": owner, "name": name, **{key: as_number(v) for key, v in values.items()}})
    if added != whole:      # every amount is split to the cent among all owners: this never happens
        raise RuntimeError("Die Ergebnisse je Eigentümer ergeben nicht das Gesamtergebnis.")
    return {"owners": rows, "totals": {key: as_number(value) for key, value in whole.items()},
            "basis": "accrual", "filters": compute_period_result(store, flt, today)["filters"]}
