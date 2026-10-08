"""Global search: per-type substring match, keyset pages by id and exact counts.

SQL stores query the database (the portfolio boundary is added to every SELECT by
portfolio_scope); the memory store filters its already scoped collections in Python
with the same haystack, ordering and cursor semantics.

Haystack: the searchable columns, NULL as "", joined by one space, lower-cased; a hit
contains the lower-cased, stripped query as a literal substring (no wildcards).
"""

import base64
import binascii
import json
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, literal, select

from ..db.orm_models import Base

DEFAULT_LIMIT = 10
MAX_LIMIT = 100
EXPORT_BATCH = 1000


class SearchError(ValueError):
    """Invalid type or cursor."""


def _contact_display(contact) -> str:
    name = " ".join(part.strip() for part in [contact.first_name, contact.last_name] if part and part.strip())
    return name or (contact.company_name or "").strip() or (contact.email or "").strip() or "Kontakt"


def _short(item) -> str:
    return str(item.id)[:8]


@dataclass(frozen=True)
class SearchType:
    entity_type: str
    table: str
    list_method: str
    fields: tuple[str, ...]
    display: Callable[[Any], str]
    detail: Callable[[Any], str]
    url: Callable[[Any], str]


def _fixed(url: str) -> Callable[[Any], str]:
    return lambda _item: url


# Order is the display order of the overview. Every field is a column of the table
# and a field of the memory model (checked in test_global_search).
SEARCH_TYPES: tuple[SearchType, ...] = (
    SearchType("property", "properties", "list_properties", ("name", "address_line", "postal_code", "city"),
               lambda p: p.name, lambda p: p.city or "", lambda p: f"/properties/{p.id}"),
    SearchType("tenant", "tenants", "list_tenants", ("full_name", "email"),
               lambda t: t.full_name, lambda t: t.email or "", _fixed("/tenants")),
    SearchType("unit", "units", "list_units", ("label",),
               lambda u: u.label, lambda u: u.unit_type, lambda u: f"/units/{u.id}"),
    SearchType("contract", "contracts", "list_contracts", ("contract_number",),
               lambda c: c.contract_number, lambda c: c.status, _fixed("/contracts")),
    SearchType("task", "tasks", "list_tasks", ("title", "description"),
               lambda t: t.title, lambda t: t.status, _fixed("/tasks")),
    SearchType("invoice", "invoices", "list_invoices", ("supplier", "payment_terms"),
               lambda i: i.supplier, lambda i: str(float(i.gross_amount)), _fixed("/invoices")),
    SearchType("account", "accounts", "list_accounts", ("name", "bank_name", "iban"),
               lambda a: a.name, lambda a: a.account_type or "", _fixed("/accounts")),
    SearchType("booking", "bookings", "list_bookings", ("payment_text",),
               lambda b: b.payment_text or _short(b), lambda b: str(float(b.amount)), _fixed("/bookings")),
    SearchType("maintenance", "maintenance_cases", "list_maintenance_cases", ("title", "description"),
               lambda m: m.title, lambda m: m.status, _fixed("/maintenance")),
    SearchType("document", "documents", "list_documents", ("title", "description"),
               lambda d: d.title, lambda d: d.document_type or "", _fixed("/documents")),
    SearchType("contact", "contacts", "list_contacts", ("first_name", "last_name", "company_name", "email"),
               _contact_display, lambda c: c.company_name or "", _fixed("/contacts")),
    SearchType("deposit", "deposits", "list_deposits", ("notes",),
               lambda d: f"Kaution {_short(d)}", lambda d: d.status or "", _fixed("/deposits")),
    SearchType("category", "categories", "list_categories", ("name",),
               lambda c: c.name, lambda c: c.category_type or "", _fixed("/categories")),
    SearchType("lead", "leads", "list_leads", ("full_name", "email"),
               lambda x: x.full_name or _short(x), lambda x: x.status or "", _fixed("/leads")),
    SearchType("listing", "listings", "list_listings", ("title", "description"),
               lambda x: x.title or _short(x), lambda x: x.status or "", _fixed("/listings")),
    SearchType("insurance", "insurances", "list_insurances", ("provider", "policy_number", "insurance_type"),
               lambda x: x.provider or _short(x), lambda x: x.insurance_type or "", _fixed("/insurances")),
)
TYPES_BY_NAME = {spec.entity_type: spec for spec in SEARCH_TYPES}


