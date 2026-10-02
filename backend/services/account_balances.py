"""Exact stored cash evidence; no bank reconciliation or financial mutations."""

import hashlib
import heapq
import hmac
import json
from contextlib import contextmanager
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from time import time

from fastapi import HTTPException
from sqlalchemy import String, and_, cast, select

from ..config import settings
from ..db.booking_order import bytewise_id
from ..db.orm_models import AccountORM, BookingORM
from .booking_export import _snapshot
from .booking_query import _b64, _unb64
from .payments import _memory_lock
from .portfolio_scope import current_scope, memory_visible, refresh_scope, scoped_clause

BATCH_SIZE = 1000
SAMPLE_SIZE = 20
STATUSES = ("open", "matched", "booked", "confirmed", "other")
FIELDS = ("id", "account_id", "booking_date", "status", "payment_text", "updated_at")


class BalanceError(ValueError):
    def __init__(self, code, message, status=409):
        super().__init__(message)
        self.code, self.status = code, status


def cents(value):
    """Assemble cents without Decimal multiplication/context rounding."""
    if value is None or isinstance(value, bool):
        raise ValueError("amount_invalid")
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValueError("amount_invalid") from None
    if not number.is_finite():
        raise ValueError("amount_not_finite")
    if not number:
        return 0
    sign, digits, exponent = number.as_tuple()
    coefficient = "".join(str(digit) for digit in digits)
    shift = int(exponent) + 2
    if shift < 0:
        if -shift > len(coefficient) - len(coefficient.rstrip("0")):
            raise ValueError("amount_fractional_cent")
        coefficient, shift = coefficient[:shift], 0
    if len(coefficient) + shift > 12:
        raise ValueError("amount_capacity")
    result = int(coefficient or "0") * 10**shift
    return -result if sign else result


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str).encode()


def _account_query(identifier, scope):
    table = AccountORM.__table__
    query = select(table.c.id, table.c.name, table.c.portfolio_id, table.c.updated_at,
        cast(table.c.opening_balance, String).label("opening_balance"), cast(table.c.balance, String).label("comparison_balance"))
    predicate = scoped_clause(table, scope=scope)
    return query.where(table.c.id == identifier, predicate) if predicate is not None else query.where(table.c.id == identifier)


def _live(engine, account, rows, scope):
    refresh_scope(scope)
    with engine.connect() as connection:
        current = connection.execute(_account_query(account["id"], scope)).mappings().first()
        if current is None or current["portfolio_id"] != account["portfolio_id"]:
            raise HTTPException(403, "Kontozugriff oder Portfoliozuordnung wurde geändert. Bitte erneut laden.")
        if rows:
            table = BookingORM.__table__
            query = select(table.c.id).where(table.c.account_id == account["id"], table.c.id.in_([row["id"] for row in rows]))
            predicate = scoped_clause(table, scope=scope)
            if predicate is not None:
                query = query.where(predicate)
            if set(connection.execute(query).scalars()) != {row["id"] for row in rows}:
                raise HTTPException(403, "Buchungsquellen wurden geändert oder sind nicht vollständig freigegeben. Bitte erneut laden.")


