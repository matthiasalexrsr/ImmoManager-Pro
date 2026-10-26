"""Versioned financial reports and canonical stored-claim settlements."""
import csv
import io
import json
from datetime import date
from decimal import Decimal
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import ValidationError as ModelValidationError

from ..auth import require_auth
from ..dependencies import store
from ..finance_models import ReportDefinition, ReverseSettlement, SaveReport, SettlementCommand
from ..models import UserRead
from ..services import finance_reports as service
from ..services.csv_export import spreadsheet_cell
from ..services.receivable_residuals import allocate, residual, reverse

Actor = Annotated[UserRead, Depends(require_auth)]
router = APIRouter(tags=["Finanzberichte v2"])


def output(data, format):
    from ..services.portfolio_scope import current_scope, refresh_scope
    from ..services.report_provenance import recheck_originals
    captured = current_scope()
    recheck_originals(store, data)
    if format == "json":
        refresh_scope(captured)
        return data
    if format == "csv":
        stream = io.StringIO()
        writer = csv.writer(stream, delimiter=";")
        writer.writerow(["Definition", json.dumps(data["definition"], ensure_ascii=False, sort_keys=True)])
        writer.writerow(["Definitionshash", data["definition_hash"]])
        writer.writerow(["Währung", data["currency"]])
        writer.writerow(["Ergebnishash", data["result_hash"]])
        writer.writerow(["Datenabruf UTC", data.get("generated_at", "")])
        writer.writerow(["Quellenstand", json.dumps(data.get("provenance", {}), ensure_ascii=False, sort_keys=True)])
        for key in ("opening_balance", "closing_balance"):
            if key in data:
                writer.writerow([key, Decimal(data[key])])
        if "totals" in data:
            writer.writerow(["totals"])
            writer.writerow(data["totals"].keys())
            writer.writerow([Decimal(value) for value in data["totals"].values()])
        numeric_columns = {"income", "expense", "net", "withdrawal", "contribution", "balance", "rent_due", "other_income", "costs",
                           "result", "amount"}
        for section in ("monthly", "baseline_monthly", "opening_sources", "sources", "baseline_sources", "warnings"):
            writer.writerow([section])
            entries = data.get(section, [])
            if entries:
                columns = list(dict.fromkeys(k for row in entries for k in row))
                writer.writerow(columns)
                writer.writerows([spreadsheet_cell(Decimal(row[k]) if k in row and
                                  ((section in ("monthly", "baseline_monthly") and k in numeric_columns) or k == "amount") else
                                  json.dumps(row[k], ensure_ascii=False, sort_keys=True) if isinstance(row.get(k), (dict, list)) else row.get(k, ""))
                                  for k in columns] for row in entries)
        refresh_scope(captured)
        recheck_originals(store, data)
        return Response(stream.getvalue(), media_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition": 'attachment; filename="finanzbericht-v2.csv"'})
    from ..services.report_render import render_report_pdf
    def monthly(rows):
        return [{key: value if key == "month" else Decimal(value) for key, value in row.items()} for row in rows]

    def sources(rows):
        return [{"Vorgang": source.get("label") or source.get("basis") or source["identity"],
                 "Datum / Monat": source.get("day", source.get("month", "–")),
                 "Betrag": Decimal(source["amount"]), "Grundlage": source.get("basis", ""),
                 "Bezug": source.get("url", ""),
                 "Originalnachweis": source.get("provenance", {}).get("original", {}).get("message", ""),
                 "Originalversion": source.get("provenance", {}).get("original", {}).get("version_id", ""),
                 "Original SHA-256": source.get("provenance", {}).get("original", {}).get("sha256", "")} for source in rows]

    printable = {"filters": data["filters"], "Stichtag": data["definition"]["as_of"],
                 "Datenabruf UTC": data.get("generated_at", ""),
                 "Quellenstand": data.get("provenance", {}),
                 "Währung": data["currency"], "monthly": monthly(data["monthly"])}
    if "totals" in data:
        printable["totals"] = {key: Decimal(value) for key, value in data["totals"].items()}
    for key in ("opening_balance", "closing_balance"):
        if key in data:
            printable[key] = Decimal(data[key])
    if data["basis"] == "liquidity-v2":
        definition = data["definition"]
        printable["Planungsannahmen"] = (f"Erwarteter Mieteingang: {definition['rent_collection_percent']} %, "
            f"Eingang offener Rückstände: {definition['arrears_collection_percent']} %, "
            f"Mietzahlungstag: {definition['rent_payment_day']}; "
            f"Einheiten im Leerstandsszenario: {len(definition['vacant_unit_ids'])}. "
            "Erfasste künftige Zahlungen ersetzen die jeweilige Erwartung; Planwerte sind keine Zahlungsgarantie.")
        printable["Quellen des Anfangssaldos"] = sources(data.get("opening_sources", []))
    printable["Quellen"] = sources(data.get("sources", []))
    printable["Hinweise"] = [{"Hinweis": warning["message"], "Quelle": warning.get("source", "")}
                             for warning in data.get("warnings", [])]
    if "baseline_monthly" in data:
        printable["Basisprognose"] = monthly(data["baseline_monthly"])
        printable["Quellen der Basisprognose"] = sources(data.get("baseline_sources", []))
    printable["Berechnungsnachweis"] = {"Definitionshash": data["definition_hash"], "Ergebnishash": data["result_hash"]}
    selection = {}
    for key, get_record, attribute in (("portfolio_id", store.get_portfolio, "name"),
                                      ("property_id", store.get_property, "name"),
                                      ("unit_id", store.get_unit, "label")):
        if data["filters"].get(key):
            selection[key] = getattr(get_record(data["filters"][key]), attribute)
    content = render_report_pdf(data["basis"], printable, selection=selection, currency=data["currency"])
    refresh_scope(captured)
    recheck_originals(store, data)
    return Response(content, media_type="application/pdf",
                    headers={"Content-Disposition": 'attachment; filename="finanzbericht-v2.pdf"'})


@router.post("/reports/v2/preview", response_model=None)
def preview(payload: ReportDefinition, actor: Actor, format: Literal["json", "csv", "pdf"] = "json", expected_result_hash: str | None = None):
    data = service.compute(store, payload)
    if expected_result_hash is not None and expected_result_hash != data["result_hash"]:
        raise HTTPException(409, "Die Berichtsquellen haben sich geändert. Bitte vor dem Export neu berechnen.")
    return output(data, format)


@router.get("/reports/v2/preview", response_model=None)
def read_preview(definition: str, actor: Actor, format: Literal["json", "csv", "pdf"] = "json", expected_result_hash: str | None = None):
    """Read-only roles use GET, under the same current source boundaries as existing reports."""
    try:
        payload = ReportDefinition.model_validate_json(definition)
    except ModelValidationError as error:
        raise HTTPException(422, "Die Berichtsdefinition ist ungültig.") from error
    return preview(payload, actor, format, expected_result_hash)


@router.post("/reports/v2/saved")
def save(payload: SaveReport, actor: Actor):
    return service.save(store, payload, actor.id)


@router.get("/reports/v2/saved")
def list_saved(actor: Actor, skip: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=1000)):
    return service.saved(store, actor.id)[skip:skip + limit]


@router.get("/reports/v2/saved/{identifier}", response_model=None)
def open_saved(identifier: str, actor: Actor, format: Literal["json", "csv", "pdf"] = "json"):
    record = service.saved(store, actor.id, identifier)
    return output(service.compute(store, ReportDefinition.model_validate(record.definition)), format)


@router.get("/receivables/{identifier}/residual")
def get_residual(identifier: str, actor: Actor, as_of: date | None = None):
    from ..services.portfolio_scope import current_scope, refresh_scope
    captured = current_scope()
    result = residual(store, store.get_receivable(identifier), as_of)
    refresh_scope(captured)
    return result


@router.post("/receivables/{identifier}/settlements")
def settle(identifier: str, payload: SettlementCommand, actor: Actor):
    return allocate(store, identifier, payload, actor.id)


@router.post("/receivables/{identifier}/settlements/{settlement_id}/reverse")
def reverse_settlement(identifier: str, settlement_id: str, payload: ReverseSettlement, actor: Actor):
    return reverse(store, identifier, settlement_id, payload, actor.id)
