"""Shared dependencies for the ImmoManager Pro API.

Supports two storage backends:
  - InMemoryStore (default, for tests and development)
  - SQLAlchemyStore (when DATABASE_URL env var is set)

Set DATABASE_URL to enable persistent database storage.
"""

import os
from collections.abc import Generator

from .storage import InMemoryStore

# Application-wide store instance (in-memory by default)
store = InMemoryStore()

# If DATABASE_URL is configured, use SQLAlchemy-backed store
_database_url = os.getenv("DATABASE_URL")
if _database_url:
    from .db.session import SessionLocal, create_tables
    from .repositories import SQLAlchemyStore

    create_tables()
    _session = SessionLocal()
    store = SQLAlchemyStore(_session)  # type: ignore[assignment]

    # Also enable SQL-backed user and audit storage
    from .auth import enable_sql_users
    from .audit import enable_sql_audit
    enable_sql_users(SessionLocal)
    enable_sql_audit(SessionLocal)


def get_store():
    """FastAPI dependency that provides the data store."""
    return store


def get_db() -> Generator:
    """FastAPI dependency that provides a per-request database session.

    Use this for endpoints that need direct DB access.
    For most endpoints, use get_store() which wraps the session.
    """
    if not _database_url:
        yield None
        return

    from .db.session import SessionLocal

    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
