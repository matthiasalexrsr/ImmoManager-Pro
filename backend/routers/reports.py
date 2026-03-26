import csv
import io
from datetime import date

from fastapi import APIRouter, Body, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from ..dependencies import store
from ..services import report_service

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
    data = report_service.compute_summary(
        properties=store.list_properties(),
        units=store.list_units(),
        contracts=store.list_contracts(),
        receivables=store.list_receivables(),
        bookings=store.list_bookings(),
        invoices=store.list_invoices(),
        maintenance_cases=store.list_maintenance_cases(),
    )

    if format == "csv":
        f = data["finance"]
        rows = [{
            "Immobilien": data["totals"]["properties"],
            "Einheiten": data["totals"]["units"],
            "Verträge": data["totals"]["contracts"],
            "Buchungen Gesamt": f["bookingsTotal"],
            "Rechnungen Gesamt": f["invoicesTotal"],
            "Offene Forderungen": f["openReceivables"],
            "Überfällige Forderungen": f["overdueReceivables"],
            "Offene Wartungsfälle": data["maintenance"]["openCases"],
        }]
        return _csv_response(rows, "zusammenfassung.csv")

    return data


@router.get("/finance")
def get_finance_report(format: str | None = Query(None, alias="format")):
    data = report_service.compute_finance(
        bookings=store.list_bookings(),
        categories=store.list_categories(),
    )

    if format == "csv":
        rows = [
            {"Kategorie": t["categoryName"], "Typ": t["categoryType"], "Betrag": t["total"]}
            for t in data["totalsByCategory"]
        ]
        if data["uncategorizedTotal"]:
            rows.append({"Kategorie": "Unkategorisiert", "Typ": "-", "Betrag": data["uncategorizedTotal"]})
        return _csv_response(rows, "finanzbericht.csv")

    return data


@router.get("/occupancy")
def get_occupancy_report(format: str | None = Query(None, alias="format")):
    data = report_service.compute_occupancy(units=store.list_units())

    if format == "csv":
        rate = data["occupancyRate"]
        rows = [{
            "Einheiten Gesamt": data["totalUnits"],
            "Vermietet": data["rentedUnits"],
            "Leerstandsquote": f"{(1 - rate) * 100:.1f}%",
            "Belegungsquote": f"{rate * 100:.1f}%",
        }]
        return _csv_response(rows, "belegungsquote.csv")

    return data


@router.get("/receivables-aging")
def get_receivables_aging(format: str | None = Query(None, alias="format")):
    data = report_service.compute_receivables_aging(
        receivables=store.list_receivables(),
    )

    if format == "csv":
        b = data["buckets"]
        rows = [{
            "Aktuell": b["current"],
            "1-30 Tage": b["days1to30"],
            "31-60 Tage": b["days31to60"],
            "61-90 Tage": b["days61to90"],
            "90+ Tage": b["days90plus"],
            "Gesamt": data["openTotal"],
        }]
        return _csv_response(rows, "forderungsalter.csv")

    return data


@router.get("/cashflow")
def get_cashflow_report(format: str | None = Query(None, alias="format")):
    data = report_service.compute_cashflow(bookings=store.list_bookings())

    if format == "csv":
        rows = [{
            "Einnahmen": data["incomeTotal"],
            "Ausgaben": data["expenseTotal"],
            "Netto": data["netTotal"],
        }]
        return _csv_response(rows, "cashflow.csv")

    return data


@router.get("/contracts-expiring")
def get_contracts_expiring_report(
    days: int = 90,
    format: str | None = Query(None, alias="format"),
):
    if days <= 0:
        days = 90

    data = report_service.compute_contracts_expiring(
        contracts=store.list_contracts(),
        days=days,
    )

    if format == "csv":
        rows = [
            {
                "Vertragsnr.": c["contractNumber"],
                "Enddatum": c["endDate"],
                "Tage verbleibend": c["daysRemaining"],
                "Vertrags-ID": c["contractId"],
            }
            for c in data["contracts"]
        ]
        return _csv_response(rows, "auslaufende_vertraege.csv")

    return data


