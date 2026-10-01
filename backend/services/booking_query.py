"""Bounded booking reads and authenticated, filter-bound keyset cursors.

Each SQL page asks for at most page_size + 1 records, without COUNT or OFFSET.
Browsing is a live view: inserts before an existing cursor appear on refresh,
while older inserts can appear on subsequent pages. CSV uses a separate snapshot.
"""
import base64
import hashlib
import heapq
import hmac
import json
import re
from datetime import date
from time import time
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import or_, select, tuple_

from ..config import settings
from ..db.booking_order import bytewise_id
from ..db.orm_models import AccountORM, BookingORM, CategoryORM, PropertyORM, TenantORM, UnitORM
from ..models import Booking
from .portfolio_scope import current_scope, scoped_clause

ORDER: Literal["booking_date_desc_id_desc"] = "booking_date_desc_id_desc"
CURSOR_LIFETIME_SECONDS = 3600
_ID = r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,99}$"


class BookingFilters(BaseModel):
    model_config = ConfigDict(extra="forbid")
    account_id: str | None = Field(default=None, pattern=_ID, max_length=100)
    property_id: str | None = Field(default=None, pattern=_ID, max_length=100)
    tenant_id: str | None = Field(default=None, pattern=_ID, max_length=100)
    status: Literal["open", "matched", "booked", "confirmed"] | None = None
    date_from: date | None = None
    date_to: date | None = None
    search: str | None = Field(default=None, max_length=200)
    view: Literal["all", "uncategorized", "no_receipt", "income", "expense"] = "all"

    @field_validator("date_from", "date_to", mode="before")
    @classmethod
    def iso_date(cls, value):
        if isinstance(value, str) and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            raise ValueError("Use an ISO date YYYY-MM-DD")
        return value

    @field_validator("search")
    @classmethod
    def safe_search(cls, value):
        if value is not None and any(ord(char) < 32 or ord(char) == 127 for char in value):
            raise ValueError("Search must not contain control characters")
        return value.strip() or None if value is not None else None

    @model_validator(mode="after")
    def date_range(self):
        if self.date_from and self.date_to and self.date_from > self.date_to:
            raise ValueError("date_from must not follow date_to")
        return self


class BookingPageQuery(BookingFilters):
    page_size: int = Field(default=100, ge=1, le=5000)
    order: Literal["booking_date_desc_id_desc"] = ORDER
    cursor: str | None = Field(default=None, min_length=1, max_length=4096)


class BookingPageItem(Booking):
    account_name: str | None = None
    category_name: str | None = None
    property_name: str | None = None
    unit_label: str | None = None
    tenant_name: str | None = None


class BookingPage(BaseModel):
    items: list[BookingPageItem]
    next_cursor: str | None
    has_more: bool


class BookingQueryError(ValueError):
    def __init__(self, clear_code, message):
        super().__init__(message)
        self.clear_code = clear_code

    @property
    def detail(self):
        return {"clear_code": self.clear_code, "message": str(self), "recovery": "restart_page"}


def maximum_page_size():
    # Root Settings owns the validated configuration. The fallback supports
    # installations while that additive setting is being integrated.
    value = getattr(settings, "booking_page_max_size", 500)
    if type(value) is not int or not 25 <= value <= 5000:
        raise RuntimeError("BOOKING_PAGE_MAX_SIZE must be an integer from 25 through 5000")
    return value


def _filter_values(query):
    return BookingFilters.model_validate(query.model_dump(include=set(BookingFilters.model_fields))).model_dump(mode="json")


def scope_binding():
    """A continuation must never silently switch principal or portfolio grants."""
    scope = current_scope()
    return None if scope is None else {
        "user_id": scope.user_id, "role": scope.role, "unrestricted": scope.unrestricted,
        "portfolio_ids": scope.portfolio_ids,
    }


def _binding(query):
    value = {"filters": _filter_values(query), "page_size": query.page_size, "order": query.order,
             "scope": scope_binding()}
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def _b64(value):
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _unb64(value):
    if not re.fullmatch(r"[A-Za-z0-9_-]+", value):
        raise ValueError("Malformed base64")
    result = base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)
    if _b64(result) != value:
        raise ValueError("Noncanonical base64")
    return result


def _signature(payload):
    # Separate the cursor protocol from JWTs and all other signed payloads.
    return hmac.new(settings.jwt_secret_key.encode(), b"immo-bookings-cursor-v1\0" + payload, hashlib.sha256).digest()


def encode_cursor(query, item, *, now=None):
    issued = int(time() if now is None else now)
    payload = json.dumps({"v": 1, "binding": _binding(query), "date": item.booking_date.isoformat(),
        "id": item.id, "issued": issued, "expires": issued + CURSOR_LIFETIME_SECONDS},
        sort_keys=True, separators=(",", ":")).encode()
    return _b64(payload) + "." + _b64(_signature(payload))


