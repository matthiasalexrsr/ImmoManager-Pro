"""Complete scoped status counts and small live work pages, without stock models."""

from bisect import bisect_right
from datetime import date, datetime, timedelta
from heapq import nsmallest
from typing import Any

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import Date, String, case, cast, func, literal, or_, select

from ..db.booking_order import bytewise_id
from ..db.orm_models import Base
from .booking_export import _snapshot
from .payments import _memory_lock
from .portfolio_scope import current_scope, memory_visible, refresh_scope, scoped_clause
from .tenancy_workflow import decode_cursor, digest, encode_cursor

CLOSED = frozenset({"archived", "cancelled", "canceled", "closed", "done", "finalized", "paid"})
OPEN_MAINTENANCE = frozenset({"open", "in_progress", "pending", "review"})
PRE_FINAL = frozenset({"draft", "review", "open"})
TOTALS = {
    "portfolios": "portfolio_count", "properties": "property_count", "units": "unit_count",
    "tenants": "tenant_count", "contracts": "contract_count", "accounts": "account_count",
    "invoices": "invoice_count", "receivables": "receivable_count", "documents": "document_count",
    "tasks": "task_count", "notifications": "notification_count", "rent_charges": "rent_charge_count",
    "billing_periods": "billing_period_count", "allocation_keys": "allocation_key_count",
    "utility_statements": "utility_statement_count",
}
STATUS_COUNTS: dict[str, dict[str, tuple[str, ...]]] = {
    "units": {"vacant_units": ("vacant",), "occupied_units": ("occupied",), "reserved_units": ("reserved",),
              "_occupied": ("occupied", "rented"), "_rented": ("rented",)},
    "contracts": {"active_contracts": ("active",)},
    "maintenance_cases": {"open_maintenance": ("open",)},
    "invoices": {"open_invoices": ("open",), "paid_invoices": ("paid",)},
    "receivables": {"open_receivables": ("open", "partial"), "paid_receivables": ("paid",)},
    "tasks": {"open_tasks": ("open",)}, "notifications": {"unread_notifications": ("unread",)},
    "rent_charges": {"open_rent_charges": ("open", "partial"), "overdue_rent_charges": ("overdue",)},
    "billing_periods": {"draft_billing_periods": ("draft",), "finalized_billing_periods": ("finalized",)},
    "utility_statements": {"draft_utility_statements": ("draft",), "finalized_utility_statements": ("finalized",)},
}
HINTS: dict[str, tuple[str, str, tuple[str, ...], str, str]] = {
    "tasks": ("tasks", "due_date", ("id", "title", "due_date", "priority"), "open_tasks", "/tasks?status=open"),
    "notifications": ("notifications", "created_at", ("id", "title", "severity", "entity_type", "entity_id"),
                      "unread_notifications", "/notifications?status=unread"),
    "expiring_contracts": ("contracts", "end_date", ("id", "contract_number", "end_date"),
                           "_expiring", "/contracts"),
}


class DashboardQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    as_of: date = Field(default_factory=date.today)
    preview_limit: int = Field(default=5, ge=1, le=20, strict=True)
    tasks_after: str | None = Field(default=None, min_length=1, max_length=8192)
    notifications_after: str | None = Field(default=None, min_length=1, max_length=8192)
    contracts_after: str | None = Field(default=None, min_length=1, max_length=8192)

    @model_validator(mode="after")
    def valid_window(self):
        if self.as_of > date.max - timedelta(days=90):
            raise ValueError("Der Stichtag lässt kein vollständiges 90-Tage-Fenster zu.")
        return self

    def after(self, family):
        return getattr(self, {"expiring_contracts": "contracts_after"}.get(family, family + "_after"))


def _visible(table, scope):
    criterion = scoped_clause(table, scope=scope)
    return criterion if criterion is not None else True


def _normalized(column):
    return func.lower(func.coalesce(column, ""))


def _expiring(table, query):
    return table.c.end_date.between(query.as_of, query.as_of + timedelta(days=90))


def _notification_clause(table, scope):
    # Exactly the existing notification_visible rule; dispatch.notification_id is unique.
    if scope is None or scope.role == "eigentuemer":
        return True
    dispatch = Base.metadata.tables["operational_dispatches"]
    return ~select(1).select_from(dispatch).where(dispatch.c.notification_id == table.c.id,
        dispatch.c.target_role.is_not(None), dispatch.c.target_role != "", dispatch.c.target_role != scope.role).exists()


