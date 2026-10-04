"""Additive complete authorized field-change inventory."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import StreamingResponse

from ..auth import require_auth
from ..dependencies import store
from ..services import history_inventory
from ..services.booking_export import closing_chunks
from ..services.checked_publication import CheckedPublicationRoute
from ..services.history_inventory import (
    FIELDS,
    HistoryInventoryPage,
    HistoryInventoryQuery,
    history_inventory_page,
    history_inventory_summary,
)
from ..services.inventory_export import csv_chunks

router = APIRouter(prefix="/inventory", route_class=CheckedPublicationRoute, dependencies=[Depends(require_auth)])


def private(response):
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["Vary"] = "Authorization"


@router.get("/page", response_model=HistoryInventoryPage)
def page(query: Annotated[HistoryInventoryQuery, Query()], response: Response):
    private(response)
    return history_inventory_page(store, query)


@router.get("/summary")
def summary(query: Annotated[HistoryInventoryQuery, Query()], response: Response):
    private(response)
    return history_inventory_summary(store, query)


@router.get("/export")
def export(query: Annotated[HistoryInventoryQuery, Query()], request: Request):
    token = request.headers.get("Authorization", "").removeprefix("Bearer ")
    return StreamingResponse(closing_chunks(csv_chunks(store, query, inventory=history_inventory, fields=FIELDS, token=token)),
        media_type="text/csv; charset=utf-8", headers={"Content-Disposition": 'attachment; filename="aenderungshistorie.csv"',
        "Cache-Control": "private, no-store", "Vary": "Authorization"})
