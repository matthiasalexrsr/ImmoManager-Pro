"""Private additive current-meter inventory, separate from retained billing sources."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import StreamingResponse

from ..auth import require_auth
from ..dependencies import store
from ..services.booking_export import closing_chunks
from ..services.checked_publication import CheckedPublicationRoute
from ..services.meter_inventory import (
    MeterInventoryItem,
    MeterInventoryPage,
    MeterInventoryQuery,
    MeterReadingsPage,
    MeterReadingsQuery,
    meter_inventory_detail,
    meter_inventory_page,
    meter_inventory_summary,
    meter_readings_page,
)
from ..services.meter_inventory_export import csv_chunks

router = APIRouter(route_class=CheckedPublicationRoute, dependencies=[Depends(require_auth)])


def private(response):
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["Vary"] = "Authorization"


@router.get("/inventory/page", response_model=MeterInventoryPage)
def page(query: Annotated[MeterInventoryQuery, Query()], response: Response):
    private(response)
    return meter_inventory_page(store, query)


@router.get("/inventory/summary")
def summary(query: Annotated[MeterInventoryQuery, Query()], response: Response):
    private(response)
    return meter_inventory_summary(store, query)


@router.get("/inventory/export")
def export(query: Annotated[MeterInventoryQuery, Query()], request: Request):
    token = request.headers.get("Authorization", "").removeprefix("Bearer ")
    return StreamingResponse(closing_chunks(csv_chunks(store, query, token=token)), media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="zaehler.csv"', "Cache-Control": "private, no-store", "Vary": "Authorization"})


@router.get("/inventory/detail/{meter_id}", response_model=MeterInventoryItem)
def detail(meter_id: str, response: Response):
    private(response)
    return meter_inventory_detail(store, meter_id)


@router.get("/{meter_id}/readings/page", response_model=MeterReadingsPage)
def readings(meter_id: str, query: Annotated[MeterReadingsQuery, Query()], response: Response):
    private(response)
    return meter_readings_page(store, meter_id, query)
