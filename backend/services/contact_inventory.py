"""Complete scoped contact inventory without expanding bank data or private notes."""

import json
from dataclasses import asdict
from datetime import datetime
from functools import cmp_to_key
from heapq import nsmallest
from typing import Literal

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import and_, case, func, or_, select

from ..db.booking_order import bytewise_id
from ..db.orm_models import ContactORM
from .concurrency import etag
from .contract_workspace import _compare, maximum_page_size
from .contract_workspace_search import UnicodeCasefold, ensure_sqlite_casefold
from .portfolio_scope import current_scope, memory_visible, refresh_scope, scoped_clause
from .reference_cursor import pack_reference_cursor, unpack_reference_cursor

ContactSort = Literal["display_name", "contact_type", "first_name", "last_name", "company_name", "email", "phone", "mobile", "city", "zip_code", "country", "updated_at"]
TEXT_SORTS = {"display_name", "contact_type", "first_name", "last_name", "company_name", "email", "phone", "mobile", "city", "zip_code", "country"}
FIELDS = ("id", "contact_type", "first_name", "last_name", "company_name", "email", "phone", "mobile", "city", "zip_code", "country", "updated_at")


class ContactInventoryQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    search: str | None = None
    contact_type: str | None = None
    view: Literal["all", "no_email", "no_phone", "unnamed"] = "all"
    sort_by: ContactSort = "display_name"
    sort_order: Literal["asc", "desc"] = "asc"
    page_size: int = Field(default=25, ge=1)
    cursor: str | None = Field(default=None, min_length=1)

    @field_validator("search", "contact_type")
    @classmethod
    def safe_text(cls, value):
        if value is None:
            return None
        if any(ord(char) < 32 or ord(char) == 127 for char in value):
            raise ValueError("Bitte Text ohne Steuerzeichen verwenden.")
        return value.strip() or None


class ContactInventoryItem(BaseModel):
    id: str
    contact_type: str
    first_name: str | None
    last_name: str | None
    company_name: str | None
    display_name: str
    email: str | None
    phone: str | None
    mobile: str | None
    city: str | None
    zip_code: str | None
    country: str
    updated_at: datetime
    edit_etag: str


class ContactInventoryPage(BaseModel):
    items: list[ContactInventoryItem]
    has_more: bool
    next_cursor: str | None


def binding(query, scope):
    return {"kind": "contact-inventory-v1", "query": query.model_dump(mode="json", exclude={"cursor"}),
            "scope": asdict(scope) if scope is not None else None}


def position(query, scope):
    encoded = unpack_reference_cursor(query.cursor, binding(query, scope))
    if encoded is None:
        return None
    try:
        value, identifier = json.loads(encoded)
        if not isinstance(identifier, str) or not identifier or value is not None and not isinstance(value, str):
            raise ValueError
        if value is not None and query.sort_by == "updated_at":
            value = datetime.fromisoformat(value)
        return value, identifier
    except (TypeError, ValueError):
        raise HTTPException(422, "Die Kontaktseite ist ungültig. Bitte die erste Seite laden.") from None


def _visible(table, scope):
    clause = scoped_clause(table, scope=scope)
    return clause if clause is not None else True


def nonblank(column):
    return func.nullif(func.trim(column), "")


def statement(query, scope):
    contacts = ContactORM.__table__
    person = func.trim(func.coalesce(nonblank(contacts.c.first_name), "") + " " + func.coalesce(nonblank(contacts.c.last_name), ""))
    display = func.coalesce(nonblank(contacts.c.company_name), nonblank(person), "Unbenannt")
    result = select(*(contacts.c[key] for key in FIELDS), display.label("display_name")).where(_visible(contacts, scope))
    if query.contact_type:
        result = result.where(contacts.c.contact_type == query.contact_type)
    if query.view == "no_email":
        result = result.where(nonblank(contacts.c.email).is_(None))
    if query.view == "no_phone":
        result = result.where(nonblank(contacts.c.phone).is_(None), nonblank(contacts.c.mobile).is_(None))
    if query.view == "unnamed":
        result = result.where(nonblank(contacts.c.company_name).is_(None), nonblank(person).is_(None))
    if query.search:
        term = query.search.casefold().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        result = result.where(or_(*(bytewise_id(UnicodeCasefold(column)).like(f"%{term}%", escape="\\") for column in
            (display, *(contacts.c[key] for key in TEXT_SORTS if key != "display_name")))))
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


