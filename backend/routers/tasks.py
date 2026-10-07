from datetime import date
from threading import RLock

from fastapi import APIRouter, HTTPException, Query, Response, status
from pydantic import BaseModel

from ..dependencies import store
from ..models import Task, TaskCreate, TaskPatch
from ..services.task_recurrence import next_due_date as _next_due_date
from ..services.task_recurrence import parse_rrule as _parse_rrule
from ..storage import NotFoundError, ValidationError

router = APIRouter(prefix="/tasks", tags=["Aufgaben"])
_recurrence_lock = RLock()  # serializes generation in this server process only


class RecurrenceError(BaseModel):
    task_id: str
    title: str
    error: str


class RecurrenceReport(BaseModel):
    created: list[Task]
    errors: list[RecurrenceError]


@router.get("", response_model=list[Task])
def list_tasks(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    status_filter: str | None = Query(None, alias="status"),
    assignee: str | None = Query(None),
    sort_by: str | None = Query(None),
    sort_order: str = Query("asc"),
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
) -> list[Task]:
    filters = {"status": status_filter, "assignee": assignee}
    return store._list_paginated(
        entity_type="task",
        skip=skip,
        limit=limit,
        filters=filters,
        order_by=sort_by,
        order_desc=(sort_order == "desc"),
        range_filters={"due_date": (
            date_from if isinstance(date_from, date) else None,
            date_to if isinstance(date_to, date) else None,
        )},
    )


@router.post("", response_model=Task, status_code=status.HTTP_201_CREATED)
def create_task(payload: TaskCreate) -> Task:
    try:
        return store.create_task(payload)
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


def _generate_recurring_report(as_of: date) -> RecurrenceReport:
    report = RecurrenceReport(created=[], errors=[])
    with _recurrence_lock:
        all_tasks = store.list_tasks()
        children: dict[str, list[Task]] = {}
        for task in all_tasks:
            if task.parent_task_id:
                children.setdefault(task.parent_task_id, []).append(task)
        for template in all_tasks:
            if not template.recurrence_rule or template.parent_task_id:
                continue
            try:
                rrule = _parse_rrule(template.recurrence_rule)
                instances = children.get(template.id, [])
                if any(task.status in {"open", "in_progress"} for task in instances):
                    continue
                # COUNT is the established number of children, not the template.
                if "COUNT" in rrule and len(instances) >= int(rrule["COUNT"]):
                    continue
                base_date = max([template.due_date or template.created_at.date(),
                                 *(task.due_date for task in instances if task.due_date)])
                next_date = _next_due_date(base_date, rrule)
                if next_date > as_of or ("UNTIL" in rrule and next_date > date.fromisoformat(rrule["UNTIL"])):
                    continue
                report.created.append(store.create_task(TaskCreate(
                    title=template.title, description=template.description, assignee=template.assignee,
                    due_date=next_date, priority=template.priority, property_id=template.property_id,
                    unit_id=template.unit_id, parent_task_id=template.id,
                )))
            except (ValueError, OverflowError, ValidationError) as exc:
                report.errors.append(RecurrenceError(task_id=template.id, title=template.title, error=str(exc)))
    return report


# Static paths MUST come before /{task_id} to avoid route collision.
@router.post("/generate-recurring/report", response_model=RecurrenceReport)
def generate_recurring_report(as_of: date | None = Query(None)) -> RecurrenceReport:
    """One due child per series, with individual errors for invalid historic rules.

    COUNT limits children; UNTIL is inclusive. Open children block another child;
    the template itself can remain open. Monthly/yearly dates clamp to day 28.
    Same-process requests serialize; separate server processes need DB idempotency.
    """
    return _generate_recurring_report(as_of if isinstance(as_of, date) else date.today())


@router.post("/generate-recurring", response_model=list[Task])
def generate_recurring_tasks(as_of: date | None = Query(None),
                             response: Response = None) -> list[Task]:  # type: ignore[assignment]  # FastAPI injects it
    """Compatible list result; use /generate-recurring/report for per-series errors."""
    report = _generate_recurring_report(as_of if isinstance(as_of, date) else date.today())
    if response is not None:
        response.headers["X-Recurring-Error-Count"] = str(len(report.errors))
    return report.created


@router.get("/{task_id}", response_model=Task)
def get_task(task_id: str) -> Task:
    try:
        return store.get_task(task_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.put("/{task_id}", response_model=Task)
def update_task(task_id: str, payload: TaskCreate) -> Task:
    try:
        return store.update_task(task_id, payload)
    except (NotFoundError, ValidationError) as exc:
        status_code = status.HTTP_404_NOT_FOUND if isinstance(exc, NotFoundError) else status.HTTP_400_BAD_REQUEST
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc


@router.patch("/{task_id}", response_model=Task)
def patch_task(task_id: str, payload: TaskPatch) -> Task:
    try:
        return store._patch_entity("task", task_id, payload)
    except (NotFoundError, ValidationError) as exc:
        status_code = status.HTTP_404_NOT_FOUND if isinstance(exc, NotFoundError) else status.HTTP_400_BAD_REQUEST
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc


@router.delete("/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_task(task_id: str) -> None:
    try:
        store.delete_task(task_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
