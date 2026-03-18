from datetime import date

from fastapi import APIRouter, HTTPException, Query, status

from ..dependencies import store
from ..models import MaintenanceCase, MaintenanceCaseCreate, MaintenanceCasePatch
from ..storage import NotFoundError, ValidationError
from ._helpers import apply_sort

router = APIRouter(prefix="/maintenance", tags=["Instandhaltung"])


@router.get("", response_model=list[MaintenanceCase])
def list_maintenance_cases(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    property_id: str | None = Query(None),
    status_filter: str | None = Query(None, alias="status"),
    sort_by: str | None = Query(None),
    sort_order: str = Query("asc"),
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
) -> list[MaintenanceCase]:
    results = store.list_maintenance_cases()
    if property_id:
        results = [c for c in results if c.property_id == property_id]
    if status_filter:
        results = [c for c in results if c.status == status_filter]
    if isinstance(date_from, date):
        results = [
            r for r in results
            if getattr(r, 'due_date', None)
            and r.due_date >= date_from
        ]
    if isinstance(date_to, date):
        results = [
            r for r in results
            if getattr(r, 'due_date', None)
            and r.due_date <= date_to
        ]
    results = apply_sort(results, sort_by, sort_order)
    return results[skip : skip + limit]


@router.post("", response_model=MaintenanceCase, status_code=status.HTTP_201_CREATED)
def create_maintenance_case(payload: MaintenanceCaseCreate) -> MaintenanceCase:
    try:
        return store.create_maintenance_case(payload)
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/{case_id}", response_model=MaintenanceCase)
def get_maintenance_case(case_id: str) -> MaintenanceCase:
    try:
        return store.get_maintenance_case(case_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.put("/{case_id}", response_model=MaintenanceCase)
def update_maintenance_case(case_id: str, payload: MaintenanceCaseCreate) -> MaintenanceCase:
    try:
        return store.update_maintenance_case(case_id, payload)
    except (NotFoundError, ValidationError) as exc:
        status_code = status.HTTP_404_NOT_FOUND if isinstance(exc, NotFoundError) else status.HTTP_400_BAD_REQUEST
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc


@router.patch("/{case_id}", response_model=MaintenanceCase)
def patch_maintenance_case(case_id: str, payload: MaintenanceCasePatch) -> MaintenanceCase:
    try:
        return store._patch_entity("maintenance", case_id, payload)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.delete("/{case_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_maintenance_case(case_id: str) -> None:
    try:
        store.delete_maintenance_case(case_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
