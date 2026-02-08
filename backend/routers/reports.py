from datetime import date, timedelta

from fastapi import APIRouter

from ..routers.portfolios import store

router = APIRouter(prefix="/reports", tags=["Berichte"])


@router.get("/summary")
def get_summary() -> dict:
    total_properties = len(store.properties)
    total_units = len(store.units)
    total_contracts = len(store.contracts)
    open_receivables = sum(
        receivable.amount_due
        for receivable in store.receivables.values()
        if receivable.status in {"open", "overdue"}
    )
    overdue_receivables = sum(
        receivable.amount_due
        for receivable in store.receivables.values()
        if receivable.status == "overdue"
    )
    total_bookings = sum(booking.amount for booking in store.bookings.values())
    total_invoices = sum(invoice.gross_amount for invoice in store.invoices.values())
    open_maintenance_cases = sum(
        1 for case in store.maintenance_cases.values() if case.status in {"open", "in_progress"}
    )

    return {
        "totals": {
            "properties": total_properties,
            "units": total_units,
            "contracts": total_contracts,
        },
        "finance": {
            "bookingsTotal": total_bookings,
            "invoicesTotal": total_invoices,
            "openReceivables": open_receivables,
            "overdueReceivables": overdue_receivables,
        },
        "maintenance": {
            "openCases": open_maintenance_cases,
        },
    }


@router.get("/finance")
def get_finance_report() -> dict:
    categories = {category.id: category for category in store.categories.values()}
    totals_by_category = {}
    uncategorized_total = 0.0

    for booking in store.bookings.values():
        if booking.category_id and booking.category_id in categories:
            category = categories[booking.category_id]
            entry = totals_by_category.setdefault(
                booking.category_id,
                {
                    "categoryId": booking.category_id,
                    "categoryName": category.name,
                    "categoryType": category.category_type,
                    "total": 0.0,
                },
            )
            entry["total"] += booking.amount
        else:
            uncategorized_total += booking.amount

    totals = sorted(totals_by_category.values(), key=lambda item: item["categoryName"])

    return {
        "totalsByCategory": totals,
        "uncategorizedTotal": uncategorized_total,
        "bookingsTotal": sum(booking.amount for booking in store.bookings.values()),
    }


@router.get("/occupancy")
def get_occupancy_report() -> dict:
    total_units = len(store.units)
    rented_units = sum(1 for unit in store.units.values() if unit.status == "rented")
    occupancy_rate = (rented_units / total_units) if total_units else 0.0

    return {
        "totalUnits": total_units,
        "rentedUnits": rented_units,
        "occupancyRate": occupancy_rate,
    }


@router.get("/receivables-aging")
def get_receivables_aging() -> dict:
    today = date.today()
    buckets = {
        "current": 0.0,
        "days1to30": 0.0,
        "days31to60": 0.0,
        "days61to90": 0.0,
        "days90plus": 0.0,
    }
    open_total = 0.0

    for receivable in store.receivables.values():
        if receivable.status not in {"open", "overdue"}:
            continue
        open_total += receivable.amount_due
        days_overdue = (today - receivable.due_date).days
        if days_overdue <= 0:
            buckets["current"] += receivable.amount_due
        elif days_overdue <= 30:
            buckets["days1to30"] += receivable.amount_due
        elif days_overdue <= 60:
            buckets["days31to60"] += receivable.amount_due
        elif days_overdue <= 90:
            buckets["days61to90"] += receivable.amount_due
        else:
            buckets["days90plus"] += receivable.amount_due

    return {
        "openTotal": open_total,
        "buckets": buckets,
    }


@router.get("/cashflow")
def get_cashflow_report() -> dict:
    income = sum(
        booking.amount
        for booking in store.bookings.values()
        if booking.amount >= 0
    )
    expenses = sum(
        -booking.amount
        for booking in store.bookings.values()
        if booking.amount < 0
    )
    net = income - expenses

    return {
        "incomeTotal": income,
        "expenseTotal": expenses,
        "netTotal": net,
    }


@router.get("/contracts-expiring")
def get_contracts_expiring_report(days: int = 90) -> dict:
    if days <= 0:
        days = 90

    today = date.today()
    threshold = today + timedelta(days=days)

    expiring = []
    for contract in store.contracts.values():
        if contract.end_date is None:
            continue
        if today <= contract.end_date <= threshold:
            expiring.append(
                {
                    "contractId": contract.id,
                    "contractNumber": contract.contract_number,
                    "propertyId": contract.property_id,
                    "unitId": contract.unit_id,
                    "tenantId": contract.tenant_id,
                    "endDate": contract.end_date.isoformat(),
                    "daysRemaining": (contract.end_date - today).days,
                }
            )

    expiring.sort(key=lambda item: item["daysRemaining"])

    return {
        "windowDays": days,
        "count": len(expiring),
        "contracts": expiring,
    }


@router.get("/maintenance-costs")
def get_maintenance_costs_report() -> dict:
    total_estimated_cost = 0.0
    by_category = {}
    open_cases = 0

    for case in store.maintenance_cases.values():
        if case.status in {"open", "in_progress"}:
            open_cases += 1
        amount = case.estimated_cost or 0.0
        total_estimated_cost += amount
        category_name = case.category or "Unkategorisiert"
        by_category[category_name] = by_category.get(category_name, 0.0) + amount

    categories = [
        {"category": name, "estimatedCost": value}
        for name, value in sorted(by_category.items(), key=lambda item: item[0])
    ]

    return {
        "openCases": open_cases,
        "totalEstimatedCost": total_estimated_cost,
        "categories": categories,
    }
