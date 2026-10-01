from datetime import date
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import JSONResponse, StreamingResponse

from ..dependencies import store
from ..models import Booking, BookingCreate, BookingPatch
from ..services.booking_export import booking_csv_chunks, closing_chunks
from ..services.booking_legacy import legacy_booking_list
from ..services.booking_lookup import BookingChoices, BookingLookupQuery, LookupKind, booking_choices
from ..services.booking_query import BookingFilters, BookingPage, BookingPageQuery, BookingQueryError, get_booking_page
from ..storage import NotFoundError, ValidationError

router = APIRouter(prefix="/bookings", tags=["Buchungen"])


@router.get("/lookup/{kind}", response_model=BookingChoices)
def lookup_bookings(kind: LookupKind, query: Annotated[BookingLookupQuery, Query()]):
    try:
        return booking_choices(store, kind, query)
    except BookingQueryError as exc:
        return JSONResponse(status_code=400, content={"error": {
            "code": exc.clear_code, "message": str(exc), "details": [exc.detail]}})


@router.get("/page", response_model=BookingPage)
def booking_page(query: Annotated[BookingPageQuery, Query()]):
    try:
        return get_booking_page(store, query)
    except BookingQueryError as exc:
        # The global legacy HTTPException adapter stringifies structured detail.
        # Keep a machine-readable recovery code through the regular API client.
        return JSONResponse(status_code=400, content={"error": {
            "code": exc.clear_code, "message": str(exc), "details": [exc.detail]}})


@router.get("/export.csv")
def export_bookings(filters: Annotated[BookingFilters, Query()]):
    return StreamingResponse(closing_chunks(booking_csv_chunks(store, filters)),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="bookings.csv"', "Cache-Control": "no-store"})


@router.get("", response_model=list[Booking])
def list_bookings(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    account_id: str | None = Query(None),
    tenant_id: str | None = Query(None),
    status_filter: str | None = Query(None, alias="status"),
    sort_by: str | None = Query(None),
    sort_order: str = Query("asc"),
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
) -> list[Booking]:
    filters = {"account_id": account_id, "tenant_id": tenant_id, "status": status_filter}
    return legacy_booking_list(store, skip=skip, limit=limit, filters=filters,
        sort_by=sort_by, descending=sort_order == "desc",
        date_from=date_from if isinstance(date_from, date) else None,
        date_to=date_to if isinstance(date_to, date) else None)


@router.post("", response_model=Booking, status_code=status.HTTP_201_CREATED)
def create_booking(payload: BookingCreate) -> Booking:
    try:
        return store.create_booking(payload)
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/{booking_id}", response_model=Booking)
def get_booking(booking_id: str) -> Booking:
    try:
        return store.get_booking(booking_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.put("/{booking_id}", response_model=Booking)
def update_booking(booking_id: str, payload: BookingCreate) -> Booking:
    try:
        return store.update_booking(booking_id, payload)
    except (NotFoundError, ValidationError) as exc:
        status_code = status.HTTP_404_NOT_FOUND if isinstance(exc, NotFoundError) else status.HTTP_400_BAD_REQUEST
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc


@router.patch("/{booking_id}", response_model=Booking)
def patch_booking(booking_id: str, payload: BookingPatch) -> Booking:
    try:
        return store._patch_entity("booking", booking_id, payload)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.delete("/{booking_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_booking(booking_id: str) -> None:
    try:
        store.delete_booking(booking_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