@contextmanager
def _sources(store, identifier, as_of, scope):
    refresh_scope(scope)
    if hasattr(store, "db"):
        engine = store.db.get_bind()
        with _snapshot(engine) as connection:
            account = connection.execute(_account_query(identifier, scope)).mappings().first()
            if account is None:
                raise HTTPException(404, "Konto nicht gefunden.")
            table = BookingORM.__table__
            base = select(*(table.c[field] for field in FIELDS), cast(table.c.amount, String).label("amount")).where(table.c.account_id == identifier)
            if as_of:
                base = base.where(table.c.booking_date <= as_of)
            predicate = scoped_clause(table, scope=scope)
            if predicate is not None:
                hidden = select(1).where(table.c.account_id == identifier, ~predicate)
                if as_of:
                    hidden = hidden.where(table.c.booking_date <= as_of)
                if connection.scalar(hidden.limit(1)):
                    raise HTTPException(403, "Kontobuchungen sind nicht vollständig freigegeben. Objektbezüge durch die Verwaltung prüfen lassen.")

            def iterator():
                after = None
                while True:
                    query = base
                    if after:
                        day, key = after
                        query = query.where((table.c.booking_date > day) | and_(table.c.booking_date == day, bytewise_id(table.c.id) > key))
                    rows = connection.execute(query.order_by(table.c.booking_date, bytewise_id(table.c.id)).limit(BATCH_SIZE)).mappings().all()
                    _live(engine, account, rows, scope)
                    if not rows:
                        return
                    yield from rows
                    after = rows[-1]["booking_date"], rows[-1]["id"]
            yield dict(account), iterator()
            # Revisit snapshot identities in bounded batches before publishing
            # a complete projection. A previously read row may since have been
            # moved to another account/portfolio while later batches were read.
            for _ in iterator():
                pass
            _live(engine, account, [], scope)
    else:
        with _memory_lock:
            raw = object.__getattribute__(store, "__dict__")
            account = raw["accounts"].get(identifier)
            if account is None or not memory_visible(store, "accounts", account, scope=scope):
                raise HTTPException(404, "Konto nicht gefunden.")
            account_values = {"id": account.id, "name": account.name, "portfolio_id": account.portfolio_id,
                "updated_at": account.updated_at, "opening_balance": account.opening_balance, "comparison_balance": account.balance}

            def iterator():
                after = None
                while True:
                    refresh_scope(scope)
                    values = (item for item in raw["bookings"].values() if item.account_id == identifier
                        and (as_of is None or item.booking_date <= as_of)
                        and (after is None or (item.booking_date, item.id.encode()) > after))
                    batch = heapq.nsmallest(BATCH_SIZE, values, key=lambda item: (item.booking_date, item.id.encode()))
                    if not batch:
                        return
                    for item in batch:
                        if not memory_visible(store, "bookings", item, scope=scope):
                            raise HTTPException(403, "Kontobuchungen sind nicht vollständig freigegeben. Objektbezüge durch die Verwaltung prüfen lassen.")
                        yield {field: getattr(item, field) for field in FIELDS} | {"amount": item.amount}
                    after = batch[-1].booking_date, batch[-1].id.encode()
            yield account_values, iterator()
            refresh_scope(scope)


def _binding(identifier, as_of, kind, scope):
    return hashlib.sha256(_canonical([identifier, as_of, kind, scope])).hexdigest()


def _cursor(binding, source_hash, after):
    body = _canonical({"v": 1, "binding": binding, "source_hash": source_hash, "after": after, "expires": int(time()) + 3600})
    signature = hmac.new(settings.jwt_secret_key.encode(), b"account-balance-sources-v1\0" + body, hashlib.sha256).digest()
    return _b64(body) + "." + _b64(signature)


def _position(cursor, binding):
    if not cursor:
        return 0, None
    try:
        raw, signature = cursor.split(".")
        body = _unb64(raw)
        expected = hmac.new(settings.jwt_secret_key.encode(), b"account-balance-sources-v1\0" + body, hashlib.sha256).digest()
        value = json.loads(body)
        if not hmac.compare_digest(expected, _unb64(signature)) or set(value) != {"v", "binding", "source_hash", "after", "expires"}:
            raise ValueError()
        if value["v"] != 1 or value["binding"] != binding or type(value["after"]) is not int or value["after"] < 0 or type(value["expires"]) is not int or value["expires"] <= time():
            raise ValueError()
        return value["after"], value["source_hash"]
    except (ValueError, TypeError, KeyError, UnicodeError):
        raise BalanceError("balance_cursor_invalid", "Quellenseite ist ungültig oder abgelaufen. Kontosaldo erneut laden.", 400) from None


def _issue(kind, identifier, field, value, code):
    return {"source_type": kind, "source_id": identifier, "field": field, "code": code,
        "value_preview": str(value)[:64], "repair": "edit_account" if kind == "account" else "edit_booking"}