def _sql_counts(scope, query, dialect):
    tables = Base.metadata.tables
    expressions: dict[str, Any] = {}
    for collection in dict.fromkeys([*TOTALS, *STATUS_COUNTS, "escalation_rules"]):
        table = tables[collection]
        flags: dict[str, Any] = {key: table.c.status.in_(states) for key, states in STATUS_COUNTS.get(collection, {}).items()}
        if collection == "contracts":
            flags["_expiring"] = _expiring(table, query)
        elif collection == "receivables":
            flags["overdue_receivables"] = or_(table.c.status == "overdue",
                (table.c.status == "partial") & (table.c.due_date < query.as_of))
            flags["dunning_receivables"] = (table.c.dunning_level.is_not(None) & (table.c.dunning_level != "")
                & ~_normalized(table.c.status).in_(CLOSED))
        elif collection == "maintenance_cases":
            flags["overdue_maintenance"] = _normalized(table.c.status).in_(OPEN_MAINTENANCE) & (table.c.due_date < query.as_of)
            rules = tables["escalation_rules"]
            days = case((rules.c.days_overdue > 0, rules.c.days_overdue), else_=0)
            cutoff = (literal(query.as_of, type_=Date()) - days if dialect == "postgresql" else
                      func.date(query.as_of, func.printf("-%d days", days)))
            relevant_rule = select(1).select_from(rules).where(_visible(rules, scope), rules.c.is_active.is_(True),
                _normalized(rules.c.entity_type) == "maintenance", table.c.due_date <= cutoff).exists()
            flags["maintenance_escalation_candidates"] = _normalized(table.c.status).in_(OPEN_MAINTENANCE) & relevant_rule
        elif collection == "escalation_rules":
            flags["active_escalation_rules"] = table.c.is_active.is_(True)
        selected = [func.count().label(TOTALS[collection])] if collection in TOTALS else []
        selected.extend(func.coalesce(func.sum(case((flag, 1), else_=0)), 0).label(key) for key, flag in flags.items())
        criterion = _visible(table, scope)
        if collection == "notifications":
            criterion = criterion & _notification_clause(table, scope) if criterion is not True else _notification_clause(table, scope)
        aggregate = select(*selected).select_from(table).where(criterion).cte("dashboard_" + collection)
        expressions.update({column.name: select(column).scalar_subquery() for column in aggregate.c})

    contracts, documents = tables["contracts"], tables["documents"]
    documented = select(1).select_from(documents).where(_visible(documents, scope), documents.c.contract_id == contracts.c.id).exists()
    expressions["active_contracts_missing_documents"] = select(func.count()).select_from(contracts).where(
        _visible(contracts, scope), _normalized(contracts.c.status) == "active", ~documented).scalar_subquery()

    periods, costs, keys = tables["billing_periods"], tables["cost_items"], tables["allocation_keys"]
    selected_period = _normalized(periods.c.status).in_(PRE_FINAL)
    overlap = select(1).select_from(contracts).where(_visible(contracts, scope),
        _normalized(contracts.c.status) == "active", contracts.c.property_id == periods.c.property_id,
        contracts.c.start_date <= periods.c.end_date,
        or_(contracts.c.end_date.is_(None), contracts.c.end_date >= periods.c.start_date)).exists()
    period_cost = (_visible(costs, scope), costs.c.billing_period_id == periods.c.id)
    has_cost = select(1).select_from(costs).where(*period_cost).exists()
    correct_key = select(1).select_from(keys).where(_visible(keys, scope), keys.c.id == costs.c.allocation_key_id,
        keys.c.property_id == periods.c.property_id).correlate(costs, periods).exists()
    invalid_key = select(1).select_from(costs).where(*period_cost, ~correct_key).correlate(periods).exists()
    presence = select(func.count().label("billing_preflight_periods_checked"),
        func.coalesce(func.sum(case((~overlap | ~has_cost | invalid_key, 1), else_=0)), 0).label("billing_preflight_blockers")
        ).select_from(periods).where(_visible(periods, scope), selected_period).cte("dashboard_presence")
    expressions.update({column.name: select(column).scalar_subquery() for column in presence.c})
    qualifying_period = select(1).select_from(periods).where(_visible(periods, scope), selected_period,
        periods.c.id == costs.c.billing_period_id).exists()
    expressions["billing_preflight_warnings"] = select(func.count()).select_from(costs).where(
        _visible(costs, scope), qualifying_period, func.coalesce(costs.c.amount, 0) <= 0).scalar_subquery()
    return select(*(expression.label(name) for name, expression in expressions.items()))


def _binding(query, scope, family):
    return {"kind": "dashboard-work-v1", "family": family, "as_of": query.as_of.isoformat(),
        "limit": query.preview_limit, "sort": "date-asc-null-last-byte-id-asc",
        "actor": None if scope is None else {"id": scope.user_id, "role": scope.role,
            "unrestricted": scope.unrestricted, "portfolio_hash": digest(list(scope.portfolio_ids))}}


