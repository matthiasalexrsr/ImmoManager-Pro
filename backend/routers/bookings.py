from datetime import date

from fastapi import APIRouter, HTTPException, Query, status

from ..dependencies import store
from ..models import Booking, BookingCreate, BookingPatch
from ..storage import NotFoundError, ValidationError

router = APIRouter(prefix="/bookings", tags=["Buchungen"])


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
    has_date_filter = isinstance(date_from, date) or isinstance(date_to, date)
    results = store._list_paginated(
        entity_type="booking",
        skip=0 if has_date_filter else skip,
        limit=10000 if has_date_filter else limit,
        filters=filters,
        order_by=sort_by,
        order_desc=(sort_order == "desc"),
    )
    if isinstance(date_from, date):
        results = [
            r for r in results
            if getattr(r, 'booking_date', None)
            and r.booking_date >= date_from
        ]
    if isinstance(date_to, date):
        results = [
            r for r in results
            if getattr(r, 'booking_date', None)
            and r.booking_date <= date_to
        ]
    if has_date_filter:
        results = results[skip : skip + limit]
    return results


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


@router.delete("/{booking_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_booking(booking_id: str) -> None:
    try:
        store.delete_booking(booking_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
