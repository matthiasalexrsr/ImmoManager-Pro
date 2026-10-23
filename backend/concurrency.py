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
import inspect
import itertools
import threading
import time
from copy import deepcopy
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import TYPE_CHECKING, Any, Callable, TypeVar
from uuid import UUID

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

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


def _after_transaction(session: Any, previous: Any = None) -> None:
    # Savepoint completion is not completion of the surrounding write. Retain
    # its private-read/commit fence even when just the nested change rolled back.
    nested = previous.parent is not None if previous is not None else session.in_nested_transaction()
    names = session.info.get("changed_tables")
    unknown = session.info.get("cache_pending_write", False)
    if not nested:
        session.info.pop("changed_tables", None)
        session.info.pop("cache_pending_write", None)
    if unknown:
        note_change()
    elif names:
        _note_tables(names)


def _after_bulk(context: Any) -> None:
    names = {context.mapper.local_table.name}
    context.session.info.setdefault("changed_tables", set()).update(names)
    _note_tables(names)


def _after_execute(state: Any) -> None:
    if not state.is_select:          # Core insert/update/delete or raw SQL through a session
        state.session.info["cache_pending_write"] = True
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


def _session(value: Any) -> Any:
    """Resolve the request session, including the application's scoped-session proxy."""
    from sqlalchemy.orm import Session, scoped_session

    db = value if isinstance(value, (Session, scoped_session)) else getattr(value, "db", None)
    if isinstance(db, scoped_session):
        db = db()
    return db if isinstance(db, Session) else None


def _shareable(db: Any) -> bool:
    from sqlalchemy.engine import Connection

    # A caller-owned connection may already be inside a transaction outside the
    # Session's knowledge. Keep those reads local to that connection.
    if isinstance(db.get_bind(), Connection):
        return False
    if (db.new or db.dirty or db.deleted or db.identity_map
            or db.info.get("changed_tables") or db.info.get("cache_pending_write")):
        return False
    if not db.in_transaction():
        return True
    # Auth/scope reads can already have opened a SQLAlchemy transaction. PostgreSQL
    # READ COMMITTED and SQLite's legacy SELECTs still see current committed rows;
    # an actual SQLite transaction or a repeatable snapshot must stay session-local.
    connection = db.connection()
    if connection.dialect.name == "sqlite":
        return not connection.connection.driver_connection.in_transaction
    if connection.dialect.name == "postgresql":
        return connection.get_isolation_level() in {"READ COMMITTED", "AUTOCOMMIT"}
    return False


class _Reads:
    def __init__(self, sources: list[Any]):
        self.sessions: list[Session] = []
        self.memory = False
        for source in sources:
            db = _session(source)
            if db is not None:
                if all(db is not other for other in self.sessions):
                    self.sessions.append(db)
            elif hasattr(source, "list_bookings"):
                self.memory = True
        # Keep the bind object itself, not its URL or id(): separate in-memory
        # databases and recycled object IDs cannot collide. Connection-bound
        # sessions remain distinct from ordinary sessions on their parent engine.
        self.identity = tuple(dict.fromkeys(db.get_bind() for db in self.sessions))

    def shared(self) -> bool:
        return _tracking and not self.memory and all(_shareable(db) for db in self.sessions)


def _sources(func: Callable, values: Any = ()) -> list[Any]:
    sources = list(values)
    owner = getattr(func, "__self__", None)
    if owner is not None:
        sources.append(owner)
    # Existing HTTP endpoints read their module's store rather than taking it as
    # an argument. Resolve it at call time, so tests/reconfigured stores get their
    # own namespace; unrelated globals do not disable pure calculation caches.
    if "store" in getattr(getattr(func, "__code__", None), "co_names", ()):
        source = getattr(func, "__globals__", {}).get("store")
        if source is not None:
            sources.append(source)
    return sources


class _Uncacheable(TypeError):
    pass


def _argument(value: Any) -> Any:
    """Typed, lossless keys; never guess at an arbitrary object's repr()."""
    db = _session(value)
    if db is not None:
        return ("database", db.get_bind())
    if value is None or type(value) in (bool, int, str, bytes):
        return (type(value), value)
    if isinstance(value, Enum):
        return (type(value), _argument(value.value))
    if type(value) is float:
        return (float, value.hex())
    if isinstance(value, (datetime, date, Decimal, UUID)):
        return (type(value), str(value))
    if type(value) in (tuple, list):
        return (type(value), tuple(_argument(item) for item in value))
    if type(value) is dict:
        # Keyword order is irrelevant; preserve ordinary mapping order because
        # an actual function can observe it.
        return (dict, tuple((_argument(key), _argument(item)) for key, item in value.items()))
    if type(value) in (set, frozenset):
        return (type(value), frozenset(_argument(item) for item in value))
    raise _Uncacheable


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
    reads = _Reads(_sources(load))
    if not reads.shared():
        return load()
    key = (name, reads.identity, _boundary())
    with _cache_lock:
        version, now = table_version(name), time.monotonic()
        _expire_cached(now)
        kept = _table_rows.get(key)
        if kept and kept[0] == version:
            cached = kept[2]
        else:
            cached = None
    if cached is not None:
        return deepcopy(cached)
    rows = load()
    saved = deepcopy(rows)
    share = reads.shared()
    with _cache_lock:
        # A write during the load makes these rows unsuitable for sharing.
        if version == table_version(name) and share:
            _table_rows[key] = (version, time.monotonic(), saved)
    return rows


def one_at_a_time(func: F) -> F:
    """Decorator for synchronous endpoints and services that read whole tables.

    Results that are plain data (dict, list) are shared as described above;
    responses (files, PDFs) are computed for every request.
    """

    signature = inspect.signature(func)

    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        bound = signature.bind(*args, **kwargs)
        bound.apply_defaults()
        reads = _Reads(_sources(func, bound.arguments.values()))
        try:
            arguments = tuple((name, _argument(value)) for name, value in bound.arguments.items())
            key = (func, reads.identity, arguments, _boundary())
        except _Uncacheable:
            key = None

        def kept_result():
            if key is not None and reads.shared():
                with _cache_lock:
                    now = time.monotonic()
                    _expire_cached(now)
                    kept = _results.get(key)
                    if kept and kept[0] == _version:
                        return kept[2]
            return None

        # A hot result must not queue behind an unrelated slow report. Recheck
        # after taking the compute lock so simultaneous misses compute once.
        cached = kept_result()
        if cached is not None:
            return deepcopy(cached)
        with _HEAVY:
            cached = kept_result()
            if cached is not None:
                return deepcopy(cached)
            with _cache_lock:
                version = _version
            result = func(*args, **kwargs)
            if key is not None and reads.shared() and isinstance(result, (dict, list)):
                saved = deepcopy(result)
                with _cache_lock:
                    if version == _version:
                        # Keep only recent variants; removed results are recomputed.
                        if key not in _results and len(_results) >= MAX_RESULT_ENTRIES:
                            del _results[next(iter(_results))]
                        _results[key] = (version, time.monotonic(), saved)
            return result

    return wrapper  # type: ignore[return-value]
