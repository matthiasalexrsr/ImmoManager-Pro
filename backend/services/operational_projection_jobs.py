"""Bounded persistent adapters for every remaining legacy automatic family."""

from datetime import date
from decimal import Decimal
from heapq import nsmallest
from time import monotonic
from typing import Any

from sqlalchemy import func, select

from ..db.operational_models import OperationalDispatchORM, OperationalOccurrenceORM
from ..db.orm_models import ContractORM, EscalationRuleORM, MaintenanceCaseORM, ReceivableORM, RentChargeORM, TaskORM
from ..models import CalendarEventCreate, NotificationCreate
from ..storage import NotFoundError
from .concurrency import next_updated_at
from .operational_schedule import _due_date, _key, validate_escalation
from .payments import payment_total

MODELS: dict[str, Any] = {"task_deadline": TaskORM, "maintenance_deadline": MaintenanceCaseORM,
    "maintenance_appointment": MaintenanceCaseORM, "due_task": TaskORM, "contract_expiry": ContractORM,
    "escalation": EscalationRuleORM, "alert_resolution": OperationalDispatchORM}
COLLECTIONS = {"task_deadline": "tasks", "maintenance_deadline": "maintenance_cases", "maintenance_appointment": "maintenance_cases",
               "due_task": "tasks", "contract_expiry": "contracts", "escalation": "escalation_rules"}
GETTERS = {"task_deadline": "task", "maintenance_deadline": "maintenance_case", "maintenance_appointment": "maintenance_case",
           "due_task": "task", "contract_expiry": "contract", "escalation": "escalation_rule"}


def identifier_column(family):
    return MODELS[family].key if family == "alert_resolution" else MODELS[family].id


def source(unit, family, identifier, *, lock=False):
    if unit.db is not None and lock:
        unit.db.scalar(select(MODELS[family]).where(identifier_column(family) == identifier)
            .with_for_update().execution_options(populate_existing=True))
    if family == "alert_resolution":
        return unit.db.get(OperationalDispatchORM, identifier) if unit.db is not None else unit.memory["dispatches"].get(identifier)
    return getattr(unit.store, "get_" + GETTERS[family])(identifier)


def query(family, parameters):
    model, point = MODELS[family], date.fromisoformat(parameters["as_of"])
    lower = date.fromordinal(max(1, point.toordinal() - parameters["lookback_days"]))
    upper = date.fromordinal(min(date.max.toordinal(), point.toordinal() + parameters["days_ahead"]))
    value = select(identifier_column(family))
    if family == "escalation":
        return value.where(model.is_active.is_(True))
    if family == "alert_resolution":
        return value.where(model.archived_by_tick.is_(False))
    if family == "contract_expiry":
        return value.where(model.status == "active", model.end_date >= point, model.end_date <= upper)
    value = value.where(model.status.in_(("open", "in_progress")))
    if family == "due_task":
        return value.where(model.due_date <= point)
    field = func.date(model.appointment_at) if family == "maintenance_appointment" else model.due_date
    return value.where(field >= lower, field <= upper)


def eligible(family, value, parameters):
    point = date.fromisoformat(parameters["as_of"])
    lower = date.fromordinal(max(1, point.toordinal() - parameters["lookback_days"]))
    upper = date.fromordinal(min(date.max.toordinal(), point.toordinal() + parameters["days_ahead"]))
    if value is None:
        return False
    if family == "escalation":
        return value.is_active
    if family == "alert_resolution":
        return not value.archived_by_tick
    if family == "contract_expiry":
        return value.status == "active" and value.end_date is not None and point <= value.end_date <= upper
    day = _due_date("task" if family in {"task_deadline", "due_task"} else "maintenance", value,
                    "appointment_at" if family == "maintenance_appointment" else "due_date")
    return value.status in {"open", "in_progress"} and day is not None and (day <= point if family == "due_task" else lower <= day <= upper)


def memory_sources(unit, family, parameters):
    values = unit.memory["dispatches"].values() if family == "alert_resolution" else getattr(unit.store, COLLECTIONS[family]).values()
    return (value.key if family == "alert_resolution" else value.id for value in values if eligible(family, value, parameters))


def _occurrence(unit, schedule, day):
    key = _key(schedule, day)
    return unit.db.get(OperationalOccurrenceORM, key) if unit.db is not None else unit.memory["occurrences"].get(key)


def _event(unit, schedule, day, payload):
    previous = _occurrence(unit, schedule, day)
    if previous:
        return previous.target_id, False
    event = unit.create("calendar", payload)
    unit.record(schedule, day, "calendar", event.id)
    return event.id, True


