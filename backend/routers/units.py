from fastapi import APIRouter, HTTPException, Query, status

from ..dependencies import store
from ..models import Unit, UnitCreate, UnitPatch
from ..storage import NotFoundError, ValidationError

router = APIRouter(prefix="/units", tags=["Einheiten"])


@router.get("", response_model=list[Unit])
def list_units(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    property_id: str | None = Query(None),
    status_filter: str | None = Query(None, alias="status"),
    sort_by: str | None = Query(None),
    sort_order: str = Query("asc"),
) -> list[Unit]:
    filters = {"property_id": property_id, "status": status_filter}
    results = store._list_paginated(
        entity_type="unit",
        skip=skip,
        limit=limit,
        filters=filters,
        order_by=sort_by,
        order_desc=(sort_order == "desc"),
    )
    return results


@router.post("", response_model=Unit, status_code=status.HTTP_201_CREATED)
def create_unit(payload: UnitCreate) -> Unit:
    try:
        return store.create_unit(payload)
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/{unit_id}", response_model=Unit)
def get_unit(unit_id: str) -> Unit:
    try:
        return store.get_unit(unit_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.put("/{unit_id}", response_model=Unit)
def update_unit(unit_id: str, payload: UnitCreate) -> Unit:
    try:
        return store.update_unit(unit_id, payload)
    except (NotFoundError, ValidationError) as exc:
        status_code = status.HTTP_404_NOT_FOUND if isinstance(exc, NotFoundError) else status.HTTP_400_BAD_REQUEST
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc


@router.patch("/{unit_id}", response_model=Unit)
def patch_unit(unit_id: str, payload: UnitPatch) -> Unit:
    try:
        return store._patch_entity("unit", unit_id, payload)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.delete("/{unit_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_unit(unit_id: str) -> None:
    try:
        store.delete_unit(unit_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
