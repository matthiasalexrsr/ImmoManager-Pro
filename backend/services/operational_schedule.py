"""Atomic local operations: anchored recurrence, calendar deadlines, deduped alerts.

Only local business rows are created. This service never sends mail or messages.
SQL ticks lock one persistent row before reading state, including across server
processes; business writes and their immutable occurrence keys commit together.
"""
import logging
from contextlib import contextmanager
from copy import deepcopy
from datetime import date, datetime, timedelta
from decimal import Decimal
from hashlib import sha256
from threading import Event, RLock, Thread
from time import monotonic
from typing import cast
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Table, select, text, update
from sqlalchemy.orm import Session
from sqlalchemy.sql import Executable

from ..db.operational_models import (
    OperationalDispatchORM,
    OperationalLockORM,
    OperationalOccurrenceORM,
    OperationalScheduleORM,
    OperationalTickORM,
)
from ..db.orm_models import CalendarEventORM, NotificationORM, TaskORM
from ..models import CalendarEvent, CalendarEventCreate, Notification, NotificationCreate, Task, TaskCreate
from ..storage import NotFoundError, ValidationError
from .concurrency import next_updated_at
from .operational_metrics import metrics
from .payments import EntityType, _memory_lock, payment_total
from .recurrence import CatchUpLimit, RecurrenceError, catch_up, parse_plan

logger = logging.getLogger(__name__)
_state_lock = RLock()
_scheduler = None


class TickRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    as_of: date = Field(default_factory=date.today)
    max_items: int = Field(default=500, ge=1, le=5000, strict=True)
    lookback_days: int = Field(default=366, ge=1, le=3660, strict=True)
    days_ahead: int = Field(default=90, ge=1, le=365, strict=True)
    full_catch_up: bool = Field(default=False, strict=True)


class CalendarScheduleInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    recurrence_rule: str = Field(min_length=1, max_length=1024)
    active: bool = Field(default=True, strict=True)
    full_catch_up: bool = Field(default=True, strict=True)


def ensure_operational_schema(connection):
    """Additive local-create_all hook; the same tables are created by Alembic."""
    for cls in (OperationalLockORM, OperationalScheduleORM, OperationalOccurrenceORM,
                OperationalDispatchORM, OperationalTickORM):
        cast(Table, cls.__table__).create(connection, checkfirst=True)
    _seed_lock(connection)


def _seed_lock(connection):
    # The unique singleton protects bootstrap itself. No check-then-insert race.
    statement: Executable
    if connection.dialect.name == "sqlite":
        from sqlalchemy.dialects.sqlite import insert as sqlite_insert
        statement = sqlite_insert(OperationalLockORM).values(id=1, generation=0).on_conflict_do_nothing(index_elements=["id"])
    elif connection.dialect.name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert as pg_insert
        statement = pg_insert(OperationalLockORM).values(id=1, generation=0).on_conflict_do_nothing(index_elements=["id"])
    else:
        raise ValidationError("Operative Läufe unterstützen SQLite und PostgreSQL.")
    connection.execute(statement)


def _key(*parts):
    return sha256("\0".join(str(part) for part in parts).encode()).hexdigest()


def _dump(row):
    return {column.key: getattr(row, column.key) for column in row.__table__.columns}


