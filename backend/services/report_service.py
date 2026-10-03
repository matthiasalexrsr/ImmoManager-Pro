"""Centralised report / analytics computation.

All financial calculations live here so they can be tested in isolation
and shared across routers, scheduled jobs, and export pipelines.
"""

from __future__ import annotations

from calendar import monthrange
from collections.abc import Iterable
from datetime import date, timedelta
from decimal import Decimal, localcontext
from typing import Any

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _add_months(d: date, months: int) -> date:
    """Advance *d* by *months* calendar months (handles month-end correctly)."""
    month = d.month - 1 + months
    year = d.year + month // 12
    month = month % 12 + 1
    day = min(d.day, monthrange(year, month)[1])
    return d.replace(year=year, month=month, day=day)


# ---------------------------------------------------------------------------
# Report computations — each accepts pre-fetched entity lists
# ---------------------------------------------------------------------------


def _open_obligations(receivables: list, rent_charges: list):
    from .payments import payment_total

    for entity_type, targets in (("receivable", receivables), ("rent_charge", rent_charges)):
        for target in targets:
            if target.status in {"cancelled", "void"}:
                continue
            remaining = payment_total("rent_charge" if entity_type == "rent_charge" else "receivable", target) - Decimal(str(getattr(target, "amount_paid", 0) or 0))
            if remaining <= 0:
                continue
            due = date.fromisoformat(f"{target.month}-03") if entity_type == "rent_charge" else target.due_date
            yield {"entity_type": entity_type, "remaining": remaining.quantize(Decimal("0.01")), "due_date": due}

def compute_summary(
    *,
    properties: list,
    units: list,
    contracts: list,
    receivables: list,
    bookings: list,
    invoices: list,
    maintenance_cases: list,
    rent_charges: list | None = None,
) -> dict[str, Any]:
    obligations = list(_open_obligations(receivables, rent_charges or []))
    open_receivables = float(sum((item["remaining"] for item in obligations), Decimal("0")))
    overdue_receivables = float(sum((item["remaining"] for item in obligations if item["due_date"] < date.today()), Decimal("0")))
    total_bookings = sum(b.amount for b in bookings)
    total_invoices = sum(inv.gross_amount for inv in invoices)
    open_maintenance = sum(
        1 for c in maintenance_cases if c.status in {"open", "in_progress"}
    )
    return {
        "totals": {
            "properties": len(properties),
            "units": len(units),
            "contracts": len(contracts),
        },
        "finance": {
            "bookingsTotal": total_bookings,
            "invoicesTotal": total_invoices,
            "openReceivables": open_receivables,
            "overdueReceivables": overdue_receivables,
            "openRentCharges": float(sum((item["remaining"] for item in obligations if item["entity_type"] == "rent_charge"), Decimal("0"))),
            "openOtherReceivables": float(sum((item["remaining"] for item in obligations if item["entity_type"] == "receivable"), Decimal("0"))),
        },
        "maintenance": {
            "openCases": open_maintenance,
        },
    }


def compute_finance(
    *,
    bookings: list,
    categories: list,
) -> dict[str, Any]:
    cat_map = {c.id: c for c in categories}
    totals_by_category: dict[str, dict] = {}
    uncategorized_total = 0.0

    for b in bookings:
        if b.category_id and b.category_id in cat_map:
            cat = cat_map[b.category_id]
            entry = totals_by_category.setdefault(
                b.category_id,
                {
                    "categoryId": b.category_id,
                    "categoryName": cat.name,
                    "categoryType": cat.category_type,
                    "total": 0.0,
                },
            )
            entry["total"] += b.amount
        else:
            uncategorized_total += b.amount

    totals = sorted(totals_by_category.values(), key=lambda i: i["categoryName"])
    return {
        "totalsByCategory": totals,
        "uncategorizedTotal": uncategorized_total,
        "bookingsTotal": sum(b.amount for b in bookings),
    }


def compute_occupancy(*, units: list) -> dict[str, Any]:
    total = len(units)
    rented = sum(1 for u in units if u.status == "occupied")
    rate = (rented / total) if total else 0.0
    return {
        "totalUnits": total,
        "rentedUnits": rented,
        "occupancyRate": rate,
    }


