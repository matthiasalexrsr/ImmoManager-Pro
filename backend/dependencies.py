"""Shared dependencies for the ImmoManager Pro API.

Supports two storage backends:
  - InMemoryStore (default, for tests and development)
  - SQLAlchemyStore (when DATABASE_URL env var is set)

Set DATABASE_URL to enable persistent database storage.
"""

from collections.abc import Generator

from .config import settings
from .storage import InMemoryStore

# Application-wide store instance (in-memory by default)
store = InMemoryStore()

# Scoped session factory (set when using SQL backend)
_scoped_session = None

# If DATABASE_URL is configured (and not the default SQLite), use SQLAlchemy store
_database_url = settings.database_url
if _database_url and "sqlite" not in _database_url:
    from sqlalchemy.orm import scoped_session

    from .db.session import SessionLocal, create_tables
    from .repositories import SQLAlchemyStore

    create_tables()
    # Use scoped_session for thread-safe, request-scoped sessions.
    # Each thread gets its own session, preventing cross-request state mixing.
    _scoped_session = scoped_session(SessionLocal)
    store = SQLAlchemyStore(_scoped_session)  # type: ignore[assignment]

    # Also enable SQL-backed user and audit storage
    from .auth import enable_sql_users
    from .audit import enable_sql_audit
    enable_sql_users(SessionLocal)
    enable_sql_audit(SessionLocal)


def get_store():
    """FastAPI dependency that provides the data store."""
    return store


def cleanup_session():
    """Remove the scoped session after a request completes.

    Must be called after each request to return the session to the pool
    and prevent stale state from leaking across requests.
    """
    if _scoped_session is not None:
        _scoped_session.remove()


def get_db() -> Generator:
    """FastAPI dependency that provides a per-request database session."""
    if not _database_url or "sqlite" in _database_url:
        yield None
        return

    from .db.session import SessionLocal

    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
