"""One exact, scoped cash source for reports, provenance pages and exports."""

import csv
import hashlib
import heapq
import io
import json
from contextlib import contextmanager
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import String, and_, cast, func, select

from ..db.booking_order import bytewise_id
from ..db.orm_models import AccountORM, BookingORM, CategoryORM, PropertyORM, UnitORM
from .booking_export import _check_live_sql_rows, _snapshot, csv_cell
from .payments import _memory_lock
from .portfolio_scope import current_scope, memory_visible, refresh_scope, scoped_clause
from .tenancy_workflow import decode_cursor, encode_cursor

BATCH_SIZE = 1000  # Transfer budget, never a stock limit.
FIELDS = ("id", "account_id", "category_id", "property_id", "unit_id", "booking_date", "status", "payment_text", "receipt_url", "updated_at")


class CashFilters(BaseModel):
    model_config = ConfigDict(extra="forbid")
    date_from: date | None = None
    date_to: date | None = None
    portfolio_id: str | None = None
    property_ids: list[str] = Field(default_factory=list)
    unit_id: str | None = None
    account_id: str | None = None
    basis: Literal["confirmed_cash", "recorded_bookings"] = "confirmed_cash"
    as_of: date = Field(default_factory=date.today)

    @model_validator(mode="after")
    def coherent(self):
        if self.date_from and self.date_to and self.date_from > self.date_to:
            raise ValueError("Der Beginn muss vor dem Ende des Zeitraums liegen.")
        self.property_ids = sorted(set(self.property_ids))
        return self


class CashSourcesQuery(CashFilters):
    after: str | None = Field(default=None, max_length=8192)
    source_hash: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    limit: int = Field(default=50, ge=1, le=500)


def cents(value):
    """Exact source cents and unbounded integer accumulation, no float sum."""
    if value is None or isinstance(value, bool):
        raise ValueError("invalid_amount")
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValueError("invalid_amount") from None
    if not number.is_finite():
        raise ValueError("amount_not_finite")
    sign, digits, exponent = number.as_tuple()
    coefficient = "".join(str(digit) for digit in digits)
    shift = int(exponent) + 2
    if shift < 0:
        if -shift > len(coefficient) - len(coefficient.rstrip("0")):
            raise ValueError("amount_fractional_cent")
        coefficient, shift = coefficient[:shift], 0
    result = int(coefficient or "0") * 10**shift
    return -result if sign else result


