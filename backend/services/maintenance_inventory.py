"""Bounded existing maintenance cases with complete operational filters and counts."""

import json
from dataclasses import asdict
from datetime import date, datetime
from functools import cmp_to_key
from heapq import nsmallest
from typing import Literal

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import and_, case, func, or_, select

from ..db.booking_order import bytewise_id
from ..db.orm_models import MaintenanceCaseORM, PropertyORM, UnitORM
from .concurrency import etag
from .contract_workspace import _compare, maximum_page_size
from .contract_workspace_search import UnicodeCasefold, ensure_sqlite_casefold
from .portfolio_scope import current_scope, memory_visible, refresh_scope, scoped_clause
from .reference_cursor import pack_reference_cursor, unpack_reference_cursor

MaintenanceSort = Literal["title", "property_name", "unit_label", "category", "status", "priority", "assignee", "contractor", "reported_by", "due_date", "appointment_at", "estimated_cost", "created_at", "updated_at"]
TEXT_SORTS = {"title", "property_name", "unit_label", "category", "status", "priority", "assignee", "contractor", "reported_by"}
FIELDS = tuple(key for key in MaintenanceCaseORM.__table__.columns.keys() if key != "description")


class MaintenanceInventoryQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    search: str | None = None
    property_id: str | None = Field(default=None, min_length=1)
    unit_id: str | None = Field(default=None, min_length=1)
    status: str | None = None
    priority: str | None = None
    category: str | None = None
    view: Literal["all", "overdue", "urgent", "no_appointment", "no_assignee"] = "all"
    as_of: date = Field(default_factory=date.today)
    date_from: date | None = None
    date_to: date | None = None
    appointment_from: date | None = None
    appointment_to: date | None = None
    sort_by: MaintenanceSort = "due_date"
    sort_order: Literal["asc", "desc"] = "asc"
    page_size: int = Field(default=25, ge=1)
    cursor: str | None = Field(default=None, min_length=1)

    @field_validator("search", "property_id", "unit_id", "status", "priority", "category")
    @classmethod
    def safe_text(cls, value):
        if value is None:
            return None
        if any(ord(char) < 32 or ord(char) == 127 for char in value):
            raise ValueError("Bitte Text ohne Steuerzeichen verwenden.")
        return value.strip() or None

    @model_validator(mode="after")
    def ordered_dates(self):
        for low, high in ((self.date_from, self.date_to), (self.appointment_from, self.appointment_to)):
            if low and high and low > high:
                raise ValueError("Das Anfangsdatum darf nicht nach dem Enddatum liegen.")
        return self


class MaintenanceInventoryItem(BaseModel):
    id: str
    property_id: str
    unit_id: str | None
    title: str
    category: str | None
    status: str
    priority: str
    assignee: str | None
    contractor: str | None
    reported_by: str | None
    due_date: date | None
    appointment_at: datetime | None
    estimated_cost: float | None
    created_at: datetime
    updated_at: datetime
    property_name: str | None
    unit_label: str | None
    edit_etag: str


class MaintenanceInventoryPage(BaseModel):
    items: list[MaintenanceInventoryItem]
    has_more: bool
    next_cursor: str | None


def binding(query, scope):
    return {"kind": "maintenance-inventory-v1", "query": query.model_dump(mode="json", exclude={"cursor"}),
            "scope": asdict(scope) if scope is not None else None}


def position(query, scope):
    encoded = unpack_reference_cursor(query.cursor, binding(query, scope))
    if encoded is None:
        return None
    try:
        value, identifier = json.loads(encoded)
        if not isinstance(identifier, str) or not identifier or value is not None and not isinstance(value, (str, float, int)):
            raise ValueError
        if value is not None and query.sort_by not in TEXT_SORTS:
            if query.sort_by == "estimated_cost":
                value = float(value)
            elif isinstance(value, str):
                value = date.fromisoformat(value) if query.sort_by == "due_date" else datetime.fromisoformat(value)
            else:
                raise ValueError
        return value, identifier
    except (TypeError, ValueError):
        raise HTTPException(422, "Die Wartungsseite ist ungültig. Bitte die erste Seite laden.") from None