def account_balance(store, identifier, *, as_of: date | None = None, kind="summary", cursor=None, source_hash=None, page_size=25, scope=None):
    if kind not in {"summary", "issues", "bookings"} or type(page_size) is not int or not 1 <= page_size <= 500:
        raise BalanceError("balance_page_invalid", "Gültige Quellenseite und Seitengröße wählen.", 400)
    scope = current_scope() if scope is None else scope
    binding = _binding(identifier, as_of, kind, scope)
    after, cursor_hash = _position(cursor, binding)
    expected_hash = cursor_hash or source_hash
    started = datetime.now(timezone.utc).isoformat()
    with _sources(store, identifier, as_of, scope) as (account, rows):
        digest = hashlib.sha256(_canonical(["stored-account-cash-v1", as_of, account]))
        issues: list[dict] = []
        selected: list[dict] = []
        issue_count, booking_count, invalid_bookings, total, income, expense = 0, 0, 0, 0, 0, 0
        first_date = last_date = None
        status_totals = {key: {"booking_count": 0, "sum": 0, "invalid_count": 0} for key in STATUSES}

        def record_issue(issue):
            nonlocal issue_count
            if len(issues) < SAMPLE_SIZE:
                issues.append(issue)
            issue_count += 1
            if kind == "issues" and issue_count > after and len(selected) <= page_size:
                selected.append(issue)

        values = {}
        for field in ("opening_balance", "comparison_balance"):
            try:
                values[field] = cents(account[field])
            except ValueError as error:
                values[field] = None
                record_issue(_issue("account", identifier, field, account[field], str(error)))
        for row in rows:
            digest.update(_canonical(dict(row)) + b"\n")
            booking_count += 1
            first_date = first_date or row["booking_date"].isoformat()
            last_date = row["booking_date"].isoformat()
            status = row["status"] if row["status"] in STATUSES[:-1] else "other"
            bucket = status_totals[status]
            bucket["booking_count"] += 1
            amount = None
            try:
                amount = cents(row["amount"])
                total += amount
                income += max(amount, 0)
                expense += min(amount, 0)
                bucket["sum"] += amount
            except ValueError as error:
                invalid_bookings += 1
                bucket["invalid_count"] += 1
                record_issue(_issue("booking", row["id"], "amount", row["amount"], str(error)))
            if kind == "bookings" and booking_count > after and len(selected) <= page_size:
                selected.append({"id": row["id"], "booking_date": row["booking_date"].isoformat(), "amount_cents": str(amount) if amount is not None else None,
                    "status": str(row["status"])[:100], "payment_text": row["payment_text"], "updated_at": str(row["updated_at"]), "valid_amount": amount is not None})
        actual_hash = digest.hexdigest()
        if expected_hash and not hmac.compare_digest(expected_hash, actual_hash):
            raise BalanceError("balance_source_changed", "Gespeicherte Quellen wurden geändert. Kontosaldo erneut laden.")
        refresh_scope(scope)
        if kind != "summary":
            count = issue_count if kind == "issues" else booking_count
            more = len(selected) > page_size
            return {"account_id": identifier, "source_hash": actual_hash, "kind": kind, "items": selected[:page_size],
                "has_more": more, "next_cursor": _cursor(binding, actual_hash, after + page_size) if more else None, "source_count": count}
        opening, comparison = values["opening_balance"], values["comparison_balance"]
        calculated = opening + total if opening is not None and not invalid_bookings else None
        return {"account_id": identifier, "account_name": account["name"], "portfolio_id": account["portfolio_id"],
            "account_updated_at": account["updated_at"].isoformat() if account["updated_at"] else None,
            "as_of": as_of.isoformat() if as_of else None, "snapshot_started_at": started, "source_hash": actual_hash,
            "source_kind": "stored_account_and_cash_bookings", "opening_is_undated": True, "comparison_is_undated": True,
            "opening_balance_cents": str(opening) if opening is not None else None,
            "comparison_balance_cents": str(comparison) if comparison is not None else None,
            "bookings_sum_cents": str(total) if not invalid_bookings else None,
            "income_sum_cents": str(income) if not invalid_bookings else None,
            "expense_sum_cents": str(expense) if not invalid_bookings else None,
            "calculated_balance_cents": str(calculated) if calculated is not None else None,
            "difference_cents": str(calculated - comparison) if calculated is not None and comparison is not None else None,
            "is_computable": calculated is not None, "booking_count": booking_count, "first_booking_date": first_date, "last_booking_date": last_date,
            "status_totals": {key: {"booking_count": bucket["booking_count"], "amount_cents": str(bucket["sum"]) if not bucket["invalid_count"] else None,
                "invalid_count": bucket["invalid_count"]} for key, bucket in status_totals.items()},
            "issues_count": issue_count, "issues_sample": issues,
            "issues_next_cursor": _cursor(_binding(identifier, as_of, "issues", scope), actual_hash, SAMPLE_SIZE) if issue_count > SAMPLE_SIZE else None}
