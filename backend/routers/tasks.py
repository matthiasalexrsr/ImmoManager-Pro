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
