"""Shared dependencies for the ImmoManager Pro API.

Supports two storage backends:
  - InMemoryStore (only when sqlite_persistent_store=False or explicit fallback)
  - SQLAlchemyStore (default for all database URLs including SQLite)

Set DATABASE_URL to configure the database. SQLite is the default.

Error handling:
  - When ALLOW_INMEMORY_FALLBACK=true (default in dev), SQL init failure
    falls back to InMemoryStore so the application can still start.
  - When ALLOW_INMEMORY_FALLBACK=false (recommended for production),
    SQL init failure aborts startup immediately.
  - cleanup_session() is safe to call even if the session is corrupted.
"""

import contextvars
import logging
import threading
from collections.abc import Generator
from typing import Any
from uuid import uuid4

from .compat.ui_contracts import ensure_ui_contracts
from .config import settings

ensure_ui_contracts()

from .storage import InMemoryStore  # noqa: E402

logger = logging.getLogger(__name__)

# Application-wide store instance (in-memory by default, overridden below)
store = InMemoryStore()

# Scoped session factory (set when using SQL backend)
_scoped_session = None

# A session belongs to one request, not to one thread. FastAPI runs sync
# endpoints in worker threads while the cleanup middleware runs in the event
# loop thread: with thread-local sessions every worker kept its session and its
# connection, and after 15 of them the pool was empty and the server hung.
# Outside a request (startup, scripts, tests calling routers directly) the
# thread stays the scope.
_request_scope: contextvars.ContextVar[str | None] = contextvars.ContextVar("db_request_scope", default=None)
# These built-ins are used by the application's read-only SQL aggregates/search.
# Unknown functions remain private: a SELECT can invoke a writing function.
_READ_FUNCTIONS = frozenset({"coalesce", "count", "sum", "min", "max", "round", "length", "lower"})
_READ_RELEASE_CHECK = object()       # only our server-side read diagnostic may bypass function conservatism


def _session_scope() -> object:
    return _request_scope.get() or threading.get_ident()


def begin_request_scope() -> contextvars.Token:
    """Give the current request its own DB session; pass the token to end_request_scope."""
    return _request_scope.set(uuid4().hex)


def end_request_scope(token: contextvars.Token) -> None:
    """Close the request's session (its connection goes back to the pool) and leave the scope."""
    try:
        cleanup_session()
    finally:
        _request_scope.reset(token)


def release_request_read_connection(source: Any) -> bool:
    """Return a clean middleware read connection before an owned write unit starts.

    Request validation can already hold a pooled connection. A second session for
    the atomic write must not wait for that first connection while every other
    writer does the same. Only this request's registered, tracked AUTOBEGIN read
    is disposable; explicit transactions and caller-owned sessions stay intact.
    The write unit must repeat its authoritative actor/scope/revision checks.
    Raw DBAPI BEGIN/SET transaction or session controls are outside this disposable
    middleware-read contract: use Session.begin() or a caller-owned connection.
    """
    from sqlalchemy.engine import Engine
    from sqlalchemy.orm import SessionTransactionOrigin

    from . import concurrency

    registry = _scoped_session
    if (_request_scope.get() is None or registry is None or not concurrency._tracking
            or registry.registry.scopefunc is not _session_scope or not registry.registry.has()):
        return False
    db = registry.registry()
    candidate = getattr(source, "db", source)
    if candidate is not registry and candidate is not db:
        return False
    transaction = db.get_transaction()
    if (transaction is None or transaction.origin is not SessionTransactionOrigin.AUTOBEGIN
            or db.info.get("request_read_connection_guard") is not transaction
            or not db.is_active or db.in_nested_transaction()
            or db.new or db.dirty or db.deleted
            or db.info.get("changed_tables") or db.info.get("cache_pending_write")
            or db.info.get("scoped_writer")):
        return False
    # A Connection bind can belong to another transaction outside this Session.
    if not isinstance(db.get_bind(), Engine):
        return False
    connection = db.connection()
    if connection.dialect.name == "sqlite":
        import sqlite3

        driver = connection.connection.driver_connection
        if not isinstance(driver, sqlite3.Connection) or driver.in_transaction:
            return False
    elif connection.dialect.name == "postgresql":
        if connection.get_isolation_level() not in {"READ COMMITTED", "AUTOCOMMIT"}:
            return False
        from sqlalchemy import and_, column, exists, func, or_, select, table

        # Raw DBAPI cursor writes bypass all SQLAlchemy execution hooks. An
        # assigned XID or nontrivial caller lock makes this transaction private.
        # Both diagnostics share one read; observing the XID does not allocate it.
        activity = table("pg_locks", column("pid"), column("granted"), column("locktype"), column("mode"),
                         schema="pg_catalog")
        caller_locks = exists().where(
            activity.c.pid == func.pg_catalog.pg_backend_pid(), activity.c.granted.is_(True),
            or_(activity.c.locktype == "advisory",
                and_(activity.c.locktype == "relation", activity.c.mode != "AccessShareLock")))
        check = select(func.pg_catalog.pg_current_xact_id_if_assigned(), caller_locks).execution_options(
            request_read_release_check=_READ_RELEASE_CHECK)
        xid, locked = connection.execute(check).one()
        if xid is not None or locked:
            db.info["cache_pending_write"] = True
            concurrency.note_change()
            return False
    else:
        return False
    db.rollback()       # returns the connection; the same request Session can be reused later
    return True


