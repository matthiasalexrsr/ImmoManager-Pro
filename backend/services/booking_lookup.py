"""Bounded searchable reference choices for the booking page/editor."""
import hashlib
import hmac
import json
import re
from time import time
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select

from ..db.booking_order import bytewise_id
from ..db.orm_models import AccountORM, CategoryORM, PropertyORM, TenantORM, UnitORM
from .booking_query import (
    _ID,
    CURSOR_LIFETIME_SECONDS,
    BookingFilters,
    BookingQueryError,
    _b64,
    _signature,
    _unb64,
    maximum_page_size,
)

LookupKind = Literal["accounts", "categories", "properties", "units", "tenants"]
REFERENCES: dict[str, tuple[Any, str]] = {"accounts": (AccountORM, "name"), "categories": (CategoryORM, "name"),
              "properties": (PropertyORM, "name"), "units": (UnitORM, "label"), "tenants": (TenantORM, "full_name")}


class BookingLookupQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    search: str | None = Field(default=None, max_length=200)
    selected_id: str | None = Field(default=None, pattern=_ID, max_length=100)
    page_size: int = Field(default=25, ge=1, le=5000)
    cursor: str | None = Field(default=None, min_length=1, max_length=4096)

    @field_validator("search")
    @classmethod
    def safe_search(cls, value):
        return BookingFilters(search=value).search


class BookingChoice(BaseModel):
    id: str
    label: str


class BookingChoices(BaseModel):
    items: list[BookingChoice]
    selected: BookingChoice | None
    next_cursor: str | None
    has_more: bool


def _binding(kind, query):
    values = {"kind": kind, "search": query.search, "page_size": query.page_size}
    return hashlib.sha256(json.dumps(values, sort_keys=True).encode()).hexdigest()


def _after(kind, query):
    if not query.cursor:
        return None
    try:
        body, mac = query.cursor.split(".")
        payload = _unb64(body)
        if not hmac.compare_digest(_unb64(mac), _signature(payload)):
            raise ValueError("Invalid signature")
        value = json.loads(payload)
        if set(value) != {"v", "binding", "id", "expires"} or value["v"] != "bookings-lookup-v1":
            raise ValueError("Invalid lookup cursor")
        if type(value["expires"]) is not int or time() >= value["expires"]:
            raise BookingQueryError("cursor_expired", "Die Auswahl ist abgelaufen. Bitte erneut suchen.")
        if value["binding"] != _binding(kind, query):
            raise BookingQueryError("cursor_filter_mismatch", "Die Auswahlfilter haben sich geändert. Bitte erneut suchen.")
        if not isinstance(value["id"], str) or not re.fullmatch(_ID, value["id"]):
            raise ValueError("Invalid position")
        return value["id"]
    except BookingQueryError:
        raise
    except (TypeError, ValueError, KeyError):
        raise BookingQueryError("cursor_invalid", "Die Auswahl konnte nicht geprüft werden. Bitte erneut suchen.") from None


def _cursor(kind, query, choice):
    payload = json.dumps({"v": "bookings-lookup-v1", "binding": _binding(kind, query), "id": choice.id,
        "expires": int(time()) + CURSOR_LIFETIME_SECONDS}, sort_keys=True, separators=(",", ":")).encode()
    return _b64(payload) + "." + _b64(_signature(payload))


def booking_choices(store, kind, query):
    if query.page_size > maximum_page_size():
        raise BookingQueryError("page_size_exceeded", "Bitte eine kleinere Auswahlseite verwenden; weitere Seiten bleiben verfügbar.")
    after = _after(kind, query)
    model, label = REFERENCES[kind]
    selected = None
    if hasattr(store, "db"):
        statement = select(model.id, getattr(model, label).label("label"))
        if query.search:
            escaped = query.search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            statement = statement.where(getattr(model, label).ilike(f"%{escaped}%", escape="\\"))
        if after:
            statement = statement.where(bytewise_id(model.id) < after)
        with store.db.no_autoflush:
            values = store.db.execute(statement.order_by(bytewise_id(model.id).desc()).limit(query.page_size + 1)).mappings()
            rows = [BookingChoice.model_validate(value) for value in values]
            if query.selected_id:
                choice = store.db.execute(select(model.id, getattr(model, label).label("label")).where(model.id == query.selected_id)).mappings().first()
                selected = BookingChoice.model_validate(choice) if choice else None
    else:
        import heapq
        items = getattr(store, kind).values()
        candidates = (item for item in items if (after is None or item.id < after)
            and (not query.search or query.search.lower() in getattr(item, label).lower()))
        rows = [BookingChoice(id=item.id, label=getattr(item, label)) for item in heapq.nlargest(query.page_size + 1, candidates, key=lambda item: item.id)]
        item = getattr(store, kind).get(query.selected_id)
        selected = BookingChoice(id=item.id, label=getattr(item, label)) if item else None
    has_more = len(rows) > query.page_size
    rows = rows[:query.page_size]
    return BookingChoices(items=rows, selected=selected, has_more=has_more,
        next_cursor=_cursor(kind, query, rows[-1]) if has_more else None)
