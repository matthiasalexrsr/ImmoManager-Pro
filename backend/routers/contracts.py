from fastapi import APIRouter, HTTPException, status

from ..models import Contract, ContractCreate
from ..routers.portfolios import store
from ..storage import NotFoundError, ValidationError

router = APIRouter(prefix="/contracts", tags=["Verträge"])


@router.get("", response_model=list[Contract])
def list_contracts() -> list[Contract]:
    return store.list_contracts()


@router.post("", response_model=Contract, status_code=status.HTTP_201_CREATED)
def create_contract(payload: ContractCreate) -> Contract:
    try:
        return store.create_contract(payload)
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/{contract_id}", response_model=Contract)
def get_contract(contract_id: str) -> Contract:
    try:
        return store.get_contract(contract_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.put("/{contract_id}", response_model=Contract)
def update_contract(contract_id: str, payload: ContractCreate) -> Contract:
    try:
        return store.update_contract(contract_id, payload)
    except (NotFoundError, ValidationError) as exc:
        status_code = status.HTTP_404_NOT_FOUND if isinstance(exc, NotFoundError) else status.HTTP_400_BAD_REQUEST
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc


@router.delete("/{contract_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_contract(contract_id: str) -> None:
    try:
        store.delete_contract(contract_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