def _position(query, scope, family):
    point = decode_cursor(query.after(family), _binding(query, scope, family))
    if point is None:
        return None
    try:
        day: date | datetime | None
        if len(point) != 2 or not isinstance(point[1], str) or not point[1]:
            raise ValueError
        if family == "notifications":
            day = datetime.fromisoformat(point[0]) if point[0] is not None else None
        else:
            day = date.fromisoformat(point[0]) if point[0] is not None else None
        if family == "expiring_contracts" and day is None:
            raise ValueError
        return day, point[1]
    except (ValueError, TypeError):
        raise HTTPException(422, "Ungültige Dashboardseite. Die erste Seite neu laden.") from None


def _sql_hints(connection, query, scope, family, point):
    collection, day_field, fields, _total, _url = HINTS[family]
    table = Base.metadata.tables[collection]
    day, identifier = table.c[day_field], bytewise_id(table.c.id)
    if family == "notifications" and connection.dialect.name == "sqlite":
        # CURRENT_TIMESTAMP lacks the fraction that SQLite's DateTime binder
        # always emits. Use one lossless key for both ordering and comparison.
        raw = cast(day, String)
        day = case((func.length(raw) == 19, raw + ".000000"), else_=raw)
        if point is not None and point[0] is not None:
            point = point[0].isoformat(sep=" ", timespec="microseconds"), point[1]
    fields = tuple(dict.fromkeys([*fields, day_field]))
    statement = select(*(table.c[field] for field in fields)).where(_visible(table, scope))
    statement = statement.where(_expiring(table, query) if family == "expiring_contracts" else
        table.c.status == ("open" if family == "tasks" else "unread"))
    if family == "notifications":
        statement = statement.where(_notification_clause(table, scope))
    if point is not None:
        value, last_id = point
        statement = statement.where((day.is_(None) & (identifier > last_id)) if value is None else
            or_(day.is_(None), day > value, (day == value) & (identifier > last_id)))
    statement = statement.order_by(day.asc().nulls_last(), identifier.asc()).limit(query.preview_limit + 1)
    return [dict(row) for row in connection.execute(statement).mappings()]


def _status(row):
    return str(getattr(row, "status", "") or "").lower()


def _memory_read(store, query, scope, points):
    raw = object.__getattribute__(store, "__dict__")
    dispatches = {row.notification_id: row.target_role
        for row in raw.get("_operational_state", {}).get("dispatches", {}).values()}

    def visible(collection, row):
        return memory_visible(store, collection, row, scope=scope) and (collection != "notifications" or
            scope is None or scope.role == "eigentuemer" or not dispatches.get(row.id) or dispatches[row.id] == scope.role)

    def rows(collection):
        return (row for row in raw.get(collection, {}).values() if visible(collection, row))

    counts = {field: 0 for field in TOTALS.values()}
    counts.update({field: 0 for flags in STATUS_COUNTS.values() for field in flags})
    counts.update({field: 0 for field in ("overdue_receivables", "dunning_receivables", "overdue_maintenance",
        "active_escalation_rules", "maintenance_escalation_candidates", "active_contracts_missing_documents",
        "billing_preflight_periods_checked", "billing_preflight_blockers", "billing_preflight_warnings", "_expiring")})
    maintenance_days = None
    for rule in rows("escalation_rules"):
        if rule.is_active:
            counts["active_escalation_rules"] += 1
            if str(rule.entity_type or "").lower() == "maintenance":
                days = max(0, int(rule.days_overdue or 0))
                maintenance_days = days if maintenance_days is None else min(days, maintenance_days)
    # A cutoff before year 1 cannot include any representable stored due_date.
    cutoff = (query.as_of - timedelta(days=maintenance_days)
        if maintenance_days is not None and maintenance_days < query.as_of.toordinal() else None)
    documented = {row.contract_id for row in rows("documents") if row.contract_id}
    intervals: dict[str, list[tuple[date, date]]] = {}
    for collection in dict.fromkeys([*TOTALS, *STATUS_COUNTS]):
        for row in rows(collection):
            if collection in TOTALS:
                counts[TOTALS[collection]] += 1
            for field, states in STATUS_COUNTS.get(collection, {}).items():
                counts[field] += row.status in states
            if collection == "contracts":
                counts["_expiring"] += bool(row.end_date and query.as_of <= row.end_date <= query.as_of + timedelta(days=90))
                if _status(row) == "active":
                    counts["active_contracts_missing_documents"] += row.id not in documented
                    intervals.setdefault(row.property_id, []).append((row.start_date, row.end_date or date.max))
            elif collection == "receivables":
                counts["overdue_receivables"] += row.status == "overdue" or row.status == "partial" and row.due_date < query.as_of
                counts["dunning_receivables"] += bool(row.dunning_level) and _status(row) not in CLOSED
            elif collection == "maintenance_cases":
                pending = _status(row) in OPEN_MAINTENANCE and row.due_date is not None
                counts["overdue_maintenance"] += bool(pending and row.due_date < query.as_of)
                counts["maintenance_escalation_candidates"] += bool(pending and cutoff is not None and row.due_date <= cutoff)
    interval_index = {}
    for property_id, values in intervals.items():
        starts, ends, latest = [], [], date.min
        for start, end in sorted(values):
            starts.append(start)
            latest = max(latest, end)
            ends.append(latest)
        interval_index[property_id] = starts, ends
    costs_by_period: dict[str, list[int | bool]] = {}
    for cost in rows("cost_items"):
        period = raw["billing_periods"].get(cost.billing_period_id)
        key = raw["allocation_keys"].get(cost.allocation_key_id)
        if period is None:
            continue
        facts = costs_by_period.setdefault(period.id, [0, False, 0])
        facts[0] += 1
        facts[1] |= not (key and visible("allocation_keys", key) and key.property_id == period.property_id)
        facts[2] += (cost.amount or 0) <= 0
    for period in rows("billing_periods"):
        if _status(period) not in PRE_FINAL:
            continue
        counts["billing_preflight_periods_checked"] += 1
        starts, ends = interval_index.get(period.property_id, ([], []))
        index = bisect_right(starts, period.end_date) - 1
        overlap = index >= 0 and ends[index] >= period.start_date
        facts = costs_by_period.get(period.id, [0, False, 0])
        counts["billing_preflight_blockers"] += bool(not overlap or not facts[0] or facts[1])
        counts["billing_preflight_warnings"] += facts[2]
    selected = {}
    for family, (collection, day_field, fields, _total, _url) in HINTS.items():
        def eligible(row):
            day = getattr(row, day_field)
            if family == "expiring_contracts":
                return bool(day and query.as_of <= day <= query.as_of + timedelta(days=90))
            return row.status == ("open" if family == "tasks" else "unread")

        def order(row):
            day = getattr(row, day_field)
            # Cursor and Memory ordering use the source's stored date/time value.
            return day is None, day.isoformat() if day is not None else "", row.id.encode("utf-8")

        point = points[family]
        after_key = None if point is None else (point[0] is None,
            point[0].isoformat() if point[0] is not None else "", point[1].encode("utf-8"))
        chosen = nsmallest(query.preview_limit + 1, (row for row in rows(collection)
            if eligible(row) and (after_key is None or order(row) > after_key)), key=order)
        selected[family] = [{field: getattr(row, field) for field in dict.fromkeys([*fields, day_field])} for row in chosen]
    return counts, selected


