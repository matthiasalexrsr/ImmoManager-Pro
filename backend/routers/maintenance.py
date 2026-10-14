from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status

from ..auth import require_auth
from ..dependencies import store
from ..models import MaintenanceCase, MaintenanceCaseCreate, MaintenanceCasePatch, UserRead
from ..services import maintenance_projects as projects
from ..storage import NotFoundError, ValidationError

router = APIRouter(prefix="/maintenance", tags=["Instandhaltung"])

# Writes go through the project service: the status change is recorded in the change
# history in the same transaction and passes the project's gates (open work packages,
# active orders); a case without project data behaves as before.


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
    filters = {"property_id": property_id, "status": status_filter}
    return store._list_paginated(
        entity_type="maintenance",
        skip=skip,
        limit=limit,
        filters=filters,
        order_by=sort_by,
        order_desc=(sort_order == "desc"),
        range_filters={"due_date": (
            date_from if isinstance(date_from, date) else None,
            date_to if isinstance(date_to, date) else None,
        )},
    )


@router.post("", response_model=MaintenanceCase, status_code=status.HTTP_201_CREATED)
def create_maintenance_case(payload: MaintenanceCaseCreate,
                            actor: UserRead = Depends(require_auth)) -> MaintenanceCase:
    try:
        return projects.create_case(store, payload, projects.actor_of(actor))
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/{case_id}", response_model=MaintenanceCase)
def get_maintenance_case(case_id: str) -> MaintenanceCase:
    try:
        return store.get_maintenance_case(case_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.put("/{case_id}", response_model=MaintenanceCase)
def update_maintenance_case(case_id: str, payload: MaintenanceCaseCreate,
                            actor: UserRead = Depends(require_auth)) -> MaintenanceCase:
    try:
        return projects.update_case(store, case_id, payload.model_dump(), projects.actor_of(actor))
    except (NotFoundError, ValidationError) as exc:
        status_code = status.HTTP_404_NOT_FOUND if isinstance(exc, NotFoundError) else status.HTTP_400_BAD_REQUEST
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc


@router.patch("/{case_id}", response_model=MaintenanceCase)
def patch_maintenance_case(case_id: str, payload: MaintenanceCasePatch,
                           actor: UserRead = Depends(require_auth)) -> MaintenanceCase:
    try:
        return projects.update_case(store, case_id, payload.model_dump(exclude_unset=True), projects.actor_of(actor))
    except (NotFoundError, ValidationError) as exc:
        status_code = status.HTTP_404_NOT_FOUND if isinstance(exc, NotFoundError) else status.HTTP_400_BAD_REQUEST
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc


@router.delete("/{case_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_maintenance_case(case_id: str, actor: UserRead = Depends(require_auth)) -> None:
    try:
        projects.delete_case(store, case_id, projects.actor_of(actor))
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
