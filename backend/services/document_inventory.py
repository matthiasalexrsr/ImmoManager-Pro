"""Small document metadata projections, full scoped filters and aggregates."""

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
from ..db.orm_models import ContractORM, DocumentORM, PropertyORM, UnitORM
from .concurrency import etag
from .contract_workspace import _compare, maximum_page_size
from .contract_workspace_search import UnicodeCasefold, ensure_sqlite_casefold
from .portfolio_scope import current_scope, memory_visible, refresh_scope, scoped_clause
from .reference_cursor import pack_reference_cursor, unpack_reference_cursor

DocumentSort = Literal["title", "document_type", "document_date", "property_name", "unit_label", "contract_label", "updated_at"]
TEXT_SORTS = {"title", "document_type", "property_name", "unit_label", "contract_label"}
FIELDS = ("id", "property_id", "unit_id", "contract_id", "title", "document_type", "document_date", "tags", "file_url", "ai_analyzed_at", "updated_at")


class DocumentInventoryQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    search: str | None = None
    property_id: str | None = Field(default=None, min_length=1)
    unit_id: str | None = Field(default=None, min_length=1)
    contract_id: str | None = Field(default=None, min_length=1)
    document_type: str | None = None
    view: Literal["all", "no_assignment", "not_analyzed", "analyzed", "with_file", "without_file"] = "all"
    date_from: date | None = None
    date_to: date | None = None
    sort_by: DocumentSort = "title"
    sort_order: Literal["asc", "desc"] = "asc"
    page_size: int = Field(default=25, ge=1)
    cursor: str | None = Field(default=None, min_length=1)

    @field_validator("search", "property_id", "unit_id", "contract_id", "document_type")
    @classmethod
    def safe_text(cls, value):
        if value is None:
            return None
        if any(ord(char) < 32 or ord(char) == 127 for char in value):
            raise ValueError("Bitte Text ohne Steuerzeichen verwenden.")
        return value.strip() or None

    @model_validator(mode="after")
    def ordered_dates(self):
        if self.date_from and self.date_to and self.date_from > self.date_to:
            raise ValueError("Das Anfangsdatum darf nicht nach dem Enddatum liegen.")
        return self


class DocumentInventoryItem(BaseModel):
    id: str
    property_id: str | None
    unit_id: str | None
    contract_id: str | None
    title: str
    document_type: str | None
    document_date: date | None
    tags: str | None
    file_url: str
    ai_analyzed_at: datetime | None
    updated_at: datetime
    property_name: str | None
    unit_label: str | None
    contract_label: str | None
    edit_etag: str


class DocumentInventoryPage(BaseModel):
    items: list[DocumentInventoryItem]
    has_more: bool
    next_cursor: str | None


def binding(query, scope):
    return {"kind": "document-inventory-v1", "query": query.model_dump(mode="json", exclude={"cursor"}),
            "scope": asdict(scope) if scope is not None else None}


def position(query, scope):
    encoded = unpack_reference_cursor(query.cursor, binding(query, scope))
    if encoded is None:
        return None
    try:
        value, identifier = json.loads(encoded)
        if not isinstance(identifier, str) or not identifier or value is not None and not isinstance(value, str):
            raise ValueError
        if value is not None and query.sort_by not in TEXT_SORTS:
            value = date.fromisoformat(value) if query.sort_by == "document_date" else datetime.fromisoformat(value)
        return value, identifier
    except (TypeError, ValueError):
        raise HTTPException(422, "Die Dokumentseite ist ungültig. Bitte die erste Seite laden.") from None


def _visible(table, scope):
    clause = scoped_clause(table, scope=scope)
    return clause if clause is not None else True


