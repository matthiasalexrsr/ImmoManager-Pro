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
MAX_RESULT_ENTRIES = 256     # ephemeral response variants, never a limit on stored data
_HEAVY = threading.RLock()   # re-entrant: a calculation may call another one
_cache_lock = threading.RLock()  # writes invalidate without waiting for calculations
_changes = itertools.count(1)
_version = 0                 # any change: results are stale
_everything = 0              # a change of unknown extent: every table is stale
_tables: dict[str, int] = {}
_results: dict[tuple, tuple[int, float, Any]] = {}
_tracking = False


def note_write(*_: Any) -> None:
    """Something changed: computed results are stale (tables are tracked on their own)."""
    global _version
    with _cache_lock:
        _version = next(_changes)
        _results.clear()


def note_change(*_: Any) -> None:
    """A change the sessions did not show (a restored backup, raw SQL): everything is stale."""
    global _version, _everything
    with _cache_lock:
        _version = _everything = next(_changes)
        _results.clear()
        _table_rows.clear()


def _note_tables(names: set[str]) -> None:
    global _version
    with _cache_lock:
        stamp = next(_changes)
        for name in names:
            _tables[name] = stamp
            for key in [key for key in _table_rows if key[0] == name]:
                del _table_rows[key]
        _version = stamp
        _results.clear()


def table_version(name: str) -> int:
    with _cache_lock:
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


_table_rows: dict[tuple, tuple[int, float, list]] = {}


def _boundary() -> Any:
    """Whose rows: results are shared only between requests with the same portfolio access."""
    from .services.portfolio_scope import current_scope

    scope = current_scope()
    return None if scope is None or scope.unrestricted else scope


def _expire_cached(now: float) -> None:
    """Release expired values on cache access; caller holds _cache_lock."""
    caches: tuple[dict[Any, tuple], ...] = (_results, _table_rows)
    for cache in caches:
        for key, entry in list(cache.items()):
            if now - entry[1] >= KEEP_SECONDS:
                del cache[key]


def whole_table(name: str, load: Callable[[], list]) -> list:
    """All rows of a table for reading, from memory while the table is unchanged."""
    if not _tracking:
        return load()
    key = (name, _boundary())
    with _cache_lock:
        version, now = table_version(name), time.monotonic()
        _expire_cached(now)
        kept = _table_rows.get(key)
        if kept and kept[0] == version:
            return list(kept[2])
    rows = load()
    with _cache_lock:
        # A write during the load makes these rows unsuitable for sharing.
        if version == table_version(name):
            _table_rows[key] = (version, time.monotonic(), rows)
    return list(rows)


def one_at_a_time(func: F) -> F:
    """Decorator for synchronous endpoints and services that read whole tables.

    Results that are plain data (dict, list) are shared as described above;
    responses (files, PDFs) are computed for every request.
    """

    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        key = (func.__module__, func.__qualname__, repr(args), repr(sorted(kwargs.items())), _boundary())
        with _HEAVY:
            with _cache_lock:
                version, now = _version, time.monotonic()
                _expire_cached(now)
                kept = _results.get(key)
                if kept and kept[0] == version:
                    return kept[2]
            result = func(*args, **kwargs)
            if _tracking and isinstance(result, (dict, list)):
                with _cache_lock:
                    if version == _version:
                        # Keep only recent variants; removed results are recomputed.
                        if key not in _results and len(_results) >= MAX_RESULT_ENTRIES:
                            del _results[next(iter(_results))]
                        _results[key] = (version, time.monotonic(), result)
            return result

    return wrapper  # type: ignore[return-value]