def _visible(table, scope):
    clause = scoped_clause(table, scope=scope)
    return clause if clause is not None else True


def statement(query, scope):
    cases, units, properties = (model.__table__ for model in (MaintenanceCaseORM, UnitORM, PropertyORM))
    labels = {"property_name": properties.c.name, "unit_label": units.c.label}
    result = select(*(cases.c[key] for key in FIELDS), *(value.label(key) for key, value in labels.items())).select_from(cases).outerjoin(
        units, and_(units.c.id == cases.c.unit_id, _visible(units, scope))).outerjoin(
        properties, and_(properties.c.id == cases.c.property_id, _visible(properties, scope))).where(_visible(cases, scope))
    for field in ("property_id", "unit_id", "status", "priority", "category"):
        value = getattr(query, field)
        if value is not None:
            result = result.where(cases.c[field] == value)
    if query.date_from:
        result = result.where(cases.c.due_date >= query.date_from)
    if query.date_to:
        result = result.where(cases.c.due_date <= query.date_to)
    if query.appointment_from:
        result = result.where(cases.c.appointment_at >= datetime.combine(query.appointment_from, datetime.min.time()))
    if query.appointment_to:
        result = result.where(cases.c.appointment_at <= datetime.combine(query.appointment_to, datetime.max.time()))
    if query.view == "overdue":
        result = result.where(cases.c.status.in_(("open", "in_progress")), cases.c.due_date < query.as_of)
    if query.view == "urgent":
        result = result.where(cases.c.priority.in_(("high", "urgent")))
    if query.view == "no_appointment":
        result = result.where(cases.c.appointment_at.is_(None))
    if query.view == "no_assignee":
        result = result.where(or_(cases.c.assignee.is_(None), func.trim(cases.c.assignee) == ""))
    if query.search:
        term = query.search.casefold().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        result = result.where(or_(*(bytewise_id(UnicodeCasefold(column)).like(f"%{term}%", escape="\\") for column in
            (cases.c.title, cases.c.category, cases.c.assignee, cases.c.contractor, cases.c.reported_by, *labels.values()))))
    return result


def ordered(base, query, after, limit):
    rows = base.subquery()
    sort = bytewise_id(rows.c[query.sort_by]) if query.sort_by in TEXT_SORTS else rows.c[query.sort_by]
    identifier = bytewise_id(rows.c.id)
    result = select(rows)
    descending = query.sort_order == "desc"
    if after is not None:
        value, last_id = after
        id_after = identifier < last_id if descending else identifier > last_id
        result = result.where(and_(sort.is_(None), id_after) if value is None else or_(
            sort.is_(None), sort < value if descending else sort > value, and_(sort == value, id_after)))
    return result.order_by(sort.desc().nulls_last() if descending else sort.asc().nulls_last(),
                           identifier.desc() if descending else identifier.asc()).limit(limit)


def memory_rows(store, query, scope):
    raw = object.__getattribute__(store, "__dict__")
    for row in raw["maintenance_cases"].values():
        if not memory_visible(store, "maintenance_cases", row, scope=scope):
            continue
        unit, prop = raw["units"].get(row.unit_id), raw["properties"].get(row.property_id)
        if any(getattr(query, field) is not None and getattr(query, field) != getattr(row, field) for field in
               ("property_id", "unit_id", "status", "priority", "category")):
            continue
        if query.date_from and (row.due_date is None or row.due_date < query.date_from) or query.date_to and (row.due_date is None or row.due_date > query.date_to):
            continue
        appointment = row.appointment_at.date() if row.appointment_at else None
        if query.appointment_from and (appointment is None or appointment < query.appointment_from) or query.appointment_to and (appointment is None or appointment > query.appointment_to):
            continue
        if query.view == "overdue" and not (row.status in {"open", "in_progress"} and row.due_date and row.due_date < query.as_of):
            continue
        if query.view == "urgent" and row.priority not in {"high", "urgent"}:
            continue
        if query.view == "no_appointment" and appointment is not None or query.view == "no_assignee" and (row.assignee or "").strip():
            continue
        labels = {"property_name": getattr(prop, "name", None), "unit_label": getattr(unit, "label", None)}
        if query.search and not any(query.search.casefold() in (value or "").casefold() for value in
                                   (row.title, row.category, row.assignee, row.contractor, row.reported_by, *labels.values())):
            continue
        yield {**{key: getattr(row, key) for key in FIELDS}, **labels}


