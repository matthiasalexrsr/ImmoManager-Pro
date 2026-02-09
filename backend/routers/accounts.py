from fastapi import APIRouter, HTTPException, Query, status

from ..dependencies import store
from ..models import Account, AccountCreate
from ..storage import NotFoundError, ValidationError

router = APIRouter(prefix="/accounts", tags=["Konten"])


@router.get("", response_model=list[Account])
def list_accounts(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    portfolio_id: str | None = Query(None),
    account_type: str | None = Query(None),
) -> list[Account]:
    results = store.list_accounts()
    if portfolio_id:
        results = [a for a in results if a.portfolio_id == portfolio_id]
    if account_type:
        results = [a for a in results if a.account_type == account_type]
    return results[skip : skip + limit]


@router.post("", response_model=Account, status_code=status.HTTP_201_CREATED)
def create_account(payload: AccountCreate) -> Account:
    try:
        return store.create_account(payload)
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/{account_id}", response_model=Account)
def get_account(account_id: str) -> Account:
    try:
        return store.get_account(account_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.put("/{account_id}", response_model=Account)
def update_account(account_id: str, payload: AccountCreate) -> Account:
    try:
        return store.update_account(account_id, payload)
    except (NotFoundError, ValidationError) as exc:
        status_code = status.HTTP_404_NOT_FOUND if isinstance(exc, NotFoundError) else status.HTTP_400_BAD_REQUEST
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc


@router.delete("/{account_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_account(account_id: str) -> None:
    try:
        store.delete_account(account_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
