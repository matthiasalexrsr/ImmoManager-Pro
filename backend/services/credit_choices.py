"""Bounded, scoped live choices; the receipt transaction rechecks all budgets."""

import heapq
from typing import Any, Literal

from pydantic import BaseModel
from sqlalchemy import String, cast, func, or_, select

from ..db.booking_order import bytewise_id
from ..db.orm_models import AccountORM, BookingORM, ReceivableORM, RentChargeORM
from .booking_lookup import BookingLookupQuery, _after, _cursor
from .booking_query import BookingQueryError, maximum_page_size
from .credit_ledger import cents, money
from .portfolio_scope import scoped_clause

CreditChoiceKind = Literal["rent_charge", "receivable", "booking"]
MODELS: dict[str, Any] = {"rent_charge": RentChargeORM, "receivable": ReceivableORM, "booking": BookingORM}
COLLECTIONS = {"rent_charge": "rent_charges", "receivable": "receivables", "booking": "bookings"}
RENT_FIELDS = ("cold_rent", "service_charge", "heating_charge", "other_charges")


class CreditChoice(BaseModel):
    id: str
    kind: CreditChoiceKind
    date: str
    text: str
    available_amount: str


class CreditChoices(BaseModel):
    contract_id: str
    items: list[CreditChoice]
    selected: CreditChoice | None
    next_cursor: str | None
    has_more: bool


def _choice(row, kind):
    if kind == "booking":
        amount = -cents(row.amount) - cents(row.allocated_amount or 0)
        date, text = str(row.booking_date), row.payment_text or ""
    elif kind == "receivable":
        amount = cents(row.amount_due) - cents(row.amount_paid or 0)
        date, text = str(row.due_date), row.description or ""
    else:
        amount = sum(cents(getattr(row, field) or 0) for field in RENT_FIELDS) - cents(row.amount_paid or 0)
        date, text = row.month, ""
    return CreditChoice(id=row.id, kind=kind, date=date, text=text, available_amount=str(money(amount)))


def credit_choices(store, contract_id: str, kind: CreditChoiceKind, query: BookingLookupQuery):
    contract = store.get_contract(contract_id)
    portfolio_id = store.get_property(contract.property_id).portfolio_id
    if query.page_size > maximum_page_size():
        raise BookingQueryError("page_size_exceeded", "Bitte eine kleinere Auswahlseite verwenden; weitere Seiten bleiben verfügbar.")
    binding = f"credit-choices:{contract_id}:{kind}"
    after = _after(binding, query)
    selected = None
    if hasattr(store, "db"):
        model = MODELS[kind]
        statement = select(model)
        if kind == "booking":
            statement = statement.join(AccountORM, AccountORM.id == BookingORM.account_id).where(
                AccountORM.portfolio_id == portfolio_id, BookingORM.amount < 0,
                -BookingORM.amount > func.coalesce(BookingORM.allocated_amount, 0))
            for field in ("tenant_id", "property_id", "unit_id"):
                column = getattr(model, field)
                statement = statement.where(or_(column.is_(None), column == getattr(contract, field)))
            search_column = model.payment_text
            date_column = model.booking_date
        else:
            total = model.amount_due if kind == "receivable" else sum(func.coalesce(getattr(model, field), 0) for field in RENT_FIELDS)
            statement = statement.where(model.contract_id == contract_id,
                model.status.not_in(("cancelled", "void", "paid")), total > func.coalesce(model.amount_paid, 0))
            search_column = model.description if kind == "receivable" else model.month
            date_column = model.due_date if kind == "receivable" else model.month
        scope = scoped_clause(model)
        if scope is not None:
            statement = statement.where(scope)
        if query.selected_id:
            selected_row = store.db.scalar(statement.where(model.id == query.selected_id))
            selected = _choice(selected_row, kind) if selected_row else None
        if query.search:
            escaped = query.search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            search = f"%{escaped}%"
            statement = statement.where(or_(model.id.ilike(search, escape="\\"), search_column.ilike(search, escape="\\"),
                                            cast(date_column, String).ilike(search, escape="\\")))
        if after is not None:
            statement = statement.where(bytewise_id(model.id) < after)
        rows = [_choice(row, kind) for row in store.db.scalars(
            statement.order_by(bytewise_id(model.id).desc()).limit(query.page_size + 1))]
    else:
        accounts = store.accounts

        def eligible(row):
            if kind == "booking":
                account = accounts.get(row.account_id)
                if not account or account.portfolio_id != portfolio_id or row.amount >= 0:
                    return False
                if any(getattr(row, field) and getattr(row, field) != getattr(contract, field)
                       for field in ("tenant_id", "property_id", "unit_id")):
                    return False
            elif row.contract_id != contract_id or row.status in {"cancelled", "void", "paid"}:
                return False
            return cents(_choice(row, kind).available_amount) > 0

        collection = getattr(store, COLLECTIONS[kind])
        selected_row = collection.get(query.selected_id)
        if selected_row and eligible(selected_row):
            selected = _choice(selected_row, kind)
        candidates = (row for row in collection.values() if eligible(row) and
                      (after is None or row.id < after) and (not query.search or
                      query.search.lower() in (row.id + " " + _choice(row, kind).text + " " + _choice(row, kind).date).lower()))
        rows = [_choice(row, kind) for row in heapq.nlargest(query.page_size + 1, candidates, key=lambda row: row.id)]
    has_more = len(rows) > query.page_size
    rows = rows[:query.page_size]
    return CreditChoices(contract_id=contract_id, items=rows, selected=selected,
                         has_more=has_more, next_cursor=_cursor(binding, query, rows[-1]) if has_more else None)