def _resolved(unit, row, *, lock=False):
    if row is None:
        return False
    kinds = {"task": "task", "maintenance": "maintenance_case", "receivable": "receivable", "rent_charge": "rent_charge", "contract": "contract"}
    try:
        if lock and unit.db is not None and row.entity_type in kinds:
            models: dict[str, Any] = {"task": TaskORM, "maintenance": MaintenanceCaseORM, "receivable": ReceivableORM,
                      "rent_charge": RentChargeORM, "contract": ContractORM}
            model = models[row.entity_type]
            unit.db.scalar(select(model).where(model.id == row.entity_id).with_for_update().execution_options(populate_existing=True))
        value = getattr(unit.store, "get_" + kinds[row.entity_type])(row.entity_id)
        resolved = value.status in {"paid", "completed", "closed", "cancelled", "void", "terminated", "inactive", "archived"}
        if row.entity_type in {"receivable", "rent_charge"}:
            resolved = resolved or payment_total(row.entity_type, value) <= Decimal(str(value.amount_paid or 0))
    except (NotFoundError, KeyError):
        resolved = True
    return resolved


def _resolution(unit, row):
    if not _resolved(unit, row, lock=True):
        return False
    try:
        if unit.db is not None:
            from ..db.orm_models import NotificationORM
            unit.db.scalar(select(NotificationORM).where(NotificationORM.id == row.notification_id)
                .with_for_update().execution_options(populate_existing=True))
        notice = unit.store.get_notification(row.notification_id)
    except NotFoundError:
        return False
    if notice.status == "archived":
        return False
    unit.journal_touch("dispatches", row.key)
    row.archived_by_tick = True
    if unit.db is not None:
        from ..db.orm_models import NotificationORM
        target = unit.db.get(NotificationORM, notice.id)
        target.status, target.updated_at = "archived", next_updated_at(notice.updated_at)
    else:
        unit.touch("notifications", notice.id)
        unit.store.notifications[notice.id] = notice.model_copy(update={"status": "archived", "updated_at": next_updated_at(notice.updated_at)})
    return True


def _notice_needed(unit, key, title, content, severity="info"):
    previous = unit.db.get(OperationalDispatchORM, key) if unit.db is not None else unit.memory["dispatches"].get(key)
    if previous is None:
        return True
    try:
        notice = unit.store.get_notification(previous.notification_id)
    except NotFoundError:
        return False  # Deliberate deletion remains a tombstone.
    return (notice.title, notice.content, notice.severity) != (title, content, severity) or previous.archived_by_tick and notice.status == "archived"


def needed(unit, job, family, value):
    """Unchanged derived effects do not create another retained work row."""
    if family == "escalation":
        return True  # One resumable rule scan, never one record per unchanged target.
    if family == "alert_resolution":
        if not _resolved(unit, value):
            return False
        try:
            return unit.store.get_notification(value.notification_id).status != "archived"
        except NotFoundError:
            return False
    if family == "due_task":
        point = date.fromisoformat(job.parameters["as_of"])
        return _notice_needed(unit, _key("due_task", value.id, value.due_date), f"Aufgabe fällig: {value.title}",
            f"Aufgabe '{value.title}' ist fällig seit {value.due_date}.", "warning" if value.due_date < point else "info")
    if family == "contract_expiry":
        day = value.end_date
        return not _occurrence(unit, "contract-deadline:" + value.id, day) or _notice_needed(unit,
            _key("contract_expiry", value.id, day), f"Vertragsende: {value.contract_number}", f"Vertrag {value.contract_number} endet am {day}.")
    kind = "task" if family == "task_deadline" else "maintenance"
    field = "appointment_at" if family == "maintenance_appointment" else "due_date"
    return _occurrence(unit, f"{kind}-{field}:" + value.id, _due_date(kind, value, field)) is None