def _result(counts, selected, query, scope):
    total, occupied = counts["unit_count"], counts.pop("_occupied")
    result: dict[str, Any] = {name: int(value) for name, value in counts.items() if not name.startswith("_")}
    result.update(as_of=query.as_of.isoformat(), basis="dashboard-status-v1", occupancy={
        "total": total, "occupied": occupied, "rented": counts["_rented"], "vacant": counts["vacant_units"],
        "reserved": counts["reserved_units"], "other": total - occupied - counts["vacant_units"] - counts["reserved_units"],
        "basis": "stored_unit_status"}, billing_presence={"basis": "basic_presence_checks", "complete_preflight": False,
            "periods_checked": counts["billing_preflight_periods_checked"], "blockers": counts["billing_preflight_blockers"],
            "warnings": counts["billing_preflight_warnings"]}, work_hints={})
    for family, (_collection, day_field, fields, total_field, url) in HINTS.items():
        rows = selected[family]
        more = len(rows) > query.preview_limit
        cursor = None
        if more:
            last = rows[query.preview_limit - 1]
            cursor = encode_cursor(_binding(query, scope, family),
                [last[day_field].isoformat() if last[day_field] is not None else None, last["id"]])
        items = []
        for row in rows[:query.preview_limit]:
            item = {field: value.isoformat() if hasattr(value, "isoformat") else value
                    for field, value in row.items() if field in fields}
            if family == "expiring_contracts":
                item["days_remaining"] = (row["end_date"] - query.as_of).days
            items.append(item)
        result["work_hints"][family] = {"total": counts[total_field], "items": items,
            "has_more": more, "next_after": cursor, "source_url": url}
    return result


def dashboard_summary(store, query: DashboardQuery | None = None) -> dict:
    query = query or DashboardQuery()
    captured = current_scope()
    refresh_scope(captured)
    points = {family: _position(query, captured, family) for family in HINTS}
    if hasattr(store, "db"):
        with store.db.no_autoflush, _snapshot(store.db.get_bind()) as connection:
            counts = {key: int(value) for key, value in connection.execute(
                _sql_counts(captured, query, connection.dialect.name)).mappings().one().items()}
            selected = {family: _sql_hints(connection, query, captured, family, points[family]) for family in HINTS}
    else:
        with _memory_lock:
            counts, selected = _memory_read(store, query, captured, points)
    refresh_scope(captured)
    return _result(counts, selected, query, captured)
