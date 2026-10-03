"""Scoped grouped property projections, bounded live pages and fresh publication."""

import json
from contextlib import contextmanager
from dataclasses import asdict
from functools import cmp_to_key
from heapq import nsmallest

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import and_, case, func, literal, or_, select
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.exc import DBAPIError
from sqlalchemy.exc import TimeoutError as PoolTimeout
from sqlalchemy.orm import Session
from sqlalchemy.pool import SingletonThreadPool, StaticPool

from ..db.booking_order import bytewise_id
from ..db.orm_models import ContractORM, MaintenanceCaseORM, PortfolioORM, PropertyORM, TenantORM, UnitORM
from ..models import Property
from .booking_export import _snapshot
from .concurrency import etag
from .contract_workspace import maximum_page_size
from .contract_workspace_search import UnicodeCasefold, ensure_sqlite_casefold
from .payments import _memory_lock
from .portfolio_scope import current_scope, memory_visible, refresh_scope, scoped_clause
from .property_inventory_money import (
    CentRank,
    CurrencyLabel,
    ExactCentSum,
    SourceCents,
    SourceMoneyValid,
    cent_text,
    currency_label,
    install_exact_sum,
    money_text,
    source_cents,
)
from .property_inventory_types import (
    COUNT_FIELDS,
    PropertyInventoryItem,
    PropertyInventoryPage,
    PropertyInventoryQuery,
    PropertyInventorySummary,
    PropertyInventoryTotals,
)
from .reference_cursor import pack_reference_cursor, unpack_reference_cursor

PROPERTY_FIELDS = tuple(Property.model_fields)
MAINTENANCE_STATUSES = ("open", "in_progress", "completed", "cancelled")
VIEW_COUNTS = {
    "manual_vacancy": "manual_vacant_unit_count",
    "open_maintenance": "open_maintenance_count",
    "no_current_contract": "no_current_contract_unit_count",
    "multiple_current_contracts": "multiple_current_contract_unit_count",
}


def _unavailable():
    return HTTPException(503, "Immobilienkennzahlen sind nicht verfügbar. Bitte erneut laden.")


def _changed():
    return HTTPException(409, {"code": "property_inventory_changed",
                              "detail": "Bestand oder Zuordnungen wurden geändert. Bitte die erste Seite neu laden."})


def _visible(table, scope):
    clause = scoped_clause(table, scope=scope)
    return clause if clause is not None else True


def prepare_read(session, query):
    """Export adapter and JSON snapshots prepare exactly their own connection."""
    actual = session.connection()
    bound = session.get_bind()
    if isinstance(bound, Connection) and bound is not actual:
        raise RuntimeError("property_inventory_connection_mismatch")
    if isinstance(bound, Engine) and actual.engine is not bound:
        raise RuntimeError("property_inventory_engine_mismatch")
    install_exact_sum(session, connection=actual)
    if query.search:
        ensure_sqlite_casefold(session)


def binding(query, scope):
    return {"kind": "property-inventory-v1", "query": query.model_dump(mode="json", exclude={"cursor"}),
            "scope": asdict(scope), "rent_sort": "currency-byte-asc-null-last/cents-direction-null-last/id-direction"}


def position(query, scope):
    encoded = unpack_reference_cursor(query.cursor, binding(query, scope))
    if encoded is None:
        return None
    try:
        point = json.loads(encoded)
        size = 3 if query.sort_by == "unit_cold_rent_sum" else 2
        if not isinstance(point, list) or len(point) != size or not isinstance(point[-1], str) or not point[-1]:
            raise ValueError
        if query.sort_by == "unit_cold_rent_sum":
            currency, cents, _ = point
            if currency is not None and currency_label(currency) is None:
                raise ValueError
            if currency is None and cents is not None:
                raise ValueError
            if cents is not None:
                if not isinstance(cents, str):
                    raise ValueError
                cent_text(cents)
        elif point[0] is not None and not isinstance(point[0], str):
            raise ValueError
        return tuple(point)
    except (TypeError, ValueError):
        raise HTTPException(422, "Die Immobilienseite ist ungültig. Bitte die erste Seite laden.") from None


def page_position(query, row):
    if query.sort_by == "unit_cold_rent_sum":
        cents = row["_rent_cents"]
        return row["rent_currency"], cent_text(cents) if cents is not None else None, row["id"]
    return row[query.sort_by], row["id"]


