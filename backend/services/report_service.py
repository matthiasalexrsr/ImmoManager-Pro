"""Centralised report / analytics computation.

All financial calculations live here so they can be tested in isolation
and shared across routers, scheduled jobs, and export pipelines.
"""

from __future__ import annotations

from calendar import monthrange
from collections import defaultdict
from datetime import date, timedelta
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

def compute_summary(
    *,
    properties: list,
    units: list,
    contracts: list,
    receivables: list,
    bookings: list,
    invoices: list,
    maintenance_cases: list,
) -> dict[str, Any]:
    open_receivables = sum(
        r.amount_due for r in receivables if r.status in {"open", "overdue"}
    )
    overdue_receivables = sum(
        r.amount_due for r in receivables if r.status == "overdue"
    )
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
) -> dict[str, Any]:
    today = today or date.today()
    buckets = {
        "current": 0.0,
        "days1to30": 0.0,
        "days31to60": 0.0,
        "days61to90": 0.0,
        "days90plus": 0.0,
    }
    open_total = 0.0

    for r in receivables:
        if r.status not in {"open", "overdue"}:
            continue
        open_total += r.amount_due
        days = (today - r.due_date).days
        if days <= 0:
            buckets["current"] += r.amount_due
        elif days <= 30:
            buckets["days1to30"] += r.amount_due
        elif days <= 60:
            buckets["days31to60"] += r.amount_due
        elif days <= 90:
            buckets["days61to90"] += r.amount_due
        else:
            buckets["days90plus"] += r.amount_due

    return {"openTotal": open_total, "buckets": buckets}


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
    bookings: list,
    months: int = 12,
    today: date | None = None,
) -> dict[str, Any]:
    """Project balance forward using calendar-aware month arithmetic."""
    today = today or date.today()
    cutoff = today - timedelta(days=365)
    recent = [b for b in bookings if b.booking_date >= cutoff]

    monthly_income: dict[str, float] = defaultdict(float)
    monthly_expense: dict[str, float] = defaultdict(float)
    for b in recent:
        key = f"{b.booking_date.year}-{b.booking_date.month:02d}"
        if b.amount > 0:
            monthly_income[key] += b.amount
        else:
            monthly_expense[key] += abs(b.amount)

    n_months = max(len(monthly_income), 1)
    avg_income = sum(monthly_income.values()) / n_months
    avg_expense = sum(monthly_expense.values()) / n_months
    current_balance = sum(b.amount for b in bookings)

    forecast = []
    balance = current_balance
    for i in range(1, months + 1):
        month_date = _add_months(today, i)
        balance += avg_income - avg_expense
        forecast.append({
            "month": f"{month_date.year}-{month_date.month:02d}",
            "projected_income": round(avg_income, 2),
            "projected_expense": round(avg_expense, 2),
            "projected_balance": round(balance, 2),
        })

    return {
        "current_balance": round(current_balance, 2),
        "avg_monthly_income": round(avg_income, 2),
        "avg_monthly_expense": round(avg_expense, 2),
        "avg_monthly_net": round(avg_income - avg_expense, 2),
        "forecast_months": months,
        "forecast": forecast,
    }
