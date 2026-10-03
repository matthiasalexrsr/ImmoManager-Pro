"""Legacy due-date pages apply filters before bounded database retrieval."""

from datetime import date
from functools import cmp_to_key
from heapq import nsmallest
from itertools import islice

from sqlalchemy import select

from ..db.booking_order import bytewise_id
from ..db.orm_models import MaintenanceCaseORM
from ..models import MaintenanceCase
from .contract_workspace import _compare
from .portfolio_scope import current_scope, memory_visible, refresh_scope, scoped_clause

SORT_FIELDS = frozenset(MaintenanceCaseORM.__table__.columns.keys())


def filtered_maintenance(store, *, skip: int, limit: int, filters: dict[str, str | None],
                         sort_by: str | None, descending: bool, date_from: date | None,
                         date_to: date | None) -> list[MaintenanceCase]:
    scope = current_scope()
    refresh_scope(scope)
    sort_by = sort_by if sort_by in SORT_FIELDS else "id"
    if hasattr(store, "db"):
        table = MaintenanceCaseORM.__table__
        statement = select(table)
        visibility = scoped_clause(table, scope=scope)
        if visibility is not None:
            statement = statement.where(visibility)
        for field in ("property_id", "status"):
            if filters.get(field) is not None:
                statement = statement.where(table.c[field] == filters[field])
        if date_from is not None:
            statement = statement.where(table.c.due_date >= date_from)
        if date_to is not None:
            statement = statement.where(table.c.due_date <= date_to)
        column = table.c[sort_by]
        if column.type.python_type is str:
            column = bytewise_id(column)
        identifier = bytewise_id(table.c.id)
        statement = statement.order_by(column.desc().nulls_last() if descending else column.asc().nulls_last(),
                                       identifier.desc() if descending else identifier.asc())
        with store.db.no_autoflush:
            result = [MaintenanceCase.model_validate(row) for row in
                      store.db.execute(statement.offset(skip).limit(limit)).mappings()]
    else:
        from .payments import _memory_lock

        with _memory_lock:
            raw = object.__getattribute__(store, "__dict__")["maintenance_cases"]
            values = (item for item in raw.values() if memory_visible(store, "maintenance_cases", item, scope=scope)
                      and all(value is None or getattr(item, field) == value for field, value in filters.items())
                      and (date_from is None or item.due_date is not None and item.due_date >= date_from)
                      and (date_to is None or item.due_date is not None and item.due_date <= date_to))

            def compare(first, second):
                return _compare((getattr(first, sort_by), first.id), (getattr(second, sort_by), second.id), descending)

            result = list(islice(nsmallest(skip + limit, values, key=cmp_to_key(compare)), skip, skip + limit))
    refresh_scope(scope)
    return result