def get_type(entity_type: str) -> SearchType:
    spec = TYPES_BY_NAME.get(entity_type)
    if spec is None:
        raise SearchError(f"Unbekannter Suchtyp: {entity_type}")
    return spec


def normalize_query(q: str) -> str:
    return q.strip().lower()


def escape_like(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def encode_cursor(entity_type: str, after_id: str) -> str:
    raw = json.dumps({"t": entity_type, "a": after_id}, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_cursor(cursor: str, entity_type: str) -> str:
    try:
        data = json.loads(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)))
    except (binascii.Error, ValueError, UnicodeDecodeError) as exc:
        raise SearchError("Ungültiger Cursor") from exc
    if not isinstance(data, dict) or data.get("t") != entity_type or not isinstance(data.get("a"), str):
        raise SearchError("Ungültiger Cursor")
    return data["a"]


def to_hit(spec: SearchType, item) -> dict:
    return {
        "entity_type": spec.entity_type,
        "id": item.id,
        "display": spec.display(item),
        "detail": spec.detail(item),
        "url": spec.url(item),
    }


@dataclass
class Page:
    items: list
    total: int | None
    has_more: bool
    next_cursor: str | None


# ── SQL ──

_ORM_BY_TABLE = {getattr(mapper.local_table, "name", None): mapper.class_ for mapper in Base.registry.mappers}


def _sql_lower(db) -> Callable[[Any], Any]:
    if db.get_bind().dialect.name == "sqlite":
        # SQLite's lower() folds ASCII only; use Python's like the memory store
        db.connection().connection.driver_connection.create_function(
            "immo_lower", 1, lambda v: v.lower() if isinstance(v, str) else v, deterministic=True)
        return func.immo_lower
    return func.lower


def _sql_match(db, model, spec: SearchType, needle: str):
    parts: list[Any] = []
    for index, field in enumerate(spec.fields):
        if index:
            parts.append(literal(" "))
        parts.append(func.coalesce(getattr(model, field), ""))
    haystack: Any = parts[0]
    for part in parts[1:]:
        haystack = haystack.op("||")(part)
    return _sql_lower(db)(haystack).like(f"%{escape_like(needle)}%", escape="\\")


def _sql_page(db, spec: SearchType, needle: str, limit: int, after: str | None, with_total: bool) -> Page:
    model = _ORM_BY_TABLE[spec.table]
    match = _sql_match(db, model, spec, needle)
    stmt = select(model).where(match)
    if after is not None:
        stmt = stmt.where(model.id > after)
    rows = list(db.scalars(stmt.order_by(model.id).limit(limit + 1)))
    total = db.scalar(select(func.count()).select_from(model).where(match)) if with_total else None
    return _page(spec, rows, limit, total)


# ── memory ──

def _memory_page(store, spec: SearchType, needle: str, limit: int, after: str | None, with_total: bool) -> Page:
    matches = sorted((item for item in getattr(store, spec.list_method)() if _memory_match(item, spec, needle)),
                     key=lambda item: item.id)
    total = len(matches) if with_total else None
    if after is not None:
        matches = [item for item in matches if item.id > after]
    return _page(spec, matches[:limit + 1], limit, total)


def _memory_match(item, spec: SearchType, needle: str) -> bool:
    values = (getattr(item, field, None) for field in spec.fields)
    return needle in " ".join("" if value is None else str(value) for value in values).lower()


def _page(spec: SearchType, rows: list, limit: int, total: int | None) -> Page:
    has_more = len(rows) > limit
    rows = rows[:limit]
    cursor = encode_cursor(spec.entity_type, rows[-1].id) if has_more and rows else None
    return Page([to_hit(spec, row) for row in rows], total, has_more, cursor)


# ── API ──

def search_page(store, spec: SearchType, q: str, *, limit: int, cursor: str | None = None,
                with_total: bool = True) -> Page:
    needle = normalize_query(q)
    after = decode_cursor(cursor, spec.entity_type) if cursor else None
    if hasattr(store, "db"):
        return _sql_page(store.db, spec, needle, limit, after, with_total)
    return _memory_page(store, spec, needle, limit, after, with_total)


def iter_all(store, spec: SearchType, q: str, batch: int = EXPORT_BATCH) -> Iterator[dict]:
    """Every hit of one type, keyset batch by batch."""
    cursor = None
    while True:
        page = search_page(store, spec, q, limit=batch, cursor=cursor, with_total=False)
        yield from page.items
        if not page.has_more:
            return
        cursor = page.next_cursor
