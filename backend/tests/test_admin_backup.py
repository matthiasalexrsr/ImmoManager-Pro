"""Tests for admin backup/restore behavior."""

import sqlite3

import pytest
from fastapi import HTTPException

from backend.models import PortfolioCreate
from backend.routers import admin as legacy_admin
from backend.routers import admin_runtime as admin


def _reset_store() -> None:
    legacy_admin._clear_store_data()


def test_create_backup_uses_active_store_snapshot(tmp_path, monkeypatch):
    monkeypatch.setattr(admin, "_BACKUP_DIR", tmp_path)
    _reset_store()
    try:
        legacy_admin.store.create_portfolio(PortfolioCreate(name="Test Portfolio"))

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
        legacy_admin.store.create_portfolio(PortfolioCreate(name="Original"))
        backup = admin.create_backup()

        _reset_store()
        legacy_admin.store.create_portfolio(PortfolioCreate(name="Different"))

        restored = admin.restore_backup(backup["backup"])

        assert restored["restored_from"] == backup["backup"]
        names = [p.name for p in legacy_admin.store.list_portfolios()]
        assert names == ["Original"]
    finally:
        _reset_store()


def test_restore_rejects_path_traversal(tmp_path, monkeypatch):
    monkeypatch.setattr(admin, "_BACKUP_DIR", tmp_path)

    try:
        admin.restore_backup("../outside.json")
        assert False, "Expected HTTPException"
    except HTTPException as exc:
        assert exc.status_code == 400


def _wal_database(path, rows):
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA wal_autocheckpoint=0")
    conn.execute("CREATE TABLE t (x INTEGER)")
    conn.executemany("INSERT INTO t VALUES (?)", [(i,) for i in range(rows)])
    conn.commit()
    return conn


def test_sqlite_restore_wins_over_live_wal(tmp_path, monkeypatch):
    """Regression: copying the file over a live WAL database was a silent no-op."""
    db_path = tmp_path / "live.db"
    live = _wal_database(db_path, 100)
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    backup = sqlite3.connect(backup_dir / "backup_old.db")
    live.backup(backup)
    backup.close()
    # The server keeps running and writes more; these pages stay in the WAL.
    live.executemany("INSERT INTO t VALUES (?)", [(i,) for i in range(100, 5000)])
    live.commit()

    monkeypatch.setattr(admin, "_BACKUP_DIR", backup_dir)
    monkeypatch.setattr(admin.settings, "database_url", f"sqlite:///{db_path}")
    result = admin.restore_backup("backup_old.db")

    assert live.execute("SELECT COUNT(*) FROM t").fetchone()[0] == 100
    live.close()
    reopened = sqlite3.connect(db_path)
    assert reopened.execute("SELECT COUNT(*) FROM t").fetchone()[0] == 100
    assert reopened.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    reopened.close()
    # The safety copy holds the pre-restore state, including WAL-only commits.
    safety = sqlite3.connect(backup_dir / result["safety_backup"])
    assert safety.execute("SELECT COUNT(*) FROM t").fetchone()[0] == 5000
    safety.close()


def test_sqlite_restore_rejects_non_database_file(tmp_path, monkeypatch):
    backup_dir = tmp_path / "backups"
    backup_dir.mkdir()
    (backup_dir / "backup_bad.db").write_text("not a database", encoding="utf-8")
    monkeypatch.setattr(admin, "_BACKUP_DIR", backup_dir)
    monkeypatch.setattr(admin.settings, "database_url", f"sqlite:///{tmp_path / 'live.db'}")
    with pytest.raises(HTTPException) as exc:
        admin.restore_backup("backup_bad.db")
    assert exc.value.status_code == 400
