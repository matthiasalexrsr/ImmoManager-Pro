import base64
import csv
import hashlib
import io
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field

from ..auth import require_auth
from ..concurrency import one_at_a_time
from ..dependencies import store
from ..domain.clock import local_today
from ..domain.money import money
from ..models import UserRead
from ..services import report_service
from ..services.bank_imports import BankImports, StageImport
from ..services.csv_export import spreadsheet_cell
from ..services.finance_ledger import Dimensions, FinanceFilter, add_months, month_start
from ..services.read_cache import CachedReads

router = APIRouter(prefix="/reports", tags=["Berichte"])

# The same filter for every finance report (services.finance_ledger.FinanceFilter). Annotated
# defaults keep the endpoints callable as plain functions (PDF export, tests).
Format = Annotated[str | None, Query(alias="format")]
DateFrom = Annotated[date | None, Query(description="Zeitraum ab diesem Tag (einschließlich)")]
DateTo = Annotated[date | None, Query(description="Zeitraum bis zu diesem Tag (einschließlich)")]
PortfolioId = Annotated[str | None, Query(description="Nur dieses Portfolio")]
PropertyId = Annotated[str | None, Query(description="Nur dieses Objekt")]
UnitId = Annotated[str | None, Query(description="Nur diese Einheit")]


def _filter(date_from: date | None = None, date_to: date | None = None, portfolio_id: str | None = None,
            property_id: str | None = None, unit_id: str | None = None) -> FinanceFilter:
    if date_from and date_to and date_from > date_to:
        raise HTTPException(status_code=422, detail="Der Zeitraum beginnt nach seinem Ende")
    return FinanceFilter(date_from=date_from, date_to=date_to, portfolio_id=portfolio_id or None,
                         property_id=property_id or None, unit_id=unit_id or None)


def _all_bookings() -> list:
    """All bookings, from memory while none changed (backend.concurrency)."""
    return CachedReads(store).list_bookings()


def _csv_response(rows: list[dict], filename: str) -> Response:
    """Build a CSV download from a list of dicts (in one piece: line-wise streaming was slow)."""
    if not rows:
        output = io.StringIO("")
    else:
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=rows[0].keys(), delimiter=";")
        writer.writeheader()
        writer.writerows({key: spreadsheet_cell(value) for key, value in row.items()} for row in rows)
    return Response(
        output.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/summary")
@one_at_a_time
def get_summary(format: Format = None, date_from: DateFrom = None, date_to: DateTo = None,
                portfolio_id: PortfolioId = None, property_id: PropertyId = None, unit_id: UnitId = None, as_of: date | None = None):
    data = report_service.compute_summary(store, _filter(date_from, date_to, portfolio_id, property_id, unit_id), today=as_of)

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
            "Offene Guthaben (Mieter)": f["openCredits"],
            "Offene Wartungsfälle": data["maintenance"]["openCases"],
        }]
        return _csv_response(rows, "zusammenfassung.csv")

    return data


@router.get("/finance")
@one_at_a_time
def get_finance_report(format: Format = None, date_from: DateFrom = None, date_to: DateTo = None,
                       portfolio_id: PortfolioId = None, property_id: PropertyId = None, unit_id: UnitId = None):
    """Bookings per category; a reversal nets the booking it cancels."""
    data = report_service.compute_finance(store, _filter(date_from, date_to, portfolio_id, property_id, unit_id))

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
@one_at_a_time
def get_occupancy_report(format: Format = None, portfolio_id: PortfolioId = None,
                         property_id: PropertyId = None, unit_id: UnitId = None):
    flt = _filter(portfolio_id=portfolio_id, property_id=property_id, unit_id=unit_id)
    dims = Dimensions(store, flt)
    data = report_service.compute_occupancy(
        units=[u for u in store.list_units() if dims.unit_record_matches(u)],
        contracts=[c for c in store.list_contracts() if dims.contract_matches(c)],
    )
    data["filters"] = flt.echo()

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
@one_at_a_time
def get_receivables_aging(format: Format = None, date_from: DateFrom = None, date_to: DateTo = None,
                          portfolio_id: PortfolioId = None, property_id: PropertyId = None,
                          unit_id: UnitId = None, as_of: date | None = None):
    """Unpaid receivables (due in the period, if given) by days past due; credits apart."""
    data = report_service.compute_receivables_aging(
        store, _filter(date_from, date_to, portfolio_id, property_id, unit_id), today=as_of)

    if format == "csv":
        b = data["buckets"]
        rows = [{
            "Aktuell": b["current"],
            "1-30 Tage": b["days1to30"],
            "31-60 Tage": b["days31to60"],
            "61-90 Tage": b["days61to90"],
            "90+ Tage": b["days90plus"],
            "Gesamt": data["openTotal"],
            "Offene Guthaben (Mieter)": data["openCredits"],
        }]
        return _csv_response(rows, "forderungsalter.csv")

    return data