def statement(query, scope):
    documents, contracts, units, properties = (model.__table__ for model in (DocumentORM, ContractORM, UnitORM, PropertyORM))
    property_id = func.coalesce(documents.c.property_id, units.c.property_id, contracts.c.property_id)
    unit_id = func.coalesce(documents.c.unit_id, contracts.c.unit_id)
    labels = {"property_name": properties.c.name, "unit_label": units.c.label, "contract_label": contracts.c.contract_number}
    result = select(*(documents.c[key] for key in FIELDS), *(value.label(key) for key, value in labels.items())).select_from(documents).outerjoin(
        contracts, and_(contracts.c.id == documents.c.contract_id, _visible(contracts, scope))).outerjoin(
        units, and_(units.c.id == unit_id, _visible(units, scope))).outerjoin(
        properties, and_(properties.c.id == property_id, _visible(properties, scope))).where(_visible(documents, scope))
    for column, value in ((property_id, query.property_id), (unit_id, query.unit_id), (documents.c.contract_id, query.contract_id), (documents.c.document_type, query.document_type)):
        if value is not None:
            result = result.where(column == value)
    if query.date_from:
        result = result.where(documents.c.document_date >= query.date_from)
    if query.date_to:
        result = result.where(documents.c.document_date <= query.date_to)
    if query.view == "no_assignment":
        result = result.where(documents.c.property_id.is_(None), documents.c.unit_id.is_(None), documents.c.contract_id.is_(None))
    if query.view in {"analyzed", "not_analyzed"}:
        result = result.where(documents.c.ai_analyzed_at.is_not(None) if query.view == "analyzed" else documents.c.ai_analyzed_at.is_(None))
    if query.view in {"with_file", "without_file"}:
        result = result.where(documents.c.file_url != "" if query.view == "with_file" else documents.c.file_url == "")
    if query.search:
        term = query.search.casefold().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        result = result.where(or_(*(bytewise_id(UnicodeCasefold(column)).like(f"%{term}%", escape="\\") for column in
            (documents.c.title, documents.c.tags, documents.c.document_type, *labels.values()))))
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
    for doc in raw["documents"].values():
        if not memory_visible(store, "documents", doc, scope=scope):
            continue
        contract = raw["contracts"].get(doc.contract_id)
        unit = raw["units"].get(doc.unit_id or getattr(contract, "unit_id", None))
        prop = raw["properties"].get(doc.property_id or getattr(unit, "property_id", None) or getattr(contract, "property_id", None))
        property_id, unit_id = getattr(prop, "id", None), getattr(unit, "id", None)
        if any(value is not None and value != actual for value, actual in ((query.property_id, property_id), (query.unit_id, unit_id), (query.contract_id, doc.contract_id), (query.document_type, doc.document_type))):
            continue
        if query.date_from and (doc.document_date is None or doc.document_date < query.date_from) or query.date_to and (doc.document_date is None or doc.document_date > query.date_to):
            continue
        if query.view == "no_assignment" and any((doc.property_id, doc.unit_id, doc.contract_id)):
            continue
        if query.view == "analyzed" and doc.ai_analyzed_at is None or query.view == "not_analyzed" and doc.ai_analyzed_at is not None:
            continue
        if query.view == "with_file" and not doc.file_url or query.view == "without_file" and doc.file_url:
            continue
        labels = {"property_name": getattr(prop, "name", None), "unit_label": getattr(unit, "label", None), "contract_label": getattr(contract, "contract_number", None)}
        if query.search and not any(query.search.casefold() in (value or "").casefold() for value in (doc.title, doc.tags, doc.document_type, *labels.values())):
            continue
        yield {**{key: getattr(doc, key) for key in FIELDS}, **labels}


def memory_page(store, query, scope, after, limit):
    def compare(first, second):
        return _compare((first[query.sort_by], first["id"]), (second[query.sort_by], second["id"]), query.sort_order == "desc")
    rows = (row for row in memory_rows(store, query, scope) if after is None or
            _compare((row[query.sort_by], row["id"]), after, query.sort_order == "desc") > 0)
    return nsmallest(limit, rows, key=cmp_to_key(compare))


def item(row):
    return DocumentInventoryItem.model_validate({**row, "edit_etag": etag("documents", row["id"], row["updated_at"])})


def _read_context(store, query):
    if query.page_size > maximum_page_size():
        raise HTTPException(422, "Bitte eine kleinere Seite wählen; alle weiteren Seiten bleiben erreichbar.")
    if hasattr(store, "db"):
        if query.search:
            ensure_sqlite_casefold(store.db)
        return store.db.no_autoflush
    from .payments import _memory_lock
    return _memory_lock


def document_inventory_page(store, query: DocumentInventoryQuery):
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
    return DocumentInventoryPage(items=[item(row) for row in rows], has_more=more, next_cursor=cursor)


def document_inventory_summary(store, query: DocumentInventoryQuery):
    scope = current_scope()
    refresh_scope(scope)
    with _read_context(store, query):
        if hasattr(store, "db"):
            rows = statement(query, scope).subquery()
            result = dict(store.db.execute(select(func.count().label("total"),
                *(func.coalesce(func.sum(case((condition, 1), else_=0)), 0).label(name) for name, condition in (
                    ("with_file", rows.c.file_url != ""), ("analyzed", rows.c.ai_analyzed_at.is_not(None)),
                    ("no_assignment", and_(rows.c.property_id.is_(None), rows.c.unit_id.is_(None), rows.c.contract_id.is_(None)))))
            ).select_from(rows)).mappings().one())
        else:
            result = dict(total=0, with_file=0, analyzed=0, no_assignment=0)
            for row in memory_rows(store, query, scope):
                result["total"] += 1
                result["with_file"] += bool(row["file_url"])
                result["analyzed"] += row["ai_analyzed_at"] is not None
                result["no_assignment"] += not any((row["property_id"], row["unit_id"], row["contract_id"]))
    refresh_scope(scope)
    return result
