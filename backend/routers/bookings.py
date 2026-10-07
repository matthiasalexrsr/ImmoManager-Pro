from datetime import date

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel

from ..dependencies import store
from ..models import Booking, BookingCreate, BookingPatch, PaymentAllocation
from ..services.payment_allocations import allocate_unassigned, auto_allocate, set_allocations
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
    return store._list_paginated(
        entity_type="booking",
        skip=skip,
        limit=limit,
        filters=filters,
        order_by=sort_by,
        order_desc=(sort_order == "desc"),
        range_filters={"booking_date": (
            date_from if isinstance(date_from, date) else None,
            date_to if isinstance(date_to, date) else None,
        )},
    )


@router.post("", response_model=Booking, status_code=status.HTTP_201_CREATED)
def create_booking(payload: BookingCreate) -> Booking:
    try:
        booking = store.create_booking(payload)
        auto_allocate(store, booking)
        return booking
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


class AllocationItem(BaseModel):
    contract_id: str
    amount: float


@router.get("/allocations", response_model=list[PaymentAllocation])
def list_allocations(contract_id: str | None = Query(None)) -> list[PaymentAllocation]:
    """Which contract each payment pays (all bookings, or one contract's)."""
    return store.list_payment_allocations(contract_id=contract_id)


@router.post("/allocate-unassigned")
def allocate_unassigned_bookings() -> dict:
    """Allocate tenant payments that have no contract yet; unclear ones are listed."""
    return allocate_unassigned(store)


@router.get("/{booking_id}/allocations", response_model=list[PaymentAllocation])
def get_booking_allocations(booking_id: str) -> list[PaymentAllocation]:
    try:
        store.get_booking(booking_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return store.list_payment_allocations(booking_id=booking_id)


@router.put("/{booking_id}/allocations", response_model=list[PaymentAllocation])
def put_booking_allocations(booking_id: str, items: list[AllocationItem]) -> list[PaymentAllocation]:
    """Split a payment across the tenant's contracts by hand (an empty list unassigns it)."""
    try:
        return set_allocations(store, booking_id, [(i.contract_id, i.amount) for i in items])
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
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
        booking = store.update_booking(booking_id, payload)
        auto_allocate(store, booking)
        return booking
    except (NotFoundError, ValidationError) as exc:
        status_code = status.HTTP_404_NOT_FOUND if isinstance(exc, NotFoundError) else status.HTTP_400_BAD_REQUEST
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc


@router.patch("/{booking_id}", response_model=Booking)
def patch_booking(booking_id: str, payload: BookingPatch) -> Booking:
    try:
        booking = store._patch_entity("booking", booking_id, payload)
        auto_allocate(store, booking)
        return booking
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.delete("/{booking_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_booking(booking_id: str) -> None:
    try:
        store.delete_booking(booking_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
