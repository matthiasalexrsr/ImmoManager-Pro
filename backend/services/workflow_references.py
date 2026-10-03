"""Private, searchable keyset choices; filters run before the bounded page."""

import heapq
from contextlib import nullcontext
from typing import Any, Literal

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from .. import auth
from ..config import settings
from ..db.booking_order import bytewise_id
from ..db.orm_models import (
    AccountORM,
    ContractORM,
    DocumentORM,
    HandoverProtocolORM,
    MeterORM,
    MeterReadingORM,
    PortfolioORM,
    PropertyORM,
    TenantORM,
    UnitORM,
)
from ..storage import NotFoundError
from .contract_workspace_search import UnicodeCasefold, ensure_sqlite_casefold
from .portfolio_scope import current_scope, refresh_scope, scope_context, scope_from_user, scoped_clause
from .reference_cursor import pack_reference_cursor, unpack_reference_cursor

ReferenceKind = Literal["properties", "units", "contracts", "users", "documents", "handover-protocols", "meter-readings", "meters", "portfolios", "accounts", "statements"]


class WorkflowReferenceQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    search: str | None = None
    portfolio_id: str | None = Field(default=None, min_length=1)
    property_id: str | None = Field(default=None, min_length=1)
    unit_id: str | None = Field(default=None, min_length=1)
    contract_id: str | None = Field(default=None, min_length=1)
    period_id: str | None = Field(default=None, min_length=1)
    dispute_case_id: str | None = Field(default=None, min_length=1)
    direction: Literal["move_in", "move_out"] | None = None
    selected_id: str | None = Field(default=None, min_length=1)
    cursor: str | None = Field(default=None, min_length=1)
    page_size: int = Field(default=25, ge=1)

    @field_validator("search")
    @classmethod
    def normalize_search(cls, value):
        if value is None:
            return None
        value.encode("utf-8")
        if any(ord(character) < 32 for character in value):
            raise ValueError("Bitte Suchtext ohne Steuerzeichen verwenden.")
        return value.strip().casefold() or None

    @field_validator("portfolio_id", "property_id", "unit_id", "contract_id", "period_id", "dispute_case_id", "selected_id", "cursor")
    @classmethod
    def safe_identifier(cls, value):
        if value is not None:
            value.encode("utf-8")
            if "\0" in value:
                raise ValueError("Die Referenz enthält ein ungültiges Nullzeichen.")
        return value


MODELS: dict[str, Any] = {"properties": PropertyORM, "units": UnitORM, "contracts": ContractORM,
                         "portfolios": PortfolioORM, "accounts": AccountORM,
                         "documents": DocumentORM, "handover-protocols": HandoverProtocolORM,
                         "meter-readings": MeterReadingORM, "meters": MeterORM}
FIELDS = {
    "portfolios": ("id", "name"),
    "accounts": ("id", "name", "portfolio_id", "account_type", "bank_name"),
    "properties": ("id", "name", "portfolio_id", "address_line", "postal_code", "city", "status"),
    "units": ("id", "label", "property_id", "status"),
    "contracts": ("id", "contract_number", "property_id", "unit_id", "tenant_id", "status", "start_date", "end_date"),
    "documents": ("id", "title", "contract_id", "document_type", "document_date"),
    "handover-protocols": ("id", "unit_id", "contract_id", "protocol_type", "protocol_date", "status"),
    "meter-readings": ("id", "handover_id", "meter_type", "meter_number", "reading_value", "unit", "created_at"),
    "meters": ("id", "unit_id", "meter_type", "serial_number", "location", "is_active"),
}


