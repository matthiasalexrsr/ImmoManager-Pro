"""Bounded booking pages and complete filtered totals/exports.

Ordinary pages stay in SQL. Owner splits and the small number of filters which
need canonical Python rules are materialized as IDs/cent amounts in batches;
following pages reuse that result while the scope and tracked inputs are current.
No complete booking collection crosses the browser boundary.
"""
from __future__ import annotations

import csv
import io
import json
import re
import tempfile
import threading
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any
from urllib.parse import unquote, urlsplit

from fastapi import HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import String, and_, case, cast, func, literal, or_, select

from .. import concurrency
from ..db.orm_models import (
    AccountORM,
    BookingORM,
    CategoryORM,
    ContractORM,
    PaymentAllocationORM,
    PropertyORM,
    TenantORM,
    UnitORM,
)
from ..domain.money import ZERO, as_number, money
from ..models import Booking
from .csv_export import spreadsheet_cell
from .finance_ledger import Dimensions, FinanceFilter, _cents, _sql_conditions, booking_side, validate_filter
from .ownership import NOBODY, Ownership, owner_key, require_owner
from .payment_allocations import non_rent_shares
from .portfolio_scope import BOUNDED, current_scope, scoped_clause
from .report_provenance import snapshot

BATCH = 500
_LOCK = threading.RLock()
_CACHE: dict[tuple, tuple[tuple, float, Any]] = {}
SORT_KEYS = frozenset({"booking_date", "amount", "owner_part", "payment_text", "status", "account_name", "category_name",
                       "property_name", "unit_label", "tenant_name", "created_at"})
FLOWS = frozenset({"all", "open", "unassigned", "no_category", "no_receipt", "income", "expense", "withdrawal", "contribution"})
COLUMN_FILTERS = frozenset({"booking_date", "amount", "owner_part", "payment_text", "status", "account_name", "category_name",
                            "property_name", "unit_label", "tenant_name", "allocation_label", "has_receipt"})
_BANK = re.compile(r"^/api/v1/bank-imports/[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}/original$")


def has_receipt(value) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    raw = value.strip()
    if _BANK.fullmatch(raw):
        return True
    if raw.startswith("//") or any(ord(c) < 32 or c == "\\" for c in raw):
        return False
    try:
        if any(part in {".", ".."} for part in unquote(re.split(r"[?#]", raw, 1)[0]).split("/")):
            return False
        parsed = urlsplit(raw)
        if parsed.scheme:
            return parsed.scheme.lower() in {"http", "https"} and bool(parsed.hostname) and not parsed.username and not parsed.password
        return raw.startswith(("/uploads/", "uploads/"))
    except (ValueError, UnicodeError):
        return False


def _versions():
    # Use the same global revision as report responses. Besides direct financial
    # edits this includes grant revocations and cascades caused by parent deletes;
    # a table-only whitelist would miss those authorization/ownership changes.
    with concurrency._cache_lock:
        return (concurrency._version,)


def _cached(store, kind, options, calculate):
    # Use the existing cache's read-transaction/pending-write fence. Connection-
    # bound and repeatable snapshots are never shared with another transaction.
    reads = concurrency._Reads([store])
    if not reads.shared():
        return calculate(store)
    key = (kind, reads.identity, current_scope(), json.dumps(options, sort_keys=True, default=str))
    with _LOCK:
        stamp, now = _versions(), time.monotonic()
        for old in list(_CACHE):
            if now - _CACHE[old][1] >= concurrency.KEEP_SECONDS:
                del _CACHE[old]
        kept = _CACHE.get(key)
        if kept and kept[0] == stamp:
            return kept[2]
        with snapshot(store) as (source, _):
            result = calculate(source)
        if stamp == _versions() and reads.shared():
            if len(_CACHE) >= 16:
                del _CACHE[next(iter(_CACHE))]
            _CACHE[key] = (stamp, time.monotonic(), result)
        return result


def _finance(options):
    return FinanceFilter(**{key: options.get(key) for key in ("date_from", "date_to", "portfolio_id", "property_id", "unit_id")})


