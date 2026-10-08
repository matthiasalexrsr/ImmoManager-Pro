from fastapi import APIRouter, HTTPException, Query, status

from ..dependencies import store
from ..models import Deposit, DepositCreate, DepositPatch
from ..storage import NotFoundError, ValidationError
from ._helpers import apply_sort

router = APIRouter(prefix="/deposits", tags=["Kautionen"])


@router.get("", response_model=list[Deposit])
def list_deposits(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    contract_id: str | None = Query(None),
    status_filter: str | None = Query(None, alias="status"),
    sort_by: str | None = Query(None),
    sort_order: str = Query("asc"),
) -> list[Deposit]:
    results = store.list_deposits()
    if contract_id:
        results = [r for r in results if r.contract_id == contract_id]
    if status_filter:
        results = [r for r in results if r.status == status_filter]
    results = apply_sort(results, sort_by, sort_order)
    return results[skip : skip + limit]


def _check_amounts(deposit: DepositCreate) -> None:
    """Reject amounts that cannot be right; kept out of the model so existing records stay readable."""
    problem = None
    if deposit.amount <= 0:
        problem = "Der Kautionsbetrag muss größer als 0 sein"
    elif deposit.deductions is not None and deposit.deductions < 0:
        problem = "Abzüge dürfen nicht negativ sein"
    elif deposit.deductions is not None and deposit.deductions > deposit.amount:
        problem = "Abzüge dürfen die Kaution nicht übersteigen; weitergehende Ansprüche sind eine eigene Forderung"
    elif deposit.held_date and deposit.return_date and deposit.return_date < deposit.held_date:
        problem = "Das Rückgabedatum liegt vor dem Eingangsdatum"
    if problem:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=problem)


@router.post("", response_model=Deposit, status_code=status.HTTP_201_CREATED)
def create_deposit(payload: DepositCreate) -> Deposit:
    _check_amounts(payload)
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
    _check_amounts(payload)
    try:
        return store.update_deposit(deposit_id, payload)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.patch("/{deposit_id}", response_model=Deposit)
def patch_deposit(deposit_id: str, payload: DepositPatch) -> Deposit:
    try:
        current = store.get_deposit(deposit_id)
        merged = DepositCreate.model_validate({
            **current.model_dump(include=set(DepositCreate.model_fields)),
            **payload.model_dump(exclude_unset=True),
        })
        _check_amounts(merged)
        return store._patch_entity("deposit", deposit_id, payload)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.delete("/{deposit_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_deposit(deposit_id: str) -> None:
    try:
        store.delete_deposit(deposit_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