class _Transaction:
    def __init__(self, store, db=None):
        self.store, self.db = store, db
        if db is None:
            if not hasattr(store, "_operational_state"):
                store._operational_state = {"schedules": {}, "occurrences": {}, "dispatches": {}, "ticks": []}
            self.memory = store._operational_state

    def schedules(self):
        return list(self.db.scalars(select(OperationalScheduleORM))) if self.db else list(self.memory["schedules"].values())

    def schedule(self, kind, source, anchor, rule, **changes):
        schedule_id = f"{kind}:{source}"
        row = self.db.get(OperationalScheduleORM, schedule_id) if self.db else self.memory["schedules"].get(schedule_id)
        if row is None:
            row = OperationalScheduleORM(id=schedule_id, source_kind=kind, source_id=source,
                anchor_date=anchor, recurrence_rule=rule, active=True, full_catch_up=False)
            if self.db:
                self.db.add(row)
            else:
                self.memory["schedules"][schedule_id] = row
        # Anchor identity is immutable. Moving an existing template or child does
        # not rewrite a series' original dates. A new template creates a new series.
        row.recurrence_rule = rule
        for field, value in changes.items():
            setattr(row, field, value)
        return row

    def occurrences(self, schedule_id):
        if self.db:
            return list(self.db.scalars(select(OperationalOccurrenceORM).where(OperationalOccurrenceORM.schedule_id == schedule_id)))
        return [row for row in self.memory["occurrences"].values() if row.schedule_id == schedule_id]

    def record(self, schedule_id, day, kind, target_id):
        key = _key(schedule_id, day)
        existing = self.db.get(OperationalOccurrenceORM, key) if self.db else self.memory["occurrences"].get(key)
        if existing:
            return existing
        row = OperationalOccurrenceORM(key=key, schedule_id=schedule_id, occurrence_date=day, target_kind=kind, target_id=target_id)
        if self.db:
            self.db.add(row)
            self.db.flush()
        else:
            self.memory["occurrences"][key] = row
        return row

    def create(self, kind, payload):
        classes: dict[str, tuple[type, type[BaseModel]]] = {"task": (TaskORM, Task), "calendar": (CalendarEventORM, CalendarEvent), "notification": (NotificationORM, Notification)}
        if self.db:
            orm, model = classes[kind]
            row = orm(id=str(uuid4()), **payload.model_dump())
            self.db.add(row)
            self.db.flush()
            self.db.refresh(row)
            return model.model_validate(_dump(row))
        return getattr(self.store, {"task": "create_task", "calendar": "create_calendar_event", "notification": "create_notification"}[kind])(payload)

    def notify(self, key, payload, role=None):
        previous = self.db.get(OperationalDispatchORM, key) if self.db else self.memory["dispatches"].get(key)
        if previous:
            # Keep the same notification and reader's status while refreshing the
            # truthful balance. Deletion remains a tombstone, never a resend.
            try:
                item = self.store.get_notification(previous.notification_id)
            except NotFoundError:
                return None
            changes = {"title": payload.title, "content": payload.content, "severity": payload.severity}
            if previous.archived_by_tick and item.status == "archived":
                changes["status"] = "unread"
            previous.archived_by_tick, previous.target_role = False, role
            if any(getattr(item, field) != value for field, value in changes.items()):
                changes["updated_at"] = next_updated_at(item.updated_at)
            if self.db:
                row = self.db.get(NotificationORM, item.id)
                for field, value in changes.items():
                    setattr(row, field, value)
            else:
                self.store.notifications[item.id] = item.model_copy(update=changes)
            return None
        item = self.create("notification", payload)
        row = OperationalDispatchORM(key=key, notification_id=item.id, target_role=role,
            family=payload.notification_type, entity_type=payload.entity_type, entity_id=payload.entity_id, archived_by_tick=False)
        if self.db:
            self.db.add(row)
        else:
            self.memory["dispatches"][key] = row
        return item

    def resolve_alerts(self, budget):
        rows = list(self.db.scalars(select(OperationalDispatchORM))) if self.db else list(self.memory["dispatches"].values())
        for row in rows:
            budget.scan()
            try:
                item = getattr(self.store, {"task": "get_task", "maintenance": "get_maintenance_case", "receivable": "get_receivable", "rent_charge": "get_rent_charge", "contract": "get_contract"}[row.entity_type])(row.entity_id)
                resolved = item.status in {"paid", "completed", "closed", "cancelled", "void", "terminated", "inactive", "archived"}
                if row.entity_type in {"receivable", "rent_charge"}:
                    resolved = resolved or payment_total(row.entity_type, item) <= Decimal(str(item.amount_paid or 0))
            except (NotFoundError, KeyError):
                resolved = True
            if not resolved:
                continue
            try:
                notification = self.store.get_notification(row.notification_id)
            except NotFoundError:
                continue
            if notification.status != "archived":
                row.archived_by_tick = True
                if self.db:
                    target = self.db.get(NotificationORM, notification.id)
                    target.status = "archived"
                    target.updated_at = next_updated_at(notification.updated_at)
                else:
                    self.store.notifications[notification.id] = notification.model_copy(update={"status": "archived", "updated_at": next_updated_at(notification.updated_at)})


