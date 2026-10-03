"""Bounded recurrence packets, sharing immutable legacy occurrence identities."""

from datetime import date
from heapq import nsmallest
from time import monotonic

from sqlalchemy import or_, select

from ..db.operational_job_models import OperationalJobORM, OperationalWorkItemORM
from ..db.operational_models import OperationalOccurrenceORM, OperationalScheduleORM
from ..db.orm_models import CalendarEventORM, TaskORM
from ..models import CalendarEventCreate, TaskCreate
from ..storage import NotFoundError
from .operational_schedule import _key, validate_task_recurrence
from .recurrence import _seek, occurrence_at, parse_plan

RECURRENCE_FAMILIES = {"recurring_task", "recurring_calendar"}


def previous_progress(unit, job, family, value):
    """Reuse only a completed full-history proof for the unchanged series.

    Version 2 used a lookback even with full_catch_up, so it is deliberately
    excluded. A later as_of must never hide holes in an earlier requested run.
    """
    full = job.parameters.get("full_catch_up", False) if family == "recurring_task" else value.full_catch_up
    if not full:
        return {}
    action, fingerprint = family + ":" + value.id, revision(value)
    if unit.db is not None:
        query = select(OperationalWorkItemORM).join(OperationalJobORM).where(
            OperationalWorkItemORM.action_key == action, OperationalWorkItemORM.planned_revision == fingerprint,
            OperationalWorkItemORM.state == "done", OperationalWorkItemORM.job_id != job.id,
            OperationalJobORM.parameters["semantics_version"].as_integer() >= 3,
            OperationalJobORM.parameters["as_of"].as_string() <= job.parameters["as_of"])
        if family == "recurring_task":
            query = query.where(OperationalJobORM.parameters["full_catch_up"].as_boolean().is_(True))
        previous = unit.db.scalar(query.order_by(OperationalWorkItemORM.created_at.desc(), OperationalWorkItemORM.id.desc()).limit(1))
    else:
        candidates = []
        for work in unit.store.__dict__.get(OperationalWorkItemORM.__tablename__, {}).values():
            if work.action_key != action or work.planned_revision != fingerprint or work.state != "done" or work.job_id == job.id:
                continue
            parameters = unit.row(OperationalJobORM, work.job_id).parameters
            if parameters["semantics_version"] >= 3 and parameters["as_of"] <= job.parameters["as_of"] and (family != "recurring_task" or parameters.get("full_catch_up")):
                candidates.append(work)
        previous = max(candidates, key=lambda work: (work.created_at, work.id), default=None)
    if previous is None or "next_index" not in previous.result:
        return {}
    return {"next_index": previous.result["next_index"], "adoption_done": True, "created_count": 0}


def needed(unit, job, family, value):
    anchor = value.due_date if family == "recurring_task" else value.anchor_date
    if anchor is not None and anchor > date.fromisoformat(job.parameters["as_of"]):
        return False
    progress = previous_progress(unit, job, family, value)
    if not progress:
        return True
    task = family == "recurring_task"
    plan = parse_plan("task:" + value.id if task else value.id, value.due_date if task else value.anchor_date,
                      value.recurrence_rule, legacy_child_count=task)
    day = occurrence_at(plan, progress["next_index"])
    return day is not None and day <= date.fromisoformat(job.parameters["as_of"])


def source(unit, family, identifier):
    if family == "recurring_task":
        return unit.store.get_task(identifier)
    return unit.db.get(OperationalScheduleORM, identifier) if unit.db is not None else unit.memory["schedules"].get(identifier)


def revision(value):
    from .contract_lifecycle import digest
    return digest(value.model_dump(mode="json") if hasattr(value, "model_dump") else
                  {column.key: getattr(value, column.key) for column in value.__table__.columns})


def _record(unit, schedule, day):
    key = _key(schedule, day)
    return unit.db.get(OperationalOccurrenceORM, key) if unit.db is not None else unit.memory["occurrences"].get(key)


def _adopt(unit, template, schedule, state, width):
    """Legacy child discovery has its own committed cursor, including tombstones."""
    if state.get("adoption_done"):
        return True
    after = state.get("adoption_cursor")
    if unit.db is not None:
        query = select(TaskORM).where(TaskORM.parent_task_id == template.id)
        if after is not None:
            query = query.where(TaskORM.id > after)
        children = list(unit.db.scalars(query.order_by(TaskORM.id).limit(width + 1)))
    else:
        children = nsmallest(width + 1, (row for row in unit.store.tasks.values()
            if row.parent_task_id == template.id and (after is None or row.id > after)), key=lambda row: row.id)
    for child in children[:width]:
        tracked = (unit.db.scalar(select(OperationalOccurrenceORM.key).where(
            OperationalOccurrenceORM.schedule_id == schedule.id, OperationalOccurrenceORM.target_id == child.id).limit(1))
            if unit.db is not None else next((row.key for row in unit.memory["occurrences"].values()
                if row.schedule_id == schedule.id and row.target_id == child.id), None))
        if tracked is None and child.due_date is not None:
            unit.record(schedule.id, child.due_date, "task", child.id)
        state["adoption_cursor"] = child.id
    state["adoption_done"] = len(children) <= width
    return state["adoption_done"]


