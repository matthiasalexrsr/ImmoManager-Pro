from datetime import date
from decimal import Decimal

from fastapi import APIRouter, HTTPException, Query, status

from ..dependencies import store
from ..domain.clock import local_today
from ..domain.money import ZERO, as_number, money
from ..models import Account, AccountCreate, AccountPatch
from ..services.deletion_guard import ensure_deletable
from ..services.finance_ledger import FinanceFilter, booking_totals
from ..services.ownership import owner_balances, require_owner
from ..storage import NotFoundError, ValidationError
from ._helpers import apply_sort

router = APIRouter(prefix="/accounts", tags=["Konten"])


def _with_balances(accounts: list[Account]) -> list[Account]:
    """The balance is the opening balance plus every booking on the account (summed in exact cents)."""
    moved: dict[str, Decimal] = {}
    for row in booking_totals(store, FinanceFilter(), by=("account",)):
        if row.account_id:
            moved[row.account_id] = moved.get(row.account_id, ZERO) + row.amount
    return [
        a.model_copy(update={"balance": as_number(money(a.opening_balance) + moved.get(a.id, ZERO))})
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


@router.get("/owner-balances")
def get_owner_balances(as_of: date | None = Query(None), portfolio_id: str | None = Query(None)) -> dict:
    """Each owner's part of the account balances: their accounts' opening balances and their part of
    every booking up to the day; the owners and "Ohne Eigentümer" add up to the balances."""
    return owner_balances(store, as_of or local_today(), portfolio_id or None)


@router.post("", response_model=Account, status_code=status.HTTP_201_CREATED)
def create_account(payload: AccountCreate) -> Account:
    require_owner(store, payload.owner_contact_id, "Der Kontoinhaber")
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
    require_owner(store, payload.owner_contact_id, "Der Kontoinhaber")
    try:
        return _with_balances([store.update_account(account_id, payload)])[0]
    except (NotFoundError, ValidationError) as exc:
        status_code = status.HTTP_404_NOT_FOUND if isinstance(exc, NotFoundError) else status.HTTP_400_BAD_REQUEST
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc


@router.patch("/{account_id}", response_model=Account)
def patch_account(account_id: str, payload: AccountPatch) -> Account:
    require_owner(store, payload.owner_contact_id, "Der Kontoinhaber")
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
