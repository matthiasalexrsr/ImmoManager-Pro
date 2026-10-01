from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import JSONResponse

from ..auth import require_auth
from ..dependencies import store
from ..models import Account, AccountCreate, AccountPatch
from ..services.account_balances import BalanceError, account_balance
from ..services.portfolio_scope import scope_from_user
from ..storage import NotFoundError, ValidationError
from ._helpers import apply_sort

router = APIRouter(prefix="/accounts", tags=["Konten"])


def _balance_response(account_id, user, **kwargs):
    try:
        return JSONResponse(content=account_balance(store, account_id, scope=scope_from_user(user.model_dump(mode="json")), **kwargs),
            headers={"Cache-Control": "no-store"})
    except BalanceError as error:
        return JSONResponse(status_code=error.status, content={"error": {"code": error.code, "message": str(error),
            "details": [{"clear_code": error.code, "recovery": "reload_account_balance"}]}}, headers={"Cache-Control": "no-store"})


@router.get("/{account_id}/balance-summary")
def get_balance_summary(account_id: str, as_of: date | None = Query(None), user=Depends(require_auth)):
    return _balance_response(account_id, user, as_of=as_of)


@router.get("/{account_id}/balance-sources")
def get_balance_sources(account_id: str, kind: Literal["issues", "bookings"] = "bookings", as_of: date | None = Query(None),
        cursor: str | None = Query(None, max_length=4096), source_hash: str | None = Query(None, pattern=r"^[a-f0-9]{64}$"),
        page_size: int = Query(25, ge=1, le=500), user=Depends(require_auth)):
    return _balance_response(account_id, user, as_of=as_of, kind=kind, cursor=cursor, source_hash=source_hash, page_size=page_size)


@router.get("", response_model=list[Account])
def list_accounts(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    portfolio_id: str | None = Query(None),
    account_type: str | None = Query(None),
    sort_by: str | None = Query(None),
    sort_order: str = Query("asc"),
) -> list[Account]:
    results = store.list_accounts()
    if portfolio_id:
        results = [a for a in results if a.portfolio_id == portfolio_id]
    if account_type:
        results = [a for a in results if a.account_type == account_type]
    results = apply_sort(results, sort_by, sort_order)
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


@router.patch("/{account_id}", response_model=Account)
def patch_account(account_id: str, payload: AccountPatch) -> Account:
    try:
        return store._patch_entity("account", account_id, payload)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.delete("/{account_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_account(account_id: str) -> None:
    try:
        store.get_account(account_id)
        from ..services.bank_import_guards import guard_bank_import_account_delete
        guard_bank_import_account_delete(store, account_id)
        store.delete_account(account_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
