"""Current meter inventory and bounded standalone readings, without historical inference."""

import json
from dataclasses import asdict
from datetime import date, timedelta
from functools import cmp_to_key
from heapq import nsmallest
from typing import Literal

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import and_, case, func, or_, select

from ..db.booking_order import bytewise_id
from ..db.orm_models import MeterORM, PropertyORM, StandaloneMeterReadingORM, UnitORM
from ..models import Meter, StandaloneMeterReading
from .concurrency import etag
from .contract_workspace import _compare, maximum_page_size
from .contract_workspace_search import UnicodeCasefold, ensure_sqlite_casefold
from .portfolio_scope import current_scope, memory_visible, refresh_scope, scoped_clause
from .reference_cursor import pack_reference_cursor, unpack_reference_cursor

MeterSort = Literal["serial_number", "meter_type", "measurement_unit", "property_name", "unit_label", "supplier",
                    "next_inspection", "last_reading_date", "last_reading_value"]
DATE_SORTS = {"next_inspection", "last_reading_date", "reading_date"}
TEXT_SORTS = {"serial_number", "meter_type", "measurement_unit", "property_name", "unit_label", "supplier"}
SEARCH_FIELDS = ("serial_number", "meter_type", "measurement_unit", "location", "supplier", "contract_number")


class MeterInventoryQuery(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    search: str | None = None
    property_id: str | None = Field(default=None, min_length=1)
    unit_id: str | None = Field(default=None, min_length=1)
    meter_type: str | None = None
    measurement_unit: str | None = None
    supplier: str | None = None
    is_active: bool | None = None
    view: Literal["all", "no_reading", "unknown_unit", "overdue", "due_soon"] = "all"
    as_of: date = Field(default_factory=date.today)
    inspection_from: date | None = None
    inspection_to: date | None = None
    sort_by: MeterSort = "serial_number"
    sort_order: Literal["asc", "desc"] = "asc"
    page_size: int = Field(default=25, ge=1)
    cursor: str | None = Field(default=None, min_length=1)

    @field_validator("search", "property_id", "unit_id", "meter_type", "measurement_unit", "supplier")
    @classmethod
    def safe_text(cls, value):
        if value is None:
            return None
        if any(ord(char) < 32 or ord(char) == 127 for char in value):
            raise ValueError("Bitte Text ohne Steuerzeichen verwenden.")
        return value if value.strip() else None

    @model_validator(mode="after")
    def valid_range(self):
        if self.inspection_from and self.inspection_to and self.inspection_from > self.inspection_to:
            raise ValueError("Das Prüfdatum von darf nicht nach dem Datum bis liegen.")
        return self


class MeterInventoryItem(Meter):
    property_id: str
    property_name: str
    unit_label: str
    last_reading_id: str | None
    last_reading_date: date | None
    last_reading_value: float | None
    edit_etag: str


class MeterInventoryPage(BaseModel):
    items: list[MeterInventoryItem]
    has_more: bool
    next_cursor: str | None


class MeterReadingsQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    search: str | None = None
    date_from: date | None = None
    date_to: date | None = None
    sort_by: Literal["reading_date"] = "reading_date"
    sort_order: Literal["asc", "desc"] = "desc"
    page_size: int = Field(default=25, ge=1)
    cursor: str | None = Field(default=None, min_length=1)

    @field_validator("search")
    @classmethod
    def safe_search(cls, value):
        return MeterInventoryQuery.safe_text(value)

    @model_validator(mode="after")
    def valid_range(self):
        if self.date_from and self.date_to and self.date_from > self.date_to:
            raise ValueError("Das Ablesedatum von darf nicht nach dem Datum bis liegen.")
        return self


class MeterReadingsPage(BaseModel):
    items: list[StandaloneMeterReading]
    has_more: bool
    next_cursor: str | None


def binding(query, scope, meter_id=None):
    return {"kind": "meter-readings-v1" if meter_id is not None else "meter-inventory-v1",
            "meter_id": meter_id, "query": query.model_dump(mode="json", exclude={"cursor"}),
            "scope": asdict(scope) if scope is not None else None}


def position(query, scope, meter_id=None):
    encoded = unpack_reference_cursor(query.cursor, binding(query, scope, meter_id))
    if encoded is None:
        return None
    try:
        value, identifier = json.loads(encoded)
        if not isinstance(identifier, str) or not identifier:
            raise ValueError
        if value is not None:
            if query.sort_by in DATE_SORTS:
                value = date.fromisoformat(value)
            elif query.sort_by in TEXT_SORTS:
                if not isinstance(value, str):
                    raise ValueError
            elif type(value) not in (int, float):
                raise ValueError
        return value, identifier
    except (TypeError, ValueError):
        raise HTTPException(422, "Die Listenseite ist ungültig. Bitte die erste Seite laden.") from None


def _visible(table, scope):
    clause = scoped_clause(table, scope=scope)
    return clause if clause is not None else True


def _matches(column, search):
    term = search.casefold().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return bytewise_id(UnicodeCasefold(column)).like(f"%{term}%", escape="\\")


def statement(query, scope):
    meters, units, properties, readings = (model.__table__ for model in
        (MeterORM, UnitORM, PropertyORM, StandaloneMeterReadingORM))
    # A reading has exactly one scope parent, this authorized meter. LIMIT 1
    # picks a stable day/ID winner without ranking/materializing all histories.
    latest_id = select(readings.c.id).where(readings.c.meter_id == meters.c.id).order_by(
        readings.c.reading_date.desc(), bytewise_id(readings.c.id).desc()).limit(1).correlate(meters).scalar_subquery()
    result = select(meters, units.c.property_id, properties.c.name.label("property_name"), units.c.label.label("unit_label"),
        readings.c.id.label("last_reading_id"), readings.c.reading_date.label("last_reading_date"),
        readings.c.value.label("last_reading_value")).join(units, and_(units.c.id == meters.c.unit_id, _visible(units, scope))).join(
        properties, and_(properties.c.id == units.c.property_id, _visible(properties, scope))).outerjoin(
        readings, readings.c.id == latest_id).where(_visible(meters, scope))
    for key in ("unit_id", "meter_type", "measurement_unit", "supplier", "is_active"):
        if getattr(query, key) is not None:
            result = result.where(meters.c[key] == getattr(query, key))
    if query.property_id is not None:
        result = result.where(units.c.property_id == query.property_id)
    for bound, operation in ((query.inspection_from, meters.c.next_inspection.__ge__),
                             (query.inspection_to, meters.c.next_inspection.__le__)):
        if bound is not None:
            result = result.where(operation(bound))
    conditions = {"no_reading": readings.c.id.is_(None),
                  "unknown_unit": or_(meters.c.measurement_unit.is_(None), func.trim(meters.c.measurement_unit) == ""),
                  "overdue": meters.c.next_inspection < query.as_of,
                  "due_soon": and_(meters.c.next_inspection >= query.as_of,
                                   meters.c.next_inspection <= query.as_of + timedelta(days=30))}
    if query.view != "all":
        result = result.where(conditions[query.view])
    if query.search:
        result = result.where(or_(*(_matches(meters.c[key], query.search) for key in SEARCH_FIELDS),
                                  _matches(units.c.label, query.search), _matches(properties.c.name, query.search)))
    return result


def ordered(base, query, after, limit):
    rows = base.subquery()
    sort = bytewise_id(rows.c[query.sort_by]) if query.sort_by in TEXT_SORTS else rows.c[query.sort_by]
    identifier = bytewise_id(rows.c.id)
    descending = query.sort_order == "desc"
    result = select(rows)
    if after is not None:
        value, last_id = after
        id_after = identifier < last_id if descending else identifier > last_id
        result = result.where(and_(sort.is_(None), id_after) if value is None else or_(
            sort.is_(None), sort < value if descending else sort > value, and_(sort == value, id_after)))
    return result.order_by(sort.desc().nulls_last() if descending else sort.asc().nulls_last(),
                           identifier.desc() if descending else identifier.asc()).limit(limit)


def memory_rows(store, query, scope, *, meter_id=None):
    raw = object.__getattribute__(store, "__dict__")
    sources = raw["meters"].values() if meter_id is None else [raw["meters"].get(meter_id)]
    for meter in sources:
        if meter is None:
            continue
        if not memory_visible(store, "meters", meter, scope=scope):
            continue
        unit = raw["units"].get(meter.unit_id)
        prop = raw["properties"].get(unit.property_id) if unit else None
        if unit is None or prop is None or not memory_visible(store, "units", unit, scope=scope) or not memory_visible(store, "properties", prop, scope=scope):
            continue
        if query.property_id is not None and query.property_id != prop.id:
            continue
        if any(getattr(query, key) is not None and getattr(meter, key) != getattr(query, key)
               for key in ("unit_id", "meter_type", "measurement_unit", "supplier", "is_active")):
            continue
        if query.inspection_from and (meter.next_inspection is None or meter.next_inspection < query.inspection_from):
            continue
        if query.inspection_to and (meter.next_inspection is None or meter.next_inspection > query.inspection_to):
            continue
        if query.search and not any(query.search.casefold() in (value or "").casefold()
                                   for value in (unit.label, prop.name, *(getattr(meter, key) for key in SEARCH_FIELDS))):
            continue
        latest = max((reading for reading in raw["standalone_meter_readings"].values() if reading.meter_id == meter.id),
                     key=lambda reading: (reading.reading_date, reading.id), default=None)
        views = {"all": True, "no_reading": latest is None,
                 "unknown_unit": not (meter.measurement_unit or "").strip(),
                 "overdue": meter.next_inspection is not None and meter.next_inspection < query.as_of,
                 "due_soon": meter.next_inspection is not None and query.as_of <= meter.next_inspection <= query.as_of + timedelta(days=30)}
        if not views[query.view]:
            continue
        yield {**meter.model_dump(), "property_id": prop.id, "property_name": prop.name, "unit_label": unit.label,
               "last_reading_id": latest.id if latest else None, "last_reading_date": latest.reading_date if latest else None,
               "last_reading_value": latest.value if latest else None}


def _memory_select(rows, query, after, limit):
    def compare(first, second):
        return _compare((first[query.sort_by], first["id"]), (second[query.sort_by], second["id"]), query.sort_order == "desc")
    available = (row for row in rows if after is None or
                 _compare((row[query.sort_by], row["id"]), after, query.sort_order == "desc") > 0)
    return nsmallest(limit, available, key=cmp_to_key(compare))


def memory_page(store, query, scope, after, limit):
    return _memory_select(memory_rows(store, query, scope), query, after, limit)


def item(row):
    return MeterInventoryItem.model_validate({**row, "edit_etag": etag("meters", row["id"], row["updated_at"])})


def _read_context(store, query):
    if query.page_size > maximum_page_size():
        raise HTTPException(422, "Bitte eine kleinere Seite wählen; alle weiteren Seiten bleiben erreichbar.")
    if hasattr(store, "db"):
        if query.search:
            ensure_sqlite_casefold(store.db)
        return store.db.no_autoflush
    from .payments import _memory_lock
    return _memory_lock


def _page(selected, query, scope, meter_id=None):
    more = len(selected) > query.page_size
    rows = selected[:query.page_size]
    cursor = pack_reference_cursor(binding(query, scope, meter_id), json.dumps(
        [rows[-1][query.sort_by], rows[-1]["id"]], default=str)) if more else None
    return dict(items=rows, has_more=more, next_cursor=cursor)


def meter_inventory_page(store, query: MeterInventoryQuery):
    scope = current_scope()
    refresh_scope(scope)
    after = position(query, scope)
    with _read_context(store, query):
        selected = ([dict(row) for row in store.db.execute(ordered(statement(query, scope), query, after, query.page_size + 1)).mappings()]
                    if hasattr(store, "db") else memory_page(store, query, scope, after, query.page_size + 1))
    refresh_scope(scope)
    page = _page(selected, query, scope)
    return MeterInventoryPage(**{**page, "items": [item(row) for row in page["items"]]})


def meter_inventory_detail(store, meter_id: str):
    scope = current_scope()
    refresh_scope(scope)
    query = MeterInventoryQuery()
    with _read_context(store, query):
        if hasattr(store, "db"):
            row = store.db.execute(statement(query, scope).where(MeterORM.id == meter_id).limit(1)).mappings().first()
        else:
            row = next(memory_rows(store, query, scope, meter_id=meter_id), None)
    refresh_scope(scope)
    if row is None:
        raise HTTPException(404, "Zähler nicht gefunden")
    return item(dict(row))


def meter_inventory_summary(store, query: MeterInventoryQuery):
    scope = current_scope()
    refresh_scope(scope)
    with _read_context(store, query):
        if hasattr(store, "db"):
            rows = statement(query, scope).subquery()
            result = dict(store.db.execute(select(func.count().label("total"),
                *(func.coalesce(func.sum(case((condition, 1), else_=0)), 0).label(name) for name, condition in (
                    ("active", rows.c.is_active.is_(True)), ("inactive", rows.c.is_active.is_(False)),
                    ("no_reading", rows.c.last_reading_id.is_(None)),
                    ("unknown_unit", or_(rows.c.measurement_unit.is_(None), func.trim(rows.c.measurement_unit) == "")),
                    ("overdue", rows.c.next_inspection < query.as_of),
                    ("due_soon", and_(rows.c.next_inspection >= query.as_of, rows.c.next_inspection <= query.as_of + timedelta(days=30)))))
            ).select_from(rows)).mappings().one())
        else:
            result = dict(total=0, active=0, inactive=0, no_reading=0, unknown_unit=0, overdue=0, due_soon=0)
            for row in memory_rows(store, query, scope):
                result["total"] += 1
                result["active"] += row["is_active"] is True
                result["inactive"] += row["is_active"] is False
                result["no_reading"] += row["last_reading_id"] is None
                result["unknown_unit"] += not (row["measurement_unit"] or "").strip()
                result["overdue"] += row["next_inspection"] is not None and row["next_inspection"] < query.as_of
                result["due_soon"] += row["next_inspection"] is not None and query.as_of <= row["next_inspection"] <= query.as_of + timedelta(days=30)
    refresh_scope(scope)
    return result


def meter_readings_page(store, meter_id: str, query: MeterReadingsQuery):
    scope = current_scope()
    refresh_scope(scope)
    after = position(query, scope, meter_id)
    with _read_context(store, query):
        # Exact scoped parent first: an unavailable meter is never an empty list.
        meter_inventory_detail(store, meter_id)
        if hasattr(store, "db"):
            readings = StandaloneMeterReadingORM.__table__
            base = select(readings).where(readings.c.meter_id == meter_id, _visible(readings, scope))
            if query.date_from:
                base = base.where(readings.c.reading_date >= query.date_from)
            if query.date_to:
                base = base.where(readings.c.reading_date <= query.date_to)
            if query.search:
                base = base.where(or_(_matches(readings.c.recorded_by, query.search), _matches(readings.c.notes, query.search)))
            selected = [dict(row) for row in store.db.execute(ordered(base, query, after, query.page_size + 1)).mappings()]
        else:
            def sources():
                for reading in store.__dict__["standalone_meter_readings"].values():
                    if reading.meter_id != meter_id or not memory_visible(store, "standalone_meter_readings", reading, scope=scope):
                        continue
                    if query.date_from and reading.reading_date < query.date_from or query.date_to and reading.reading_date > query.date_to:
                        continue
                    if query.search and not any(query.search.casefold() in (value or "").casefold() for value in (reading.recorded_by, reading.notes)):
                        continue
                    yield reading.model_dump()
            selected = _memory_select(sources(), query, after, query.page_size + 1)
    refresh_scope(scope)
    return MeterReadingsPage(**_page(selected, query, scope, meter_id))
