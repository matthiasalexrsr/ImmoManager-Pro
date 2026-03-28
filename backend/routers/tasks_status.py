"""Task status endpoint for polling background job progress."""

from fastapi import APIRouter, HTTPException

from ..services.task_queue import get_queue

router = APIRouter(prefix="/task-status", tags=["Task Status"])


@router.get("/{task_id}")
def get_task_status(task_id: str) -> dict:
    """Get the current status of a background task."""
    result = get_queue().get_status(task_id)
    if not result:
        raise HTTPException(status_code=404, detail="Task not found")
    response = {
        "task_id": result.task_id,
        "status": result.status,
        "created_at": result.created_at.isoformat(),
    }
    if result.status == "completed" and result.result is not None:
        response["result"] = result.result
    if result.status == "failed" and result.error:
        response["error"] = result.error
    return response
