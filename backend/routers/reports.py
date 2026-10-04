import csv
import io
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from typing import Annotated, Any
from urllib.parse import urlencode

from fastapi import APIRouter, Body, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from ..dependencies import store
from ..services import financial_cash, report_service

router = APIRouter(prefix="/reports", tags=["Berichte"])


def _cash_source_url(filters):
    """Provenance must retain exactly the report's basis and object selection."""
    values = {key: value for key, value in filters.items() if value is not None and value != []}
    return "/api/v1/reports/cash/sources?" + urlencode(values, doseq=True)


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
        rent_charges=store.list_rent_charges(),
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
def get_finance_report(format: Annotated[str | None, Query(alias="format")] = None,
                       date_from: date | None = None, date_to: date | None = None,
                       portfolio_id: str | None = None, property_id: str | None = None, unit_id: str | None = None):
    source = financial_cash.report(store, financial_cash.CashFilters(date_from=date_from, date_to=date_to,
        portfolio_id=portfolio_id, property_ids=[property_id] if property_id else [], unit_id=unit_id, basis="recorded_bookings"))
    data: dict[str, Any] = {"totalsByCategory": [{"categoryId": row["category_id"], "categoryName": row["name"],
        "categoryType": row["category_type"], "total": float(row["net"]), "exactTotal": row["net"]}
        for row in source["categories"] if row["category_id"]],
        "uncategorizedTotal": float(next((row["net"] for row in source["categories"] if row["category_id"] is None), "0.00")),
        "exactUncategorizedTotal": next((row["net"] for row in source["categories"] if row["category_id"] is None), "0.00"),
        "bookingsTotal": float(source["net"]), "exactTotal": source["net"], "currency": source["currency"],
        "basis": source["basis"], "source_hash": source["source_hash"], "source_count": source["source_count"],
        "excluded_count": source["excluded_count"], "source_filters": source["filters"],
        "source_url": _cash_source_url(source["filters"])}

    if format == "csv":
        rows = [
            {"Kategorie": t["categoryName"], "Typ": t["categoryType"], "Betrag": t["exactTotal"]}
            for t in data["totalsByCategory"]
        ]
        if data["uncategorizedTotal"]:
            rows.append({"Kategorie": "Unkategorisiert", "Typ": "-", "Betrag": data["exactUncategorizedTotal"]})
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
        rent_charges=store.list_rent_charges(),
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
def get_cashflow_report(format: Annotated[str | None, Query(alias="format")] = None,
                        date_from: date | None = None, date_to: date | None = None,
                        portfolio_id: str | None = None, property_id: str | None = None, unit_id: str | None = None):
    source = financial_cash.report(store, financial_cash.CashFilters(date_from=date_from, date_to=date_to,
        portfolio_id=portfolio_id, property_ids=[property_id] if property_id else [], unit_id=unit_id, basis="recorded_bookings"))
    data = {"incomeTotal": float(source["income"]), "expenseTotal": float(source["expense"]), "netTotal": float(source["net"]),
        "exactIncome": source["income"], "exactExpense": source["expense"], "exactNet": source["net"],
        "currency": source["currency"], "basis": source["basis"], "source_hash": source["source_hash"],
        "source_count": source["source_count"], "excluded_count": source["excluded_count"],
        "source_filters": source["filters"], "source_url": _cash_source_url(source["filters"])}

    if format == "csv":
        rows = [{
            "Einnahmen": data["exactIncome"],
            "Ausgaben": data["exactExpense"],
            "Netto": data["exactNet"],
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
def datev_export(start_date: date | None = Query(None), end_date: date | None = Query(None)):
    raise HTTPException(410, "DATEV requires an explicitly reviewed mapping profile. Open /datev and use /api/v1/reports/datev/profiles and /preview. For general historical data use /api/v1/bookings/export.csv.")


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

    from tempfile import TemporaryFile

    from ..services.bank_import import (
        BankConfirm,
        BankImportError,
        capacity,
        commit_import,
        import_receipts,
        preview_import,
        stage_import,
    )
    from ..services.bank_import_parser import BankMapping
    from ..services.portfolio_scope import current_scope

    selected_scope = current_scope()
    def legacy_call(operation, *args, **kwargs):
        try:
            return operation(*args, **kwargs)
        except BankImportError as error:
            from fastapi import HTTPException
            raise HTTPException(status_code=error.status, detail=error.detail) from None

    # The legacy JSON contract necessarily already supplies a complete string.
    # Do not create another full encoded copy or materialise parsed row lists.
    with TemporaryFile(mode="w+b") as source:
        for offset in range(0, len(_csv_content), 65_536):
            source.write(_csv_content[offset:offset + 65_536].encode("utf-8"))
        job = legacy_call(stage_import, store, source, _account_id, BankMapping(),
            filename="legacy-bank.csv", actor_id=selected_scope.user_id if selected_scope else "internal", scope=selected_scope)
    page_size = min(100, capacity()[0])
    error_page = legacy_call(preview_import, store, job["id"], page_size=page_size, errors_only=True, scope=selected_scope)
    errors = [{"row": row["ordinal"], "error": row["error_message"]} for row in error_page["items"]]
    receipts: dict[str, Any] = {"items": [], "has_more": False, "next_after": None}
    if not job["error_count"] and job["state"] in {"ready", "committed"}:
        job = legacy_call(commit_import, store, job["id"], BankConfirm(revision=job["revision"], preview_hash=job["preview_hash"]), scope=selected_scope)
        receipts = legacy_call(import_receipts, store, job["id"], page_size=page_size, scope=selected_scope)
    imported = [{"row": row["ordinal"], "bookingId": row["booking_id"]} for row in receipts["items"]]

    return {
        "imported": job["published_count"],
        "errors": job["error_count"],
        "details": {"imported": imported, "errors": errors,
            "has_more_imported": receipts["has_more"], "next_after": receipts["next_after"],
            "has_more_errors": error_page["has_more"], "next_error_cursor": error_page["next_cursor"]},
        "import_id": job["id"], "state": job["state"], "source_sha256": job["source_sha256"], "replay": job["replay"],
    }


@router.get("/liquidity-forecast", response_model=None)
def liquidity_forecast(
    months: Annotated[int, Query(ge=1)] = 12,
    property_id: str | None = None,
    portfolio_id: str | None = None,
    unit_id: str | None = None,
    as_of: date | None = None,
    starting_balance: str | None = None,
):
    """Historical scenario; separate from future contractual obligations."""
    filters = financial_cash.CashFilters(portfolio_id=portfolio_id, property_ids=[property_id] if property_id else [],
        unit_id=unit_id, basis="recorded_bookings", as_of=as_of or date.today())
    try:
        with financial_cash.sources(store, filters) as rows:
            data = report_service.compute_liquidity_forecast(bookings=(SimpleNamespace(booking_date=date.fromisoformat(row["booking_date"]),
                amount=Decimal(row["amount"])) for row in rows if row["included"]), months=months,
                today=filters.as_of, starting_balance=starting_balance)
        return data | {"source_basis": filters.basis, "filters": filters.model_dump(mode="json")}
    except ValueError as error:
        raise HTTPException(422, str(error)) from None


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
