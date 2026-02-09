from fastapi import APIRouter, HTTPException, Query, status

from ..dependencies import store
from ..models import Property, PropertyCreate
from ..storage import NotFoundError, ValidationError

router = APIRouter(prefix="/properties", tags=["Immobilien"])


@router.get("", response_model=list[Property])
def list_properties(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    portfolio_id: str | None = Query(None),
    status_filter: str | None = Query(None, alias="status"),
) -> list[Property]:
    results = store.list_properties()
    if portfolio_id:
        results = [p for p in results if p.portfolio_id == portfolio_id]
    if status_filter:
        results = [p for p in results if p.status == status_filter]
    return results[skip : skip + limit]


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


@router.delete("/{property_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_property(property_id: str) -> None:
    try:
        store.delete_property(property_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