@contextmanager
def _transaction(store):
    if hasattr(store, "db"):
        # A fresh Session avoids committing a caller's unrelated pending writes.
        from ..repositories.sql_store import SQLAlchemyStore
        with Session(bind=store.db.get_bind(), expire_on_commit=False) as db:
            with db.begin():
                if db.get_bind().dialect.name == "postgresql":
                    db.execute(text("SET LOCAL lock_timeout = '5s'"))
                    db.execute(text("SET LOCAL statement_timeout = '30s'"))
                _seed_lock(db.connection())
                db.execute(update(OperationalLockORM).where(OperationalLockORM.id == 1)
                           .values(generation=OperationalLockORM.generation + 1))
                yield _Transaction(SQLAlchemyStore(db), db)
        store.db.expire_all()
    else:
        # Memory is scoped to this store. SQL is the restart-persistent backend.
        with _state_lock, _memory_lock:
            state = getattr(store, "_operational_state", None)
            snapshot = {name: deepcopy(getattr(store, name)) for name in ("tasks", "calendar_events", "notifications")}
            previous = deepcopy(state)
            try:
                yield _Transaction(store)
            except Exception:
                for name, rows in snapshot.items():
                    setattr(store, name, rows)
                store._operational_state = previous or {"schedules": {}, "occurrences": {}, "dispatches": {}, "ticks": []}
                raise


def validate_task_recurrence(payload):
    if payload.recurrence_rule:
        if payload.parent_task_id:
            raise ValidationError("Eine Wiederholungsinstanz darf keine eigene Wiederholungsregel besitzen.")
        if not payload.due_date:
            raise ValidationError("Eine wiederkehrende Aufgabe benötigt ein festes Ankerdatum.")
        try:
            parse_plan("validation", payload.due_date, payload.recurrence_rule, legacy_child_count=True)
        except RecurrenceError as exc:
            raise ValidationError(str(exc)) from exc


def configure_calendar(store, event_id, payload):
    with _transaction(store) as tx:
        event = tx.store.get_calendar_event(event_id)
        try:
            parse_plan(event_id, event.event_date, payload.recurrence_rule)
        except RecurrenceError as exc:
            raise ValidationError(str(exc)) from exc
        row = tx.schedule("calendar", event_id, event.event_date, payload.recurrence_rule,
                          active=payload.active, full_catch_up=payload.full_catch_up)
        tx.record(row.id, row.anchor_date, "calendar", event_id)
        return _schedule_view(row)


def _schedule_view(row):
    return {field: getattr(row, field) for field in ("id", "source_kind", "source_id", "anchor_date", "recurrence_rule", "active", "full_catch_up")}


def list_schedules(store, kind=None):
    if hasattr(store, "db"):
        rows = store.db.scalars(select(OperationalScheduleORM)).all()
    else:
        rows = getattr(store, "_operational_state", {}).get("schedules", {}).values()
    return [_schedule_view(row) for row in rows if kind is None or row.source_kind == kind]