def money(value):
    absolute = abs(value)
    return ("-" if value < 0 else "") + str(absolute // 100) + "." + str(absolute % 100).zfill(2)


def _validate_context(store, filters):
    portfolio = filters.portfolio_id
    if portfolio:
        store.get_portfolio(portfolio)
    for identifier in filters.property_ids:
        prop = store.get_property(identifier)
        if portfolio and prop.portfolio_id != portfolio:
            raise HTTPException(422, "Die Immobilienauswahl gehört nicht zum gewählten Portfolio.")
    if filters.unit_id:
        unit = store.get_unit(filters.unit_id)
        prop = store.get_property(unit.property_id)
        if ((filters.property_ids and prop.id not in filters.property_ids)
                or (portfolio and prop.portfolio_id != portfolio)):
            raise HTTPException(422, "Die Einheit gehört nicht zur gewählten Immobilienauswahl.")
    if filters.account_id:
        account = store.get_account(filters.account_id)
        if portfolio and account.portfolio_id != portfolio:
            raise HTTPException(422, "Das Konto gehört nicht zum gewählten Portfolio.")


def _query(filters, scope):
    book, account, category, prop, unit = (value.__table__ for value in (BookingORM, AccountORM, CategoryORM, PropertyORM, UnitORM))
    query = select(*(book.c[field] for field in FIELDS), cast(book.c.amount, String).label("amount"),
        account.c.portfolio_id.label("portfolio_id"), account.c.name.label("account_name"),
        category.c.name.label("category_name"), category.c.category_type.label("category_type"),
        category.c.portfolio_id.label("category_portfolio_id"), prop.c.name.label("property_name"),
        prop.c.portfolio_id.label("property_portfolio_id"), unit.c.label.label("unit_label"),
        unit.c.property_id.label("unit_property_id"),
        func.coalesce(book.c.property_id, unit.c.property_id).label("effective_property_id"))
    query = query.select_from(book.join(account, book.c.account_id == account.c.id)
        .outerjoin(category, book.c.category_id == category.c.id)
        .outerjoin(unit, book.c.unit_id == unit.c.id)
        .outerjoin(prop, prop.c.id == func.coalesce(book.c.property_id, unit.c.property_id)))
    predicate = scoped_clause(account, scope=scope)
    if predicate is not None:
        query = query.where(predicate)
    if filters.portfolio_id:
        query = query.where(account.c.portfolio_id == filters.portfolio_id)
    if filters.property_ids:
        query = query.where(func.coalesce(book.c.property_id, unit.c.property_id).in_(filters.property_ids))
    for field in ("unit_id", "account_id"):
        if (value := getattr(filters, field)) is not None:
            query = query.where(book.c[field] == value)
    if filters.date_from:
        query = query.where(book.c.booking_date >= filters.date_from)
    if filters.date_to:
        query = query.where(book.c.booking_date <= filters.date_to)
    return query


def _safe_row(row):
    result = dict(row)
    if (result["category_id"] and result["category_portfolio_id"] != result["portfolio_id"]
            or result["effective_property_id"] and result["property_portfolio_id"] != result["portfolio_id"]
            or result["unit_id"] and (not result["unit_property_id"] or result["property_id"]
                and result["property_id"] != result["unit_property_id"])):
        raise HTTPException(409, "Ein Buchungsbezug ist widersprüchlich. Konto, Kategorie und Objektzuordnung prüfen.")
    try:
        amount = cents(result["amount"])
    except ValueError as error:
        raise HTTPException(409, f"Buchung {result['id']}: Betrag prüfen ({error}).") from None
    result["amount"] = money(amount)
    result["amount_cents"] = str(amount)
    as_of, basis = result.pop("as_of"), result.pop("basis")
    result["included"] = (result["booking_date"] <= as_of
        and result["status"] not in {"cancelled", "void"}
        and (basis == "recorded_bookings" or result["status"] == "confirmed"))
    result["exclusion_reason"] = ("after_cutoff" if result["booking_date"] > as_of else
        "cancelled" if result["status"] in {"cancelled", "void"} else
        "unconfirmed" if not result["included"] else None)
    for field in ("booking_date", "updated_at"):
        if result[field] is not None:
            result[field] = result[field].isoformat()
    return result


@contextmanager
def sources(store, filters):
    captured = current_scope()
    refresh_scope(captured)
    _validate_context(store, filters)
    if hasattr(store, "db"):
        engine = store.db.get_bind()
        with _snapshot(engine) as connection:
            base = _query(filters, captured)
            predicate = scoped_clause(BookingORM, scope=captured)
            if predicate is not None and connection.execute(base.where(~predicate).limit(1)).first():
                raise HTTPException(403, "Buchungsbezüge sind nicht vollständig freigegeben. Objektzuordnung prüfen lassen.")

            def iterator():
                after = None
                while True:
                    query = base
                    if after:
                        day, identifier = after
                        query = query.where((BookingORM.booking_date > day) | and_(BookingORM.booking_date == day, bytewise_id(BookingORM.id) > identifier))
                    rows = connection.execute(query.order_by(BookingORM.booking_date, bytewise_id(BookingORM.id)).limit(BATCH_SIZE)).mappings().all()
                    refresh_scope(captured)
                    _check_live_sql_rows(engine, rows, captured)
                    if not rows:
                        return
                    for row in rows:
                        yield _safe_row(dict(row) | {"as_of": filters.as_of, "basis": filters.basis})
                    after = rows[-1]["booking_date"], rows[-1]["id"]
            yield iterator()
            # Recheck already read identities before publishing aggregates.
            for _ in iterator():
                pass
    else:
        with _memory_lock:
            raw = object.__getattribute__(store, "__dict__")

            def selected(booking):
                account = raw["accounts"].get(booking.account_id)
                unit = raw["units"].get(booking.unit_id)
                prop_id = booking.property_id or (unit.property_id if unit else None)
                return (account is not None and memory_visible(store, "accounts", account)
                    and (not filters.portfolio_id or account.portfolio_id == filters.portfolio_id)
                    and (not filters.property_ids or prop_id in filters.property_ids)
                    and (not filters.unit_id or booking.unit_id == filters.unit_id)
                    and (not filters.account_id or booking.account_id == filters.account_id)
                    and (not filters.date_from or booking.booking_date >= filters.date_from)
                    and (not filters.date_to or booking.booking_date <= filters.date_to))

            def iterator():
                after = None
                while True:
                    batch = heapq.nsmallest(BATCH_SIZE, (row for row in raw["bookings"].values() if selected(row)
                        and (after is None or (row.booking_date, row.id.encode()) > after)), key=lambda row: (row.booking_date, row.id.encode()))
                    refresh_scope(captured)
                    if not batch:
                        return
                    for booking in batch:
                        if not memory_visible(store, "bookings", booking):
                            raise HTTPException(403, "Buchungsbezüge sind nicht vollständig freigegeben. Objektzuordnung prüfen lassen.")
                        account = raw["accounts"][booking.account_id]
                        category = raw["categories"].get(booking.category_id)
                        unit = raw["units"].get(booking.unit_id)
                        prop_id = booking.property_id or (unit.property_id if unit else None)
                        prop = raw["properties"].get(prop_id)
                        row = {field: getattr(booking, field) for field in FIELDS} | {"amount": booking.amount,
                            "portfolio_id": account.portfolio_id, "account_name": account.name,
                            "category_name": category.name if category else None, "category_type": category.category_type if category else None,
                            "category_portfolio_id": category.portfolio_id if category else None,
                            "effective_property_id": prop_id, "property_name": prop.name if prop else None,
                            "property_portfolio_id": prop.portfolio_id if prop else None,
                            "unit_label": unit.label if unit else None, "unit_property_id": unit.property_id if unit else None,
                            "as_of": filters.as_of, "basis": filters.basis}
                        yield _safe_row(row)
                    after = batch[-1].booking_date, batch[-1].id.encode()
            yield iterator()
    refresh_scope(captured)


def _canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":"), default=str).encode()