def _parents(store, query):
    property_id, unit_id, contract_id = query.property_id, query.unit_id, query.contract_id
    try:
        if query.portfolio_id:
            store.get_portfolio(query.portfolio_id)
        if contract_id:
            contract = store.get_contract(contract_id)
            if (property_id and property_id != contract.property_id) or (unit_id and unit_id != contract.unit_id):
                raise HTTPException(422, "Vertrag, Immobilie und Einheit gehören nicht zusammen.")
            property_id, unit_id = contract.property_id, contract.unit_id
        if unit_id:
            unit = store.get_unit(unit_id)
            if property_id and property_id != unit.property_id:
                raise HTTPException(422, "Einheit und Immobilie gehören nicht zusammen.")
            property_id = unit.property_id
        prop = store.get_property(property_id) if property_id else None
        if prop and query.portfolio_id and prop.portfolio_id != query.portfolio_id:
            raise HTTPException(422, "Immobilie und Portfolio gehören nicht zusammen.")
        return prop, unit_id, contract_id
    except NotFoundError:
        raise HTTPException(404, "Die ausgewählte Referenz ist nicht verfügbar.") from None


def _statement(kind):
    model = MODELS[kind]
    columns = [getattr(model, field) for field in FIELDS[kind]]
    statement = select(*columns)
    property_column = unit_column = contract_column = None
    if kind in {"portfolios", "accounts"}:
        pass
    elif kind == "properties":
        property_column = model.id
    elif kind == "units":
        property_column, unit_column = model.property_id, model.id
    elif kind == "contracts":
        statement = statement.add_columns(TenantORM.full_name.label("tenant_name")).join(TenantORM, TenantORM.id == model.tenant_id)
        property_column, unit_column, contract_column = model.property_id, model.unit_id, model.id
    elif kind == "documents":
        statement = statement.outerjoin(ContractORM, ContractORM.id == model.contract_id).outerjoin(UnitORM, UnitORM.id == model.unit_id)
        property_column = func.coalesce(model.property_id, UnitORM.property_id, ContractORM.property_id)
        unit_column = func.coalesce(model.unit_id, ContractORM.unit_id)
        contract_column = model.contract_id
        statement = statement.add_columns(property_column.label("property_id"), unit_column.label("unit_id"))
    elif kind in {"handover-protocols", "meter-readings"}:
        protocol = model if kind == "handover-protocols" else HandoverProtocolORM
        if kind == "meter-readings":
            statement = statement.join(protocol, protocol.id == model.handover_id).add_columns(
                protocol.unit_id, protocol.contract_id, protocol.protocol_type, protocol.status.label("protocol_status"))
        statement = statement.join(ContractORM, ContractORM.id == protocol.contract_id).where(protocol.status == "finalized")
        property_column, unit_column, contract_column = ContractORM.property_id, protocol.unit_id, protocol.contract_id
        statement = statement.add_columns(property_column.label("property_id"))
    else:
        statement = statement.join(UnitORM, UnitORM.id == model.unit_id)
        property_column, unit_column = UnitORM.property_id, model.unit_id
        statement = statement.add_columns(property_column.label("property_id"))
    clause = scoped_clause(model)
    if clause is not None:
        statement = statement.where(clause)
    return statement, property_column, unit_column, contract_column


def _memory_choice(store, kind, row):
    result = {field: getattr(row, field) for field in FIELDS[kind]}
    if kind == "contracts":
        result["tenant_name"] = store.get_tenant(row.tenant_id).full_name
    elif kind == "documents":
        contract = store.get_contract(row.contract_id) if row.contract_id else None
        unit = store.get_unit(row.unit_id) if row.unit_id else None
        result["property_id"] = row.property_id or (unit.property_id if unit else None) or (contract.property_id if contract else None)
        result["unit_id"] = row.unit_id or (contract.unit_id if contract else None)
    elif kind in {"handover-protocols", "meter-readings"}:
        protocol = row if kind == "handover-protocols" else store.get_handover_protocol(row.handover_id)
        if protocol.status != "finalized":
            return None
        contract = store.get_contract(protocol.contract_id)
        result["property_id"] = contract.property_id
        if kind == "meter-readings":
            result.update(unit_id=protocol.unit_id, contract_id=protocol.contract_id,
                          protocol_type=protocol.protocol_type, protocol_status=protocol.status)
    elif kind == "meters":
        result["property_id"] = store.get_unit(row.unit_id).property_id
    return result


