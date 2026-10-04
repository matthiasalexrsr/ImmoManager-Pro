"""Bounded, authorized unit context reusing the existing contract keyset reader."""

from contextlib import nullcontext
from dataclasses import asdict
from heapq import nsmallest

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from ..db.booking_order import bytewise_id
from ..db.orm_models import InsuranceORM, PropertyORM, UnitORM
from ..models import Insurance, Unit
from .contract_workspace import get_contract_workspace_page, maximum_page_size
from .contract_workspace_types import ContractWorkspacePage, ContractWorkspaceQuery
from .portfolio_scope import current_scope, memory_visible, refresh_scope, scoped_clause
from .reference_cursor import pack_reference_cursor, unpack_reference_cursor


class UnitWorkspaceQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    page_size: int = Field(default=25, ge=1)
    active_cursor: str | None = Field(default=None, min_length=1)
    history_cursor: str | None = Field(default=None, min_length=1)
    insurance_cursor: str | None = Field(default=None, min_length=1)


class UnitProperty(BaseModel):
    id: str
    name: str
    address_line: str | None = None
    postal_code: str | None = None
    city: str | None = None


class UnitInsurancePage(BaseModel):
    items: list[Insurance]
    has_more: bool
    next_cursor: str | None


class UnitWorkspace(BaseModel):
    unit: Unit
    property: UnitProperty
    active_contracts: ContractWorkspacePage
    contract_history: ContractWorkspacePage
    insurances: UnitInsurancePage


def _parents(store, identifier: str, scope) -> tuple[Unit, UnitProperty]:
    if hasattr(store, "db"):
        units, properties = UnitORM.__table__, PropertyORM.__table__
        statement = select(units, *(properties.c[key].label("workspace_property_" + key)
                                   for key in UnitProperty.model_fields)).join(
            properties, properties.c.id == units.c.property_id).where(units.c.id == identifier)
        for table in (units, properties):
            clause = scoped_clause(table, scope=scope)
            if clause is not None:
                statement = statement.where(clause)
        row = store.db.execute(statement).mappings().first()
        if row is not None:
            return (Unit.model_validate(dict(row)), UnitProperty.model_validate(
                {key: row["workspace_property_" + key] for key in UnitProperty.model_fields}))
    else:
        from .payments import _memory_lock

        with _memory_lock:
            raw = object.__getattribute__(store, "__dict__")
            unit = raw["units"].get(identifier)
            if unit is not None and memory_visible(store, "units", unit, scope=scope):
                prop = raw["properties"].get(unit.property_id)
                if prop is not None and memory_visible(store, "properties", prop, scope=scope):
                    return unit.model_copy(deep=True), UnitProperty.model_validate(prop.model_dump())
    raise HTTPException(404, "Die Einheit ist nicht verfügbar.")


def _insurances(store, unit: Unit, query: UnitWorkspaceQuery, scope) -> UnitInsurancePage:
    binding = {"kind": "unit-workspace-insurances-v1", "unit_id": unit.id,
               "property_id": unit.property_id, "page_size": query.page_size,
               "scope": asdict(scope) if scope is not None else None}
    after = unpack_reference_cursor(query.insurance_cursor, binding)
    if hasattr(store, "db"):
        table = InsuranceORM.__table__
        statement = select(table).where(table.c.unit_id == unit.id, table.c.property_id == unit.property_id)
        clause = scoped_clause(table, scope=scope)
        if clause is not None:
            statement = statement.where(clause)
        if after is not None:
            statement = statement.where(bytewise_id(table.c.id) > after)
        statement = statement.order_by(bytewise_id(table.c.id)).limit(query.page_size + 1)
        selected = [Insurance.model_validate(dict(row)) for row in store.db.execute(statement).mappings()]
    else:
        from .payments import _memory_lock

        with _memory_lock:
            rows = object.__getattribute__(store, "__dict__")["insurances"].values()
            selected = [row.model_copy(deep=True) for row in nsmallest(query.page_size + 1,
                (row for row in rows if row.unit_id == unit.id and row.property_id == unit.property_id
                 and (after is None or row.id > after) and memory_visible(store, "insurances", row, scope=scope)),
                key=lambda row: row.id)]
    more = len(selected) > query.page_size
    items = selected[:query.page_size]
    return UnitInsurancePage(items=items, has_more=more,
                             next_cursor=pack_reference_cursor(binding, items[-1].id) if more else None)


def get_unit_workspace(store, identifier: str, query: UnitWorkspaceQuery) -> UnitWorkspace:
    if query.page_size > maximum_page_size():
        raise HTTPException(422, "Bitte eine kleinere Seite wählen. Weitere Seiten bleiben verfügbar.")
    scope = current_scope()
    refresh_scope(scope)
    # Core table projections never autoflush unrelated pending business writes.
    with store.db.no_autoflush if hasattr(store, "db") else nullcontext():
        unit, prop = _parents(store, identifier, scope)
        common = {"unit_id": unit.id, "property_id": unit.property_id,
                  "sort_by": "start_date", "sort_order": "desc", "page_size": query.page_size}
        active = get_contract_workspace_page(store, ContractWorkspaceQuery.model_validate(
            {**common, "status": "active", "cursor": query.active_cursor}))
        history = get_contract_workspace_page(store, ContractWorkspaceQuery.model_validate(
            {**common, "cursor": query.history_cursor}))
        insurances = _insurances(store, unit, query, scope)
        current_unit, current_property = _parents(store, identifier, scope)
        if current_unit != unit or current_property != prop:
            raise HTTPException(409, "Die Einheit wurde zwischenzeitlich geändert. Bitte erneut laden.")
    refresh_scope(scope)
    return UnitWorkspace(unit=unit, property=prop, active_contracts=active,
                         contract_history=history, insurances=insurances)
