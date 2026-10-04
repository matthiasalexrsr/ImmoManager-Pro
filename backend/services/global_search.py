"""Complete bounded keyword pages across actual, authorized entity sources."""

from dataclasses import dataclass
from heapq import nlargest
from typing import Any

from fastapi import HTTPException
from sqlalchemy import String, func, literal, select

from ..db.booking_order import bytewise_id
from ..db.orm_models import Base
from .contract_workspace_search import UnicodeCasefold, ensure_sqlite_casefold
from .payments import _memory_lock
from .portfolio_scope import current_scope, memory_visible, refresh_scope, scoped_clause
from .tenancy_workflow import decode_cursor, encode_cursor


@dataclass(frozen=True)
class Source:
    kind: str
    collection: str
    fields: tuple[str, ...]
    display_fields: tuple[str, ...]
    detail: str | None
    url: str
    detail_url: bool = False


SOURCES = (
    Source("property", "properties", ("name", "address_line", "postal_code", "city"), ("name",), "city", "/properties", True),
    Source("tenant", "tenants", ("full_name", "email"), ("full_name",), "email", "/tenants"),
    Source("unit", "units", ("label",), ("label",), "unit_type", "/units", True),
    Source("contract", "contracts", ("contract_number",), ("contract_number",), "status", "/contracts"),
    Source("task", "tasks", ("title", "description"), ("title",), "status", "/tasks"),
    Source("invoice", "invoices", ("supplier", "payment_terms"), ("supplier",), "gross_amount", "/invoices"),
    Source("account", "accounts", ("name", "bank_name", "iban"), ("name",), "account_type", "/accounts"),
    Source("booking", "bookings", ("payment_text",), ("payment_text",), "amount", "/bookings"),
    Source("maintenance", "maintenance_cases", ("title", "description"), ("title",), "status", "/maintenance"),
    Source("document", "documents", ("title", "description"), ("title",), "document_type", "/documents"),
    Source("contact", "contacts", ("first_name", "last_name", "email", "company_name"), ("first_name", "last_name", "company_name"), "company_name", "/contacts"),
    Source("deposit", "deposits", ("notes",), (), "status", "/deposits"),
    Source("category", "categories", ("name",), ("name",), "category_type", "/categories"),
    Source("lead", "leads", ("full_name", "email"), ("full_name",), "status", "/leads"),
    Source("listing", "listings", ("title", "description"), ("title",), "status", "/listings"),
    Source("insurance", "insurances", ("provider", "policy_number", "insurance_type"), ("provider",), "insurance_type", "/insurances"),
)


def _joined(table, fields):
    expression: Any = literal("")
    for field in fields:
        expression = expression + func.coalesce(table.c[field].cast(String()), "") + literal(" ")
    return func.trim(expression)


def _sql_page(store, source, term, upper, width):
    table = Base.metadata.tables[source.collection]
    columns = {"id", *source.display_fields}
    if source.detail:
        columns.add(source.detail)
    query = select(*(table.c[field] for field in sorted(columns)))
    escaped = term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    query = query.where(UnicodeCasefold(_joined(table, source.fields)).like("%" + escaped + "%", escape="\\"))
    scope = scoped_clause(table)
    if scope is not None:
        query = query.where(scope)
    identifier = bytewise_id(table.c.id)
    if upper is not None:
        query = query.where(identifier < upper)
    return store.db.execute(query.order_by(identifier.desc()).limit(width)).mappings().all()


def _memory_page(store, source, term, upper, width):
    raw = object.__getattribute__(store, "__dict__").get(source.collection, {})
    candidates = (
        row for row in raw.values()
        if (upper is None or row.id < upper)
        and memory_visible(store, source.collection, row)
        and term in " ".join(str(getattr(row, field, None) or "") for field in source.fields).strip().casefold()
    )
    return [row.model_dump() for row in nlargest(width, candidates, key=lambda row: row.id)]


def _hit(source, row):
    identifier = row["id"]
    display = " ".join(str(row.get(field) or "") for field in source.display_fields).strip()
    if not display:
        display = ("Kaution " if source.kind == "deposit" else "") + identifier[:8]
    detail = row.get(source.detail) if source.detail else None
    return {"entity_type": source.kind, "id": identifier, "display": display,
            "detail": "" if detail is None else str(detail),
            "url": source.url + ("/" + identifier if source.detail_url else "")}


def page(store, query: str, *, after: str | None = None, limit: int = 50):
    term = query.strip().casefold()
    if not term:
        raise HTTPException(422, "Bitte einen Suchbegriff eingeben.")
    if type(limit) is not int or not 1 <= limit <= 500:
        raise HTTPException(422, "Bitte eine Seitengröße zwischen 1 und 500 wählen.")
    captured = current_scope()
    refresh_scope(captured)
    binding = {"kind": "global-keyword-search-v1", "query": term, "limit": limit,
               "actor": None if captured is None else {
                   "id": captured.user_id, "role": captured.role,
                   "unrestricted": captured.unrestricted, "portfolio_ids": list(captured.portfolio_ids)}}
    point = decode_cursor(after, binding)
    if point is not None and (len(point) != 2 or type(point[0]) is not int
                              or not 0 <= point[0] < len(SOURCES) or not isinstance(point[1], str)):
        raise HTTPException(422, "Ungültige Suchseite. Erste Seite erneut laden.")
    sql = hasattr(store, "db")
    if sql:
        ensure_sqlite_casefold(store.db)
    found: list[dict[str, Any]] = []
    positions: list[list[Any]] = []
    with store.db.no_autoflush if sql else _memory_lock:
        for rank, source in enumerate(SOURCES):
            if point is not None and rank < point[0]:
                continue
            upper = point[1] if point is not None and rank == point[0] else None
            width = limit + 1 - len(found)
            rows = (_sql_page if sql else _memory_page)(store, source, term, upper, width)
            found.extend(_hit(source, row) for row in rows)
            positions.extend([rank, row["id"]] for row in rows)
            if len(found) > limit:
                break
    refresh_scope(captured)
    has_more = len(found) > limit
    return {"query": query, "count": min(len(found), limit), "results": found[:limit],
            "semantic": False, "has_more": has_more,
            "next_after": encode_cursor(binding, positions[limit - 1]) if has_more else None}
