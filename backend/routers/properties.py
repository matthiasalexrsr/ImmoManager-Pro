from fastapi import APIRouter, HTTPException, Query, status

from ..dependencies import store
from ..models import Property, PropertyCreate, PropertyPatch
from ..storage import NotFoundError, ValidationError

router = APIRouter(prefix="/properties", tags=["Immobilien"])


@router.get("", response_model=list[Property])
def list_properties(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    portfolio_id: str | None = Query(None),
    status_filter: str | None = Query(None, alias="status"),
    sort_by: str | None = Query(None),
    sort_order: str = Query("asc"),
) -> list[Property]:
    filters = {"portfolio_id": portfolio_id, "status": status_filter}
    results = store._list_paginated(
        entity_type="property",
        skip=skip,
        limit=limit,
        filters=filters,
        order_by=sort_by,
        order_desc=(sort_order == "desc"),
    )
    return results


@router.post("", response_model=Property, status_code=status.HTTP_201_CREATED)
def create_property(payload: PropertyCreate) -> Property:
    try:
        return store.create_property(payload)
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/{property_id}", response_model=Property)
def get_property(property_id: str) -> Property:
    try:
        return store.get_property(property_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.put("/{property_id}", response_model=Property)
def update_property(property_id: str, payload: PropertyCreate) -> Property:
    try:
        return store.update_property(property_id, payload)
    except (NotFoundError, ValidationError) as exc:
        status_code = status.HTTP_404_NOT_FOUND if isinstance(exc, NotFoundError) else status.HTTP_400_BAD_REQUEST
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc


@router.patch("/{property_id}", response_model=Property)
def patch_property(property_id: str, payload: PropertyPatch) -> Property:
    try:
        return store._patch_entity("property", property_id, payload)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.delete("/{property_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_property(property_id: str) -> None:
    try:
        store.delete_property(property_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
