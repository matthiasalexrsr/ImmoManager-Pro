"""Shared dependencies for the ImmoManager Pro API.

Supports two storage backends:
  - InMemoryStore (default, for tests and development)
  - SQLAlchemyStore (when DATABASE_URL env var is set)

Set DATABASE_URL to enable persistent database storage.
"""

import os

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


def get_store():
    """FastAPI dependency that provides the data store."""
    return store