class _Budget:
    def __init__(self, limit):
        self.limit, self.used = limit, 0
        self.scanned, self.deadline = 0, monotonic() + 30

    def scan(self):
        self.scanned += 1
        if self.scanned > max(10000, self.limit * 20) or monotonic() > self.deadline:
            raise CatchUpLimit("Der Lauf überschreitet das Prüf- oder Zeitbudget. Zeitraum oder aktive Regeln eingrenzen.")

    def take(self):
        self.scan()
        self.used += 1
        if self.used > self.limit:
            raise CatchUpLimit("Der Lauf überschreitet die maximale Anzahl. Zeitraum eingrenzen oder Limit erhöhen.")


def _recurring(tx, request, budget, kinds):
    created_tasks, created_events, warnings = [], [], []
    tasks = tx.store.list_tasks() if "tasks" in kinds else []
    if "tasks" in kinds:
        current = {task.id: task for task in tasks}
        for previous in tx.schedules():
            if previous.source_kind == "task":
                source = current.get(previous.source_id)
                previous.active = bool(source and source.recurrence_rule and source.status not in {"cancelled", "archived"})
    for template in sorted((task for task in tasks if task.recurrence_rule and not task.parent_task_id), key=lambda task: task.id):
        budget.scan()
        try:
            validate_task_recurrence(template)
        except ValidationError as exc:
            warnings.append({"source_kind": "task", "source_id": template.id, "error": str(exc)})
            continue
        row = tx.schedule("task", template.id, template.due_date, template.recurrence_rule,
                          active=template.status not in {"cancelled", "archived"})
        if template.status in {"cancelled", "archived"}:
            continue
        # Adopt legacy children once; subsequent moves/deletes cannot erase keys.
        records = tx.occurrences(row.id)
        tracked = {record.target_id for record in records}
        children = [child for child in tasks if child.parent_task_id == template.id or child.id in tracked]
        for child in children:
            if child.id not in tracked and child.due_date:
                tx.record(row.id, child.due_date, "task", child.id)
        if not request.full_catch_up and any(child.status in {"open", "in_progress"} for child in children):
            continue
        plan = parse_plan(row.id, row.anchor_date, row.recurrence_rule, legacy_child_count=True)
        records = tx.occurrences(row.id)
        recorded = [(row.id, row.anchor_date), *((row.id, record.occurrence_date) for record in records)]
        days = catch_up(plan, request.as_of, recorded=recorded,
                        since=max(date.min, request.as_of - timedelta(days=min(request.lookback_days, request.as_of.toordinal() - 1))),
                        limit=request.max_items)
        for occurrence in days if request.full_catch_up else days[:1]:
            day = occurrence.occurrence_date
            budget.take()
            child = tx.create("task", TaskCreate(**{**template.model_dump(include=set(TaskCreate.model_fields)),
                "due_date": day, "recurrence_rule": None, "parent_task_id": template.id, "status": "open"}))
            tx.record(row.id, day, "task", child.id)
            created_tasks.append(child)
    if "calendar" in kinds:
        for row in sorted(tx.schedules(), key=lambda item: item.id):
            budget.scan()
            if row.source_kind != "calendar" or not row.active:
                continue
            try:
                template = tx.store.get_calendar_event(row.source_id)
            except NotFoundError:
                continue
            plan = parse_plan(row.id, row.anchor_date, row.recurrence_rule)
            recorded = [(row.id, record.occurrence_date) for record in tx.occurrences(row.id)]
            days = catch_up(plan, request.as_of, recorded=recorded,
                since=date.fromordinal(max(1, request.as_of.toordinal() - request.lookback_days)), limit=request.max_items)
            for occurrence in days if row.full_catch_up else days[:1]:
                day = occurrence.occurrence_date
                budget.take()
                event = tx.create("calendar", CalendarEventCreate(**{**template.model_dump(include=set(CalendarEventCreate.model_fields)), "event_date": day}))
                tx.record(row.id, day, "calendar", event.id)
                created_events.append(event)
    return created_tasks, created_events, warnings