def compute_receivables_aging(
    *,
    receivables: list,
    today: date | None = None,
    rent_charges: list | None = None,
) -> dict[str, Any]:
    today = today or date.today()
    buckets = {
        "current": Decimal("0"),
        "days1to30": Decimal("0"),
        "days31to60": Decimal("0"),
        "days61to90": Decimal("0"),
        "days90plus": Decimal("0"),
    }
    open_total = Decimal("0")

    for item in _open_obligations(receivables, rent_charges or []):
        remaining = item["remaining"]
        open_total += remaining
        days = (today - item["due_date"]).days
        if days <= 0:
            buckets["current"] += remaining
        elif days <= 30:
            buckets["days1to30"] += remaining
        elif days <= 60:
            buckets["days31to60"] += remaining
        elif days <= 90:
            buckets["days61to90"] += remaining
        else:
            buckets["days90plus"] += remaining

    return {"openTotal": float(open_total), "buckets": {key: float(value) for key, value in buckets.items()},
            "source": "monthly_rent_and_other_receivables"}


def compute_cashflow(*, bookings: list) -> dict[str, Any]:
    income = sum(b.amount for b in bookings if b.amount >= 0)
    expenses = sum(-b.amount for b in bookings if b.amount < 0)
    return {
        "incomeTotal": income,
        "expenseTotal": expenses,
        "netTotal": income - expenses,
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


def compute_maintenance_costs(*, maintenance_cases: list) -> dict[str, Any]:
    total = 0.0
    by_cat: dict[str, float] = {}
    open_cases = 0

    for c in maintenance_cases:
        if c.status in {"open", "in_progress"}:
            open_cases += 1
        amt = c.estimated_cost or 0.0
        total += amt
        cat = c.category or "Unkategorisiert"
        by_cat[cat] = by_cat.get(cat, 0.0) + amt

    categories_list = [
        {"category": name, "estimatedCost": val}
        for name, val in sorted(by_cat.items())
    ]
    return {
        "openCases": open_cases,
        "totalEstimatedCost": total,
        "categories": categories_list,
    }


def compute_liquidity_forecast(
    *,
    bookings: Iterable[Any],
    months: int = 12,
    today: date | None = None,
    starting_balance: str | None = None,
) -> dict[str, Any]:
    """Explicit historical scenario using twelve complete months, including zeros."""
    from .financial_cash import cents

    today = today or date.today()
    if type(months) is not int or months < 1 or months > (9999 - today.year) * 12 + 12 - today.month:
        raise ValueError("Der Prognosezeitraum liegt außerhalb des darstellbaren Kalenders.")
    current_month = today.replace(day=1)
    cutoff = _add_months(current_month, -12)
    income, expense, total = 0, 0, 0
    for booking in bookings:
        if booking.booking_date > today or getattr(booking, "status", "confirmed") in {"cancelled", "void"}:
            continue
        amount = cents(booking.amount)
        total += amount
        if cutoff <= booking.booking_date < current_month:
            income += max(amount, 0)
            expense += max(-amount, 0)
    initial = cents(starting_balance) if starting_balance is not None else total
    with localcontext() as context:
        context.prec = max(34, len(str(abs(initial))) + len(str(months)) + 16)
        average_income, average_expense = Decimal(income) / 1200, Decimal(expense) / 1200
        balance = Decimal(initial) / 100
        forecast = []
        def rounded(value):
            return format(value.quantize(Decimal(".01")), ".2f")
        for index in range(1, months + 1):
            day = _add_months(current_month, index)
            balance += average_income - average_expense
            precise = {"income": rounded(average_income), "expense": rounded(average_expense), "balance": rounded(balance)}
            forecast.append({"month": f"{day.year:04d}-{day.month:02d}", "projected_income": float(precise["income"]),
                "projected_expense": float(precise["expense"]), "projected_balance": float(precise["balance"]), "exact": precise})
        exact = {"current_balance": rounded(Decimal(initial) / 100), "avg_monthly_income": rounded(average_income),
                 "avg_monthly_expense": rounded(average_expense), "avg_monthly_net": rounded(average_income - average_expense)}
    return {**{key: float(value) for key, value in exact.items()}, "exact": exact, "currency": "EUR", "forecast_months": months,
        "forecast": forecast, "scenario": "twelve_completed_calendar_month_average", "history_months": 12,
        "history_from": cutoff.isoformat(), "history_until": current_month.isoformat(), "as_of": today.isoformat(),
        "balance_basis": "explicit_scenario_start" if starting_balance is not None else "stored_bookings_without_undated_opening",
        "opening_balance_included": False}
