import csv
import io
from datetime import date, timedelta

from fastapi import APIRouter, Body, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from ..dependencies import store

router = APIRouter(prefix="/reports", tags=["Berichte"])


def _csv_response(rows: list[dict], filename: str) -> StreamingResponse:
    """Build a CSV StreamingResponse from a list of dicts."""
    if not rows:
        output = io.StringIO("")
    else:
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=rows[0].keys(), delimiter=";")
        writer.writeheader()
        writer.writerows(rows)
    output.seek(0)
    return StreamingResponse(
        output,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/summary")
def get_summary(format: str | None = Query(None, alias="format")):
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

    data = {
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

    if format == "csv":
        rows = [{
            "Immobilien": total_properties,
            "Einheiten": total_units,
            "Verträge": total_contracts,
            "Buchungen Gesamt": total_bookings,
            "Rechnungen Gesamt": total_invoices,
            "Offene Forderungen": open_receivables,
            "Überfällige Forderungen": overdue_receivables,
            "Offene Wartungsfälle": open_maintenance_cases,
        }]
        return _csv_response(rows, "zusammenfassung.csv")

    return data


@router.get("/finance")
def get_finance_report(format: str | None = Query(None, alias="format")):
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

    if format == "csv":
        rows = [
            {"Kategorie": t["categoryName"], "Typ": t["categoryType"], "Betrag": t["total"]}
            for t in totals
        ]
        if uncategorized_total:
            rows.append({"Kategorie": "Unkategorisiert", "Typ": "-", "Betrag": uncategorized_total})
        return _csv_response(rows, "finanzbericht.csv")

    return {
        "totalsByCategory": totals,
        "uncategorizedTotal": uncategorized_total,
        "bookingsTotal": sum(booking.amount for booking in store.bookings.values()),
    }


@router.get("/occupancy")
def get_occupancy_report(format: str | None = Query(None, alias="format")):
    total_units = len(store.units)
    rented_units = sum(1 for unit in store.units.values() if unit.status == "rented")
    occupancy_rate = (rented_units / total_units) if total_units else 0.0

    if format == "csv":
        rows = [{
            "Einheiten Gesamt": total_units,
            "Vermietet": rented_units,
            "Leerstandsquote": f"{(1 - occupancy_rate) * 100:.1f}%",
            "Belegungsquote": f"{occupancy_rate * 100:.1f}%",
        }]
        return _csv_response(rows, "belegungsquote.csv")

    return {
        "totalUnits": total_units,
        "rentedUnits": rented_units,
        "occupancyRate": occupancy_rate,
    }


@router.get("/receivables-aging")
def get_receivables_aging(format: str | None = Query(None, alias="format")):
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

    if format == "csv":
        rows = [{
            "Aktuell": buckets["current"],
            "1-30 Tage": buckets["days1to30"],
            "31-60 Tage": buckets["days31to60"],
            "61-90 Tage": buckets["days61to90"],
            "90+ Tage": buckets["days90plus"],
            "Gesamt": open_total,
        }]
        return _csv_response(rows, "forderungsalter.csv")

    return {
        "openTotal": open_total,
        "buckets": buckets,
    }


@router.get("/cashflow")
def get_cashflow_report(format: str | None = Query(None, alias="format")):
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

    if format == "csv":
        rows = [{
            "Einnahmen": income,
            "Ausgaben": expenses,
            "Netto": net,
        }]
        return _csv_response(rows, "cashflow.csv")

    return {
        "incomeTotal": income,
        "expenseTotal": expenses,
        "netTotal": net,
    }


@router.get("/contracts-expiring")
def get_contracts_expiring_report(
    days: int = 90,
    format: str | None = Query(None, alias="format"),
):
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

    if format == "csv":
        rows = [
            {
                "Vertragsnr.": c["contractNumber"],
                "Enddatum": c["endDate"],
                "Tage verbleibend": c["daysRemaining"],
                "Vertrags-ID": c["contractId"],
            }
            for c in expiring
        ]
        return _csv_response(rows, "auslaufende_vertraege.csv")

    return {
        "windowDays": days,
        "count": len(expiring),
        "contracts": expiring,
    }


@router.get("/maintenance-costs")
def get_maintenance_costs_report(format: str | None = Query(None, alias="format")):
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

    categories_list = [
        {"category": name, "estimatedCost": value}
        for name, value in sorted(by_category.items(), key=lambda item: item[0])
    ]

    if format == "csv":
        rows = [
            {"Kategorie": c["category"], "Geschätzte Kosten": c["estimatedCost"]}
            for c in categories_list
        ]
        return _csv_response(rows, "instandhaltungskosten.csv")

    return {
        "openCases": open_cases,
        "totalEstimatedCost": total_estimated_cost,
        "categories": categories_list,
    }


# ---------------------------------------------------------------------------
# Phase 6.2: DATEV Export
# ---------------------------------------------------------------------------

@router.get("/datev-export")
def datev_export(
    start_date: date | None = Query(None),
    end_date: date | None = Query(None),
) -> StreamingResponse:
    """Export bookings in DATEV-compliant CSV format (Buchungsstapel).

    DATEV Buchungsstapel format uses semicolons, German number formatting,
    and specific column headers recognized by DATEV accounting software.
    """
    bookings = list(store.bookings.values())

    if start_date:
        bookings = [b for b in bookings if b.booking_date >= start_date]
    if end_date:
        bookings = [b for b in bookings if b.booking_date <= end_date]

    bookings.sort(key=lambda b: b.booking_date)

    # DATEV Buchungsstapel columns (simplified)
    output = io.StringIO()
    writer = csv.writer(output, delimiter=";", quoting=csv.QUOTE_MINIMAL)

    # Header row
    writer.writerow([
        "Umsatz (ohne Soll/Haben-Kz)",
        "Soll/Haben-Kennzeichen",
        "WKZ Umsatz",
        "Konto",
        "Gegenkonto (ohne BU-Schlüssel)",
        "BU-Schlüssel",
        "Belegdatum",
        "Belegfeld 1",
        "Buchungstext",
    ])

    accounts = {acc.id: acc for acc in store.accounts.values()}
    categories = {cat.id: cat for cat in store.categories.values()}

    for booking in bookings:
        amount = abs(booking.amount)
        # S = Soll (debit), H = Haben (credit)
        soll_haben = "S" if booking.amount >= 0 else "H"
        # Format amount with comma as decimal separator (German)
        amount_str = f"{amount:.2f}".replace(".", ",")
        # DATEV date format: DDMM
        beleg_datum = booking.booking_date.strftime("%d%m")
        # Account info
        konto = accounts.get(booking.account_id, None)
        konto_name = konto.name if konto else booking.account_id
        # Category as Gegenkonto
        gegen_konto = ""
        if booking.category_id and booking.category_id in categories:
            gegen_konto = categories[booking.category_id].name

        writer.writerow([
            amount_str,
            soll_haben,
            "EUR",
            konto_name,
            gegen_konto,
            "",
            beleg_datum,
            booking.id[:8],
            booking.payment_text or "",
        ])

    output.seek(0)
    return StreamingResponse(
        output,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="EXTF_Buchungsstapel.csv"'},
    )


# ---------------------------------------------------------------------------
# Phase 6.3: Bank Statement Import
# ---------------------------------------------------------------------------

class ImportBookingsRequest(BaseModel):
    account_id: str
    csv_content: str = Field(..., description="CSV content with columns: date;amount;text")


@router.post("/bookings/import")
def import_bookings(
    account_id: str | None = None,
    csv_content: str | None = None,
    payload: ImportBookingsRequest | None = Body(None),
) -> dict:
    """Import bookings from CSV data.

    Accepts either a JSON body with account_id and csv_content,
    or keyword arguments (for backward compatibility).

    Expected CSV format (semicolon-separated):
    date;amount;text
    2024-01-15;-500.00;Handwerker Rechnung
    2024-01-20;800.00;Miete Wohnung 1
    """
    # Support both body and direct keyword arguments
    _account_id = account_id if account_id is not None else (payload.account_id if payload else None)
    _csv_content = csv_content if csv_content is not None else (payload.csv_content if payload else None)

    if not _account_id or not _csv_content:
        from fastapi import HTTPException
        raise HTTPException(status_code=422, detail="account_id and csv_content are required")

    reader = csv.DictReader(io.StringIO(_csv_content), delimiter=";")
    imported = []
    errors = []

    from ..models import BookingCreate

    for i, row in enumerate(reader, start=1):
        try:
            booking_date = date.fromisoformat(row["date"].strip())
            amount = float(row["amount"].strip().replace(",", "."))
            text = row.get("text", "").strip()

            booking = store.create_booking(BookingCreate(
                account_id=_account_id,
                booking_date=booking_date,
                amount=amount,
                payment_text=text,
            ))
            imported.append({"row": i, "bookingId": booking.id})
        except Exception as e:
            errors.append({"row": i, "error": str(e)})

    return {
        "imported": len(imported),
        "errors": len(errors),
        "details": {"imported": imported, "errors": errors},
    }