def _eligible(choice, kind, prop, unit_id, contract_id, direction):
    if prop and (choice["id"] if kind == "properties" else choice.get("property_id")) != prop.id:
        return False
    if unit_id and kind != "properties" and (choice["id"] if kind == "units" else choice.get("unit_id")) != unit_id:
        return False
    if contract_id and kind in {"contracts", "documents", "handover-protocols", "meter-readings"}:
        if (choice["id"] if kind == "contracts" else choice.get("contract_id")) != contract_id:
            return False
    return not direction or choice.get("protocol_type") == direction


def _rows(store, kind, query, prop, unit_id, contract_id, after, *, selected=False):
    if hasattr(store, "db"):
        statement, property_column, unit_column, contract_column = _statement(kind)
        if query.portfolio_id:
            if kind == "portfolios":
                statement = statement.where(MODELS[kind].id == query.portfolio_id)
            elif kind in {"accounts", "properties"}:
                statement = statement.where(MODELS[kind].portfolio_id == query.portfolio_id)
            else:
                statement = statement.where(property_column.in_(select(PropertyORM.id).where(PropertyORM.portfolio_id == query.portfolio_id)))
        if prop:
            statement = statement.where(property_column == prop.id)
        if unit_id and unit_column is not None:
            statement = statement.where(unit_column == unit_id)
        if contract_id and contract_column is not None:
            statement = statement.where(contract_column == contract_id)
        if query.direction:
            protocol = MODELS[kind] if kind == "handover-protocols" else HandoverProtocolORM
            statement = statement.where(protocol.protocol_type == query.direction)
        if selected:
            return [dict(row) for row in store.db.execute(statement.where(MODELS[kind].id == query.selected_id).limit(1)).mappings()]
        if query.search:
            ensure_sqlite_casefold(store.db)
            escaped = query.search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            # Search only the minimal selection metadata, never hidden notes,
            # secrets, original documents or whole private adapter sources.
            strings = [column for column in statement.selected_columns if isinstance(column.type.python_type, type)
                       and column.type.python_type is str]
            statement = statement.where(or_(*(UnicodeCasefold(column).like(f"%{escaped}%", escape="\\") for column in strings)))
        identifier = bytewise_id(MODELS[kind].id)
        if after is not None:
            statement = statement.where(identifier < after)
        return [dict(row) for row in store.db.execute(statement.order_by(identifier.desc()).limit(query.page_size + 1)).mappings()]

    collection = getattr(store, kind.replace("-", "_"))

    def candidates():
        source = [collection.get(query.selected_id)] if selected else collection.values()
        for row in source:
            if row is None or (not selected and after is not None and row.id >= after):
                continue
            try:
                choice = _memory_choice(store, kind, row)
            except NotFoundError:
                continue
            if not choice or not _eligible(choice, kind, prop, unit_id, contract_id, query.direction):
                continue
            if query.portfolio_id:
                portfolio = choice["id"] if kind == "portfolios" else choice.get("portfolio_id")
                if portfolio is None and choice.get("property_id"):
                    portfolio = store.get_property(choice["property_id"]).portfolio_id
                if portfolio != query.portfolio_id:
                    continue
            if not selected and query.search and not any(query.search in value.casefold() for value in choice.values() if isinstance(value, str)):
                continue
            yield choice
    return list(candidates()) if selected else heapq.nlargest(query.page_size + 1, candidates(), key=lambda row: row["id"])


def workflow_reference_choices(store, kind: ReferenceKind, query: WorkflowReferenceQuery, actor_id: str):
    # Resolve accounts before domain state, as compound memory writes do. A
    # bounded heap still iterates the source; normal writers must not change
    # its size or parents while either the page or pinned choice is resolved.
    from .tenant_privacy import _memory_privacy_lock

    with nullcontext() if hasattr(store, "db") else _memory_privacy_lock():
        return _reference_choices_locked(store, kind, query, actor_id)