def validate(store, options):
    validate_filter(store, _finance(options), require_visible=True)
    if options.get("owner_contact_id") != NOBODY:
        require_owner(store, options.get("owner_contact_id"))
    if options.get("flow", "all") not in FLOWS:
        raise HTTPException(422, "Unbekannte Buchungsauswahl.")
    if options.get("sort_by", "booking_date") not in SORT_KEYS:
        raise HTTPException(422, "Diese Buchungsspalte kann nicht sortiert werden.")
    if options.get("sort_order", "desc") not in {"asc", "desc"}:
        raise HTTPException(422, "Unbekannte Sortierreihenfolge.")
    for key, value in options.get("column_filters", {}).items():
        if key not in COLUMN_FILTERS:
            raise HTTPException(422, "Diese Spalte kann nicht gefiltert werden.")
        if key in {"booking_date", "amount", "owner_part"}:
            if not isinstance(value, list) or len(value) != 2 or any(not isinstance(part, str) for part in value):
                raise HTTPException(422, "Der Spaltenfilter benötigt einen gültigen Bereich.")
            try:
                if key == "booking_date":
                    dates = [date.fromisoformat(part) for part in value if part]
                    if len(dates) == 2 and dates[0] > dates[1]:
                        raise ValueError
                else:
                    numbers = [Decimal(part) for part in value if part]
                    if any(not part.is_finite() for part in numbers) or len(numbers) == 2 and numbers[0] > numbers[1]:
                        raise ValueError
            except (ValueError, ArithmeticError):
                raise HTTPException(422, "Der Spaltenfilter enthält einen ungültigen Bereich.") from None
            if key == "owner_part" and not options.get("owner_contact_id"):
                raise HTTPException(422, "Für einen Eigentümeranteil bitte zuerst einen Eigentümer wählen.")
        elif not isinstance(value, str) or len(value) > 500:
            raise HTTPException(422, "Der Spaltenfilter enthält keinen gültigen Suchtext.")


def _label(column, parent, target):
    query = select(column).where(parent.c.id == target)
    boundary = scoped_clause(parent)
    if boundary is not None:
        query = query.where(boundary)
    return query.correlate(BookingORM.__table__).scalar_subquery()


def _labels():
    b = BookingORM.__table__.c
    return {"account_name": _label(AccountORM.__table__.c.name, AccountORM.__table__, b.account_id),
            "category_name": _label(CategoryORM.__table__.c.name, CategoryORM.__table__, b.category_id),
            "property_name": _label(PropertyORM.__table__.c.name, PropertyORM.__table__, b.property_id),
            "unit_label": _label(UnitORM.__table__.c.label, UnitORM.__table__, b.unit_id),
            "tenant_name": _label(TenantORM.__table__.c.full_name, TenantORM.__table__, b.tenant_id)}


def _side():
    b = BookingORM.__table__.c
    category = _label(CategoryORM.__table__.c.category_type, CategoryORM.__table__, b.category_id)
    incoming = or_(and_(b.reverses_booking_id.is_(None), b.amount > 0), and_(b.reverses_booking_id.is_not(None), b.amount < 0))
    return case((category.in_(["income", "expense"]), category),
                (category == "private", case((incoming, literal("contribution")), else_=literal("withdrawal"))),
                (b.tenant_id.is_not(None), literal("income")), (incoming, literal("income")), else_=literal("expense"))


