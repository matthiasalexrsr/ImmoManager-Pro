"""Catch-up of recurring tasks as a durable job, deduplicated per (series, rule version, date).

Rule version: a hash of the normalized rule and its anchor date. A changed rule
starts after the last occurrence any earlier version processed, so history is
neither repeated nor rewritten. Occurrences are local (Europe/Berlin) calendar dates.

Modes (payload "mode", default settings.recurring_catch_up):
  latest - only the most recent due occurrence becomes a task, and only while no
           child of the series is open; older ones are recorded as skipped.
  all    - every due occurrence becomes a task.
Each chunk handles at most `chunk` occurrences and commits them with the checkpoint.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlalchemy import func, select

from ...db.orm_models import TaskORM
from ...models import TaskCreate
from ..notifier import OPEN_WORK_STATUSES
from ..task_recurrence import next_due_date, parse_rrule
from .core import JobContext, MemoryJobStore, MemoryLedger, SqlLedger

KIND = "tasks.recurring"
CHUNK = 500
TEMPLATE_PAGE = 100
MAX_REPORTED_ERRORS = 50
_PROCESS_LEDGER = MemoryLedger()   # memory business store next to a SQL job store (not configured)


def rule_key(template_id: str) -> str:
    return f"task:{template_id}"


def anchor_of(template: Any) -> date:
    return template.due_date or template.created_at.date()


def rule_version(template: Any) -> str:
    rule = parse_rrule(template.recurrence_rule)
    text = ";".join(f"{k}={rule[k]}" for k in sorted(rule)) + f"|{anchor_of(template).isoformat()}"
    return hashlib.sha256(text.encode()).hexdigest()[:16]


@dataclass
class Children:
    count: int = 0
    latest_due: date | None = None
    has_open: bool = False


def _is_sql(store: Any) -> bool:
    return hasattr(store, "db") and hasattr(store, "communication")


def templates_after(store: Any, after: str, limit: int) -> list[Any]:
    if _is_sql(store):
        query = (select(TaskORM).where(TaskORM.recurrence_rule.is_not(None), TaskORM.recurrence_rule != "",
                                       TaskORM.parent_task_id.is_(None), TaskORM.id > after)
                 .order_by(TaskORM.id).limit(limit))
        return list(store.db.scalars(query))
    found = sorted((t for t in store.list_tasks() if t.recurrence_rule and not t.parent_task_id and t.id > after),
                   key=lambda t: t.id)
    return found[:limit]


def children_of(store: Any, template_id: str) -> Children:
    if _is_sql(store):
        row = store.db.execute(select(
            func.count(TaskORM.id), func.max(TaskORM.due_date),
            func.count(TaskORM.id).filter(TaskORM.status.in_(tuple(OPEN_WORK_STATUSES))),
        ).where(TaskORM.parent_task_id == template_id)).one()
        return Children(row[0], row[1], bool(row[2]))
    found = [t for t in store.list_tasks() if t.parent_task_id == template_id]
    dues = [t.due_date for t in found if t.due_date]
    return Children(len(found), max(dues) if dues else None,
                    any(t.status in OPEN_WORK_STATUSES for t in found))


def child_payload(template: Any, due: date) -> TaskCreate:
    return TaskCreate(title=template.title, description=template.description, assignee=template.assignee,
                      due_date=due, priority=template.priority, property_id=template.property_id,
                      unit_id=template.unit_id, parent_task_id=template.id)


def validate_task(store: Any, data: TaskCreate) -> None:
    (store.communication if _is_sql(store) else store).validate_task(data)


def ledger_for(store: Any) -> Any:
    """The ledger in the store's own transaction (SQL) or the process ledger (memory)."""
    if _is_sql(store):
        return SqlLedger(store.db)
    from .scheduler import get_job_store

    jobs = get_job_store()
    return jobs.ledger if isinstance(jobs, MemoryJobStore) else _PROCESS_LEDGER


def stage_task(store: Any, data: TaskCreate) -> Any:
    """Create without committing on SQL (the chunk commits); memory creates directly."""
    if _is_sql(store):
        store.communication.validate_task(data)
        return store.communication._tasks.create(data)
    return store.create_task(data)


def processed_through(store: Any, ledger: Any, template: Any, children: Children) -> date:
    """Last date the series is settled through: anchor, newest child, newest ledger entry."""
    candidates = [anchor_of(template)]
    if children.latest_due:
        candidates.append(children.latest_due)
    latest = ledger.latest(rule_key(template.id))
    if latest:
        candidates.append(date.fromisoformat(latest))
    return max(candidates)


def catch_up_template(unit: Any, template: Any, as_of: date, mode: str, budget: int,
                      progress: dict) -> tuple[int, bool]:
    """Process up to budget occurrences; returns (used, finished)."""
    try:
        rrule = parse_rrule(template.recurrence_rule)
        version = rule_version(template)
    except (ValueError, OverflowError) as exc:
        _error(progress, template, exc)
        return 1, True
    key = rule_key(template.id)
    children = children_of(unit.store, template.id)
    current = processed_through(unit.store, unit.ledger, template, children)
    bound = min(as_of, date.fromisoformat(rrule["UNTIL"])) if "UNTIL" in rrule else as_of
    limit = int(rrule["COUNT"]) if "COUNT" in rrule else None
    used = 0
    while used < budget:
        try:
            due = next_due_date(current, rrule)
            following = next_due_date(due, rrule)
        except (ValueError, OverflowError) as exc:
            _error(progress, template, exc)
            return used + 1, True
        if due > bound or (limit is not None and children.count >= limit):
            return used, True
        create = mode == "all" or (following > bound and not children.has_open)
        if unit.ledger.record(key, version, due.isoformat(), "created" if create else "skipped", unit.run.id):
            if create:
                stage_task(unit.store, child_payload(template, due))
                children.count += 1
                children.has_open = True
                progress["created"] = progress.get("created", 0) + 1
            else:
                progress["skipped"] = progress.get("skipped", 0) + 1
        current = due
        used += 1
    return used, False


def _error(progress: dict, template: Any, exc: Exception) -> None:
    errors = progress.setdefault("errors", [])
    progress["error_count"] = progress.get("error_count", 0) + 1
    if len(errors) < MAX_REPORTED_ERRORS:
        errors.append({"task_id": template.id, "title": template.title, "error": str(exc)})


def make_handler(chunk: int = CHUNK, default_mode: str | None = None):
    def handle(ctx: JobContext) -> bool:
        from ...config import settings

        as_of = date.fromisoformat(ctx.run.payload["as_of"])
        mode = ctx.run.payload.get("mode") or default_mode or settings.recurring_catch_up
        if mode not in {"latest", "all"}:
            raise ValueError(f"Unknown catch-up mode {mode!r}")
        after = ctx.checkpoint.get("after_template", "")
        progress = ctx.progress
        budget = chunk
        with ctx.unit() as unit:
            while budget > 0:
                templates = templates_after(unit.store, after, TEMPLATE_PAGE)
                if not templates:
                    unit.save({"after_template": after, "done": True}, progress)
                    return True
                for template in templates:
                    used, finished = catch_up_template(unit, template, as_of, mode, budget, progress)
                    budget -= max(used, 1)   # visiting a settled series costs too: chunks stay bounded
                    if not finished:
                        break          # mid-series: the ledger is that series' own checkpoint
                    after = template.id
                    if budget <= 0:
                        break
                else:
                    continue
                break
            unit.save({"after_template": after}, progress)
        return False

    return handle