@router.get("/cashflow")
@one_at_a_time
def get_cashflow_report(format: Format = None,
                        months: Annotated[int | None, Query(ge=1, le=120)] = None,
                        date_from: DateFrom = None, date_to: DateTo = None, portfolio_id: PortfolioId = None,
                        property_id: PropertyId = None, unit_id: UnitId = None):
    """Cash view: payments in and out, in total and per month (months without bookings as zero rows).

    The period is `date_from`/`date_to`, or the last `months` calendar months (this one included,
    up to today), or every booking.
    """
    if months and not (date_from or date_to):
        today = local_today()
        date_from, date_to = add_months(month_start(today), -(months - 1)), today
    data = report_service.compute_cashflow(store, _filter(date_from, date_to, portfolio_id, property_id, unit_id))

    if format == "csv":
        rows = [{
            "Einnahmen": data["incomeTotal"],
            "Ausgaben": data["expenseTotal"],
            "Netto": data["netTotal"],
        }]
        return _csv_response(rows, "cashflow.csv")

    return data


@router.get("/period-result")
@one_at_a_time
def get_period_result(format: Format = None, date_from: DateFrom = None, date_to: DateTo = None,
                      portfolio_id: PortfolioId = None, property_id: PropertyId = None, unit_id: UnitId = None):
    """Period result in whole calendar months: rent due + other income - costs (default: last 12 months).

    Tenants' payments settle the rent due and are not counted again; the cash view shows them.
    """
    data = report_service.compute_period_result(
        store, _filter(date_from, date_to, portfolio_id, property_id, unit_id))

    if format == "csv":
        rows = [{
            "Monat": m["month"],
            "Sollmiete": m["rent_due"],
            "Sonstige Erträge": m["other_income"],
            "Kosten": m["costs"],
            "Ergebnis": m["result"],
            "Eingänge ohne Zuordnung": m["unassigned_income"],
        } for m in data["monthly"]]
        return _csv_response(rows, "periodenergebnis.csv")

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
def get_maintenance_costs_report(format: Format = None, portfolio_id: PortfolioId = None,
                                 property_id: PropertyId = None, unit_id: UnitId = None):
    data = report_service.compute_maintenance_costs(
        store, _filter(portfolio_id=portfolio_id, property_id=property_id, unit_id=unit_id))

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
@one_at_a_time
def datev_export(
    start_date: Annotated[date | None, Query()] = None,
    end_date: Annotated[date | None, Query()] = None,
    portfolio_id: PortfolioId = None,
    property_id: PropertyId = None,
    unit_id: UnitId = None,
) -> Response:
    """Export neutral booking CSV; this is not a DATEV EXTF contract.

    Historical URL retained for clients. Validated EXTF files use /datev/preview
    and its immutable export history; this file deliberately uses display names.
    A reversal is its own line with the opposite Soll/Haben mark.
    """
    dims = Dimensions(store, _filter(start_date, end_date, portfolio_id, property_id, unit_id))
    bookings = sorted((b for b in _all_bookings() if dims.booking_matches(b)), key=lambda b: b.booking_date)

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
        amount = abs(money(booking.amount))
        # S = Soll (debit), H = Haben (credit)
        soll_haben = "S" if money(booking.amount) >= 0 else "H"
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

    return Response(
        output.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="Buchungen_neutral.csv"'},
    )


# ---------------------------------------------------------------------------
# Phase 6.3: Bank Statement Import
# ---------------------------------------------------------------------------

class ImportBookingsRequest(BaseModel):
    account_id: str
    csv_content: str = Field(..., description="CSV content with columns: date;amount;text")
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=128)


@router.post("/bookings/import")
def import_bookings(
    account_id: str | None = None,
    csv_content: str | None = None,
    payload: Annotated[ImportBookingsRequest | None, Body()] = None,
    user: UserRead = Depends(require_auth),
) -> dict:
    """Legacy input now prepares the controlled preview, never a partial import."""
    if not isinstance(user, UserRead):
        raise HTTPException(409, 'Bankimporte benötigen einen angemeldeten Benutzer und eine bestätigte Vorschau unter /api/v1/bank-imports')
    account = account_id or (payload.account_id if payload else None)
    content = csv_content if csv_content is not None else payload.csv_content if payload else None
    if not account or not content:
        raise HTTPException(422, 'Bitte Konto und CSV-Inhalt angeben')
    raw = content.encode('utf-8')
    key = payload.idempotency_key if payload and payload.idempotency_key else 'legacy-bank/' + hashlib.sha256((account + '\0' + content).encode()).hexdigest()
    preview = BankImports(store).stage(StageImport(idempotency_key=key, account_id=account,
        filename='Legacy-Bankimport.csv', source_base64=base64.b64encode(raw).decode(), format='csv',
        options={'source_provenance': 'submitted_text_utf8'}), user.id)
    return {'imported': 0, 'errors': preview['error_count'], 'requires_confirmation': True,
            'preview': preview, 'preview_url': f"/api/v1/bank-imports/{preview['id']}",
            'message': 'Die vollständige Vorschau prüfen und anschließend ausdrücklich bestätigen.'}


