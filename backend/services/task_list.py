"""Date-filtered task pages without a hidden 10,000-row inventory cap."""

from collections.abc import Iterable
from datetime import date
from heapq import nlargest, nsmallest
from itertools import islice
from typing import Any

from sqlalchemy import select

from ..db.orm_models import TaskORM
from ..models import Task
from .portfolio_scope import memory_visible, scoped_clause

SORT_FIELDS = frozenset(TaskORM.__table__.columns.keys())


def filtered_tasks(
    store: Any,
    *,
    skip: int,
    limit: int,
    filters: dict[str, str | None],
    sort_by: str | None,
    descending: bool,
    date_from: date | None,
    date_to: date | None,
) -> list[Task]:
    """Apply due-date filters and authorization before offset/limit."""
    if hasattr(store, "db"):
        table = TaskORM.__table__
        statement = select(table)
        visibility = scoped_clause(table)
        if visibility is not None:
            statement = statement.where(visibility)
        for field in ("status", "assignee"):
            value = filters.get(field)
            if value is not None:
                statement = statement.where(table.c[field] == value)
        if date_from is not None:
            statement = statement.where(table.c.due_date >= date_from)
        if date_to is not None:
            statement = statement.where(table.c.due_date <= date_to)
        if sort_by in SORT_FIELDS:
            column = table.c[sort_by]
            statement = statement.order_by(column.desc() if descending else column.asc())
        with store.db.no_autoflush:
            return [
                Task.model_validate(row)
                for row in store.db.execute(statement.offset(skip).limit(limit)).mappings()
            ]

    from .payments import _memory_lock

    with _memory_lock:
        raw = object.__getattribute__(store, "__dict__")["tasks"]
        values: Iterable[Task] = (
            item
            for item in raw.values()
            if memory_visible(store, "tasks", item)
            and all(value is None or getattr(item, field) == value for field, value in filters.items())
            and (date_from is None or (item.due_date is not None and item.due_date >= date_from))
            and (date_to is None or (item.due_date is not None and item.due_date <= date_to))
        )
        if sort_by in SORT_FIELDS:
            def key(item: Task):
                value = getattr(item, sort_by)
                return value is None, value

            values = (nlargest if descending else nsmallest)(skip + limit, values, key=key)
        return list(islice(values, skip, skip + limit))