def _escalation(unit, rule, item, point, width, deadline):
    validate_escalation(rule)
    state = dict(item.result)
    models: dict[str, Any] = {"task": TaskORM, "maintenance": MaintenanceCaseORM, "receivable": ReceivableORM, "rent_charge": RentChargeORM}
    collections = {"task": "tasks", "maintenance": "maintenance_cases", "receivable": "receivables", "rent_charge": "rent_charges"}
    getters = {"task": "task", "maintenance": "maintenance_case", "receivable": "receivable", "rent_charge": "rent_charge"}
    model = models[rule.entity_type]
    after = state.get("cursor")
    if "upper" not in state:
        state["upper"] = (unit.db.scalar(select(model.id).order_by(model.id.desc()).limit(1)) if unit.db is not None
                          else max(getattr(unit.store, collections[rule.entity_type]), default=None))
    if state["upper"] is None:
        return True, "skipped", state
    if unit.db is not None:
        selection = select(model.id).where(model.id <= state["upper"])
        if after is not None:
            selection = selection.where(model.id > after)
        identifiers = list(unit.db.scalars(selection.order_by(model.id).limit(width + 1)))
    else:
        identifiers = nsmallest(width + 1, (key for key in getattr(unit.store, collections[rule.entity_type])
            if key <= state["upper"] and (after is None or key > after)))
    cutoff = date.fromordinal(max(1, point.toordinal() - rule.days_overdue))
    count = 0
    for identifier in identifiers[:width]:
        if count and monotonic() >= deadline:
            break
        if unit.db is not None:
            unit.db.scalar(select(model).where(model.id == identifier).with_for_update().execution_options(populate_existing=True))
        try:
            value = getattr(unit.store, "get_" + getters[rule.entity_type])(identifier)
        except NotFoundError:
            state["cursor"], count = identifier, count + 1
            continue
        amount = None
        eligible_source = value.status in {"open", "in_progress"}
        if rule.entity_type in {"receivable", "rent_charge"}:
            amount = payment_total(rule.entity_type, value) - Decimal(str(value.amount_paid or 0))
            eligible_source = value.status not in {"paid", "cancelled", "void"} and amount > 0
        due = _due_date(rule.entity_type, value, rule.condition_field)
        if eligible_source and due and due <= cutoff:
            title = getattr(value, "title", "Überfällige Forderung")
            suffix = f" Offener Restbetrag: {amount:.2f} EUR." if amount is not None else ""
            notice = unit.notify(_key("escalation", rule.id, rule.entity_type, value.id, due),
                NotificationCreate(notification_type="escalation", title=f"Eskalation: {title}",
                    content=f"Frist {due} ist überschritten. Regel: {rule.name}.{suffix}", severity=rule.notification_severity,
                    entity_type=rule.entity_type, entity_id=value.id), rule.target_role or None)
            state["created_count"] = state.get("created_count", 0) + int(notice is not None)
        state["cursor"], count = identifier, count + 1
    done = count == len(identifiers) or count == width and len(identifiers) <= width
    return done, "created" if state.get("created_count") else "skipped", state


def apply(unit, job, lane, item, *, width, deadline):
    from .operational_recurrence_jobs import revision
    try:
        value = source(unit, lane.family, item.source_id, lock=True)
    except NotFoundError:
        return True, "skipped", {}
    if not eligible(lane.family, value, job.parameters):
        return True, "skipped", {}
    point = date.fromisoformat(job.parameters["as_of"])
    if lane.family == "escalation":
        if revision(value) != item.planned_revision:
            raise ValueError("escalation_rule_changed")
        return _escalation(unit, value, item, point, width, deadline)
    if lane.family == "alert_resolution":
        return True, "updated" if _resolution(unit, value) else "skipped", {}
    if lane.family == "contract_expiry":
        day = value.end_date
        key = _key("contract_expiry", value.id, day)
        notice = unit.notify(key, NotificationCreate(notification_type="contract_expiry", title=f"Vertragsende: {value.contract_number}",
            content=f"Vertrag {value.contract_number} endet am {day}.", entity_type="contract", entity_id=value.id))
        target, created = _event(unit, "contract-deadline:" + value.id, day, CalendarEventCreate(
            title=f"Vertragsende: {value.contract_number}", event_type="deadline", event_date=day,
            property_id=value.property_id, unit_id=value.unit_id))
        return True, "created" if created or notice else "skipped", {"executed_revision": revision(value),
            "target_id": target, "effect_key": _key("contract-deadline:" + value.id, day)}
    if lane.family == "due_task":
        key = _key("due_task", value.id, value.due_date)
        notice = unit.notify(key, NotificationCreate(notification_type="task_due", title=f"Aufgabe fällig: {value.title}",
            content=f"Aufgabe '{value.title}' ist fällig seit {value.due_date}.",
            severity="warning" if value.due_date < point else "info", entity_type="task", entity_id=value.id))
        return True, "created" if notice else "skipped", {}
    kind = "task" if lane.family == "task_deadline" else "maintenance"
    appointment = lane.family == "maintenance_appointment"
    field = "appointment_at" if appointment else "due_date"
    day = _due_date(kind, value, field)
    name = "Aufgabe" if kind == "task" else "Instandhaltung"
    _, created = _event(unit, f"{kind}-{field}:" + value.id, day, CalendarEventCreate(title=f"{name}: {value.title}",
        event_type="maintenance" if appointment else "deadline", event_date=day,
        event_time=value.appointment_at.strftime("%H:%M") if appointment else None, property_id=value.property_id,
        unit_id=value.unit_id, description=f"Automatisch abgeleiteter Termin. Quelle: {kind}/{value.id}. Friststand bei Erstellung: {day}."))
    return True, "created" if created else "skipped", {}
