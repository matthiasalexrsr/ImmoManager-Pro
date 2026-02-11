"""Background task queue interface.

Provides an abstract interface for background job processing.
Supports:
- SyncQueue (default): Runs tasks synchronously (for development)
- CeleryQueue: Redis + Celery backend (for production)

Configure via TASK_QUEUE_BACKEND environment variable.
"""

import logging
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Callable, Optional
from uuid import uuid4

logger = logging.getLogger(__name__)


class TaskResult:
    """Result of a queued task."""

    def __init__(self, task_id: str, status: str = "pending", result: Any = None, error: Optional[str] = None):
        self.task_id = task_id
        self.status = status  # pending, running, completed, failed
        self.result = result
        self.error = error
        self.created_at = datetime.utcnow()


class TaskQueue(ABC):
    """Abstract interface for background task processing."""

    @abstractmethod
    def enqueue(self, func: Callable, *args, **kwargs) -> TaskResult:
        """Add a task to the queue."""
        ...

    @abstractmethod
    def get_status(self, task_id: str) -> Optional[TaskResult]:
        """Get the status of a queued task."""
        ...

    @abstractmethod
    def cancel(self, task_id: str) -> bool:
        """Cancel a pending task."""
        ...


class SyncQueue(TaskQueue):
    """Synchronous task execution (no actual queuing).

    Executes tasks immediately in the calling thread.
    Suitable for development and small deployments.
    """

    def __init__(self):
        self._results: dict[str, TaskResult] = {}

    def enqueue(self, func: Callable, *args, **kwargs) -> TaskResult:
        task_id = str(uuid4())
        result = TaskResult(task_id, status="running")
        self._results[task_id] = result

        try:
            ret = func(*args, **kwargs)
            result.status = "completed"
            result.result = ret
        except Exception as exc:
            result.status = "failed"
            result.error = str(exc)
            logger.exception("Task %s failed: %s", task_id, func.__name__)

        return result

    def get_status(self, task_id: str) -> Optional[TaskResult]:
        return self._results.get(task_id)

    def cancel(self, task_id: str) -> bool:
        result = self._results.get(task_id)
        if result and result.status == "pending":
            result.status = "cancelled"
            return True
        return False


class CeleryQueue(TaskQueue):
    """Celery-based task queue using Redis as broker.

    Requires:
      pip install celery[redis]
      CELERY_BROKER_URL=redis://localhost:6379/0
    """

    def __init__(self, broker_url: str = "redis://localhost:6379/0"):
        self.broker_url = broker_url
        self._app = None
        try:
            from celery import Celery
            self._app = Celery("immomanager", broker=broker_url)
            logger.info("Celery connected to %s", broker_url)
        except ImportError:
            logger.warning("Celery not installed. Background tasks will run synchronously.")

    def enqueue(self, func: Callable, *args, **kwargs) -> TaskResult:
        if self._app is None:
            # Fallback to sync execution
            return SyncQueue().enqueue(func, *args, **kwargs)

        task = self._app.send_task(func.__name__, args=args, kwargs=kwargs)
        return TaskResult(task_id=task.id, status="pending")

    def get_status(self, task_id: str) -> Optional[TaskResult]:
        if self._app is None:
            return None
        result = self._app.AsyncResult(task_id)
        status_map = {"PENDING": "pending", "STARTED": "running", "SUCCESS": "completed", "FAILURE": "failed"}
        return TaskResult(
            task_id=task_id,
            status=status_map.get(result.status, "unknown"),
            result=result.result if result.ready() else None,
            error=str(result.result) if result.failed() else None,
        )

    def cancel(self, task_id: str) -> bool:
        if self._app is None:
            return False
        self._app.control.revoke(task_id, terminate=True)
        return True


# Default: synchronous queue
_queue: TaskQueue = SyncQueue()


def get_queue() -> TaskQueue:
    """Get the configured task queue instance."""
    return _queue


def set_queue(queue: TaskQueue) -> None:
    """Set the global task queue instance."""
    global _queue
    _queue = queue
