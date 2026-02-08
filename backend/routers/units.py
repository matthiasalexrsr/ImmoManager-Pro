from fastapi import APIRouter, HTTPException, status

from ..models import Unit, UnitCreate
from ..routers.portfolios import store
from ..storage import NotFoundError, ValidationError

router = APIRouter(prefix="/units", tags=["Einheiten"])


@router.get("", response_model=list[Unit])
def list_units() -> list[Unit]:
    return store.list_units()


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


@router.delete("/{unit_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_unit(unit_id: str) -> None:
    try:
        store.delete_unit(unit_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