def _open_child(unit, template, schedule):
    if unit.db is not None:
        tracked = select(OperationalOccurrenceORM.target_id).where(OperationalOccurrenceORM.schedule_id == schedule.id)
        return unit.db.scalar(select(TaskORM.id).where(TaskORM.status.in_(("open", "in_progress")),
            or_(TaskORM.parent_task_id == template.id, TaskORM.id.in_(tracked))).limit(1)) is not None
    tracked_ids = {row.target_id for row in unit.memory["occurrences"].values() if row.schedule_id == schedule.id}
    return any(row.status in {"open", "in_progress"} and (row.parent_task_id == template.id or row.id in tracked_ids)
               for row in unit.store.tasks.values())


def _untracked_child(unit, template, schedule, day):
    """New legacy children can arrive after a completed adoption scan."""
    if unit.db is not None:
        tracked = select(OperationalOccurrenceORM.target_id).where(OperationalOccurrenceORM.schedule_id == schedule.id)
        return unit.db.scalar(select(TaskORM.id).where(TaskORM.parent_task_id == template.id,
            TaskORM.due_date == day, TaskORM.id.not_in(tracked)).order_by(TaskORM.id).limit(1))
    tracked_ids = {row.target_id for row in unit.memory["occurrences"].values() if row.schedule_id == schedule.id}
    return next((row.id for row in unit.store.tasks.values() if row.parent_task_id == template.id
                 and row.due_date == day and row.id not in tracked_ids), None)


def apply(unit, job, lane, item, *, width, deadline):
    """Return completion, source outcome and O(1) resumable progress per series."""
    state = dict(item.result)
    state.setdefault("created_count", 0)
    task = lane.family == "recurring_task"
    try:
        if unit.db is not None:
            model = TaskORM if task else OperationalScheduleORM
            unit.db.scalar(select(model).where(model.id == item.source_id).with_for_update().execution_options(populate_existing=True))
        value = source(unit, lane.family, item.source_id)
        if task:
            if value.status in {"cancelled", "archived"} or not value.recurrence_rule or value.parent_task_id:
                return True, "skipped", state
            validate_task_recurrence(value)
            unit.journal_touch("schedules", "task:" + value.id)
            schedule = unit.schedule("task", value.id, value.due_date, value.recurrence_rule, active=True)
            template = value
        else:
            schedule = value
            if schedule is None or not schedule.active:
                return True, "skipped", state
            if unit.db is not None:
                unit.db.scalar(select(CalendarEventORM).where(CalendarEventORM.id == schedule.source_id).with_for_update().execution_options(populate_existing=True))
            template = unit.store.get_calendar_event(schedule.source_id)
    except NotFoundError:
        return True, "skipped", state
    fingerprint = revision(value)
    if fingerprint != item.planned_revision:
        # A reviewed series is not silently rewritten while its work is pending.
        raise ValueError("recurrence_source_changed")
    if not item.result:
        state.update(previous_progress(unit, job, lane.family, value))
    plan = parse_plan(schedule.id, schedule.anchor_date, schedule.recurrence_rule, legacy_child_count=task)
    if task and not _adopt(unit, template, schedule, state, width):
        return False, "skipped", state
    full = job.parameters.get("full_catch_up", False) if task else schedule.full_catch_up
    if task and not full and _open_child(unit, template, schedule):
        return True, "skipped", state
    point = date.fromisoformat(job.parameters["as_of"])
    lower = plan.anchor if full else date.fromordinal(max(1, point.toordinal() - job.parameters["lookback_days"]))
    index = state.get("next_index", _seek(plan, max(lower, plan.anchor)))
    processed = 0
    while processed < width:
        if processed and monotonic() >= deadline:
            return False, "skipped", state
        day = occurrence_at(plan, index)
        state["next_index"] = index
        if day is None or day > point:
            return True, "created" if state["created_count"] else "skipped", state
        index += 1
        state["next_index"] = index
        processed += 1
        if day < lower or task and day == plan.anchor or _record(unit, schedule.id, day):
            continue
        if task:
            existing = _untracked_child(unit, template, schedule, day)
            if existing:
                unit.record(schedule.id, day, "task", existing)
                continue
            child = unit.create("task", TaskCreate(**{**template.model_dump(include=set(TaskCreate.model_fields)),
                "due_date": day, "recurrence_rule": None, "parent_task_id": template.id, "status": "open"}))
        else:
            child = unit.create("calendar", CalendarEventCreate(**{
                **template.model_dump(include=set(CalendarEventCreate.model_fields)), "event_date": day}))
        unit.record(schedule.id, day, "task" if task else "calendar", child.id)
        state["created_count"] += 1
        if not full:
            return True, "created", state
    return False, "skipped", state