def _address_sql(properties):
    line, postal, city = (func.coalesce(properties.c[field], "") for field in ("address_line", "postal_code", "city"))
    place = case((and_(postal != "", city != ""), postal + " " + city), else_=postal + city)
    return func.nullif(case((and_(line != "", place != ""), line + ", " + place), else_=line + place), "")


def _flag_sum(condition):
    return func.sum(case((condition, 1), else_=0))


def _projection(query, scope):
    properties, portfolios, units, contracts, tenants, maintenance = (
        model.__table__ for model in (PropertyORM, PortfolioORM, UnitORM, ContractORM, TenantORM, MaintenanceCaseORM))
    props = select(*(properties.c[field] for field in PROPERTY_FIELDS), portfolios.c.name.label("portfolio_name"),
                   CurrencyLabel(portfolios.c.currency).label("rent_currency"), _address_sql(properties).label("address"))
    props = props.outerjoin(portfolios, and_(portfolios.c.id == properties.c.portfolio_id, _visible(portfolios, scope))).where(
        _visible(properties, scope))
    if not scope.unrestricted:
        props = props.where(portfolios.c.id.is_not(None))
    props = props.cte("property_inventory_parents")
    eligible_units = select(units.c.id, units.c.property_id, units.c.status, units.c.cold_rent).join(
        props, props.c.id == units.c.property_id).where(_visible(units, scope)).cte("property_inventory_units")
    current = select(contracts.c.unit_id, func.count().label("current_count")).join(
        eligible_units, and_(eligible_units.c.id == contracts.c.unit_id,
                             eligible_units.c.property_id == contracts.c.property_id)).join(
        tenants, tenants.c.id == contracts.c.tenant_id).where(
        _visible(contracts, scope), contracts.c.status.in_(("active", "terminated")),
        contracts.c.start_date <= query.as_of, or_(contracts.c.end_date.is_(None), contracts.c.end_date >= query.as_of)
    ).group_by(contracts.c.unit_id).cte("property_inventory_current_contracts")
    per_unit = select(eligible_units, func.coalesce(current.c.current_count, 0).label("current_count")).outerjoin(
        current, current.c.unit_id == eligible_units.c.id).cte("property_inventory_unit_basis")
    valid = SourceMoneyValid(per_unit.c.cold_rent)
    unit_counts = {
        "unit_count": func.count(),
        "occupied_unit_count": _flag_sum(per_unit.c.current_count > 0),
        "no_current_contract_unit_count": _flag_sum(per_unit.c.current_count == 0),
        "multiple_current_contract_unit_count": _flag_sum(per_unit.c.current_count > 1),
        "manual_occupied_unit_count": _flag_sum(per_unit.c.status.in_(("occupied", "rented"))),
        "manual_vacant_unit_count": _flag_sum(per_unit.c.status == "vacant"),
        "manual_reserved_unit_count": _flag_sum(per_unit.c.status == "reserved"),
        "rent_known_unit_count": _flag_sum(valid),
        "rent_missing_unit_count": _flag_sum(per_unit.c.cold_rent.is_(None)),
        "rent_invalid_unit_count": _flag_sum(and_(per_unit.c.cold_rent.is_not(None), ~valid)),
    }
    unit_totals = select(per_unit.c.property_id, *(value.label(key) for key, value in unit_counts.items()),
                         ExactCentSum(SourceCents(per_unit.c.cold_rent)).label("cent_sum")).group_by(
        per_unit.c.property_id).cte("property_inventory_unit_totals")
    maintenance_totals = select(maintenance.c.property_id,
        _flag_sum(maintenance.c.status.in_(("open", "in_progress"))).label("open_maintenance_count"),
        _flag_sum(or_(maintenance.c.status.is_(None), ~maintenance.c.status.in_(MAINTENANCE_STATUSES))).label(
            "unknown_maintenance_status_count")
    ).join(props, props.c.id == maintenance.c.property_id).outerjoin(eligible_units, and_(
        eligible_units.c.id == maintenance.c.unit_id, eligible_units.c.property_id == maintenance.c.property_id)
    ).where(_visible(maintenance, scope), or_(maintenance.c.unit_id.is_(None), eligible_units.c.id.is_not(None))).group_by(
        maintenance.c.property_id).cte("property_inventory_maintenance_totals")
    counts = {key: func.coalesce(unit_totals.c[key] if key in unit_counts else maintenance_totals.c[key], 0)
              for key in COUNT_FIELDS}
    complete = and_(props.c.rent_currency.is_not(None), counts["rent_missing_unit_count"] == 0,
                    counts["rent_invalid_unit_count"] == 0)
    return select(props, *(value.label(key) for key, value in counts.items()), case(
        (complete, func.coalesce(unit_totals.c.cent_sum, "0")), else_=None).label("_rent_cents")).outerjoin(
        unit_totals, unit_totals.c.property_id == props.c.id).outerjoin(
        maintenance_totals, maintenance_totals.c.property_id == props.c.id)


