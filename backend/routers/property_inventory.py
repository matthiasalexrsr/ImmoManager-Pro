"""Additive property read routes; Root owns mounting into existing CRUD."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import StreamingResponse

from ..auth import require_auth
from ..dependencies import store
from ..services.booking_export import closing_chunks
from ..services.checked_publication import CheckedPublicationRoute
from ..services.property_inventory import property_inventory_page, property_inventory_summary
from ..services.property_inventory_export import csv_chunks
from ..services.property_inventory_types import PropertyInventoryPage, PropertyInventoryQuery, PropertyInventorySummary

router = APIRouter(prefix="/inventory", route_class=CheckedPublicationRoute, dependencies=[Depends(require_auth)])


def private(response):
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["Vary"] = "Authorization"


@router.get("/page", response_model=PropertyInventoryPage)
def page(query: Annotated[PropertyInventoryQuery, Query()], response: Response):
    private(response)
    return property_inventory_page(store, query)


@router.get("/summary", response_model=PropertyInventorySummary)
def summary(query: Annotated[PropertyInventoryQuery, Query()], response: Response):
    private(response)
    return property_inventory_summary(store, query)


@router.get("/export")
def export(query: Annotated[PropertyInventoryQuery, Query()], request: Request):
    token = request.headers.get("Authorization", "").removeprefix("Bearer ")
    return StreamingResponse(closing_chunks(csv_chunks(store, query, token=token)), media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="immobilien.csv"',
                 "Cache-Control": "private, no-store", "Vary": "Authorization"})
