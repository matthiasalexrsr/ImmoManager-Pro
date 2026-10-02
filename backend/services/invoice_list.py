"""Bounded invoice reads: filter dates in SQL before pagination."""
from collections.abc import Iterable
from itertools import islice
from typing import Any

from sqlalchemy import select

from ..db.orm_models import InvoiceORM
from ..models import Invoice
from .portfolio_scope import scoped_clause

SORT_FIELDS = frozenset(InvoiceORM.__table__.columns.keys())


def filtered_invoices(store, *, skip, limit, filters, sort_by, descending, date_from, date_to):
    if hasattr(store, "db"):
        statement = select(InvoiceORM.__table__)
        predicate = scoped_clause(InvoiceORM.__table__)
        if predicate is not None:
            statement = statement.where(predicate)
        for field, value in filters.items():
            if value is not None:
                statement = statement.where(getattr(InvoiceORM, field) == value)
        if date_from:
            statement = statement.where(InvoiceORM.invoice_date >= date_from)
        if date_to:
            statement = statement.where(InvoiceORM.invoice_date <= date_to)
        if sort_by in SORT_FIELDS:
            column = getattr(InvoiceORM, sort_by)
            statement = statement.order_by(column.desc() if descending else column.asc())
        with store.db.no_autoflush:
            return [Invoice.model_validate(row) for row in store.db.execute(statement.offset(skip).limit(limit)).mappings()]
    values: Iterable[Any] = (item for item in store.invoices.values()
        if all(value is None or getattr(item, field) == value for field, value in filters.items())
        and (date_from is None or item.invoice_date >= date_from)
        and (date_to is None or item.invoice_date <= date_to))
    if sort_by in SORT_FIELDS:
        values = sorted(values, key=lambda item: (getattr(item, sort_by) is None, getattr(item, sort_by)), reverse=descending)
    return list(islice(values, skip, skip + limit))
