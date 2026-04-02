"""Background task queue interface.

Provides an abstract interface for background job processing.
Supports:
- SyncQueue (default): Runs tasks synchronously (for development)
- ThreadPoolQueue: In-process thread pool (for moderate concurrency)
- CeleryQueue: Redis + Celery backend (for production)

Configure via TASK_QUEUE_BACKEND environment variable:
  sync   — SyncQueue (default)
  thread — ThreadPoolQueue
  celery — CeleryQueue
"""

import logging
import os
from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
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
        self.created_at = datetime.now(timezone.utc)


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


class ThreadPoolQueue(TaskQueue):
    """Thread-pool-based task queue for in-process background execution.

    Runs tasks in a bounded thread pool. No external infrastructure needed.
    Suitable for moderate concurrency in single-process deployments.
    """

    def __init__(self, max_workers: int = 4):
        self._pool = ThreadPoolExecutor(max_workers=max_workers)
        self._results: dict[str, TaskResult] = {}

    def enqueue(self, func: Callable, *args, **kwargs) -> TaskResult:
        task_id = str(uuid4())
        result = TaskResult(task_id, status="pending")
        self._results[task_id] = result

        def _run():
            result.status = "running"
            try:
                ret = func(*args, **kwargs)
                result.status = "completed"
                result.result = ret
            except Exception as exc:
                result.status = "failed"
                result.error = str(exc)
                logger.exception("Task %s failed: %s", task_id, func.__name__)

        self._pool.submit(_run)
        return result

    def get_status(self, task_id: str) -> Optional[TaskResult]:
        return self._results.get(task_id)

    def cancel(self, task_id: str) -> bool:
        # ThreadPoolExecutor doesn't support cancellation of running tasks
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


# Configure queue based on TASK_QUEUE_BACKEND environment variable
_backend = os.getenv("TASK_QUEUE_BACKEND", "sync").lower()

if _backend == "thread":
    _queue: TaskQueue = ThreadPoolQueue()
    logger.info("Task queue: ThreadPoolQueue")
elif _backend == "celery":
    _queue = CeleryQueue()
    if _queue._app is None:
        logger.warning("Task queue: CeleryQueue configured but celery not installed — falling back to sync")
    else:
        logger.info("Task queue: CeleryQueue")
else:
    _queue = SyncQueue()
    logger.info("Task queue: SyncQueue (synchronous)")


def get_queue() -> TaskQueue:
    """Get the configured task queue instance."""
    return _queue


def set_queue(queue: TaskQueue) -> None:
    """Set the global task queue instance."""
    global _queue
    _queue = queue
