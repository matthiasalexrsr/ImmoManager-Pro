from datetime import date, timedelta

from fastapi import APIRouter, HTTPException, Query, status

from ..dependencies import store
from ..models import Task, TaskCreate, TaskPatch
from ..storage import NotFoundError, ValidationError

router = APIRouter(prefix="/tasks", tags=["Aufgaben"])


@router.get("", response_model=list[Task])
def list_tasks(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    status_filter: str | None = Query(None, alias="status"),
    assignee: str | None = Query(None),
) -> list[Task]:
    results = store.list_tasks()
    if status_filter:
        results = [t for t in results if t.status == status_filter]
    if assignee:
        results = [t for t in results if t.assignee == assignee]
    return results[skip : skip + limit]


@router.post("", response_model=Task, status_code=status.HTTP_201_CREATED)
def create_task(payload: TaskCreate) -> Task:
    try:
        return store.create_task(payload)
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


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
        return store._patch_entity(store.tasks, task_id, payload, "Aufgabe nicht gefunden")
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.delete("/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_task(task_id: str) -> None:
    try:
        store.delete_task(task_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


def _parse_rrule(rule: str) -> dict:
    """Parse a simplified iCal RRULE string into a dict."""
    parts = {}
    for part in rule.split(";"):
        if "=" in part:
            key, value = part.split("=", 1)
            parts[key.strip().upper()] = value.strip()
    return parts


def _next_due_date(current: date, rrule: dict) -> date:
    """Calculate the next due date based on an RRULE."""
    freq = rrule.get("FREQ", "MONTHLY").upper()
    interval = int(rrule.get("INTERVAL", "1"))
    if freq == "DAILY":
        return current + timedelta(days=interval)
    elif freq == "WEEKLY":
        return current + timedelta(weeks=interval)
    elif freq == "MONTHLY":
        month = current.month + interval
        year = current.year + (month - 1) // 12
        month = (month - 1) % 12 + 1
        day = min(current.day, 28)  # safe for all months
        return date(year, month, day)
    elif freq == "YEARLY":
        return date(current.year + interval, current.month, min(current.day, 28))
    return current + timedelta(days=30 * interval)


@router.post("/generate-recurring", response_model=list[Task])
def generate_recurring_tasks(
    as_of: date | None = Query(None),
) -> list[Task]:
    """Generate next instances of recurring tasks that are due.

    Looks at all tasks with a recurrence_rule and creates the next instance
    if the current instance is completed and the next due date is <= as_of.
    """
    if as_of is None:
        as_of = date.today()

    all_tasks = store.list_tasks()
    recurring_templates = [t for t in all_tasks if t.recurrence_rule]
    existing_children = {t.parent_task_id for t in all_tasks if t.parent_task_id}

    created = []
    for template in recurring_templates:
        # Skip if there's already an open child task
        has_open_child = any(
            t.parent_task_id == template.id and t.status in {"open", "in_progress"}
            for t in all_tasks
        )
        if has_open_child:
            continue

        rrule = _parse_rrule(template.recurrence_rule)
        base_date = template.due_date or date.today()
        next_date = _next_due_date(base_date, rrule)

        # Check COUNT limit
        count_limit = int(rrule.get("COUNT", "0"))
        if count_limit > 0:
            child_count = sum(1 for t in all_tasks if t.parent_task_id == template.id)
            if child_count >= count_limit:
                continue

        # Check UNTIL limit
        until = rrule.get("UNTIL")
        if until:
            try:
                until_date = date.fromisoformat(until)
                if next_date > until_date:
                    continue
            except ValueError:
                pass

        if next_date <= as_of:
            new_task = store.create_task(TaskCreate(
                title=template.title,
                description=template.description,
                assignee=template.assignee,
                due_date=next_date,
                priority=template.priority,
                property_id=template.property_id,
                unit_id=template.unit_id,
                parent_task_id=template.id,
            ))
            created.append(new_task)

    return created