def report(store, filters: CashFilters, *, after=None, limit=50, source_hash=None, details=False):
    if type(limit) is not int or not 1 <= limit <= 500:
        raise HTTPException(422, "Bitte eine Seitengröße zwischen1 und500 wählen.")
    if after and not source_hash:
        raise HTTPException(422, "Bitte den Quellenstand der Auswertung mitgeben.")
    scope = current_scope()
    scope_key = None if scope is None else {"user_id": scope.user_id, "role": scope.role,
        "unrestricted": scope.unrestricted, "portfolio_ids": list(scope.portfolio_ids)}
    binding = {"kind": "financial-cash-v1", "filters": filters.model_dump(mode="json"), "scope": scope_key,
               "limit": limit, "source_hash": source_hash}
    point = decode_cursor(after, binding)
    if point is not None and (len(point) != 2 or not all(isinstance(value, str) for value in point)):
        raise HTTPException(422, "Ungültige Belegseite. Auswertung erneut laden.")
    digest = hashlib.sha256(_canonical(["financial-cash-v1", filters.model_dump(mode="json")]))
    income, expense, count, excluded = 0, 0, 0, 0
    categories: dict[Any, dict[str, Any]] = {}
    months: dict[str, dict[str, Any]] = {}
    locations: dict[Any, dict[str, Any]] = {}
    selected: list[dict[str, Any]] = []

    def add(groups, key, labels, amount):
        bucket = groups.setdefault(key, dict(labels) | {"income": 0, "expense": 0, "count": 0})
        bucket["income"] += max(amount, 0)
        bucket["expense"] += max(-amount, 0)
        bucket["count"] += 1

    with sources(store, filters) as rows:
        for row in rows:
            digest.update(_canonical(row) + b"\n")
            amount = int(row["amount_cents"])
            if row["included"]:
                income += max(amount, 0)
                expense += max(-amount, 0)
                count += 1
                add(categories, row["category_id"], {"category_id": row["category_id"], "name": row["category_name"], "category_type": row["category_type"]}, amount)
                add(months, row["booking_date"][:7], {"month": row["booking_date"][:7]}, amount)
                add(locations, (row["effective_property_id"], row["unit_id"]), {"property_id": row["effective_property_id"], "property_name": row["property_name"], "unit_id": row["unit_id"], "unit_label": row["unit_label"]}, amount)
            else:
                excluded += 1
            if details and (point is None or [row["booking_date"], row["id"]] > point) and len(selected) <= limit:
                selected.append(row)
        actual_hash = digest.hexdigest()
        if source_hash and source_hash != actual_hash:
            raise HTTPException(409, "Die Buchungsquellen haben sich geändert. Auswertung erneut laden.")
    refresh_scope(scope)

    def format_bucket(bucket):
        incoming, outgoing = bucket["income"], bucket["expense"]
        return {key: value for key, value in bucket.items() if key not in {"income", "expense"}} | {
            "income": money(incoming), "expense": money(outgoing), "net": money(incoming - outgoing)}
    more = len(selected) > limit
    return {"basis": filters.basis, "currency": "EUR", "filters": filters.model_dump(mode="json"),
        "source_hash": actual_hash, "income": money(income), "expense": money(expense), "net": money(income - expense),
        "source_count": count, "excluded_count": excluded,
        "categories": [format_bucket(value) for _, value in sorted(categories.items(), key=lambda item: str(item[0]))],
        "months": [format_bucket(value) for _, value in sorted(months.items())],
        "locations": [format_bucket(value) for _, value in sorted(locations.items(), key=lambda item: str(item[0]))],
        "items": selected[:limit], "has_more": more,
        "next_after": encode_cursor(binding | {"source_hash": actual_hash}, [selected[limit - 1]["booking_date"], selected[limit - 1]["id"]]) if more else None}


CSV_FIELDS = ("id", "booking_date", "portfolio_id", "account_id", "account_name", "effective_property_id", "property_name",
              "unit_id", "unit_label", "category_id", "category_name", "amount", "currency", "status", "included", "exclusion_reason", "payment_text", "receipt_url")


def csv_chunks(store, filters):
    """Full-source export with a single consistent snapshot and bounded buffers."""
    with sources(store, filters) as rows:
        buffer = io.StringIO(newline="")
        writer = csv.writer(buffer, delimiter=";", lineterminator="\r\n")
        writer.writerow(CSV_FIELDS)
        header = b"\xef\xbb\xbf" + buffer.getvalue().encode("utf-8")
        buffer.seek(0)
        buffer.truncate()
        buffered = 0
        # First batch validation happens before publishing even the header.
        for row in rows:
            writer.writerow([row["amount"] if field == "amount" else csv_cell((row | {"currency": "EUR"}).get(field)) for field in CSV_FIELDS])
            buffered += 1
            if buffered == BATCH_SIZE:
                yield header
                header = b""
                yield buffer.getvalue().encode("utf-8")
                buffer.seek(0)
                buffer.truncate()
                buffered = 0
        yield header + buffer.getvalue().encode("utf-8")
