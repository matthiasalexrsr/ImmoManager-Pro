from fastapi import APIRouter, HTTPException, Query, status

from ..dependencies import store
from ..models import CalendarEvent, CalendarEventCreate, CalendarEventPatch
from ..storage import NotFoundError, ValidationError

router = APIRouter(prefix="/calendar", tags=["Kalender"])


@router.get("", response_model=list[CalendarEvent])
def list_calendar_events(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    property_id: str | None = Query(None),
    event_type: str | None = Query(None),
) -> list[CalendarEvent]:
    results = store.list_calendar_events()
    if property_id:
        results = [e for e in results if e.property_id == property_id]
    if event_type:
        results = [e for e in results if e.event_type == event_type]
    return results[skip : skip + limit]


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


@router.patch("/{event_id}", response_model=CalendarEvent)
def patch_calendar_event(event_id: str, payload: CalendarEventPatch) -> CalendarEvent:
    try:
        return store._patch_entity(None, event_id, payload, "Termin nicht gefunden")
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.delete("/{event_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_calendar_event(event_id: str) -> None:
    try:
        store.delete_calendar_event(event_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
