"""Bounded authorized field-change reads; no inferred actions or actor names."""

import json
from dataclasses import asdict
from datetime import datetime, timezone
from heapq import nlargest
from typing import Literal

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import DateTime, and_, func, or_, select
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.sql.elements import ColumnElement
from sqlalchemy.sql.visitors import InternalTraversal

from ..db.booking_order import bytewise_id
from ..db.orm_models import ChangeHistoryORM
from ..models import ChangeHistoryEntry
from .contract_workspace import maximum_page_size
from .contract_workspace_search import UnicodeCasefold, ensure_sqlite_casefold
from .payments import _memory_lock
from .portfolio_scope import current_scope, memory_visible, refresh_scope, scoped_clause
from .reference_cursor import pack_reference_cursor, unpack_reference_cursor

FIELDS = tuple(ChangeHistoryEntry.model_fields)
TEXT_FIELDS = tuple(field for field in FIELDS if field != "changed_at")
EXACT_FIELDS = ("entity_type", "entity_id", "field_name", "changed_by")


def stamp(value):
    try:
        return value.astimezone(timezone.utc).replace(tzinfo=None) if value is not None and value.tzinfo else value
    except OverflowError:
        raise ValueError("Der Zeitpunkt liegt nach UTC-Umrechnung außerhalb des darstellbaren Bereichs.") from None


class HistoryInventoryQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    search: str | None = None
    entity_type: str | None = None
    entity_id: str | None = None
    field_name: str | None = None
    changed_by: str | None = None
    changed_from: datetime | None = None
    changed_before: datetime | None = None
    sort_by: Literal["changed_at"] = "changed_at"
    page_size: int = Field(default=25, ge=1)
    cursor: str | None = Field(default=None, min_length=1)

    @field_validator("search", *EXACT_FIELDS)
    @classmethod
    def safe_text(cls, value):
        if value is None:
            return None
        if any(ord(char) < 32 or ord(char) == 127 for char in value):
            raise ValueError("Bitte Text ohne Steuerzeichen verwenden.")
        return value.strip() or None

    @field_validator("changed_from", "changed_before")
    @classmethod
    def utc_time(cls, value):
        return stamp(value)

    @model_validator(mode="after")
    def interval(self):
        if self.changed_from is not None and self.changed_before is not None and self.changed_from >= self.changed_before:
            raise ValueError("Der Beginn muss vor dem Ende des Zeitraums liegen.")
        return self


class HistoryInventoryItem(ChangeHistoryEntry):
    # Old tables may contain an undated row. Display this absence explicitly.
    changed_at: datetime | None


class HistoryInventoryPage(BaseModel):
    items: list[HistoryInventoryItem]
    has_more: bool
    next_cursor: str | None


class Chronology(ColumnElement):
    """One typed comparator for native PG dates and both SQLite spellings."""

    type = DateTime()
    inherit_cache = False
    _traverse_internals = [("column", InternalTraversal.dp_clauseelement)]

    def __init__(self, column):
        self.column = column

    @property
    def _from_objects(self):
        return self.column._from_objects


@compiles(Chronology)
def native_chronology(element, compiler, **kwargs):
    return compiler.process(element.column, **kwargs)


@compiles(Chronology, "sqlite")
def sqlite_chronology(element, compiler, **kwargs):
    column = compiler.process(element.column, **kwargs)
    raw = "CAST(" + column + " AS VARCHAR)"
    return "(CASE WHEN length(" + raw + ") = 19 THEN " + raw + " || '.000000' ELSE " + raw + " END)"


def binding(query, scope):
    return {"kind": "change-history-inventory-v1", "query": query.model_dump(mode="json", exclude={"cursor"}),
            "sort": "utc-desc-null-last-byte-id-desc", "scope": asdict(scope) if scope is not None else None}


def position(query, scope):
    encoded = unpack_reference_cursor(query.cursor, binding(query, scope))
    if encoded is None:
        return None
    try:
        point = json.loads(encoded)
        if not isinstance(point, list) or len(point) != 2 or not isinstance(point[1], str) or not point[1]:
            raise ValueError
        if point[0] is not None and not isinstance(point[0], str):
            raise ValueError
        return stamp(datetime.fromisoformat(point[0])) if point[0] is not None else None, point[1]
    except (TypeError, ValueError):
        raise HTTPException(422, "Die Historienseite ist ungültig. Bitte die erste Seite laden.") from None