def memory_page(store, query, scope, after, limit):
    def compare(first, second):
        return _compare((first[query.sort_by], first["id"]), (second[query.sort_by], second["id"]), query.sort_order == "desc")
    rows = (row for row in memory_rows(store, query, scope) if after is None or
            _compare((row[query.sort_by], row["id"]), after, query.sort_order == "desc") > 0)
    return nsmallest(limit, rows, key=cmp_to_key(compare))


def item(row):
    return MaintenanceInventoryItem.model_validate({**row, "edit_etag": etag("maintenance", row["id"], row["updated_at"])})


def _read_context(store, query):
    if query.page_size > maximum_page_size():
        raise HTTPException(422, "Bitte eine kleinere Seite wählen; alle weiteren Seiten bleiben erreichbar.")
    if hasattr(store, "db"):
        if query.search:
            ensure_sqlite_casefold(store.db)
        return store.db.no_autoflush
    from .payments import _memory_lock
    return _memory_lock


def maintenance_inventory_page(store, query: MaintenanceInventoryQuery):
    scope = current_scope()
    refresh_scope(scope)
    after = position(query, scope)
    with _read_context(store, query):
        if hasattr(store, "db"):
            selected = [dict(row) for row in store.db.execute(ordered(statement(query, scope), query, after, query.page_size + 1)).mappings()]
        else:
            selected = memory_page(store, query, scope, after, query.page_size + 1)
    refresh_scope(scope)
    more = len(selected) > query.page_size
    rows = selected[:query.page_size]
    cursor = pack_reference_cursor(binding(query, scope), json.dumps([rows[-1][query.sort_by], rows[-1]["id"]], default=str)) if more else None
    return MaintenanceInventoryPage(items=[item(row) for row in rows], has_more=more, next_cursor=cursor)


def maintenance_inventory_summary(store, query: MaintenanceInventoryQuery):
    scope = current_scope()
    refresh_scope(scope)
    with _read_context(store, query):
        if hasattr(store, "db"):
            rows = statement(query, scope).subquery()
            conditions = {
                "open": rows.c.status == "open",
                "in_progress": rows.c.status == "in_progress",
                "overdue": and_(rows.c.status.in_(("open", "in_progress")), rows.c.due_date < query.as_of),
                "no_appointment": rows.c.appointment_at.is_(None),
                "no_assignee": or_(rows.c.assignee.is_(None), func.trim(rows.c.assignee) == ""),
            }
            aggregates = (func.coalesce(func.sum(case((condition, 1), else_=0)), 0).label(name)
                          for name, condition in conditions.items())
            result = dict(store.db.execute(select(func.count().label("total"), *aggregates)
                                           .select_from(rows)).mappings().one())
        else:
            result = dict(total=0, open=0, in_progress=0, overdue=0, no_appointment=0, no_assignee=0)
            for row in memory_rows(store, query, scope):
                result["total"] += 1
                result["open"] += row["status"] == "open"
                result["in_progress"] += row["status"] == "in_progress"
                result["overdue"] += bool(row["status"] in {"open", "in_progress"} and row["due_date"] and row["due_date"] < query.as_of)
                result["no_appointment"] += row["appointment_at"] is None
                result["no_assignee"] += not (row["assignee"] or "").strip()
    refresh_scope(scope)
    return {**result, "as_of": query.as_of}