def _open_items(store):
    for kind, values in (("receivable", store.list_receivables()), ("rent_charge", store.list_rent_charges())):
        for item in values:
            if item.status in {"paid", "cancelled", "void"}:
                continue
            remaining = (payment_total(cast(EntityType, kind), item) - Decimal(str(item.amount_paid or 0))).quantize(Decimal("0.01"))
            if remaining > 0:
                yield kind, item, remaining


def validate_escalation(rule):
    allowed = {"task": {"due_date"}, "maintenance": {"due_date", "appointment_at"}, "receivable": {"due_date"}, "rent_charge": {"due_date"}}
    if rule.entity_type not in allowed or rule.condition_field not in allowed[rule.entity_type]:
        raise ValidationError("Nicht unterstützte Entität oder Frist für die Eskalation.")
    if rule.action != "notify":
        raise ValidationError("Unterstützte Aktion: notify. Automatische Zuweisung oder Prioritätsänderung ist nicht aktiviert.")
    if rule.target_role not in {None, "", "eigentuemer", "verwalter", "buchhaltung", "techniker", "readonly"}:
        raise ValidationError("Ungültige Zielrolle.")
    if not 0 <= rule.days_overdue <= 3660 or rule.notification_severity not in {"info", "warning", "critical"}:
        raise ValidationError("Ungültige Frist oder Benachrichtigungsschwere.")


def _tenant_name(store, contract_id):
    try:
        return store.get_tenant(store.get_contract(contract_id).tenant_id).full_name
    except NotFoundError:
        return "Unbekannt"


def _due_date(kind, item, field="due_date"):
    if kind == "rent_charge":
        # Same contractual day used by the rental ledger and open-item reports.
        from .rent_ledger import month_date
        return month_date(item.month).replace(day=3)
    value = getattr(item, field, None)
    return value.date() if isinstance(value, datetime) else value


def _calendar_deadlines(tx, request, budget):
    """Keep dated local milestones; deleting a projected entry is respected."""
    created = []
    lower = date.fromordinal(max(1, request.as_of.toordinal() - request.lookback_days))
    upper = date.fromordinal(min(date.max.toordinal(), request.as_of.toordinal() + request.days_ahead))
    sources = (("task", tx.store.list_tasks(), "due_date"),
               ("maintenance", tx.store.list_maintenance_cases(), "due_date"),
               ("maintenance", tx.store.list_maintenance_cases(), "appointment_at"))
    for kind, items, field in sources:
        for item in items:
            budget.scan()
            day = _due_date(kind, item, field)
            if item.status not in {"open", "in_progress"} or day is None or not lower <= day <= upper:
                continue
            schedule_id = f"{kind}-{field}:{item.id}"
            if any(row.occurrence_date == day for row in tx.occurrences(schedule_id)):
                continue
            budget.take()
            appointment = field == "appointment_at"
            source = "Aufgabe" if kind == "task" else "Instandhaltung"
            event = tx.create("calendar", CalendarEventCreate(title=f"{source}: {item.title}",
                event_type="maintenance" if appointment else "deadline", event_date=day,
                event_time=item.appointment_at.strftime("%H:%M") if appointment else None,
                property_id=item.property_id, unit_id=item.unit_id,
                description=f"Automatisch abgeleiteter Termin. Quelle: {kind}/{item.id}. Friststand bei Erstellung: {day}."))
            tx.record(schedule_id, day, "calendar", event.id)
            created.append(event)
    return created


