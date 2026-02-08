from fastapi import APIRouter, HTTPException, status

from ..models import Booking, BookingCreate
from ..routers.portfolios import store
from ..storage import NotFoundError, ValidationError

router = APIRouter(prefix="/bookings", tags=["Buchungen"])


@router.get("", response_model=list[Booking])
def list_bookings() -> list[Booking]:
    return store.list_bookings()


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


@router.delete("/{booking_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_booking(booking_id: str) -> None:
    try:
        store.delete_booking(booking_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
