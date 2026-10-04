"""Exact shared cash reporting and complete source export."""

from typing import Annotated

from fastapi import APIRouter, Query, Response
from fastapi.responses import StreamingResponse

from ..dependencies import store
from ..services import financial_cash as service
from ..services.booking_export import closing_chunks
from ..services.checked_publication import CheckedPublicationRoute

router = APIRouter(prefix="/reports/cash", tags=["Zahlungsübersicht"], route_class=CheckedPublicationRoute)


@router.get("")
def cash_report(filters: Annotated[service.CashFilters, Query()], response: Response):
    response.headers["Cache-Control"] = "private, no-store"
    return service.report(store, filters)


@router.get("/sources")
def cash_sources(query: Annotated[service.CashSourcesQuery, Query()], response: Response):
    response.headers["Cache-Control"] = "private, no-store"
    filters = service.CashFilters.model_validate(query.model_dump(include=set(service.CashFilters.model_fields)))
    return service.report(store, filters, after=query.after, source_hash=query.source_hash, limit=query.limit, details=True)


@router.get("/export.csv")
def cash_export(filters: Annotated[service.CashFilters, Query()]):
    return StreamingResponse(closing_chunks(service.csv_chunks(store, filters)), media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="zahlungsquellen.csv"', "Cache-Control": "private, no-store"})
