"""Bounded, explicit portfolio cash snapshots; no receivable/payment double count."""

from contextlib import contextmanager
from datetime import date
from decimal import Decimal, InvalidOperation

from fastapi import HTTPException
from sqlalchemy import String, and_, cast, select

from ..db.booking_order import bytewise_id
from ..db.orm_models import AccountORM, BookingORM, CategoryORM, PropertyORM
from .booking_export import _snapshot
from .payments import _memory_lock
from .portfolio_scope import current_scope, memory_visible, refresh_scope, scoped_clause

BATCH_SIZE = 1000  # A transfer buffer, never a record/export limit.
FIELDS = ("id", "account_id", "category_id", "property_id", "unit_id", "tenant_id", "booking_date",
          "amount", "status", "payment_text", "receipt_url", "updated_at")


def cents(value):
    if isinstance(value, bool) or value is None:
        raise ValueError("invalid_cash_amount")
    try:
        result = Decimal(str(value))
        if not result.is_finite() or result == 0 or abs(result) > Decimal("9999999999.99") or result != result.quantize(Decimal("0.01")):
            raise ValueError("invalid_cash_amount")
        return int(result * 100)
    except InvalidOperation:
        raise ValueError("invalid_cash_amount") from None


def scoped(query, model, captured):
    predicate = scoped_clause(model, scope=captured)
    return query.where(predicate) if predicate is not None else query


def _query(portfolio_id, year, captured):
    book, account, category, prop = (model.__table__ for model in (BookingORM, AccountORM, CategoryORM, PropertyORM))
    joins = book.join(account, book.c.account_id == account.c.id)
    for table, joined_model, foreign in ((category, CategoryORM, book.c.category_id), (prop, PropertyORM, book.c.property_id)):
        condition = table.c.id == foreign
        predicate = scoped_clause(joined_model, scope=captured)
        if predicate is not None:
            condition = and_(condition, predicate)
        joins = joins.outerjoin(table, condition)
    query = select(*(book.c[name] for name in FIELDS if name != "amount"), cast(book.c.amount, String).label("amount"),
        account.c.name.label("account_name"), account.c.portfolio_id.label("account_portfolio_id"),
        category.c.name.label("category_name"), category.c.portfolio_id.label("category_portfolio_id"),
        prop.c.name.label("property_name"), prop.c.portfolio_id.label("property_portfolio_id"))
    query = query.select_from(joins).where(account.c.portfolio_id == portfolio_id,
        book.c.booking_date >= date(year, 1, 1), book.c.booking_date < date(year + 1, 1, 1))
    for model in (BookingORM, AccountORM):
        query = scoped(query, model, captured)
    return query


def _safe_entry(row):
    result = dict(row)
    for key in ("booking_date", "updated_at"):
        if result[key] is not None:
            result[key] = result[key].isoformat()
    result["amount"] = str(result["amount"])
    return result


@contextmanager
def cash_source(store, portfolio_id, year):
    """Include pending/future entries as excluded review evidence, not income."""
    captured = current_scope()
    store.get_portfolio(portfolio_id)
    if hasattr(store, "db"):
        with _snapshot(store.db.get_bind()) as connection:
            # An authorized account with hidden cross-references cannot yield a
            # falsely complete portfolio tax report. Reveal no hidden IDs/data.
            predicate = scoped_clause(BookingORM, scope=captured)
            if predicate is not None:
                hidden = select(1).select_from(BookingORM.__table__.join(AccountORM.__table__)).where(
                    AccountORM.portfolio_id == portfolio_id, BookingORM.booking_date >= date(year, 1, 1),
                    BookingORM.booking_date < date(year + 1, 1, 1), ~predicate).limit(1)
                if connection.scalar(hidden):
                    raise HTTPException(403, "annual_tax_source_scope_incomplete: Die Objektbezüge müssen durch die Verwaltung geprüft werden.")

            def iterator():
                after = None
                base = _query(portfolio_id, year, captured)
                while True:
                    query = base
                    if after:
                        day, identifier = after
                        query = query.where((BookingORM.booking_date > day) | and_(BookingORM.booking_date == day, bytewise_id(BookingORM.id) > identifier))
                    rows = connection.execute(query.order_by(BookingORM.booking_date, bytewise_id(BookingORM.id)).limit(BATCH_SIZE)).mappings().all()
                    if not rows:
                        return
                    refresh_scope(captured)
                    for row in rows:
                        yield _safe_entry(row)
                    after = rows[-1]["booking_date"], rows[-1]["id"]
            yield iterator()
    else:
        with _memory_lock:
            raw = object.__getattribute__(store, "__dict__")
            if captured is not None and not captured.unrestricted:
                for booking in raw["bookings"].values():
                    account = raw["accounts"].get(booking.account_id)
                    if (account and account.portfolio_id == portfolio_id and booking.booking_date.year == year
                            and not memory_visible(store, "bookings", booking, scope=captured)):
                        raise HTTPException(403, "annual_tax_source_scope_incomplete: Die Objektbezüge müssen durch die Verwaltung geprüft werden.")
            entries = []
            for booking in store.bookings.values():
                account = store.get_account(booking.account_id)
                if account.portfolio_id != portfolio_id or booking.booking_date.year != year:
                    continue
                category = store.get_category(booking.category_id) if booking.category_id else None
                prop = store.get_property(booking.property_id) if booking.property_id else None
                row = booking.model_dump(include=set(FIELDS))
                row.update(account_name=account.name, account_portfolio_id=account.portfolio_id,
                    category_name=category.name if category else None, category_portfolio_id=category.portfolio_id if category else None,
                    property_name=prop.name if prop else None, property_portfolio_id=prop.portfolio_id if prop else None)
                entries.append(_safe_entry(row))
            entries.sort(key=lambda row: (row["booking_date"], row["id"].encode()))
        def iterator():
            for index, row in enumerate(entries):
                if index % BATCH_SIZE == 0:
                    refresh_scope(captured)
                yield row
        yield iterator()
    refresh_scope(captured)
