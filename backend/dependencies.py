"""Shared dependencies for the ImmoManager Pro API.

Supports two storage backends:
  - InMemoryStore (for tests only when sqlite_persistent_store=False)
  - SQLAlchemyStore (default for all database URLs including SQLite)

Set DATABASE_URL to configure the database. SQLite is the default.

Error handling:
  - SQL backend initialization is wrapped in try/except with fallback
    to InMemoryStore so the application always starts.
  - cleanup_session() is safe to call even if the session is corrupted.
"""

import logging
from collections.abc import Generator

from .config import settings
from .storage import InMemoryStore

logger = logging.getLogger(__name__)

# Application-wide store instance (in-memory by default, overridden below)
store = InMemoryStore()

# Scoped session factory (set when using SQL backend)
_scoped_session = None

# Use SQLAlchemy store for all databases including SQLite (default).
# InMemoryStore is only used when sqlite_persistent_store is explicitly False.
_database_url = settings.database_url
_use_sql_store = bool(_database_url) and (
    "sqlite" not in _database_url or settings.sqlite_persistent_store
)

if _use_sql_store:
    try:
        from sqlalchemy.orm import scoped_session

        from .db.session import SessionLocal, create_tables
        from .repositories import SQLAlchemyStore

        create_tables()
        # Use scoped_session for thread-safe, request-scoped sessions.
        # Each thread gets its own session, preventing cross-request state mixing.
        _scoped_session = scoped_session(SessionLocal)
        store = SQLAlchemyStore(_scoped_session)  # type: ignore[assignment]

        # Enable SQL-backed user and audit storage for configured SQL store.
        from .audit import enable_sql_audit
        from .auth import enable_sql_users

        enable_sql_users(SessionLocal)
        enable_sql_audit(SessionLocal)

        logger.info("SQL backend initialized successfully (url=%s...)", _database_url[:30])
    except Exception:
        logger.exception(
            "Failed to initialize SQL backend — falling back to InMemoryStore. "
            "Data will NOT be persisted! Fix DATABASE_URL or database connectivity."
        )
        store = InMemoryStore()
        _scoped_session = None
else:
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
