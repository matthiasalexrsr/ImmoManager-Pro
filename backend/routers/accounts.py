from fastapi import APIRouter, HTTPException, Query, status

from ..dependencies import store
from ..models import Account, AccountCreate, AccountPatch
from ..services.deletion_guard import ensure_deletable
from ..storage import NotFoundError, ValidationError
from ._helpers import apply_sort

router = APIRouter(prefix="/accounts", tags=["Konten"])


def _with_balances(accounts: list[Account]) -> list[Account]:
    """The balance is the opening balance plus every booking on the account."""
    moved: dict[str, float] = {}
    for booking in store.list_bookings():
        moved[booking.account_id] = moved.get(booking.account_id, 0.0) + booking.amount
    return [
        a.model_copy(update={"balance": round((a.opening_balance or 0.0) + moved.get(a.id, 0.0), 2)})
        for a in accounts
    ]


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
    results = apply_sort(_with_balances(results), sort_by, sort_order)
    return results[skip : skip + limit]


@router.post("", response_model=Account, status_code=status.HTTP_201_CREATED)
def create_account(payload: AccountCreate) -> Account:
    try:
        return _with_balances([store.create_account(payload)])[0]
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/{account_id}", response_model=Account)
def get_account(account_id: str) -> Account:
    try:
        return _with_balances([store.get_account(account_id)])[0]
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.put("/{account_id}", response_model=Account)
def update_account(account_id: str, payload: AccountCreate) -> Account:
    try:
        return _with_balances([store.update_account(account_id, payload)])[0]
    except (NotFoundError, ValidationError) as exc:
        status_code = status.HTTP_404_NOT_FOUND if isinstance(exc, NotFoundError) else status.HTTP_400_BAD_REQUEST
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc


@router.patch("/{account_id}", response_model=Account)
def patch_account(account_id: str, payload: AccountPatch) -> Account:
    try:
        return _with_balances([store._patch_entity("account", account_id, payload)])[0]
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.delete("/{account_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_account(account_id: str) -> None:
    try:
        ensure_deletable(store, "account", account_id)
        store.delete_account(account_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
