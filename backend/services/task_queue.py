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
import threading
import time
from abc import ABC, abstractmethod
from collections import deque
from concurrent.futures import Future, ThreadPoolExecutor
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
        self.finished_at: Optional[datetime] = None


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


class _RetainedQueue(TaskQueue):
    """In-process status is temporary, separate from persisted business history.

    Terminal results are available for an hour by default. Expiry is cleaned on
    queue operations or explicit cleanup_results(); pending/running work never
    expires. Callers may choose a longer retention or None to retain indefinitely.
    There is no lifetime job count limit and no submitted work is dropped.
    """

    def __init__(self, result_retention_seconds: float | None = 3600):
        if result_retention_seconds is not None and result_retention_seconds < 0:
            raise ValueError("Result retention must be non-negative or None")
        self.result_retention_seconds = result_retention_seconds
        self._results: dict[str, TaskResult] = {}
        self._finished: deque[tuple[float, str]] = deque()
        self._lock = threading.RLock()

    def cleanup_results(self) -> int:
        """Remove expired terminal statuses, returning the number removed."""
        with self._lock:
            now, removed = time.monotonic(), 0
            while self._finished and self._finished[0][0] <= now:
                _deadline, task_id = self._finished.popleft()
                if self._results.pop(task_id, None) is not None:
                    removed += 1
            return removed

    def _finish(self, result: TaskResult, status: str, value: Any = None, error: str | None = None) -> None:
        with self._lock:
            result.status, result.result, result.error = status, value, error
            result.finished_at = datetime.now(timezone.utc)
            if self.result_retention_seconds is not None:
                self._finished.append((time.monotonic() + self.result_retention_seconds, result.task_id))

    def get_status(self, task_id: str) -> Optional[TaskResult]:
        with self._lock:
            self.cleanup_results()
            return self._results.get(task_id)


class SyncQueue(_RetainedQueue):
    """Synchronous task execution (no actual queuing).

    Executes tasks immediately in the calling thread.
    Suitable for development and small deployments.
    """

    def enqueue(self, func: Callable, *args, **kwargs) -> TaskResult:
        task_id = str(uuid4())
        result = TaskResult(task_id, status="running")
        with self._lock:
            self.cleanup_results()
            self._results[task_id] = result

        try:
            ret = func(*args, **kwargs)
            self._finish(result, "completed", value=ret)
        except Exception as exc:
            self._finish(result, "failed", error=str(exc))
            logger.exception("Task %s failed: %s", task_id, getattr(func, "__name__", type(func).__name__))

        return result

    def cancel(self, task_id: str) -> bool:
        self.cleanup_results()
        return False


class ThreadPoolQueue(_RetainedQueue):
    """Thread-pool-based task queue for in-process background execution.

    Runs tasks in a bounded thread pool. No external infrastructure needed.
    Suitable for moderate concurrency in single-process deployments.
    """

    def __init__(self, max_workers: int = 4, result_retention_seconds: float | None = 3600):
        super().__init__(result_retention_seconds=result_retention_seconds)
        self._pool = ThreadPoolExecutor(max_workers=max_workers)
        self._futures: dict[str, Future] = {}

    def enqueue(self, func: Callable, *args, **kwargs) -> TaskResult:
        task_id = str(uuid4())
        result = TaskResult(task_id, status="pending")
        def _run():
            with self._lock:
                if result.status == "cancelled":
                    return
                result.status = "running"
            try:
                ret = func(*args, **kwargs)
                self._finish(result, "completed", value=ret)
            except Exception as exc:
                self._finish(result, "failed", error=str(exc))
                logger.exception("Task %s failed: %s", task_id, getattr(func, "__name__", type(func).__name__))

        def _discard_future(_future):
            with self._lock:
                self._futures.pop(task_id, None)

        with self._lock:
            self.cleanup_results()
            self._results[task_id] = result
            try:
                future = self._pool.submit(_run)
            except Exception:
                del self._results[task_id]
                raise
            self._futures[task_id] = future
            future.add_done_callback(_discard_future)
        return result

    def cancel(self, task_id: str) -> bool:
        with self._lock:
            self.cleanup_results()
            result = self._results.get(task_id)
            future = self._futures.get(task_id)
            # The executor decides whether work actually started. Merely marking
            # a pending status cancelled would leave the callable in its queue.
            if result is None or result.status != "pending" or future is None or not future.cancel():
                return False
            self._finish(result, "cancelled")
            return True


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
        logger.warning(
            "TASK_QUEUE_BACKEND=celery but Celery is not installed. "
            "All tasks will execute synchronously as a fallback."
        )
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