def _guard_request_read_connection(db: Any, transaction: Any, connection: Any) -> None:
    """Track SQL on exactly the request connection, including direct Connection DML.

    Session execution hooks cannot see ``session.connection().exec_driver_sql``.
    Treat uncompiled SQL as unknown, and preserve that evidence through the
    existing cache guard's outer commit/rollback fence.
    """
    from sqlalchemy import event
    from sqlalchemy.sql import visitors
    from sqlalchemy.sql.elements import TextClause
    from sqlalchemy.sql.functions import FunctionElement

    registry = _scoped_session
    if (_request_scope.get() is None or registry is None or transaction.parent is not None
            or registry.registry.scopefunc is not _session_scope or not registry.registry.has()
            or registry.registry() is not db):
        return
    db.info["request_read_connection_guard"] = transaction

    def before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
        compiled = context.compiled
        expression = compiled.statement if compiled is not None else None
        diagnostic = context.execution_options.get("request_read_release_check") is _READ_RELEASE_CHECK

        def read_function(node):
            name = str(getattr(node, "name", "")).lower()
            packages = getattr(node, "packagenames", ())
            catalog = not packages or (conn.dialect.name == "postgresql" and packages == ("pg_catalog",))
            return catalog and (name in _READ_FUNCTIONS or (conn.dialect.name == "sqlite" and name == "immo_lower"))

        readonly = expression is not None and getattr(expression, "is_select", False) and not any(
            getattr(node, "is_dml", False) or isinstance(node, TextClause)
            or (isinstance(node, FunctionElement) and not diagnostic and not read_function(node))
            or getattr(node, "_for_update_arg", None) is not None for node in visitors.iterate(expression))
        if not readonly:
            from . import concurrency

            db.info["cache_pending_write"] = True
            concurrency.note_change()

    event.listen(connection, "before_cursor_execute", before_cursor_execute)


def _track_request_read_connections() -> None:
    from sqlalchemy import event
    from sqlalchemy.orm import Session

    event.listen(Session, "after_begin", _guard_request_read_connection)

# Use SQLAlchemy store for all databases including SQLite (default).
# InMemoryStore is only used when sqlite_persistent_store is explicitly False.
_database_url = settings.database_url
_use_sql_store = bool(_database_url) and (
    "sqlite" not in _database_url or settings.sqlite_persistent_store
)

if _use_sql_store:
    from .db.schema_state import SchemaUpgradeRequired

    try:
        from sqlalchemy.orm import scoped_session

        from .db.session import SessionLocal, create_tables
        from .repositories import SQLAlchemyStore

        # Initialises an empty database; an existing one must already be at the
        # Alembic head (explicit upgrade: python -m backend.upgrade).
        create_tables()
        # One session per request (see _session_scope), so concurrent requests
        # never share state and every request returns its connection.
        _scoped_session = scoped_session(SessionLocal, scopefunc=_session_scope)
        store = SQLAlchemyStore(_scoped_session)  # type: ignore[assignment, arg-type]
        from .concurrency import track_database_changes

        track_database_changes()

        # Enable SQL-backed user and audit storage for configured SQL store.
        from .audit import enable_sql_audit
        from .auth import enable_sql_users

        enable_sql_users(SessionLocal)
        enable_sql_audit(SessionLocal)

        logger.info("SQL backend initialized successfully (url=%s...)", _database_url[:30])
    except SchemaUpgradeRequired as exc:
        # never hidden behind the in-memory fallback: the data exists, it needs the explicit upgrade
        logger.critical("Start refused: %s", exc)
        raise
    except Exception:
        if not settings.allow_inmemory_fallback:
            raise RuntimeError(
                "Failed to initialize SQL backend and ALLOW_INMEMORY_FALLBACK=false. "
                "Fix DATABASE_URL or database connectivity, or set "
                "ALLOW_INMEMORY_FALLBACK=true to allow non-persistent fallback."
            )
        logger.exception(
            "Failed to initialize SQL backend — falling back to InMemoryStore. "
            "Data will NOT be persisted! Fix DATABASE_URL or database connectivity."
        )
        store = InMemoryStore()
        _scoped_session = None
else:
    if not settings.allow_inmemory_fallback:
        raise RuntimeError(
            "InMemoryStore is not allowed when ALLOW_INMEMORY_FALLBACK=false. "
            "Set DATABASE_URL and SQLITE_PERSISTENT_STORE=true for production."
        )
    logger.info("Using InMemoryStore — data will NOT be persisted across restarts.")

# Log active store type for clarity
logger.info("Active store: %s", type(store).__name__)


def get_store():
    """FastAPI dependency that provides the data store."""
    return store


def cleanup_session():
    """Remove the scoped session after a request completes.

    Must be called after each request to return the session to the pool
    and prevent stale state from leaking across requests.

    IMPORTANT: We rollback before removing to ensure any failed transaction
    state is cleared. Without this, a single IntegrityError (e.g. FK constraint
    on delete) would poison the session for ALL subsequent requests, causing
    cascading 500 errors until the application is restarted.

    Safe to call even if the session is in a bad state.
    """
    if _scoped_session is not None:
        try:
            _scoped_session.rollback()
        except Exception:
            logger.debug("Rollback during cleanup (expected if no active tx).", exc_info=True)
        try:
            _scoped_session.remove()
        except Exception:
            logger.warning("Failed to remove scoped session — ignoring.", exc_info=True)


def get_db() -> Generator:
    """FastAPI dependency that provides a per-request database session."""
    if not _use_sql_store:
        yield None
        return

    from .db.session import SessionLocal

    db = SessionLocal()
    try:
        yield db
    except Exception:
        logger.warning("Exception during DB session — rolling back.", exc_info=True)
        db.rollback()
        raise
    finally:
        db.close()


_track_request_read_connections()
