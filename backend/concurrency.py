"""Run long calculations one after the other, and share a result until data changes.

Reports, the review list and the dashboard figures read thousands of rows. Run
side by side in the server's thread pool they slow each other down many times
over: SQLite gives up Python's GIL for every row it reads and has to queue to get
it back behind the other calculations. One after the other they finish sooner,
also for the one who asked last (dashboard: 13 s side by side, 2 s in a row).

People who open the same page at the same moment get the same answer: a result is
kept until the next change and at most a few seconds. Changes are every flush or
commit of a database session (requests, jobs, imports) and every write
request; the time limit covers what this process cannot see (another server
process). Without a database (the in-memory store) nothing is kept.
"""

from __future__ import annotations

import functools
import itertools
import threading
import time
from typing import Any, Callable, TypeVar

F = TypeVar("F", bound=Callable[..., Any])

_HEAVY = threading.RLock()   # re-entrant: a calculation may call another one
_KEEP_SECONDS = 5.0
_changes = itertools.count(1)
_version = 0
_results: dict[tuple, tuple[int, float, Any]] = {}
_tracking = False


def note_change(*_: Any) -> None:
    """Results computed before now are stale."""
    global _version
    _version = next(_changes)


def track_database_changes() -> None:
    """Keep results only while every database change is seen (called when the SQL store starts)."""
    global _tracking
    if _tracking:
        return
    from sqlalchemy import event
    from sqlalchemy.orm import Session

    # not rollbacks: closing a reading session rolls back too, and undone changes were flushed first
    for name in ("after_flush", "after_commit", "after_bulk_update", "after_bulk_delete"):
        event.listen(Session, name, note_change)
    _tracking = True


def one_at_a_time(func: F) -> F:
    """Decorator for synchronous endpoints and services that read whole tables.

    Results that are plain data (dict, list) are shared as described above;
    responses (files, PDFs) are computed for every request.
    """

    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        key = (func.__module__, func.__qualname__, repr(args), repr(sorted(kwargs.items())))
        with _HEAVY:
            version, now = _version, time.monotonic()
            kept = _results.get(key)
            if kept and kept[0] == version and now - kept[1] < _KEEP_SECONDS:
                return kept[2]
            result = func(*args, **kwargs)
            if _tracking and isinstance(result, (dict, list)):
                _results[key] = (version, now, result)
            return result

    return wrapper  # type: ignore[return-value]