def _notifications(tx, request, budget, kinds):
    generated, rules_checked, warnings, events = [], 0, [], []
    def notify(key, payload, role=None):
        result = tx.notify(key, payload, role)
        if result:
            budget.take()
            generated.append(result)
    balances = list(_open_items(tx.store)) if kinds & {"overdue", "escalation"} else []
    if "overdue" in kinds:
        for kind, item, remaining in balances:
            budget.scan()
            due = _due_date(kind, item)
            if due < request.as_of:
                notify(_key("overdue", kind, item.id, due), NotificationCreate(
                    notification_type="overdue_payment", title=f"Überfällige Zahlung: {_tenant_name(tx.store, item.contract_id)}",
                    content=f"Offener Restbetrag: {remaining:.2f} EUR. Fällig am {due}.",
                    severity="warning", entity_type=kind, entity_id=item.id))
    if "due_tasks" in kinds:
        for task in tx.store.list_tasks():
            budget.scan()
            if task.status in {"open", "in_progress"} and task.due_date and task.due_date <= request.as_of:
                notify(_key("due_task", task.id, task.due_date), NotificationCreate(notification_type="task_due",
                    title=f"Aufgabe fällig: {task.title}", content=f"Aufgabe '{task.title}' ist fällig seit {task.due_date}.",
                    severity="warning" if task.due_date < request.as_of else "info", entity_type="task", entity_id=task.id))
    if "contracts" in kinds:
        horizon = date.fromordinal(min(date.max.toordinal(), request.as_of.toordinal() + request.days_ahead))
        for contract in tx.store.list_contracts():
            budget.scan()
            if contract.status == "active" and contract.end_date and request.as_of <= contract.end_date <= horizon:
                notify(_key("contract_expiry", contract.id, contract.end_date), NotificationCreate(notification_type="contract_expiry",
                    title=f"Vertragsende: {contract.contract_number}", content=f"Vertrag {contract.contract_number} endet am {contract.end_date}.",
                    entity_type="contract", entity_id=contract.id))
                schedule_id = f"contract-deadline:{contract.id}"
                if not tx.occurrences(schedule_id) or not any(r.occurrence_date == contract.end_date for r in tx.occurrences(schedule_id)):
                    budget.take()
                    event = tx.create("calendar", CalendarEventCreate(title=f"Vertragsende: {contract.contract_number}",
                        event_type="deadline", event_date=contract.end_date, property_id=contract.property_id, unit_id=contract.unit_id))
                    tx.record(schedule_id, contract.end_date, "calendar", event.id)
                    events.append(event)
    if "escalation" in kinds:
        for rule in tx.store.list_escalation_rules():
            budget.scan()
            if not rule.is_active:
                continue
            rules_checked += 1
            try:
                validate_escalation(rule)
            except ValidationError as exc:
                warnings.append({"source_kind": "escalation_rule", "source_id": rule.id, "error": str(exc)})
                continue
            cutoff = date.fromordinal(max(1, request.as_of.toordinal() - rule.days_overdue))
            if rule.entity_type in {"task", "maintenance"}:
                source = tx.store.list_tasks() if rule.entity_type == "task" else tx.store.list_maintenance_cases()
                values = [(rule.entity_type, item, None) for item in source if item.status in {"open", "in_progress"}]
            else:
                values = [value for value in balances if value[0] == rule.entity_type]
            for kind, item, remaining in values:
                budget.scan()
                due = _due_date(kind, item, rule.condition_field)
                if due and due <= cutoff:
                    title = getattr(item, "title", "Überfällige Forderung")
                    amount = f" Offener Restbetrag: {remaining:.2f} EUR." if remaining is not None else ""
                    notify(_key("escalation", rule.id, kind, item.id, due), NotificationCreate(notification_type="escalation",
                        title=f"Eskalation: {title}", content=f"Frist {due} ist überschritten. Regel: {rule.name}.{amount}",
                        severity=rule.notification_severity, entity_type=kind, entity_id=item.id), rule.target_role or None)
    return generated, rules_checked, warnings, events


