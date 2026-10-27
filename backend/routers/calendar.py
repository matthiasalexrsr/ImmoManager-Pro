from datetime import date
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status

from ..dependencies import store
from ..models import CalendarEventCreate, CalendarEventPatch
from ..services.calendar_records import CalendarEventView, list_events, with_projects
from ..services.office_records import delete_calendar_record, save_record
from ..storage import NotFoundError, ValidationError

router = APIRouter(prefix="/calendar", tags=["Kalender"])


@router.get("", response_model=list[CalendarEventView])
def list_calendar_events(
    skip: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
    property_id: str | None = None,
    unit_id: str | None = None,
    event_type: str | None = None,
    maintenance_case_id: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
) -> list[CalendarEventView]:
    if date_from and date_to and date_from > date_to:
        raise HTTPException(422, "Das Enddatum darf nicht vor dem Anfang liegen.")
    return list_events(store, skip=skip, limit=limit, property_id=property_id, unit_id=unit_id,
                       event_type=event_type, maintenance_case_id=maintenance_case_id,
                       date_from=date_from, date_to=date_to)


@router.post("", response_model=CalendarEventView, status_code=status.HTTP_201_CREATED)
def create_calendar_event(payload: CalendarEventCreate) -> CalendarEventView:
    try:
        return with_projects(store, [save_record(store, "calendar_events", payload)])[0]
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/{event_id}", response_model=CalendarEventView)
def get_calendar_event(event_id: str) -> CalendarEventView:
    try:
        return with_projects(store, [store.get_calendar_event(event_id)])[0]
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.put("/{event_id}", response_model=CalendarEventView)
def update_calendar_event(event_id: str, payload: CalendarEventCreate) -> CalendarEventView:
    try:
        return with_projects(store, [save_record(store, "calendar_events", payload, event_id)])[0]
    except (NotFoundError, ValidationError) as exc:
        status_code = status.HTTP_404_NOT_FOUND if isinstance(exc, NotFoundError) else status.HTTP_400_BAD_REQUEST
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc


@router.patch("/{event_id}", response_model=CalendarEventView)
def patch_calendar_event(event_id: str, payload: CalendarEventPatch) -> CalendarEventView:
    try:
        return with_projects(store, [save_record(store, "calendar_events", payload, event_id, partial=True)])[0]
    except (NotFoundError, ValidationError) as exc:
        raise HTTPException(status_code=404 if isinstance(exc, NotFoundError) else 400, detail=str(exc)) from exc


@router.delete("/{event_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_calendar_event(event_id: str) -> None:
    try:
        delete_calendar_record(store, event_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
