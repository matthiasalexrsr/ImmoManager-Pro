"""Additive contact pages, scoped counts and complete CSV."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import StreamingResponse

from ..auth import require_auth
from ..dependencies import store
from ..services.booking_export import closing_chunks
from ..services.checked_publication import CheckedPublicationRoute
from ..services.contact_inventory import (
    ContactInventoryPage,
    ContactInventoryQuery,
    contact_inventory_page,
    contact_inventory_summary,
)
from ..services.contact_inventory_export import csv_chunks

router = APIRouter(prefix="/inventory", route_class=CheckedPublicationRoute, dependencies=[Depends(require_auth)])


def private(response):
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["Vary"] = "Authorization"


@router.get("/page", response_model=ContactInventoryPage)
def page(query: Annotated[ContactInventoryQuery, Query()], response: Response):
    private(response)
    return contact_inventory_page(store, query)


@router.get("/summary")
def summary(query: Annotated[ContactInventoryQuery, Query()], response: Response):
    private(response)
    return contact_inventory_summary(store, query)


@router.get("/export")
def export(query: Annotated[ContactInventoryQuery, Query()], request: Request):
    token = request.headers.get("Authorization", "").removeprefix("Bearer ")
    return StreamingResponse(closing_chunks(csv_chunks(store, query, token=token)), media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="kontakte.csv"', "Cache-Control": "private, no-store", "Vary": "Authorization"})