def operational_tick(store, request=None, *, kinds=None):
    request = request or TickRequest()
    kinds = set(kinds or {"tasks", "calendar", "overdue", "contracts", "due_tasks", "escalation"})
    budget = _Budget(request.max_items)
    with metrics.operational_tick(), _transaction(store) as tx:
        tx.resolve_alerts(budget)
        tasks, events, warnings = _recurring(tx, request, budget, kinds)
        if "calendar" in kinds:
            events.extend(_calendar_deadlines(tx, request, budget))
        notifications, rules_checked, more_warnings, deadline_events = _notifications(tx, request, budget, kinds)
        events.extend(deadline_events)
        result = {"as_of": request.as_of.isoformat(), "tasks_created": len(tasks), "calendar_events_created": len(events),
                  "rules_checked": rules_checked, "notifications_generated": len(notifications),
                  "notification_ids": [item.id for item in notifications], "warnings": warnings + more_warnings,
                  "task_ids": [item.id for item in tasks], "calendar_event_ids": [item.id for item in events],
                  "lookback_days": request.lookback_days, "max_items": request.max_items,
                  "full_catch_up": request.full_catch_up}
        if tx.db:
            tx.db.add(OperationalTickORM(id=str(uuid4()), as_of=request.as_of, result=result))
        else:
            tx.memory["ticks"].append(result)
        return result


def generate_tasks(store, as_of, *, full_catch_up=False, max_items=500, lookback_days=366):
    result = operational_tick(store, TickRequest(as_of=as_of, full_catch_up=full_catch_up,
        max_items=max_items, lookback_days=lookback_days), kinds={"tasks"})
    return [store.get_task(item_id) for item_id in result["task_ids"]]


def generate_notifications(store, kind, as_of, *, days_ahead=90):
    result = operational_tick(store, TickRequest(as_of=as_of, days_ahead=days_ahead), kinds={kind})
    return [store.get_notification(item_id) for item_id in result["notification_ids"]]


def notification_visible(store, item_id, role):
    if hasattr(store, "db"):
        row = store.db.scalar(select(OperationalDispatchORM).where(OperationalDispatchORM.notification_id == item_id))
    else:
        row = next((item for item in getattr(store, "_operational_state", {}).get("dispatches", {}).values() if item.notification_id == item_id), None)
    return row is None or not row.target_role or role == "eigentuemer" or row.target_role == role


def recent_ticks(store, limit=20):
    if hasattr(store, "db"):
        rows = store.db.scalars(select(OperationalTickORM).order_by(OperationalTickORM.completed_at.desc(), OperationalTickORM.id).limit(limit))
        return [row.result for row in rows]
    return list(reversed(getattr(store, "_operational_state", {}).get("ticks", [])[-limit:]))


def scheduler_status():
    return {"automatic_enabled": bool(_scheduler and _scheduler.enabled),
            "automatic_running": bool(_scheduler and _scheduler._thread and _scheduler._thread.is_alive()),
            "interval_seconds": _scheduler.interval_seconds if _scheduler else None}


class OperationalScheduler:
    """An explicitly enabled local worker; lifecycle is owned by app lifespan."""
    def __init__(self, store, *, enabled=False, interval_seconds=300, max_items=500, lookback_days=366):
        if not 10 <= interval_seconds <= 86400:
            raise ValueError("Scheduler interval must be between 10 and 86400 seconds")
        self.store, self.enabled, self.interval_seconds = store, enabled, interval_seconds
        self.parameters = {"max_items": max_items, "lookback_days": lookback_days}
        TickRequest(**self.parameters)
        self._stop = Event()
        self._thread = None

    def start(self):
        global _scheduler
        _scheduler = self
        if not self.enabled or self._thread is not None:
            return
        self._stop.clear()
        self._thread = Thread(target=self._run, name="immo-operational-scheduler", daemon=True)
        self._thread.start()

    def _run(self):
        try:
            while not self._stop.is_set():
                try:
                    operational_tick(self.store, TickRequest(**self.parameters))
                except Exception:
                    logger.exception("Operativer Lauf fehlgeschlagen; kein erfolgreicher Lauf protokolliert")
                if self._stop.wait(self.interval_seconds):
                    break
        finally:
            remove = getattr(getattr(self.store, "db", None), "remove", None)
            if remove:
                remove()

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=35)
            if self._thread.is_alive():
                raise RuntimeError("Operational scheduler did not stop within thirty-five seconds")
            self._thread = None
