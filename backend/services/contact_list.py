"""Keep the original full contact DTO while applying scope and pagination in SQL."""

from functools import cmp_to_key
from heapq import nsmallest
from itertools import islice

from sqlalchemy import select

from ..db.booking_order import bytewise_id
from ..db.orm_models import ContactORM
from ..models import Contact
from .contract_workspace import _compare
from .portfolio_scope import current_scope, memory_visible, refresh_scope, scoped_clause


def contact_list(store, *, skip, limit, contact_type, sort_by, descending):
    scope = current_scope()
    refresh_scope(scope)
    table = ContactORM.__table__
    sort_by = sort_by if isinstance(sort_by, str) and sort_by in table.c else "id"
    if hasattr(store, "db"):
        source = select(table)
        visibility = scoped_clause(table, scope=scope)
        if visibility is not None:
            source = source.where(visibility)
        if contact_type:
            source = source.where(table.c.contact_type == contact_type)
        column = table.c[sort_by]
        if column.type.python_type is str:
            column = bytewise_id(column)
        identifier = bytewise_id(table.c.id)
        source = source.order_by(column.desc().nulls_last() if descending else column.asc().nulls_last(),
                                 identifier.desc() if descending else identifier.asc()).offset(skip).limit(limit)
        with store.db.no_autoflush:
            result = [Contact.model_validate(row) for row in store.db.execute(source).mappings()]
    else:
        from .payments import _memory_lock
        with _memory_lock:
            raw = object.__getattribute__(store, "__dict__")["contacts"]
            rows = (row for row in raw.values() if memory_visible(store, "contacts", row, scope=scope)
                    and (not contact_type or row.contact_type == contact_type))
            def compare(first, second):
                return _compare((getattr(first, sort_by), first.id), (getattr(second, sort_by), second.id), descending)
            result = list(islice(nsmallest(skip + limit, rows, key=cmp_to_key(compare)), skip, skip + limit))
    refresh_scope(scope)
    return result