def _conditions(options, *, flow=False):
    b = BookingORM.__table__.c
    conditions = _sql_conditions(_finance(options))
    boundary = scoped_clause(BookingORM)
    if boundary is not None:
        conditions.append(boundary)
    for key in ("account_id", "tenant_id", "category_id", "status"):
        if options.get(key):
            conditions.append(b[key] == options[key])
    search = options.get("search", "").strip().lower()
    if search:
        needle = search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        columns = [b.payment_text, b.status, cast(b.booking_date, String), cast(b.amount, String), *_labels().values()]
        matches: list[Any] = [func.lower(func.coalesce(column, "")).like(f"%{needle}%", escape="\\") for column in columns]
        allocated_contracts = select(PaymentAllocationORM.booking_id).join(ContractORM, ContractORM.id == PaymentAllocationORM.contract_id)
        for model in (PaymentAllocationORM, ContractORM):
            boundary = scoped_clause(model)
            if boundary is not None:
                allocated_contracts = allocated_contracts.where(boundary)
        matches.append(b.id.in_(allocated_contracts.where(func.lower(ContractORM.contract_number).like(f"%{needle}%", escape="\\"))))
        if re.fullmatch(r"\d{2}\.\d{2}\.\d{4}", search):
            try:
                matches.append(b.booking_date == date.fromisoformat(search[6:] + "-" + search[3:5] + "-" + search[:2]))
            except ValueError:
                pass
        conditions.append(or_(*matches))
    if flow:
        selected = options.get("flow", "all")
        if selected == "open":
            conditions.append(b.status == "open")
        elif selected == "no_category":
            conditions.append(b.category_id.is_(None))
        elif selected in {"income", "expense", "withdrawal", "contribution"}:
            conditions.append(_side() == selected)
    return conditions


def _query(options, *, flow=False):
    return select(*BookingORM.__table__.c).where(*_conditions(options, flow=flow)).execution_options(**{BOUNDED: True})


def _order(options):
    key = options.get("sort_by", "booking_date")
    column = _labels()[key] if key in {"account_name", "category_name", "property_name", "unit_label", "tenant_name"} else BookingORM.__table__.c.get(key)
    column = column if column is not None else BookingORM.__table__.c.amount
    return [(column.desc() if options.get("sort_order", "desc") == "desc" else column.asc()).nulls_last(), BookingORM.id]


def _sql_rows(store, options, skip, limit, *, ids=None):
    query = _query(options, flow=ids is None)
    if ids is not None:
        if not ids:
            return []
        query = query.where(BookingORM.id.in_(ids))
    query = query.order_by(*_order(options)).offset(skip).limit(limit)
    return [Booking.model_validate(dict(row)) for row in store.db.execute(query).mappings()]


def allocations(store, ids):
    ids = list(ids)
    if not ids:
        return [], {}
    if hasattr(store, "db"):
        query = select(*PaymentAllocationORM.__table__.c).where(PaymentAllocationORM.booking_id.in_(ids))
        boundary = scoped_clause(PaymentAllocationORM)
        if boundary is not None:
            query = query.where(boundary)
        query = query.execution_options(**{BOUNDED: True})
        rows = [dict(row) for row in store.db.execute(query).mappings()]
    else:
        wanted = set(ids)
        rows = [row.model_dump(mode="json") for row in store.list_payment_allocations() if row.booking_id in wanted]
    reserved = {key: as_number(value) for key, value in non_rent_shares(store, ids).items() if value}
    return rows, reserved


def _blank_summary():
    return {"count": 0, "income": ZERO, "expense": ZERO, "withdrawal": ZERO, "contribution": ZERO, "no_category": 0, "no_receipt": 0}


def _matches_columns(row, amount, receipt, labels, filters):
    for key, value in filters.items():
        if key in {"booking_date", "amount", "owner_part"}:
            current = row.booking_date.isoformat() if key == "booking_date" else amount if key == "owner_part" else money(row.amount)
            for index, endpoint in enumerate(value):
                if not endpoint:
                    continue
                bound = endpoint if key == "booking_date" else Decimal(endpoint)
                if index == 0 and current < bound or index == 1 and current > bound:
                    return False
        elif key == "has_receipt":
            actual = "Vorhanden" if receipt else "Ungültig" if (row.receipt_url or "").strip() else "Fehlt"
            if value.lower() not in actual.lower():
                return False
        elif key == "status":
            if value and row.status != value:
                return False
        else:
            actual = labels.get(key, getattr(row, key, ""))
            if value.lower() not in str(actual or "").lower():
                return False
    return True


