"""Run long calculations one after the other, and share what they read until data changes.

Reports, the review list and the dashboard figures read thousands of rows. Run
side by side in the server's thread pool they slow each other down many times
over: SQLite gives up Python's GIL for every row it reads and has to queue to get
it back behind the other calculations. One after the other they finish sooner,
also for the one who asked last (dashboard: 13 s side by side, 2 s in a row).

People who open the same page at the same moment get the same answer: a result is
kept until the next change and at most a few seconds. Whole tables read for such
results (the bookings) are kept until that table changes. Changes are seen from the
database sessions (every flush, commit, bulk or raw statement: requests, jobs,
imports), from write requests and from restoring a backup; the time limit covers
what this process cannot see (another server process). Without a database (the
in-memory store) nothing is kept.
"""

from __future__ import annotations

import functools
import itertools
import threading
import time
from typing import Any, Callable, TypeVar

F = TypeVar("F", bound=Callable[..., Any])

KEEP_SECONDS = 5.0
_HEAVY = threading.RLock()   # re-entrant: a calculation may call another one
_changes = itertools.count(1)
_version = 0                 # any change: results are stale
_everything = 0              # a change of unknown extent: every table is stale
_tables: dict[str, int] = {}
_results: dict[tuple, tuple[int, float, Any]] = {}
_tracking = False


def note_write(*_: Any) -> None:
    """Something changed: computed results are stale (tables are tracked on their own)."""
    global _version
    _version = next(_changes)


def note_change(*_: Any) -> None:
    """A change the sessions did not show (a restored backup, raw SQL): everything is stale."""
    global _version, _everything
    _version = _everything = next(_changes)


def _note_tables(names: set[str]) -> None:
    global _version
    stamp = next(_changes)
    for name in names:
        _tables[name] = stamp
    _version = stamp


def table_version(name: str) -> int:
    return max(_tables.get(name, 0), _everything)


def _after_flush(session: Any, _context: Any) -> None:
    names = {obj.__table__.name for obj in (*session.new, *session.dirty, *session.deleted)
             if hasattr(obj, "__table__")}
    # visible to others only after the commit (or undone): what they read in between is stale then
    session.info.setdefault("changed_tables", set()).update(names)
    _note_tables(names)


def _after_transaction(session: Any, *_: Any) -> None:
    names = session.info.pop("changed_tables", None)
    if names:
        _note_tables(names)


def _after_bulk(context: Any) -> None:
    _note_tables({context.mapper.local_table.name})


def _after_execute(state: Any) -> None:
    if not state.is_select:          # Core insert/update/delete or raw SQL through a session
        note_change()


def track_database_changes() -> None:
    """Keep results only while every database change is seen (called when the SQL store starts)."""
    global _tracking
    if _tracking:
        return
    from sqlalchemy import event
    from sqlalchemy.orm import Session

    event.listen(Session, "after_flush", _after_flush)
    event.listen(Session, "after_commit", _after_transaction)
    event.listen(Session, "after_soft_rollback", _after_transaction)
    event.listen(Session, "after_bulk_update", _after_bulk)
    event.listen(Session, "after_bulk_delete", _after_bulk)
    event.listen(Session, "do_orm_execute", _after_execute)
    _tracking = True


_table_rows: dict[str, tuple[int, float, list]] = {}
_table_lock = threading.Lock()


def whole_table(name: str, load: Callable[[], list]) -> list:
    """All rows of a table for reading, from memory while the table is unchanged."""
    if not _tracking:
        return load()
    version, now = table_version(name), time.monotonic()
    with _table_lock:
        kept = _table_rows.get(name)
    if kept and kept[0] == version and now - kept[1] < KEEP_SECONDS:
        return list(kept[2])
    rows = load()
    with _table_lock:
        _table_rows[name] = (version, now, rows)
    return list(rows)


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
            if kept and kept[0] == version and now - kept[1] < KEEP_SECONDS:
                return kept[2]
            result = func(*args, **kwargs)
            if _tracking and isinstance(result, (dict, list)):
                _results[key] = (version, now, result)
            return result

    return wrapper  # type: ignore[return-value]
