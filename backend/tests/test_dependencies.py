"""Tests for dependency wiring and backend selection."""

import importlib

from backend import audit, auth, config
import backend.dependencies as dependencies


def test_sqlite_url_uses_sqlalchemy_store(monkeypatch):
    original_url = config.settings.database_url
    monkeypatch.setattr(config.settings, "database_url", "sqlite:///:memory:")

    deps = importlib.reload(dependencies)

    assert deps._scoped_session is not None
    assert deps.store.__class__.__name__ == "SQLAlchemyStore"

    db_gen = deps.get_db()
    db = next(db_gen)
    assert db is not None
    db_gen.close()

    # Avoid cross-test state pollution from SQL-backed globals.
    auth._user_store = auth.InMemoryUserStore()
    audit._audit_store = audit.InMemoryAuditStore()

    config.settings.database_url = original_url
    importlib.reload(dependencies)