def _public_summary(summary):
    return {key: as_number(value) if isinstance(value, Decimal) else value for key, value in summary.items()}


def _sql_summary(store, options):
    b = BookingORM.__table__.c
    rows = select(_side().label("side"), _cents(store.db, b.amount).label("cents"), b.category_id).where(*_conditions(options)).execution_options(**{BOUNDED: True}).subquery()
    result = _blank_summary()
    query = select(rows.c.side, func.count(), func.sum(rows.c.cents), func.sum(case((rows.c.category_id.is_(None), 1), else_=0))).group_by(rows.c.side)
    for side, count, cents, no_category in store.db.execute(query.execution_options(**{BOUNDED: True})):
        result["count"] += count
        result["no_category"] += no_category or 0
        result[side] = money(Decimal(cents or 0) / 100) * (-1 if side in {"expense", "withdrawal"} else 1)
    query = select(b.receipt_url).where(*_conditions(options)).execution_options(**{BOUNDED: True, "yield_per": BATCH})
    result["no_receipt"] = sum(not has_receipt(value) for value in store.db.scalars(query))
    return _public_summary(result)


def _maps(store):
    return {"account_name": {r.id: r.name for r in store.list_accounts()},
            "category_name": {r.id: r.name for r in store.list_categories()},
            "property_name": {r.id: r.name for r in store.list_properties()},
            "unit_label": {r.id: r.label for r in store.list_units()},
            "tenant_name": {r.id: r.full_name for r in store.list_tenants()}}


def _memory_base(store, options):
    dimensions = Dimensions(store, _finance(options))
    maps = _maps(store)
    ids = {"account_name": "account_id", "category_name": "category_id", "property_name": "property_id", "unit_label": "unit_id", "tenant_name": "tenant_id"}
    needle = options.get("search", "").strip().lower()
    contracts = {row.id: row.contract_number for row in store.list_contracts()} if needle else {}
    contract_labels = defaultdict(list)
    if needle:
        for allocation in store.list_payment_allocations():
            contract_labels[allocation.booking_id].append(contracts.get(allocation.contract_id, ""))
    for row in store.list_bookings():
        if not dimensions.booking_matches(row) or any(options.get(key) and getattr(row, key) != options[key] for key in ("account_id", "tenant_id", "category_id", "status")):
            continue
        texts = [row.payment_text, row.status, str(row.booking_date), row.booking_date.strftime("%d.%m.%Y"), str(row.amount)]
        texts += [maps[key].get(getattr(row, field), "") for key, field in ids.items()]
        texts += contract_labels[row.id]
        if needle and not any(needle in str(text or "").lower() for text in texts):
            continue
        yield row


@dataclass(frozen=True)
class Selection:
    ids: tuple[str, ...]
    parts: dict[str, Decimal]
    summary: dict