def display_name(row):
    return (row.company_name or "").strip() or " ".join(value.strip() for value in (row.first_name or "", row.last_name or "") if value.strip()) or "Unbenannt"


def memory_rows(store, query, scope):
    raw = object.__getattribute__(store, "__dict__")
    for row in raw["contacts"].values():
        if not memory_visible(store, "contacts", row, scope=scope):
            continue
        if query.contact_type and query.contact_type != row.contact_type:
            continue
        if query.view == "no_email" and (row.email or "").strip():
            continue
        if query.view == "no_phone" and ((row.phone or "").strip() or (row.mobile or "").strip()):
            continue
        if query.view == "unnamed" and any((value or "").strip() for value in (row.company_name, row.first_name, row.last_name)):
            continue
        projected = {**{key: getattr(row, key) for key in FIELDS}, "display_name": display_name(row)}
        if query.search and not any(query.search.casefold() in (projected[key] or "").casefold() for key in TEXT_SORTS):
            continue
        yield projected


def memory_page(store, query, scope, after, limit):
    def compare(first, second):
        return _compare((first[query.sort_by], first["id"]), (second[query.sort_by], second["id"]), query.sort_order == "desc")
    rows = (row for row in memory_rows(store, query, scope) if after is None or
            _compare((row[query.sort_by], row["id"]), after, query.sort_order == "desc") > 0)
    return nsmallest(limit, rows, key=cmp_to_key(compare))


def item(row):
    return ContactInventoryItem.model_validate({**row, "edit_etag": etag("contacts", row["id"], row["updated_at"])})


def _read_context(store, query):
    if query.page_size > maximum_page_size():
        raise HTTPException(422, "Bitte eine kleinere Seite wählen; alle weiteren Seiten bleiben erreichbar.")
    if hasattr(store, "db"):
        if query.search:
            ensure_sqlite_casefold(store.db)
        return store.db.no_autoflush
    from .payments import _memory_lock
    return _memory_lock


def contact_inventory_page(store, query: ContactInventoryQuery):
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
    return ContactInventoryPage(items=[item(row) for row in rows], has_more=more, next_cursor=cursor)


def contact_inventory_summary(store, query: ContactInventoryQuery):
    scope = current_scope()
    refresh_scope(scope)
    with _read_context(store, query):
        if hasattr(store, "db"):
            rows = statement(query, scope).subquery()
            conditions = {kind: rows.c.contact_type == kind for kind in ("tenant", "owner", "supplier", "manager")}
            conditions.update(no_email=nonblank(rows.c.email).is_(None),
                              no_phone=and_(nonblank(rows.c.phone).is_(None), nonblank(rows.c.mobile).is_(None)))
            aggregates = (func.coalesce(func.sum(case((condition, 1), else_=0)), 0).label(name)
                          for name, condition in conditions.items())
            result = dict(store.db.execute(select(func.count().label("total"), *aggregates).select_from(rows)).mappings().one())
        else:
            result = dict(total=0, tenant=0, owner=0, supplier=0, manager=0, no_email=0, no_phone=0)
            for row in memory_rows(store, query, scope):
                result["total"] += 1
                if row["contact_type"] in {"tenant", "owner", "supplier", "manager"}:
                    result[row["contact_type"]] += 1
                result["no_email"] += not (row["email"] or "").strip()
                result["no_phone"] += not ((row["phone"] or "").strip() or (row["mobile"] or "").strip())
    refresh_scope(scope)
    return result
