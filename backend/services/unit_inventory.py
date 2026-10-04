"""Bounded unit pages and full scoped aggregates; existing CRUD remains unchanged."""

import json
from dataclasses import asdict
from decimal import Decimal
from functools import cmp_to_key
from heapq import nsmallest
from typing import Literal

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import Numeric, and_, case, cast, func, or_, select

from ..db.booking_order import bytewise_id
from ..db.orm_models import ContractORM, PropertyORM, TenantORM, UnitORM
from ..models import Unit
from .concurrency import etag
from .contract_workspace import _compare, maximum_page_size
from .contract_workspace_search import UnicodeCasefold, ensure_sqlite_casefold
from .portfolio_scope import current_scope, memory_visible, refresh_scope, scoped_clause
from .reference_cursor import pack_reference_cursor, unpack_reference_cursor

UnitSort = Literal["label", "property_name", "unit_type", "status", "area_sqm", "cold_rent", "rooms", "person_count", "tenant_name"]
TEXT_SORTS = {"label", "property_name", "unit_type", "status", "tenant_name"}


class UnitInventoryQuery(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    search: str | None = None
    property_id: str | None = Field(default=None, min_length=1)
    status: str | None = None
    unit_type: str | None = None
    view: Literal["all", "no_contract", "no_area", "no_person_count", "multiple_active"] = "all"
    area_min: float | None = None
    area_max: float | None = None
    rent_min: float | None = None
    rent_max: float | None = None
    sort_by: UnitSort = "label"
    sort_order: Literal["asc", "desc"] = "asc"
    page_size: int = Field(default=25, ge=1)
    cursor: str | None = Field(default=None, min_length=1)

    @field_validator("search", "property_id", "status", "unit_type")
    @classmethod
    def safe_text(cls, value):
        if value is None:
            return None
        if any(ord(char) < 32 or ord(char) == 127 for char in value):
            raise ValueError("Bitte Text ohne Steuerzeichen verwenden.")
        return value.strip() or None

    @model_validator(mode="after")
    def valid_ranges(self):
        for low, high in ((self.area_min, self.area_max), (self.rent_min, self.rent_max)):
            if low is not None and high is not None and low > high:
                raise ValueError("Der Mindestwert darf den Höchstwert nicht überschreiten.")
        return self


class UnitInventoryItem(Unit):
    property_name: str | None
    tenant_name: str | None
    active_contract_count: int
    has_contract: bool
    edit_etag: str


class UnitInventoryPage(BaseModel):
    items: list[UnitInventoryItem]
    has_more: bool
    next_cursor: str | None


def binding(query, scope):
    return {"kind": "unit-inventory-v1", "query": query.model_dump(mode="json", exclude={"cursor"}),
            "scope": asdict(scope) if scope is not None else None}


def position(query, scope):
    encoded = unpack_reference_cursor(query.cursor, binding(query, scope))
    if encoded is None:
        return None
    try:
        value, identifier = json.loads(encoded)
        if not isinstance(identifier, str) or not identifier:
            raise ValueError
        if value is not None and (not isinstance(value, str) if query.sort_by in TEXT_SORTS else type(value) not in (int, float)):
            raise ValueError
        return value, identifier
    except (TypeError, ValueError):
        raise HTTPException(422, "Die Listenseite ist ungültig. Bitte die erste Seite laden.") from None


def _visible(table, scope):
    clause = scoped_clause(table, scope=scope)
    return clause if clause is not None else True


def statement(query, scope):
    units, properties, contracts, tenants = (model.__table__ for model in (UnitORM, PropertyORM, ContractORM, TenantORM))
    related = [contracts.c.unit_id == units.c.id, contracts.c.property_id == units.c.property_id, _visible(contracts, scope)]
    active = [*related, contracts.c.status == "active"]
    count = select(func.count()).select_from(contracts).where(*active).correlate(units).scalar_subquery()
    tenant = select(tenants.c.full_name).select_from(contracts.join(tenants, tenants.c.id == contracts.c.tenant_id)).where(
        *active).correlate(units).limit(1).scalar_subquery()
    labels = {"property_name": properties.c.name, "active_contract_count": count,
              "has_contract": select(1).select_from(contracts).where(*related).correlate(units).exists(),
              "tenant_name": case((count == 1, tenant), else_=None)}
    result = select(units, *(value.label(key) for key, value in labels.items())).join(
        properties, and_(properties.c.id == units.c.property_id, _visible(properties, scope))).where(_visible(units, scope))
    for key in ("property_id", "status", "unit_type"):
        if getattr(query, key) is not None:
            result = result.where(units.c[key] == getattr(query, key))
    for column, low, high in ((units.c.area_sqm, query.area_min, query.area_max), (units.c.cold_rent, query.rent_min, query.rent_max)):
        if low is not None:
            result = result.where(column >= low)
        if high is not None:
            result = result.where(column <= high)
    if query.view == "no_contract":
        result = result.where(~labels["has_contract"])
    elif query.view in {"no_area", "no_person_count"}:
        column = units.c.area_sqm if query.view == "no_area" else units.c.person_count
        result = result.where(or_(column.is_(None), column == 0))
    elif query.view == "multiple_active":
        result = result.where(count > 1)
    if query.search:
        term = query.search.casefold().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        def matches(column):
            return bytewise_id(UnicodeCasefold(column)).like(f"%{term}%", escape="\\")
        party_matches = select(1).select_from(contracts.join(tenants, tenants.c.id == contracts.c.tenant_id)).where(
            *active, matches(tenants.c.full_name)).correlate(units).exists()
        result = result.where(or_(matches(units.c.label), matches(properties.c.name), matches(units.c.unit_type), party_matches))
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
    for unit in raw["units"].values():
        if not memory_visible(store, "units", unit, scope=scope):
            continue
        prop = raw["properties"].get(unit.property_id)
        if prop is None or not memory_visible(store, "properties", prop, scope=scope):
            continue
        if any(getattr(query, key) is not None and getattr(unit, key) != getattr(query, key) for key in ("property_id", "status", "unit_type")):
            continue
        if any((low is not None and (value is None or value < low)) or (high is not None and (value is None or value > high))
               for value, low, high in ((unit.area_sqm, query.area_min, query.area_max), (unit.cold_rent, query.rent_min, query.rent_max))):
            continue
        count, has_contract, tenant_name, party_match = 0, False, None, False
        for contract in raw["contracts"].values():
            if contract.unit_id != unit.id or contract.property_id != prop.id or not memory_visible(store, "contracts", contract, scope=scope):
                continue
            has_contract = True
            if contract.status == "active":
                count += 1
                tenant_name = getattr(raw["tenants"].get(contract.tenant_id), "full_name", None)
                party_match |= bool(query.search and query.search.casefold() in (tenant_name or "").casefold())
        if query.view == "no_contract" and has_contract or query.view == "multiple_active" and count <= 1:
            continue
        if query.view == "no_area" and unit.area_sqm not in (None, 0) or query.view == "no_person_count" and unit.person_count not in (None, 0):
            continue
        if query.search and not party_match and not any(query.search.casefold() in (value or "").casefold()
                                                       for value in (unit.label, prop.name, unit.unit_type)):
            continue
        yield {**unit.model_dump(), "property_name": prop.name, "tenant_name": tenant_name if count == 1 else None,
               "active_contract_count": count, "has_contract": has_contract}


def memory_page(store, query, scope, after, limit):
    def compare(first, second):
        return _compare((first[query.sort_by], first["id"]), (second[query.sort_by], second["id"]), query.sort_order == "desc")
    rows = (row for row in memory_rows(store, query, scope) if after is None or
            _compare((row[query.sort_by], row["id"]), after, query.sort_order == "desc") > 0)
    return nsmallest(limit, rows, key=cmp_to_key(compare))


def item(row):
    return UnitInventoryItem.model_validate({**row, "edit_etag": etag("units", row["id"], row["updated_at"])})


def _read_context(store, query):
    if query.page_size > maximum_page_size():
        raise HTTPException(422, "Bitte eine kleinere Seite wählen; alle weiteren Seiten bleiben erreichbar.")
    if hasattr(store, "db"):
        if query.search:
            ensure_sqlite_casefold(store.db)
        return store.db.no_autoflush
    from .payments import _memory_lock
    return _memory_lock


def unit_inventory_page(store, query: UnitInventoryQuery):
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
    cursor = pack_reference_cursor(binding(query, scope), json.dumps([rows[-1][query.sort_by], rows[-1]["id"]])) if more else None
    return UnitInventoryPage(items=[item(row) for row in rows], has_more=more, next_cursor=cursor)


def unit_inventory_summary(store, query: UnitInventoryQuery):
    scope = current_scope()
    refresh_scope(scope)
    with _read_context(store, query):
        if hasattr(store, "db"):
            rows = statement(query, scope).subquery()
            result = dict(store.db.execute(select(func.count().label("total"),
                func.count(rows.c.cold_rent).label("rent_count"),
                func.avg(cast(rows.c.cold_rent, Numeric(24, 6))).label("average_cold_rent"),
                *(func.coalesce(func.sum(case((condition, 1), else_=0)), 0).label(name) for name, condition in (
                    ("occupied", rows.c.status.in_(["occupied", "rented"])), ("vacant", rows.c.status == "vacant"),
                    ("reserved", rows.c.status == "reserved"), ("multiple_active", rows.c.active_contract_count > 1)))
            ).select_from(rows)).mappings().one())
        else:
            result = dict(total=0, rent_count=0, occupied=0, vacant=0, reserved=0, multiple_active=0)
            rent_sum = Decimal(0)
            for row in memory_rows(store, query, scope):
                result["total"] += 1
                result["occupied"] += row["status"] in {"occupied", "rented"}
                result["vacant"] += row["status"] == "vacant"
                result["reserved"] += row["status"] == "reserved"
                result["multiple_active"] += row["active_contract_count"] > 1
                if row["cold_rent"] is not None:
                    result["rent_count"] += 1
                    rent_sum += Decimal(str(row["cold_rent"]))
            result["average_cold_rent"] = str(rent_sum / result["rent_count"]) if result["rent_count"] else None
    refresh_scope(scope)
    return result