def _materialize(store, options):
    owner = options.get("owner_contact_id")
    view, key = (Ownership(store), owner_key(owner)) if owner else (None, None)
    categories = {r.id: r.category_type for r in store.list_categories()}
    maps = _maps(store)
    contracts = {row.id: row.contract_number for row in store.list_contracts()} if "allocation_label" in options.get("column_filters", {}) else {}
    summary = _blank_summary()
    selected: list[tuple[Any, str]] = []
    parts: dict[str, Decimal] = {}
    key_name = options.get("sort_by", "booking_date")
    fields = {"account_name": "account_id", "category_name": "category_id", "property_name": "property_id", "unit_label": "unit_id", "tenant_name": "tenant_id"}

    def batches():
        if hasattr(store, "db"):
            offset = 0
            while True:
                rows = [Booking.model_validate(dict(row)) for row in store.db.execute(
                    _query(options).order_by(BookingORM.id).offset(offset).limit(BATCH)).mappings()]
                if not rows:
                    break
                yield rows
                if len(rows) < BATCH:
                    break
                offset += BATCH
        else:
            group = []
            for row in _memory_base(store, options):
                group.append(row)
                if len(group) == BATCH:
                    yield group
                    group = []
            if group:
                yield group

    for group in batches():
        allocated, reserved = allocations(store, [row.id for row in group]) if options.get("flow") == "unassigned" or "allocation_label" in options.get("column_filters", {}) else ([], {})
        assigned: dict[str, Decimal] = defaultdict(lambda: ZERO)
        allocation_labels = defaultdict(list)
        for allocation in allocated:
            assigned[allocation["booking_id"]] += money(allocation["amount"])
            allocation_labels[allocation["booking_id"]].append(contracts.get(allocation["contract_id"], "?"))
        for row in group:
            amount = view.booking_split(row).get(key, ZERO) if view else money(row.amount)
            if view and not amount:
                continue
            if owner:
                parts[row.id] = amount
            side = booking_side(categories.get(row.category_id), row)
            receipt = has_receipt(row.receipt_url)
            labels = {name: values.get(getattr(row, fields[name])) or "—" for name, values in maps.items()}
            labels["allocation_label"] = " + ".join(allocation_labels[row.id]) or ("Kaution / Forderung" if reserved.get(row.id) else "—")
            if not _matches_columns(row, amount, receipt, labels, options.get("column_filters", {})):
                continue
            summary["count"] += 1
            summary[side] += amount * (-1 if side in {"expense", "withdrawal"} else 1)
            summary["no_category"] += not row.category_id
            summary["no_receipt"] += not receipt
            flow = options.get("flow", "all")
            if ((flow == "open" and row.status != "open") or (flow == "no_category" and row.category_id)
                or (flow == "no_receipt" and receipt) or (flow in {"income", "expense", "withdrawal", "contribution"} and side != flow)
                or (flow == "unassigned" and (not row.tenant_id or money(row.amount) - money(reserved.get(row.id, 0)) - assigned[row.id] == 0))):
                continue
            value = amount if key_name == "owner_part" else maps[key_name].get(getattr(row, fields[key_name])) if key_name in fields else getattr(row, key_name, None)
            if isinstance(value, str):
                value = value.lower()
            selected.append((value, row.id))
    # Missing values are last in both directions; IDs remain a stable tie breaker.
    selected.sort(key=lambda item: item[1])
    present = [item for item in selected if item[0] is not None]
    present.sort(key=lambda item: item[0], reverse=options.get("sort_order", "desc") == "desc")
    ids = tuple(item[1] for item in [*present, *[item for item in selected if item[0] is None]])
    return Selection(ids, parts, _public_summary(summary))


def _special(options):
    return bool(options.get("owner_contact_id") or options.get("column_filters")) or options.get("flow") in {"unassigned", "no_receipt"} or options.get("sort_by") == "owner_part"


def page(store, options, *, skip=0, limit=25):
    validate(store, options)
    special = _special(options) or not hasattr(store, "db")
    selection = _cached(store, "selection", options, lambda source: _materialize(source, options)) if special else None
    if selection is not None:
        wanted = selection.ids[skip:skip + limit]
        rows = _sql_rows(store, options, 0, limit, ids=wanted) if hasattr(store, "db") else [store.get_booking(identifier) for identifier in wanted]
        by_id = {row.id: row for row in rows}
        rows = [by_id[identifier] for identifier in wanted if identifier in by_id]
        total, summary = len(selection.ids), dict(selection.summary)
    else:
        rows = _sql_rows(store, options, skip, limit)
        summary = _cached(store, "summary", {**options, "flow": "all", "sort_by": "booking_date", "sort_order": "asc"}, lambda source: _sql_summary(source, options))
        query = select(func.count()).select_from(BookingORM).where(*_conditions(options, flow=True)).execution_options(**{BOUNDED: True})
        total = store.db.scalar(query) or 0
    owner_parts = selection.parts if selection is not None else {}
    items = [row.model_dump(mode="json") | ({"owner_part": as_number(owner_parts[row.id])} if options.get("owner_contact_id") else {}) for row in rows]
    allocated, reserved = allocations(store, [row.id for row in rows])
    return {"items": items, "total": total, "skip": skip, "limit": limit, "has_more": skip + len(items) < total,
            "summary": summary, "allocations": allocated, "reserved_amounts": reserved}


