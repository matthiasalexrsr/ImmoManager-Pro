from datetime import date
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, status

from ..dependencies import store
from ..models import Task, TaskCreate, TaskPatch
from ..services.operational_schedule import (
    TickRequest,
    generate_tasks,
    operational_tick,
    recent_ticks,
    scheduler_status,
    validate_task_recurrence,
)
from ..services.recurrence import CatchUpLimit, occurrence_at, parse_plan
from ..storage import NotFoundError, ValidationError

router = APIRouter(prefix="/tasks", tags=["Aufgaben"])


def _parse_rrule(rule: str) -> dict:
    # Compatibility helpers use the same strict parser as the scheduler.
    plan = parse_plan("compatibility", date(2000, 1, 1), rule, legacy_child_count=True)
    return {"FREQ": plan.frequency, "INTERVAL": str(plan.interval)}


def _next_due_date(current: date, rrule: dict) -> date:
    rule = ";".join(f"{key}={value}" for key, value in rrule.items())
    result = occurrence_at(parse_plan("compatibility", current, rule), 1)
    if result is None:
        raise ValidationError("Das nächste Datum liegt außerhalb des unterstützten Bereichs.")
    return result


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
    has_date_filter = isinstance(date_from, date) or isinstance(date_to, date)
    results = store._list_paginated(
        entity_type="task",
        skip=0 if has_date_filter else skip,
        limit=10000 if has_date_filter else limit,
        filters=filters,
        order_by=sort_by,
        order_desc=(sort_order == "desc"),
    )
    if isinstance(date_from, date):
        results = [
            r for r in results
            if getattr(r, 'due_date', None)
            and r.due_date >= date_from
        ]
    if isinstance(date_to, date):
        results = [
            r for r in results
            if getattr(r, 'due_date', None)
            and r.due_date <= date_to
        ]
    if has_date_filter:
        results = results[skip : skip + limit]
    return results


@router.post("", response_model=Task, status_code=status.HTTP_201_CREATED)
def create_task(payload: TaskCreate) -> Task:
    try:
        validate_task_recurrence(payload)
        return store.create_task(payload)
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


# Static paths precede /{task_id}.
@router.post("/generate-recurring", response_model=list[Task])
def generate_recurring_tasks(as_of: date | None = Query(None), full_catch_up: bool = False,
                             max_items: Annotated[int, Query(ge=1, le=5000)] = 500,
                             lookback_days: Annotated[int, Query(ge=1, le=3660)] = 366) -> list[Task]:
    try:
        return generate_tasks(store, as_of if isinstance(as_of, date) else date.today(),
                              full_catch_up=full_catch_up, max_items=max_items, lookback_days=lookback_days)
    except (ValidationError, CatchUpLimit) as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post("/operational-tick", response_model=None)
def run_operational_tick(payload: TickRequest):
    try:
        return operational_tick(store, payload)
    except (ValidationError, CatchUpLimit) as exc:
        raise HTTPException(409, str(exc)) from exc


@router.get("/operational-ticks", response_model=None)
def list_operational_ticks(limit: int = Query(20, ge=1, le=100)):
    return recent_ticks(store, limit)


@router.get("/operational-status", response_model=None)
def operational_status():
    return scheduler_status()


@router.get("/{task_id}", response_model=Task)
def get_task(task_id: str) -> Task:
    try:
        return store.get_task(task_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.put("/{task_id}", response_model=Task)
def update_task(task_id: str, payload: TaskCreate) -> Task:
    try:
        previous = store.get_task(task_id)
        if previous.parent_task_id and "parent_task_id" not in payload.model_fields_set:
            payload = payload.model_copy(update={"parent_task_id": previous.parent_task_id})
        validate_task_recurrence(payload)
        return store.update_task(task_id, payload)
    except (NotFoundError, ValidationError) as exc:
        status_code = status.HTTP_404_NOT_FOUND if isinstance(exc, NotFoundError) else status.HTTP_400_BAD_REQUEST
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc


@router.patch("/{task_id}", response_model=Task)
def patch_task(task_id: str, payload: TaskPatch) -> Task:
    try:
        current = store.get_task(task_id)
        merged = TaskCreate(**{**current.model_dump(include=set(TaskCreate.model_fields)), **payload.model_dump(exclude_unset=True)})
        validate_task_recurrence(merged)
        return store._patch_entity("task", task_id, payload)
    except (NotFoundError, ValidationError) as exc:
        raise HTTPException(404 if isinstance(exc, NotFoundError) else 400, str(exc)) from exc


@router.delete("/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_task(task_id: str) -> None:
    try:
        store.delete_task(task_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