def _reference_choices_locked(store, kind, query, actor_id):
    if query.page_size > settings.workflow_reference_page_budget:
        raise HTTPException(422, "Bitte eine kleinere Auswahlseite verwenden; alle weiteren Seiten bleiben verfügbar.")
    if query.direction and kind not in {"handover-protocols", "meter-readings"}:
        raise HTTPException(422, "Eine Übergaberichtung gilt nur für Protokolle und deren Ablesungen.")
    if kind == "statements":
        if bool(query.period_id) == bool(query.dispute_case_id):
            raise HTTPException(422, "Bitte genau eine Abrechnungsperiode oder Widerspruchsakte auswählen.")
    elif query.period_id or query.dispute_case_id:
        raise HTTPException(422, "Abrechnungsperiode und Widerspruchsakte gelten nur für Einzelabrechnungen.")
    if kind in {"portfolios", "accounts"} and (query.property_id or query.unit_id or query.contract_id):
        raise HTTPException(422, "Konten und Portfolios werden anhand des Portfolios ausgewählt.")
    user = auth.get_user_by_id(actor_id)
    if not user or not user["is_active"]:
        raise HTTPException(401, "Die Anmeldung ist nicht mehr gültig.")
    captured = current_scope()
    if captured is not None and captured.user_id != actor_id:
        raise HTTPException(403, "Die Benutzerbindung ist nicht gültig.")
    if captured is None:
        captured = scope_from_user(user)
    else:
        refresh_scope(captured)
    binding = {"kind": kind, "query": query.model_dump(mode="json", exclude={"cursor"}),
               "scope": {"user_id": captured.user_id, "role": captured.role,
                         "unrestricted": captured.unrestricted, "portfolio_ids": captured.portfolio_ids}}
    after = unpack_reference_cursor(query.cursor, binding)
    with scope_context(captured):
        if kind == "statements":
            from .billing_statement_choices import statement_reference_choices
            return statement_reference_choices(store, query, actor_id, binding, after, resolve_parents=_parents)
        with Session(store.db.get_bind(), autoflush=False) if hasattr(store, "db") else nullcontext() as db:
            if db is not None:
                from ..repositories.sql_store import SQLAlchemyStore

                active = SQLAlchemyStore(db)
            else:
                active = store
            prop, unit_id, contract_id = _parents(active, query)
            selected = None
            if kind == "users":
                if user["role"] not in {"eigentuemer", "verwalter"}:
                    raise HTTPException(403, "Nur die Verwaltung darf Verantwortliche auswählen.")
                if prop is None:
                    raise HTTPException(422, "Bitte zuerst eine Immobilie für die Verantwortlichenwahl auswählen.")
                rows = auth.assignment_choices(prop.portfolio_id, query.search, after, query.page_size + 1)
                if query.selected_id:
                    candidate = auth.get_user_by_id(query.selected_id)
                    if candidate and candidate["is_active"]:
                        from ..permissions import may_write_resource

                        if may_write_resource(candidate["role"], "tasks") and (candidate["role"] == "eigentuemer"
                            or candidate.get("portfolio_access") == "all" or prop.portfolio_id in candidate.get("portfolio_ids", ())):
                            selected = {key: candidate[key] for key in ("id", "full_name", "role")}
            else:
                rows = _rows(active, kind, query, prop, unit_id, contract_id, after)
                if query.selected_id:
                    selected_rows = _rows(active, kind, query, prop, unit_id, contract_id, None, selected=True)
                    selected = selected_rows[0] if selected_rows else None
            more = len(rows) > query.page_size
            items = rows[:query.page_size]
            refresh_scope(captured)
            return {"items": items, "selected": selected, "has_more": more,
                    "next_cursor": pack_reference_cursor(binding, items[-1]["id"]) if more else None}