CSV_COLUMNS = {"booking_date": "Datum", "account_name": "Konto", "tenant_name": "Mieter", "allocation_label": "Vertrag",
               "amount": "Betrag (€)", "owner_part": "Anteil des Eigentümers (€)", "payment_text": "Buchungstext",
               "property_name": "Immobilie", "unit_label": "Einheit", "category_name": "Kategorie", "status": "Status",
               "has_receipt": "Beleg"}


def export_csv(store, options, *, columns=None):
    validate(store, options)
    chosen = [key for key in (columns or CSV_COLUMNS) if key in CSV_COLUMNS]
    if not chosen:
        raise HTTPException(422, "Keine exportierbare Buchungsspalte gewählt.")
    buffer = tempfile.SpooledTemporaryFile(max_size=1 << 20, mode="w+b")
    text = io.TextIOWrapper(buffer, encoding="utf-8-sig", newline="")
    writer = csv.writer(text, delimiter=";")
    writer.writerow([CSV_COLUMNS[key] for key in chosen])
    try:
        # Materialize the file while the request scope and a stable DB snapshot
        # are active. The streaming response only reads already authorized bytes.
        with snapshot(store) as (source, _):
            maps = _maps(source)
            contracts = {row.id: row.contract_number for row in source.list_contracts()}
            selection = _materialize(source, options) if _special(options) or not hasattr(source, "db") else None
            owner_parts = selection.parts if selection is not None else {}
            offset = 0
            while True:
                if selection is not None:
                    wanted = selection.ids[offset:offset + BATCH]
                    rows = _sql_rows(source, options, 0, BATCH, ids=wanted) if hasattr(source, "db") else [source.get_booking(identifier) for identifier in wanted]
                    by_id = {row.id: row for row in rows}
                    rows = [by_id[identifier] for identifier in wanted if identifier in by_id]
                else:
                    rows = _sql_rows(source, options, offset, BATCH)
                if not rows:
                    break
                allocated, reserved = allocations(source, [row.id for row in rows])
                labels: dict[str, list[str]] = defaultdict(list)
                for allocation in allocated:
                    label = contracts.get(allocation["contract_id"], "?")
                    if label not in labels[allocation["booking_id"]]:
                        labels[allocation["booking_id"]].append(label)
                for row in rows:
                    values = row.model_dump()
                    values.update({key: mapping.get(getattr(row, {"account_name": "account_id", "category_name": "category_id", "property_name": "property_id", "unit_label": "unit_id", "tenant_name": "tenant_id"}[key]), "—") for key, mapping in maps.items()})
                    label = (" + ".join(labels[row.id]) or ("Kaution / Forderung" if reserved.get(row.id) else "—")) if row.tenant_id else "—"
                    receipt = "Vorhanden" if has_receipt(row.receipt_url) else "Ungültig" if (row.receipt_url or "").strip() else "Fehlt"
                    values.update(allocation_label=label, has_receipt=receipt)
                    values["owner_part"] = owner_parts[row.id] if options.get("owner_contact_id") else None
                    writer.writerow([format(money(values[key]), "f").replace(".", ",")
                                     if key in {"amount", "owner_part"} and values.get(key) is not None
                                     else spreadsheet_cell(values.get(key)) for key in chosen])
                offset += len(rows)
                if len(rows) < BATCH:
                    break
        text.flush()
        text.detach()
        buffer.seek(0)
    except BaseException:
        text.close()
        raise

    def chunks():
        try:
            while block := buffer.read(64 * 1024):
                yield block
        finally:
            buffer.close()
    return StreamingResponse(chunks(), media_type="text/csv; charset=utf-8", headers={"Content-Disposition": "attachment; filename=Buchungen.csv", "Cache-Control": "no-store"})