@router.get("/maintenance-costs")
def get_maintenance_costs_report(format: str | None = Query(None, alias="format")):
    data = report_service.compute_maintenance_costs(
        maintenance_cases=store.list_maintenance_cases(),
    )

    if format == "csv":
        rows = [
            {"Kategorie": c["category"], "Geschätzte Kosten": c["estimatedCost"]}
            for c in data["categories"]
        ]
        return _csv_response(rows, "instandhaltungskosten.csv")

    return data


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
    bookings = store.list_bookings()

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

    accounts = {acc.id: acc for acc in store.list_accounts()}
    categories = {cat.id: cat for cat in store.list_categories()}

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


@router.get("/liquidity-forecast", response_model=None)
def liquidity_forecast(
    months: int = Query(12, ge=1, le=60),
    property_id: str | None = Query(None),
):
    """T28: Liquidity forecast for 3/6/12 months based on historical data."""
    bookings = store.list_bookings()
    if property_id:
        bookings = [b for b in bookings if b.property_id == property_id]

    return report_service.compute_liquidity_forecast(
        bookings=bookings,
        months=months,
    )


@router.get("/pdf/{report_name}", response_model=None)
def export_report_pdf(report_name: str):
    """T8: Export a report as PDF.

    Uses simple text-based PDF generation.
    Supported reports: summary, finance, occupancy, cashflow.
    """

    valid_reports = ["summary", "finance", "occupancy", "cashflow", "receivables-aging"]
    if report_name not in valid_reports:
        raise HTTPException(
            status_code=400,
            detail=f"Ungültiger Report. Erlaubt: {', '.join(valid_reports)}",
        )

    # Get report data
    if report_name == "summary":
        data = get_summary()
    elif report_name == "finance":
        data = get_finance_report()
    elif report_name == "occupancy":
        data = get_occupancy_report()
    elif report_name == "cashflow":
        data = get_cashflow_report()
    elif report_name == "receivables-aging":
        data = get_receivables_aging()
    else:
        data = {}

    # Generate simple text-based PDF
    lines = [
        f"ImmoManager Pro - {report_name.replace('-', ' ').title()}",
        f"Erstellt am: {date.today().isoformat()}",
        "=" * 60,
        "",
    ]

    def _flatten(obj, prefix=""):
        if isinstance(obj, dict):
            for k, v in obj.items():
                _flatten(v, f"{prefix}{k}: " if not prefix else f"{prefix}.{k}: ")
        elif isinstance(obj, list):
            for i, item in enumerate(obj):
                _flatten(item, f"{prefix}[{i}] ")
        else:
            lines.append(f"{prefix}{obj}")

    _flatten(data)
    text_content = "\n".join(lines)

    # Try to use reportlab for real PDF
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.pdfgen import canvas

        buf = io.BytesIO()
        c = canvas.Canvas(buf, pagesize=A4)
        width, height = A4
        y = height - 50
        c.setFont("Helvetica-Bold", 16)
        c.drawString(50, y, f"ImmoManager Pro - {report_name.replace('-', ' ').title()}")
        y -= 25
        c.setFont("Helvetica", 10)
        c.drawString(50, y, f"Erstellt am: {date.today().isoformat()}")
        y -= 20
        c.line(50, y, width - 50, y)
        y -= 15
        c.setFont("Helvetica", 9)
        for line in text_content.split("\n")[3:]:  # Skip header
            if y < 50:
                c.showPage()
                y = height - 50
                c.setFont("Helvetica", 9)
            c.drawString(50, y, line[:100])  # Truncate long lines
            y -= 12
        c.save()
        buf.seek(0)
        return StreamingResponse(
            buf,
            media_type="application/pdf",
            headers={"Content-Disposition": f"attachment; filename={report_name}.pdf"},
        )
    except ImportError:
        # Fallback: return as plain text with PDF-like header
        buf = io.BytesIO(text_content.encode("utf-8"))
        return StreamingResponse(
            buf,
            media_type="text/plain",
            headers={"Content-Disposition": f"attachment; filename={report_name}.txt",
                     "X-PDF-Fallback": "reportlab not installed"},
        )
