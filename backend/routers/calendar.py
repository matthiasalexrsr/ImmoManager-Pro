from fastapi import APIRouter, HTTPException, status

from ..models import CalendarEvent, CalendarEventCreate
from ..routers.portfolios import store
from ..storage import NotFoundError, ValidationError

router = APIRouter(prefix="/calendar", tags=["Kalender"])


@router.get("", response_model=list[CalendarEvent])
def list_calendar_events() -> list[CalendarEvent]:
    return store.list_calendar_events()


@router.post("", response_model=CalendarEvent, status_code=status.HTTP_201_CREATED)
def create_calendar_event(payload: CalendarEventCreate) -> CalendarEvent:
    try:
        return store.create_calendar_event(payload)
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/{event_id}", response_model=CalendarEvent)
def get_calendar_event(event_id: str) -> CalendarEvent:
    try:
        return store.get_calendar_event(event_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.put("/{event_id}", response_model=CalendarEvent)
def update_calendar_event(event_id: str, payload: CalendarEventCreate) -> CalendarEvent:
    try:
        return store.update_calendar_event(event_id, payload)
    except (NotFoundError, ValidationError) as exc:
        status_code = status.HTTP_404_NOT_FOUND if isinstance(exc, NotFoundError) else status.HTTP_400_BAD_REQUEST
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc


@router.delete("/{event_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_calendar_event(event_id: str) -> None:
    try:
        store.delete_calendar_event(event_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
