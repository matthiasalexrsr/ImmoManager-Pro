from fastapi import APIRouter, HTTPException, status

from ..models import Property, PropertyCreate
from ..routers.portfolios import store
from ..storage import NotFoundError, ValidationError

router = APIRouter(prefix="/properties", tags=["Immobilien"])


@router.get("", response_model=list[Property])
def list_properties() -> list[Property]:
    return store.list_properties()


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
