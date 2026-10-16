"""Versioned financial reports and canonical stored-claim settlements."""
import csv
import io
import json
from datetime import date
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
    captured = current_scope()
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
        for section in ("monthly", "baseline_monthly", "sources", "warnings"):
            writer.writerow([section])
            entries = data.get(section, [])
            if entries:
                columns = list(dict.fromkeys(k for row in entries for k in row))
                writer.writerow(columns)
                writer.writerows([spreadsheet_cell(row.get(k, "")) for k in columns] for row in entries)
        refresh_scope(captured)
        return Response(stream.getvalue(), media_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition": 'attachment; filename="finanzbericht-v2.csv"'})
    from ..services.report_render import render_report_pdf
    # The same definition, numbers and sources; definition is printable text, not executable configuration.
    printable = {"Definition": json.dumps(data["definition"], ensure_ascii=False, sort_keys=True),
                 "filters": data["filters"],
                 "Definitionshash": data["definition_hash"], "Währung": data["currency"], "Ergebnishash": data["result_hash"], "monthly": data["monthly"],
                 "Quellen": [{"Quelle": s.get("identity", s.get("source", "")),
                               "Datum / Monat": s.get("day", s.get("month", "")),
                               "Betrag": s.get("amount", ""), "Bezug": s.get("url", "")}
                              for s in data.get("sources", [])], "Hinweise": data.get("warnings", [])}
    if "baseline_monthly" in data:
        printable["Basisprognose"] = data["baseline_monthly"]
    content = render_report_pdf(data["basis"], printable)
    refresh_scope(captured)
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