def decode_cursor(query, *, now=None):
    if not query.cursor:
        return None
    try:
        payload_text, signature_text = query.cursor.split(".")
        payload, signature = _unb64(payload_text), _unb64(signature_text)
        if not hmac.compare_digest(signature, _signature(payload)):
            raise ValueError("Invalid signature")
        value = json.loads(payload)
        if not isinstance(value, dict) or set(value) != {"v", "binding", "date", "id", "issued", "expires"}:
            raise ValueError("Invalid cursor fields")
        if type(value["v"]) is not int or value["v"] != 1:
            raise ValueError("Unsupported version")
        if type(value["issued"]) is not int or type(value["expires"]) is not int:
            raise ValueError("Invalid timestamps")
        if value["expires"] - value["issued"] != CURSOR_LIFETIME_SECONDS:
            raise ValueError("Invalid lifetime")
        current = int(time() if now is None else now)
        if value["issued"] > current + 60:
            raise ValueError("Future cursor")
        if current >= value["expires"]:
            raise BookingQueryError("cursor_expired", "Die Buchungsseite ist abgelaufen. Bitte die erste Seite neu laden.")
        if not hmac.compare_digest(value["binding"], _binding(query)):
            raise BookingQueryError("cursor_filter_mismatch", "Filter, Seitengröße oder Zugriffsrechte wurden geändert. Bitte die erste Seite laden.")
        if not isinstance(value["id"], str) or not re.fullmatch(_ID, value["id"]):
            raise ValueError("Invalid position")
        if not isinstance(value["date"], str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value["date"]):
            raise ValueError("Invalid date")
        return date.fromisoformat(value["date"]), value["id"]
    except BookingQueryError:
        raise
    except (ValueError, TypeError, KeyError, UnicodeError):
        raise BookingQueryError("cursor_invalid", "Die Buchungsseite konnte nicht geprüft werden. Bitte die erste Seite neu laden.") from None


def booking_statement(filters, *, after=None, limit, include_labels=False, scope=None):
    """Fixed columns only; user filters are bound SQL parameters."""
    query = select(BookingORM.__table__)
    clause = scoped_clause(BookingORM.__table__, scope=scope)
    if clause is not None:
        query = query.where(clause)
    if include_labels:
        query = query.add_columns(AccountORM.name.label("account_name"), CategoryORM.name.label("category_name"),
            PropertyORM.name.label("property_name"), UnitORM.label.label("unit_label"), TenantORM.full_name.label("tenant_name"))
        for model, field in ((AccountORM, "account_id"), (CategoryORM, "category_id"), (PropertyORM, "property_id"),
                             (UnitORM, "unit_id"), (TenantORM, "tenant_id")):
            query = query.outerjoin(model, getattr(BookingORM, field) == model.id)
    for field in ("account_id", "property_id", "tenant_id", "status"):
        value = getattr(filters, field)
        if value is not None:
            query = query.where(getattr(BookingORM, field) == value)
    if filters.date_from:
        query = query.where(BookingORM.booking_date >= filters.date_from)
    if filters.date_to:
        query = query.where(BookingORM.booking_date <= filters.date_to)
    if filters.search:
        escaped = filters.search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        query = query.where(or_(BookingORM.payment_text.ilike(f"%{escaped}%", escape="\\"),
                               BookingORM.id.ilike(f"%{escaped}%", escape="\\")))
    if filters.view == "uncategorized":
        query = query.where(BookingORM.category_id.is_(None))
    elif filters.view == "no_receipt":
        query = query.where(or_(BookingORM.receipt_url.is_(None), BookingORM.receipt_url == ""))
    elif filters.view == "income":
        query = query.where(BookingORM.amount > 0)
    elif filters.view == "expense":
        query = query.where(BookingORM.amount < 0)
    if after:
        query = query.where(tuple_(BookingORM.booking_date, bytewise_id(BookingORM.id)) < tuple_(after[0], after[1]))
    return query.order_by(BookingORM.booking_date.desc(), bytewise_id(BookingORM.id).desc()).limit(limit)


def memory_matches(item, filters):
    if any(getattr(filters, key) is not None and getattr(item, key) != getattr(filters, key)
           for key in ("account_id", "property_id", "tenant_id", "status")):
        return False
    if filters.date_from and item.booking_date < filters.date_from or filters.date_to and item.booking_date > filters.date_to:
        return False
    if filters.search and filters.search.lower() not in (item.payment_text or "").lower() and filters.search.lower() not in item.id.lower():
        return False
    return {"all": True, "uncategorized": item.category_id is None, "no_receipt": not item.receipt_url,
            "income": item.amount > 0, "expense": item.amount < 0}[filters.view]


def booking_key(item):
    return item.booking_date, item.id


def memory_page(items, filters, *, after=None, limit):
    # O(limit) extra space; never sort or serialize the entire memory store.
    return heapq.nlargest(limit, (item for item in items if memory_matches(item, filters)
        and (after is None or booking_key(item) < after)), key=booking_key)


def get_booking_page(store, query):
    if query.page_size > maximum_page_size():
        raise BookingQueryError("page_size_exceeded", f"Bitte eine Seitengröße bis {maximum_page_size()} wählen; weitere Seiten bleiben verfügbar.")
    after = decode_cursor(query)
    if hasattr(store, "db"):
        # Reviewed draft property: reading a page must not flush unrelated
        # pending domain writes in the caller's Session.
        with store.db.no_autoflush:
            with store.db.execute(booking_statement(query, after=after, limit=query.page_size + 1, include_labels=True)) as result:
                selected = [BookingPageItem.model_validate(row) for row in result.mappings()]
    else:
        selected = memory_page(store.bookings.values(), query, after=after, limit=query.page_size + 1)
        enriched = []
        for item in selected:
            labels = {}
            for collection, field, label, attribute in (("accounts", "account_id", "account_name", "name"),
                ("categories", "category_id", "category_name", "name"), ("properties", "property_id", "property_name", "name"),
                ("units", "unit_id", "unit_label", "label"), ("tenants", "tenant_id", "tenant_name", "full_name")):
                reference = getattr(store, collection).get(getattr(item, field))
                labels[label] = getattr(reference, attribute, None)
            enriched.append(BookingPageItem.model_validate({**item.model_dump(), **labels}))
        selected = enriched
    has_more = len(selected) > query.page_size
    items = selected[:query.page_size]
    return BookingPage(items=items, has_more=has_more,
        next_cursor=encode_cursor(query, items[-1]) if has_more else None)
