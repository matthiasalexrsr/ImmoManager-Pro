from datetime import date

from fastapi import APIRouter, HTTPException, Query, status

from ..dependencies import store
from ..domain.occupancy import unit_statuses_on
from ..models import Unit, UnitCreate, UnitPatch
from ..services.deletion_guard import ensure_deletable
from ..services.document_versions import ensure_binding_kept
from ..storage import NotFoundError, ValidationError

router = APIRouter(prefix="/units", tags=["Einheiten"])


def _current(units: list[Unit]) -> list[Unit]:
    """Units with today's status: occupied follows the contracts, not a stored flag."""
    statuses = unit_statuses_on(date.today(), units, store.list_contracts())
    return [u if u.status == statuses[u.id] else u.model_copy(update={"status": statuses[u.id]}) for u in units]


@router.get("", response_model=list[Unit])
def list_units(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    property_id: str | None = Query(None),
    status_filter: str | None = Query(None, alias="status"),
    sort_by: str | None = Query(None),
    sort_order: str = Query("asc"),
) -> list[Unit]:
    def page(skip: int, limit: int) -> list[Unit]:
        return store._list_paginated(
            entity_type="unit",
            skip=skip,
            limit=limit,
            filters={"property_id": property_id},
            order_by=sort_by,
            order_desc=(sort_order == "desc"),
        )

    if status_filter is None:
        return _current(page(skip, limit))
    # The status depends on today's contracts, so filter after computing it.
    matching = [u for u in _current(page(0, store.count_entities("unit") or 1)) if u.status == status_filter]
    return matching[skip : skip + limit]


@router.post("", response_model=Unit, status_code=status.HTTP_201_CREATED)
def create_unit(payload: UnitCreate) -> Unit:
    try:
        return _current([store.create_unit(payload)])[0]
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/{unit_id}", response_model=Unit)
def get_unit(unit_id: str) -> Unit:
    try:
        return _current([store.get_unit(unit_id)])[0]
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.put("/{unit_id}", response_model=Unit)
def update_unit(unit_id: str, payload: UnitCreate) -> Unit:
    try:
        ensure_binding_kept(store, "unit", unit_id, store.get_unit(unit_id), payload.model_dump())
        return _current([store.update_unit(unit_id, payload)])[0]
    except (NotFoundError, ValidationError) as exc:
        status_code = status.HTTP_404_NOT_FOUND if isinstance(exc, NotFoundError) else status.HTTP_400_BAD_REQUEST
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc


@router.patch("/{unit_id}", response_model=Unit)
def patch_unit(unit_id: str, payload: UnitPatch) -> Unit:
    try:
        ensure_binding_kept(store, "unit", unit_id, store.get_unit(unit_id), payload.model_dump(exclude_unset=True))
        return _current([store._patch_entity("unit", unit_id, payload)])[0]
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.delete("/{unit_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_unit(unit_id: str) -> None:
    try:
        ensure_deletable(store, "unit", unit_id)
        store.delete_unit(unit_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