def statement(query, scope, *, matching=True):
    rows = _projection(query, scope).subquery()
    result = select(rows)
    if not matching:
        return result
    for field in ("portfolio_id", "status", "property_type"):
        value = getattr(query, field)
        if value is not None:
            result = result.where(rows.c[field] == value)
    if query.view in VIEW_COUNTS:
        result = result.where(rows.c[VIEW_COUNTS[query.view]] > 0)
    if query.search:
        term = query.search.casefold().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        result = result.where(or_(*(bytewise_id(UnicodeCasefold(rows.c[field])).like(f"%{term}%", escape="\\")
                                   for field in ("name", "address", "portfolio_name", "property_type"))))
    return result


def _after_value(value, identifier, last_value, last_id, descending):
    id_after = identifier < last_id if descending else identifier > last_id
    if last_value is None:
        return and_(value.is_(None), id_after)
    return or_(value.is_(None), value < last_value if descending else value > last_value,
               and_(value == last_value, id_after))


def ordered(base, query, after, limit):
    rows = base.subquery()
    identifier = bytewise_id(rows.c.id)
    descending = query.sort_order == "desc"
    result = select(rows)
    if query.sort_by == "unit_cold_rent_sum":
        currency, text = bytewise_id(rows.c.rent_currency), bytewise_id(rows.c._rent_cents)
        rank = CentRank(rows.c._rent_cents)
        if after is not None:
            last_currency, last_cents, last_id = after
            same_currency = currency.is_(None) if last_currency is None else currency == last_currency
            if last_cents is None:
                within = _after_value(text, identifier, None, last_id, descending)
            else:
                magnitude = CentRank(literal(last_cents))
                within = or_(text.is_(None), rank < magnitude if descending else rank > magnitude,
                    and_(rank == magnitude, _after_value(text, identifier, last_cents, last_id, descending)))
            later_currency = False if last_currency is None else or_(currency.is_(None), currency > last_currency)
            result = result.where(or_(later_currency, and_(same_currency, within)))
        sort_columns = [currency.asc().nulls_last(), rank.desc().nulls_last() if descending else rank.asc().nulls_last(),
                        text.desc().nulls_last() if descending else text.asc().nulls_last()]
    else:
        value = bytewise_id(rows.c[query.sort_by])
        if after is not None:
            result = result.where(_after_value(value, identifier, *after, descending))
        sort_columns = [value.desc().nulls_last() if descending else value.asc().nulls_last()]
    return result.order_by(*sort_columns, identifier.desc() if descending else identifier.asc()).limit(limit)


def _address(row):
    place = " ".join(value for value in (row.get("postal_code"), row.get("city")) if value)
    return ", ".join(value for value in (row.get("address_line"), place) if value) or None


