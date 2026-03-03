from fastapi import APIRouter, HTTPException, Query, status

from ..dependencies import store
from ..models import ViewingAppointment, ViewingAppointmentCreate, ViewingAppointmentPatch
from ..storage import NotFoundError, ValidationError

router = APIRouter(prefix="/viewings", tags=["Besichtigungen"])


@router.get("", response_model=list[ViewingAppointment])
def list_viewings(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    status_filter: str | None = Query(None, alias="status"),
    lead_id: str | None = Query(None),
    unit_id: str | None = Query(None),
) -> list[ViewingAppointment]:
    results = store.list_viewing_appointments()
    if status_filter:
        results = [r for r in results if r.status == status_filter]
    if lead_id:
        results = [r for r in results if r.lead_id == lead_id]
    if unit_id:
        results = [r for r in results if r.unit_id == unit_id]
    return results[skip : skip + limit]


@router.post("", response_model=ViewingAppointment, status_code=status.HTTP_201_CREATED)
def create_viewing(payload: ViewingAppointmentCreate) -> ViewingAppointment:
    try:
        return store.create_viewing_appointment(payload)
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/{appointment_id}", response_model=ViewingAppointment)
def get_viewing(appointment_id: str) -> ViewingAppointment:
    try:
        return store.get_viewing_appointment(appointment_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.put("/{appointment_id}", response_model=ViewingAppointment)
def update_viewing(appointment_id: str, payload: ViewingAppointmentCreate) -> ViewingAppointment:
    try:
        return store.update_viewing_appointment(appointment_id, payload)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.patch("/{appointment_id}", response_model=ViewingAppointment)
def patch_viewing(appointment_id: str, payload: ViewingAppointmentPatch) -> ViewingAppointment:
    try:
        return store._patch_entity(
            None, appointment_id, payload, "Besichtigungstermin nicht gefunden"
        )
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.delete("/{appointment_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_viewing(appointment_id: str) -> None:
    try:
        store.delete_viewing_appointment(appointment_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
