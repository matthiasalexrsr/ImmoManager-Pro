from datetime import date

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field

from ..dependencies import store
from ..domain.clock import local_today
from ..domain.money import money, money_sum
from ..models import Booking, BookingCreate, BookingPatch, PaymentAllocation
from ..services.bank_imports import protect_bank_booking
from ..services.booking_writes import booking_write
from ..services.deletion_guard import ensure_deletable
from ..services.deposits import _booking_linked, ensure_booking_unchanged
from ..services.maintenance_projects import ensure_booking_unallocated
from ..services.ownership import require_owner
from ..services.payment_allocations import (
    allocate_unassigned,
    auto_allocate,
    non_rent_shares,
    reallocate_reversals,
    set_allocations,
)
from ..storage import NotFoundError, ValidationError

router = APIRouter(prefix="/bookings", tags=["Buchungen"])


def _deposit_linked(booking_id: str) -> bool:
    return _booking_linked(store, booking_id)


def _allocate(target, booking: Booking) -> None:
    """Credit the booking to contracts; its reversals follow it."""
    auto_allocate(target, booking)
    reallocate_reversals(target, booking)


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
    require_owner(store, payload.owner_contact_id)
    try:
        with booking_write(store, reversal_of=payload.reverses_booking_id, changes=payload.model_dump()) as target:
            booking = target.create_booking(payload)
            auto_allocate(target, booking)
            return booking
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


class AllocationItem(BaseModel):
    contract_id: str
    amount: float


class ReversalRequest(BaseModel):
    booking_date: date | None = None
    amount: float | None = Field(None, gt=0, description="Stornierter Betrag ohne Vorzeichen; "
                                                         "ohne Angabe der noch nicht stornierte Rest")
    payment_text: str | None = None


class AllocationOverview(BaseModel):
    allocations: list[PaymentAllocation]
    reserved_amounts: dict[str, float]


@router.get("/allocations", response_model=list[PaymentAllocation] | AllocationOverview)
def list_allocations(contract_id: str | None = Query(None), include_reservations: bool = Query(False)):
    """Which contract each payment pays (all bookings, or one contract's)."""
    allocations = store.list_payment_allocations(contract_id=contract_id)
    if not include_reservations:
        return allocations
    # Only amounts of already authorized cash sources cross the portfolio fence.
    # A hidden deposit/claim identity is never part of this response.
    ids = [row.id for row in store.list_bookings()]
    return AllocationOverview(allocations=allocations, reserved_amounts={
        key: float(value) for key, value in non_rent_shares(store, ids).items() if value})


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
        with booking_write(store, booking_id=booking_id) as target:
            return set_allocations(target, booking_id, [(i.contract_id, i.amount) for i in items])
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/{booking_id}/reverse", response_model=Booking, status_code=status.HTTP_201_CREATED)
def reverse_booking(booking_id: str, payload: ReversalRequest | None = None) -> Booking:
    """Book a reversal (Storno): same account and assignment, opposite sign, linked to the booking.

    Without an amount, the part not reversed yet is reversed; dated today (not before the
    booking). It is credited to the booking's contracts; reports net both.
    """
    request = payload or ReversalRequest(amount=None)
    try:
        with booking_write(store, booking_id=booking_id) as target:
            original = target.get_booking(booking_id)
            remaining = money(original.amount) + money_sum(r.amount for r in target.list_booking_reversals(original.id))
            if original.reverses_booking_id:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                                    detail="Eine Stornobuchung lässt sich nicht stornieren")
            if remaining == 0:
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                                    detail="Die Buchung ist bereits vollständig storniert")
            amount = -remaining if request.amount is None else (money(request.amount) * (-1 if remaining > 0 else 1))
            text = request.payment_text or f"Storno: {original.payment_text or original.booking_date.strftime('%d.%m.%Y')}"
            data = BookingCreate(
                account_id=original.account_id, category_id=original.category_id, property_id=original.property_id,
                unit_id=original.unit_id, tenant_id=original.tenant_id, owner_contact_id=original.owner_contact_id,
                booking_date=request.booking_date or max(local_today(), original.booking_date),
                amount=float(amount), status=original.status, payment_text=text, reverses_booking_id=original.id)
            reversal = target.create_booking(data)
            auto_allocate(target, reversal)
            return reversal
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
    require_owner(store, payload.owner_contact_id)
    try:
        with booking_write(store, booking_id=booking_id, changes=payload.model_dump()) as target:
            protect_bank_booking(target, booking_id, payload.model_dump())
            ensure_booking_unchanged(target, booking_id, payload.model_dump())
            booking = target.update_booking(booking_id, payload)
            _allocate(target, booking)
            return booking
    except (NotFoundError, ValidationError) as exc:
        status_code = status.HTTP_404_NOT_FOUND if isinstance(exc, NotFoundError) else status.HTTP_400_BAD_REQUEST
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc


@router.patch("/{booking_id}", response_model=Booking)
def patch_booking(booking_id: str, payload: BookingPatch) -> Booking:
    require_owner(store, payload.owner_contact_id)
    try:
        with booking_write(store, booking_id=booking_id, changes=payload.model_dump(exclude_unset=True)) as target:
            protect_bank_booking(target, booking_id, payload.model_dump(exclude_unset=True))
            ensure_booking_unchanged(target, booking_id, payload.model_dump(exclude_unset=True))
            booking = target._patch_entity("booking", booking_id, payload)
            _allocate(target, booking)
            return booking
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.delete("/{booking_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_booking(booking_id: str) -> None:
    try:
        with booking_write(store, booking_id=booking_id) as target:
            target.get_booking(booking_id)
            protect_bank_booking(target, booking_id)
            from ..services.payment_allocations import ensure_allocations_visible
            ensure_allocations_visible(target, booking_id)
            ensure_deletable(target, "booking", booking_id)
            ensure_booking_unallocated(target, booking_id)
            target.delete_booking(booking_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