def _memory_projection(store, query, scope):
    raw = object.__getattribute__(store, "__dict__")
    props = {}
    for prop in raw["properties"].values():
        if not memory_visible(store, "properties", prop, scope=scope):
            continue
        portfolio = raw["portfolios"].get(prop.portfolio_id)
        if portfolio is not None and not memory_visible(store, "portfolios", portfolio, scope=scope):
            portfolio = None
        if portfolio is None and not scope.unrestricted:
            continue
        fields = prop.model_dump()
        props[prop.id] = {**fields, **dict.fromkeys(COUNT_FIELDS, 0), "address": _address(fields),
                          "portfolio_name": getattr(portfolio, "name", None),
                          "rent_currency": currency_label(getattr(portfolio, "currency", None)), "_rent_cents": 0}
    units = {unit.id: unit for unit in raw["units"].values()
             if unit.property_id in props and memory_visible(store, "units", unit, scope=scope)}
    contracts = {}
    for contract in raw["contracts"].values():
        unit = units.get(contract.unit_id)
        if (unit is not None and contract.property_id == unit.property_id and contract.tenant_id in raw["tenants"]
                and memory_visible(store, "contracts", contract, scope=scope)
                and contract.status in {"active", "terminated"} and contract.start_date <= query.as_of
                and (contract.end_date is None or contract.end_date >= query.as_of)):
            contracts[unit.id] = contracts.get(unit.id, 0) + 1
    for unit in units.values():
        row, count = props[unit.property_id], contracts.get(unit.id, 0)
        row["unit_count"] += 1
        row["occupied_unit_count"] += count > 0
        row["no_current_contract_unit_count"] += count == 0
        row["multiple_current_contract_unit_count"] += count > 1
        row["manual_occupied_unit_count"] += unit.status in {"occupied", "rented"}
        row["manual_vacant_unit_count"] += unit.status == "vacant"
        row["manual_reserved_unit_count"] += unit.status == "reserved"
        try:
            cents = source_cents(unit.cold_rent)
        except ValueError:
            row["rent_invalid_unit_count"] += 1
        else:
            if cents is None:
                row["rent_missing_unit_count"] += 1
            else:
                row["rent_known_unit_count"] += 1
                row["_rent_cents"] += cents
    for case_row in raw["maintenance_cases"].values():
        row, unit = props.get(case_row.property_id), units.get(case_row.unit_id)
        if row is None or not memory_visible(store, "maintenance_cases", case_row, scope=scope):
            continue
        if case_row.unit_id is not None and (unit is None or unit.property_id != case_row.property_id):
            continue
        row["open_maintenance_count"] += case_row.status in {"open", "in_progress"}
        row["unknown_maintenance_status_count"] += case_row.status not in MAINTENANCE_STATUSES
    for row in props.values():
        row["_rent_cents"] = (cent_text(row["_rent_cents"]) if row["rent_currency"] is not None
                              and row["rent_missing_unit_count"] == row["rent_invalid_unit_count"] == 0 else None)
    return props.values()


def _matches(row, query):
    if any(getattr(query, field) is not None and row[field] != getattr(query, field)
           for field in ("portfolio_id", "status", "property_type")):
        return False
    if query.view in VIEW_COUNTS and row[VIEW_COUNTS[query.view]] == 0:
        return False
    return not query.search or any(query.search.casefold() in (row[field] or "").casefold()
                                   for field in ("name", "address", "portfolio_name", "property_type"))


def memory_rows(store, query, scope):
    return (row for row in _memory_projection(store, query, scope) if _matches(row, query))


def _compare_nullable(first, second):
    if first is None or second is None:
        return (first is None) - (second is None)
    return (first > second) - (first < second)


def _compare_position(first, second, query):
    direction = -1 if query.sort_order == "desc" else 1
    if query.sort_by == "unit_cold_rent_sum":
        result = _compare_nullable(first[0].encode() if first[0] is not None else None,
                                   second[0].encode() if second[0] is not None else None)
        if result:
            return result
        a, b = first[1], second[1]
        if a is None or b is None:
            result = _compare_nullable(a, b)
        else:
            result = _compare_nullable((len(a), a), (len(b), b)) * direction
    else:
        a, b = first[0], second[0]
        result = _compare_nullable(a.encode() if a is not None else None, b.encode() if b is not None else None)
        if a is not None and b is not None:
            result *= direction
    return result or _compare_nullable(first[-1].encode(), second[-1].encode()) * direction


def _select_memory(rows, query, after, limit):
    eligible = (row for row in rows if after is None or _compare_position(page_position(query, row), after, query) > 0)
    return nsmallest(limit, eligible, key=cmp_to_key(
        lambda first, second: _compare_position(page_position(query, first), page_position(query, second), query)))


def memory_page(store, query, scope, after, limit):
    return _select_memory(memory_rows(store, query, scope), query, after, limit)


def item(row):
    fields = {key: row[key] for key in (*PROPERTY_FIELDS, *COUNT_FIELDS, "portfolio_name", "address", "rent_currency")}
    return PropertyInventoryItem(**fields, unit_cold_rent_sum=(
        money_text(row["_rent_cents"]) if row["_rent_cents"] is not None else None),
        edit_etag=etag("properties", row["id"], row["updated_at"]))


def export_row(row):
    return item(row).model_dump(mode="json")


