"""Shared dependencies for the ImmoManager Pro API."""

from .storage import InMemoryStore

# Application-wide store instance
store = InMemoryStore()


def get_store() -> InMemoryStore:
    """FastAPI dependency that provides the data store."""
    return store
