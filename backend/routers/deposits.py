from fastapi import APIRouter, HTTPException, Query, status

from ..dependencies import store
from ..models import Deposit, DepositCreate, DepositPatch
from ..storage import NotFoundError, ValidationError

router = APIRouter(prefix="/deposits", tags=["Kautionen"])


@router.get("", response_model=list[Deposit])
def list_deposits(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    contract_id: str | None = Query(None),
    status_filter: str | None = Query(None, alias="status"),
) -> list[Deposit]:
    results = store.list_deposits()
    if contract_id:
        results = [r for r in results if r.contract_id == contract_id]
    if status_filter:
        results = [r for r in results if r.status == status_filter]
    return results[skip : skip + limit]


@router.post("", response_model=Deposit, status_code=status.HTTP_201_CREATED)
def create_deposit(payload: DepositCreate) -> Deposit:
    try:
        return store.create_deposit(payload)
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/{deposit_id}", response_model=Deposit)
def get_deposit(deposit_id: str) -> Deposit:
    try:
        return store.get_deposit(deposit_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.put("/{deposit_id}", response_model=Deposit)
def update_deposit(deposit_id: str, payload: DepositCreate) -> Deposit:
    try:
        return store.update_deposit(deposit_id, payload)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.patch("/{deposit_id}", response_model=Deposit)
def patch_deposit(deposit_id: str, payload: DepositPatch) -> Deposit:
    try:
        return store._patch_entity(None, deposit_id, payload, "Kaution nicht gefunden")
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.delete("/{deposit_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_deposit(deposit_id: str) -> None:
    try:
        store.delete_deposit(deposit_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