def _counts(rows):
    counts = dict.fromkeys(COUNT_FIELDS, 0)
    total = 0
    for row in rows:
        total += 1
        for field in COUNT_FIELDS:
            counts[field] += row[field]
    return PropertyInventoryTotals(property_count=total, **counts)


def _sql_totals(db, base):
    rows = base.subquery()
    counts = db.execute(select(func.count().label("property_count"), *(func.coalesce(func.sum(rows.c[field]), 0).label(field)
                           for field in COUNT_FIELDS)).select_from(rows)).mappings().one()
    return PropertyInventoryTotals.model_validate(dict(counts))


def _scope(query, *, summary=False):
    if not isinstance(query, PropertyInventoryQuery) or query.page_size > maximum_page_size():
        raise HTTPException(422, "Bitte gültige Filter und eine kleinere Seite wählen; alle weiteren Seiten bleiben erreichbar.")
    if summary and query.cursor is not None:
        raise HTTPException(422, "Kennzahlen benötigen Filter, keinen Seitencursor.")
    scope = current_scope()
    if scope is None:
        raise HTTPException(403, "Eine geprüfte Benutzerbindung ist erforderlich.")
    refresh_scope(scope)
    return scope


def _engine(store):
    db = getattr(store, "db", None)
    if not isinstance(db, Session):
        raise _unavailable()
    bound = db.get_bind()
    engine = bound.engine if isinstance(bound, Connection) else bound
    if not isinstance(engine, Engine) or engine.dialect.name not in {"sqlite", "postgresql"}:
        raise _unavailable()
    if engine.dialect.name == "sqlite" and isinstance(engine.pool, (StaticPool, SingletonThreadPool)):
        # Such pools can re-lease the caller's physical driver; rollback would
        # then touch its transaction and no independent fresh read is possible.
        raise _unavailable()
    return engine


@contextmanager
def _read(engine, query, scope):
    refresh_scope(scope)
    with _snapshot(engine) as connection, Session(bind=connection, autoflush=False) as db:
        if connection.engine is not engine or db.get_bind() is not connection:
            raise RuntimeError("property_inventory_snapshot_identity_mismatch")
        prepare_read(db, query)
        yield db
        refresh_scope(scope)


def _page_read(engine, query, scope, after):
    with _read(engine, query, scope) as db:
        return [dict(row) for row in db.execute(ordered(statement(query, scope), query, after, query.page_size + 1)).mappings()]


def property_inventory_page(store, query):
    scope = _scope(query)
    after = position(query, scope)
    try:
        if hasattr(store, "db"):
            engine = _engine(store)
            first = _page_read(engine, query, scope, after)
            # First transaction is closed; parents and children are read anew.
            actual = _page_read(engine, query, scope, after)
            if actual != first:
                raise _changed()
        else:
            with _memory_lock:
                first = memory_page(store, query, scope, after, query.page_size + 1)
                refresh_scope(scope)
        more = len(first) > query.page_size
        rows = first[:query.page_size]
        cursor = pack_reference_cursor(binding(query, scope), json.dumps(page_position(query, rows[-1]))) if more else None
        result = PropertyInventoryPage(items=[item(row) for row in rows], has_more=more, next_cursor=cursor, as_of=query.as_of)
        refresh_scope(scope)
        return result
    except (DBAPIError, PoolTimeout, ValidationError, ValueError):
        raise _unavailable() from None


def _summary_read(engine, query, scope):
    with _read(engine, query, scope) as db:
        return (_sql_totals(db, statement(query, scope, matching=False)), _sql_totals(db, statement(query, scope)))


def property_inventory_summary(store, query):
    scope = _scope(query, summary=True)
    try:
        if hasattr(store, "db"):
            engine = _engine(store)
            counts = _summary_read(engine, query, scope)
            actual = _summary_read(engine, query, scope)
            if actual != counts:
                raise _changed()
        else:
            with _memory_lock:
                rows = _memory_projection(store, query, scope)
                counts = (_counts(rows), _counts(row for row in rows if _matches(row, query)))
                refresh_scope(scope)
        result = PropertyInventorySummary(as_of=query.as_of, scope_totals=counts[0], matching_totals=counts[1])
        refresh_scope(scope)
        return result
    except (DBAPIError, PoolTimeout, ValidationError, ValueError):
        raise _unavailable() from None
