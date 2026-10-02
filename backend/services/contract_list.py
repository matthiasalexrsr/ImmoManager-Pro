"""Date-filtered contract pages without materializing the full SQL inventory."""

from collections.abc import Iterable
from datetime import date
from heapq import nlargest, nsmallest
from itertools import islice
from typing import Any

from sqlalchemy import select

from ..db.orm_models import ContractORM
from ..models import Contract
from .portfolio_scope import memory_visible, scoped_clause

SORT_FIELDS = frozenset(ContractORM.__table__.columns.keys())


def filtered_contracts(
    store: Any, *, skip: int, limit: int, filters: dict[str, str | None],
    sort_by: str | None, descending: bool, date_from: date | None, date_to: date | None,
) -> list[Contract]:
    """Apply exact start/end boundaries and visibility before offset/limit."""
    if hasattr(store, "db"):
        table = ContractORM.__table__
        statement = select(table)
        visibility = scoped_clause(table)
        if visibility is not None:
            statement = statement.where(visibility)
        for field in ("property_id", "tenant_id", "status"):
            if filters.get(field) is not None:
                statement = statement.where(table.c[field] == filters[field])
        if date_from is not None:
            statement = statement.where(table.c.start_date >= date_from)
        if date_to is not None:
            # SQL NULL comparison excludes open-ended contracts, as before.
            statement = statement.where(table.c.end_date <= date_to)
        if sort_by in SORT_FIELDS:
            column = table.c[sort_by]
            statement = statement.order_by(column.desc() if descending else column.asc())
        with store.db.no_autoflush:
            return [Contract.model_validate(row) for row in store.db.execute(statement.offset(skip).limit(limit)).mappings()]

    # ScopedCollection.__iter__ materializes every visible key. Iterate the raw
    # memory reference instead, retaining the same authoritative scope check.
    from .payments import _memory_lock
    with _memory_lock:
        return _memory_contracts(store, skip=skip, limit=limit, filters=filters,
            sort_by=sort_by, descending=descending, date_from=date_from, date_to=date_to)


def _memory_contracts(
    store: Any, *, skip: int, limit: int, filters: dict[str, str | None],
    sort_by: str | None, descending: bool, date_from: date | None, date_to: date | None,
) -> list[Contract]:
    """Caller holds the write lock through visibility checks and selection."""
    collection = object.__getattribute__(store, "__dict__")["contracts"]
    values: Iterable[Contract] = (
        item for item in collection.values()
        if memory_visible(store, "contracts", item)
        and all(value is None or getattr(item, field) == value for field, value in filters.items())
        and (date_from is None or item.start_date >= date_from)
        and (date_to is None or (item.end_date is not None and item.end_date <= date_to))
    )
    if sort_by in SORT_FIELDS:
        # Retain only the requested prefix, rather than sorting/copying every
        # matching contract into another list in the memory adapter.
        def key(item: Contract) -> tuple[bool, Any]:
            value = getattr(item, sort_by)
            return value is None, value

        values = (nlargest if descending else nsmallest)(skip + limit, values, key=key)
    return list(islice(values, skip, skip + limit))