@router.get("/liquidity-forecast", response_model=None)
@one_at_a_time
def liquidity_forecast(
    months: Annotated[int, Query(ge=1, le=60)] = 12,
    property_id: PropertyId = None,
    portfolio_id: PortfolioId = None,
    unit_id: UnitId = None,
):
    """T28: Liquidity forecast for the next months: the rent the contracts will owe, plus the
    average other income and costs of the last complete months (months without bookings count).

    Opening balances belong to accounts, not to properties, so a forecast for
    one property or unit starts from its bookings alone.
    """
    return report_service.compute_liquidity_forecast(
        store, _filter(portfolio_id=portfolio_id, property_id=property_id, unit_id=unit_id), months=months)


@router.get("/pdf/{report_name}", response_model=None)
@one_at_a_time
def export_report_pdf(report_name: str, date_from: DateFrom = None, date_to: DateTo = None,
                      portfolio_id: PortfolioId = None, property_id: PropertyId = None,
                      unit_id: UnitId = None,
                      months: Annotated[int | None, Query(ge=1, le=120)] = None, as_of: date | None = None):
    """Export the same filtered figures as JSON, with complete, wrapping PDF content."""
    from ..services.report_render import REPORT_TITLES, render_report_pdf

    allowed = set(REPORT_TITLES) - {"performance-period-v2", "liquidity-v2"}
    if report_name not in allowed:
        raise HTTPException(400, f"Unbekannter Bericht. Möglich: {', '.join(sorted(allowed))}. Periodenergebnis und Liquiditätsplanung werden über die Finanzberichte exportiert.")
    if as_of is not None and report_name not in ("summary", "receivables-aging"):
        raise HTTPException(422, "Der Stichtag gilt hier nur für Forderungsreste und die Zusammenfassung.")
    flt = _filter(date_from, date_to, portfolio_id, property_id, unit_id)
    if months is not None and report_name != "cashflow":
        raise HTTPException(422, "Monatsanzahl gilt nur für die Zahlungsübersicht")
    if report_name == "occupancy":
        if date_from or date_to:
            raise HTTPException(422, "Die Belegungsübersicht zeigt den heutigen Stand; kein Zeitraum möglich")
        data = get_occupancy_report(portfolio_id=portfolio_id, property_id=property_id, unit_id=unit_id)
    elif report_name == "cashflow":
        data = get_cashflow_report(date_from=date_from, date_to=date_to, portfolio_id=portfolio_id,
                                   property_id=property_id, unit_id=unit_id, months=months)
    else:
        compute = {
            "summary": report_service.compute_summary,
            "finance": report_service.compute_finance,
            "receivables-aging": report_service.compute_receivables_aging,
            "period-result": report_service.compute_period_result,
        }[report_name]
        if report_name == "summary":
            data = report_service.compute_summary(store, flt, today=as_of)
        elif report_name == "receivables-aging":
            data = report_service.compute_receivables_aging(store, flt, today=as_of)
        else:
            data = compute(store, flt)
    if report_name == "receivables-aging":
        data = {**data, "Forderungsreste": [{"Forderung": r["receivable_id"], "Rest": r["residual"],
                "Altbestand ungeklärt": "Ja" if r["unresolved_legacy"] else "Nein"} for r in data.get("residuals", [])]}
        data.pop("residuals", None)

    # Resolve labels through the same scoped store as the report. Never expose names
    # from an unfiltered lookup when a requested id is outside this user's access.
    selection = {}
    for field, method, label in (("portfolio_id", "get_portfolio", "name"),
                                  ("property_id", "get_property", "name"),
                                  ("unit_id", "get_unit", "label")):
        value = data["filters"].get(field)
        if value:
            try:
                record = getattr(store, method)(value)
                selection[field] = getattr(record, label) if record else "Nicht verfügbar"
            except KeyError:
                selection[field] = "Nicht verfügbar"
    return Response(render_report_pdf(report_name, data, selection=selection), media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{report_name}.pdf"'})
