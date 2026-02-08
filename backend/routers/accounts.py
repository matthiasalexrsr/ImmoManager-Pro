from fastapi import APIRouter, HTTPException, status

from ..models import Account, AccountCreate
from ..routers.portfolios import store
from ..storage import NotFoundError, ValidationError

router = APIRouter(prefix="/accounts", tags=["Konten"])


@router.get("", response_model=list[Account])
def list_accounts() -> list[Account]:
    return store.list_accounts()


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
