"""Tests for admin backup/restore behavior."""

from backend.models import PortfolioCreate
from backend.routers import admin


def _reset_store() -> None:
    admin._clear_store_data()


def test_create_backup_uses_active_store_snapshot(tmp_path, monkeypatch):
    monkeypatch.setattr(admin, "_BACKUP_DIR", tmp_path)
    _reset_store()
    try:
        admin.store.create_portfolio(PortfolioCreate(name="Test Portfolio"))

        result = admin.create_backup()

        backup_path = tmp_path / result["backup"]
        assert result["backup"].endswith(".json")
        assert backup_path.exists()
        assert result["size_bytes"] > 0
    finally:
        _reset_store()


def test_restore_json_backup_replaces_store_data(tmp_path, monkeypatch):
    monkeypatch.setattr(admin, "_BACKUP_DIR", tmp_path)
    _reset_store()
    try:
        admin.store.create_portfolio(PortfolioCreate(name="Original"))
        backup = admin.create_backup()

        _reset_store()
        admin.store.create_portfolio(PortfolioCreate(name="Different"))

        restored = admin.restore_backup(backup["backup"])

        assert restored["restored_from"] == backup["backup"]
        names = [p.name for p in admin.store.list_portfolios()]
        assert names == ["Original"]
    finally:
        _reset_store()