def statement(query, scope):
    history = ChangeHistoryORM.__table__
    criterion = scoped_clause(history, scope=scope)
    result = select(*(history.c[field] for field in FIELDS)).where(criterion if criterion is not None else True)
    for field in EXACT_FIELDS:
        if getattr(query, field):
            result = result.where(history.c[field] == getattr(query, field))
    time = Chronology(history.c.changed_at)
    if query.changed_from is not None:
        result = result.where(time >= query.changed_from)
    if query.changed_before is not None:
        result = result.where(time < query.changed_before)
    if query.search:
        term = query.search.casefold().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        result = result.where(or_(*(bytewise_id(UnicodeCasefold(history.c[field])).like(f"%{term}%", escape="\\")
                                   for field in TEXT_FIELDS)))
    return result


def ordered(base, query, after, limit):
    rows = base.subquery()
    time, identifier = Chronology(rows.c.changed_at), bytewise_id(rows.c.id)
    result = select(rows)
    if after is not None:
        value, last_id = after
        value = stamp(value)
        result = result.where(and_(time.is_(None), identifier < last_id) if value is None else
                              or_(time.is_(None), time < value, and_(time == value, identifier < last_id)))
    return result.order_by(time.desc().nulls_last(), identifier.desc()).limit(limit)


def memory_rows(store, query, scope):
    for row in object.__getattribute__(store, "__dict__")["change_history"].values():
        if not memory_visible(store, "change_history", row, scope=scope):
            continue
        if any(getattr(query, field) and getattr(row, field) != getattr(query, field) for field in EXACT_FIELDS):
            continue
        time = stamp(row.changed_at)
        if query.changed_from is not None and (time is None or time < query.changed_from):
            continue
        if query.changed_before is not None and (time is None or time >= query.changed_before):
            continue
        projected = row.model_dump()
        if query.search and not any(query.search.casefold() in (projected[field] or "").casefold() for field in TEXT_FIELDS):
            continue
        yield projected


def memory_key(row):
    time = stamp(row["changed_at"])
    return time is not None, time or datetime.min, row["id"].encode("utf-8")


def memory_page(store, query, scope, after, limit):
    key = memory_key({"changed_at": after[0], "id": after[1]}) if after is not None else None
    rows = (row for row in memory_rows(store, query, scope) if key is None or memory_key(row) < key)
    return nlargest(limit, rows, key=memory_key)


def item(row):
    return HistoryInventoryItem.model_validate(row)


def read_context(store, query):
    if query.page_size > maximum_page_size():
        raise HTTPException(422, "Bitte eine kleinere Seite wählen; alle weiteren Seiten bleiben erreichbar.")
    if hasattr(store, "db"):
        if query.search:
            ensure_sqlite_casefold(store.db)
        return store.db.no_autoflush
    return _memory_lock


def history_inventory_page(store, query):
    scope = current_scope()
    refresh_scope(scope)
    after = position(query, scope)
    with read_context(store, query):
        if hasattr(store, "db"):
            rows = [dict(row) for row in store.db.execute(ordered(statement(query, scope), query, after, query.page_size + 1)).mappings()]
        else:
            rows = memory_page(store, query, scope, after, query.page_size + 1)
    refresh_scope(scope)
    more = len(rows) > query.page_size
    selected = rows[:query.page_size]
    cursor = pack_reference_cursor(binding(query, scope), json.dumps([
        stamp(selected[-1]["changed_at"]).isoformat() if selected[-1]["changed_at"] is not None else None,
        selected[-1]["id"]])) if more else None
    return HistoryInventoryPage(items=[item(row) for row in selected], has_more=more, next_cursor=cursor)


def history_inventory_summary(store, query):
    scope = current_scope()
    refresh_scope(scope)
    with read_context(store, query):
        total = store.db.scalar(select(func.count()).select_from(statement(query, scope).subquery())) if hasattr(store, "db") else sum(
            1 for _ in memory_rows(store, query, scope))
    refresh_scope(scope)
    return {"total": total}


def legacy_history_list(store, *, skip, limit, entity_type=None, entity_id=None):
    query = HistoryInventoryQuery(entity_type=entity_type, entity_id=entity_id)
    scope = current_scope()
    refresh_scope(scope)
    with read_context(store, query):
        if hasattr(store, "db"):
            rows = [dict(row) for row in store.db.execute(ordered(statement(query, scope), query, None, limit).offset(skip)).mappings()]
        else:
            # Legacy offset callers inherently require skipping earlier rows;
            # the product uses cursor pages instead.
            rows = memory_page(store, query, scope, None, skip + limit)[skip:]
    refresh_scope(scope)
    return [ChangeHistoryEntry.model_validate(row) for row in rows]
