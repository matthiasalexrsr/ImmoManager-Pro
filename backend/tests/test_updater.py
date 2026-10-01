"""Update rollback, WAL snapshot and truthful restart regression cases."""

import json
import sqlite3
import subprocess
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
from threading import Barrier

import pytest

from backend import updater
from backend.config import Environment
from backend.tests.test_frontend_build import write_dist

_REAL_INSTALL = updater._install_dependencies
_REAL_MIGRATE = updater._run_migrations
_REAL_REBUILD = updater._rebuild_frontend
_REAL_STASH = updater._stash_changes


@pytest.fixture
def isolated_update(tmp_path, monkeypatch):
    project = tmp_path / "checkout"
    project.mkdir()
    (project / "frontend").mkdir()
    (project / "requirements.txt").write_text("original requirements")
    (project / "pyproject.toml").write_text('[project]\nversion = "1.0.0"\n')
    dist = project / "frontend" / "dist"
    write_dist(dist, "previous UI")
    runtime = tmp_path / "runtime data"
    runtime.mkdir()
    backups = runtime / "backups"
    updates = runtime / ".updates"
    database = runtime / "database with spaces.db"
    with closing(sqlite3.connect(database)) as connection:
        connection.execute("CREATE TABLE business_data (value TEXT)")
        connection.execute("INSERT INTO business_data VALUES ('before')")
        connection.commit()
    for name, value in {"_PROJECT_ROOT": project, "_RUNTIME_DIR": runtime, "_BACKUP_DIR": backups,
                        "_UPDATE_DIR": updates, "_LOCK_FILE": updates / "update.lock", "_HISTORY_FILE": updates / "history.json",
                        "_FRONTEND_DIST": dist, "_lock_token": None}.items():
        monkeypatch.setattr(updater, name, value)
    monkeypatch.setattr(updater.settings, "database_url", f"sqlite:///{database.as_posix()}")
    monkeypatch.setattr(updater.settings, "data_dir", str(runtime))
    monkeypatch.setattr(updater.settings, "backup_dir", str(backups))
    monkeypatch.setattr(updater.settings, "environment", Environment.development)
    monkeypatch.setattr(updater.settings, "update_repo_url", "https://github.com/example/project")
    monkeypatch.setattr(updater.settings, "app_version", "1.0.0")
    monkeypatch.setattr(updater, "_is_git_repo", lambda: True)
    monkeypatch.setattr(updater, "_get_current_branch", lambda: "main")
    current = {"commit": "previous-commit"}
    calls = []
    def run_git(*args, **kwargs):
        calls.append(args)
        if args[0] in {"merge", "checkout"}:
            current["commit"] = "updated-commit"
            (project / "pyproject.toml").write_text('[project]\nversion = "1.1.0"\n')
            (project / "requirements.txt").write_text("new requirements")
        elif args[0] == "reset":
            current["commit"] = "previous-commit"
            (project / "pyproject.toml").write_text('[project]\nversion = "1.0.0"\n')
            (project / "requirements.txt").write_text("original requirements")
        return subprocess.CompletedProcess(args, 0, stdout="", stderr="")
    monkeypatch.setattr(updater, "_run_git", run_git)
    monkeypatch.setattr(updater, "_get_current_commit", lambda: current["commit"])
    monkeypatch.setattr(updater, "_stash_changes", lambda: False)
    monkeypatch.setattr(updater, "_create_pre_update_backup", lambda: "backup.json")
    monkeypatch.setattr(updater, "_install_dependencies", lambda: (True, "dependencies verified"))
    monkeypatch.setattr(updater, "_rebuild_frontend", lambda: (True, "frontend verified"))
    monkeypatch.setattr(updater, "_run_migrations", lambda: (True, "migration verified"))
    return {"project": project, "runtime": runtime, "backups": backups, "database": database, "dist": dist, "git_calls": calls}


def value(database):
    with closing(sqlite3.connect(database)) as connection:
        return connection.execute("SELECT value FROM business_data").fetchone()[0]


def test_online_wal_snapshot_contains_committed_pages_without_checkpoint(isolated_update):
    database = isolated_update["database"]
    with closing(sqlite3.connect(database)) as live:
        live.execute("PRAGMA journal_mode=WAL")
        live.execute("PRAGMA wal_autocheckpoint=0")
        live.execute("INSERT INTO business_data VALUES ('committed in WAL')")
        live.commit()
        assert Path(str(database) + "-wal").is_file()
        snapshot = updater._create_db_snapshot()
        assert snapshot
        with closing(sqlite3.connect(isolated_update["backups"] / snapshot)) as restored:
            assert restored.execute("SELECT value FROM business_data").fetchall() == [("before",), ("committed in WAL",)]
        assert value(database) == "before"


def test_snapshot_restore_refuses_live_database_and_verifies_offline_restore(isolated_update):
    snapshot = updater._create_db_snapshot()
    with closing(sqlite3.connect(isolated_update["database"])) as connection:
        connection.execute("UPDATE business_data SET value='newer'")
        connection.commit()
    assert not updater._restore_db_snapshot(snapshot)
    assert value(isolated_update["database"]) == "newer"
    assert updater._restore_db_snapshot(snapshot, offline=True)
    assert value(isolated_update["database"]) == "before"


def test_corrupt_snapshot_is_rejected_without_overwriting_live_data(isolated_update):
    snapshot = updater._create_db_snapshot()
    with (isolated_update["backups"] / snapshot).open("ab") as stream:
        stream.write(b"corrupted")
    assert not updater._restore_db_snapshot(snapshot, offline=True)
    assert value(isolated_update["database"]) == "before"
    assert not updater._restore_db_snapshot("../database with spaces.db", offline=True)


def test_failed_pip_install_aborts_before_build_and_migration_and_rolls_back_dependencies(isolated_update, monkeypatch):
    installations = []
    def install():
        installations.append((isolated_update["project"] / "requirements.txt").read_text())
        return (False, "installation failed") if len(installations) == 1 else (True, "old dependencies verified")
    monkeypatch.setattr(updater, "_install_dependencies", install)
    monkeypatch.setattr(updater, "_rebuild_frontend", lambda: pytest.fail("Frontend must not build after pip failure"))
    monkeypatch.setattr(updater, "_run_migrations", lambda: pytest.fail("DB must not migrate after pip failure"))
    result = updater.apply_update(offline=True)
    assert not result["success"] and result["rollback_performed"]
    assert result["rollback_completed"] and result["startup_ready"]
    assert not result["manual_recovery_required"]
    assert installations == ["new requirements", "original requirements"]
    assert "previous UI" in (isolated_update["dist"] / "assets" / "app.js").read_text()
    assert not updater.is_update_locked()


def test_failed_rollback_dependencies_never_claim_startup_ready(isolated_update, monkeypatch):
    monkeypatch.setattr(updater, "_install_dependencies", lambda: (False, "network unavailable"))
    result = updater.apply_update(offline=True)
    assert not result["success"] and result["rollback_performed"]
    assert not result["rollback_completed"] and not result["startup_ready"]
    assert result["manual_recovery_required"]
    assert "unvollständig" in result["message"]


def test_frontend_failure_preserves_previous_generated_dist_and_skips_migration(isolated_update, monkeypatch):
    def failed_frontend():
        (isolated_update["dist"] / "assets" / "app.js").write_text("partial bad output")
        return False, "npm failed"
    monkeypatch.setattr(updater, "_rebuild_frontend", failed_frontend)
    monkeypatch.setattr(updater, "_run_migrations", lambda: pytest.fail("DB must not migrate before a valid frontend exists"))
    result = updater.apply_update(offline=True)
    assert not result["success"] and result["rollback_completed"]
    assert "previous UI" in (isolated_update["dist"] / "assets" / "app.js").read_text()
    assert value(isolated_update["database"]) == "before"


@pytest.mark.parametrize("offline", [False, True])
def test_migration_failure_reports_database_recovery_honestly(isolated_update, monkeypatch, offline):
    def failed_migration():
        with closing(sqlite3.connect(isolated_update["database"])) as connection:
            connection.execute("UPDATE business_data SET value='partially migrated'")
            connection.commit()
        return False, "migration failed"
    monkeypatch.setattr(updater, "_run_migrations", failed_migration)
    result = updater.apply_update(offline=offline)
    if not offline:
        assert result["offline_update_required"] and not result["rollback_performed"]
        assert isolated_update["git_calls"] == []
        assert value(isolated_update["database"]) == "before"
        return
    assert not result["success"] and result["rollback_performed"]
    assert result["rollback_completed"] == offline
    assert result["startup_ready"] == offline
    assert result["database_restore_required"] != offline
    assert result["manual_recovery_required"] != offline
    assert value(isolated_update["database"]) == ("before" if offline else "partially migrated")


def test_backup_failure_aborts_before_stash_or_destructive_reset(isolated_update, monkeypatch):
    (isolated_update["project"] / "local-notes.txt").write_text("keep local work")
    monkeypatch.setattr(updater, "_create_pre_update_backup", lambda: None)
    monkeypatch.setattr(updater, "_stash_changes", lambda: pytest.fail("No code changes before successful backup"))
    result = updater.apply_update(offline=True)
    assert not result["success"] and not result["rollback_performed"]
    assert not any(command[0] == "reset" for command in isolated_update["git_calls"])
    assert (isolated_update["project"] / "local-notes.txt").read_text() == "keep local work"


def test_failed_sqlite_snapshot_aborts_update_even_when_json_export_succeeded(isolated_update, monkeypatch):
    monkeypatch.setattr(updater, "_create_db_snapshot", lambda: None)
    result = updater.apply_update(offline=True)
    assert not result["success"]
    assert isolated_update["git_calls"] == []
    assert "Snapshot" in result["message"]


def test_success_requires_verified_dependencies_frontend_and_migration_and_manual_restart(isolated_update, monkeypatch):
    operations = []
    monkeypatch.setattr(updater, "_install_dependencies", lambda: (operations.append("dependencies") or True, "verified"))
    monkeypatch.setattr(updater, "_rebuild_frontend", lambda: (operations.append("frontend") or True, "verified"))
    monkeypatch.setattr(updater, "_run_migrations", lambda: (operations.append("migration") or True, "verified"))
    result = updater.apply_update(offline=True)
    assert result["success"] and result["restart_required"] and result["startup_ready"]
    assert result["new_version"] == "1.1.0"
    assert operations == ["dependencies", "frontend", "migration"]
    assert updater.get_update_history()[0]["success"]
    assert "manuell" in result["message"]
    restart = updater.signal_restart()
    assert not restart["restart_signaled"] and restart["manual_restart_required"]
    assert not (updater._UPDATE_DIR / "restart_requested").exists()


def test_missing_npm_is_not_reported_as_success_by_updater(isolated_update, monkeypatch):
    from backend import frontend_build
    monkeypatch.setattr(frontend_build.shutil, "which", lambda command: None)
    (isolated_update["project"] / "frontend" / "package.json").write_text("{}")
    ok, message = _REAL_REBUILD()
    assert not ok and "Node.js/npm fehlt" in message


def test_update_lock_is_atomic_and_never_stolen_based_on_age(isolated_update):
    barrier = Barrier(2)
    def acquire():
        barrier.wait(timeout=10)
        return updater._acquire_lock()
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(acquire), executor.submit(acquire)]
        assert sorted(future.result(timeout=20) for future in futures) == [False, True]
    assert updater.is_update_locked()
    updater._release_lock()
    updater._LOCK_FILE.write_text(json.dumps({"locked_at": "2000-01-01T00:00:00+00:00", "pid": 999999}))
    assert updater.is_update_locked() and not updater._acquire_lock()


def test_release_lock_cannot_delete_another_owners_lock(isolated_update):
    assert updater._acquire_lock()
    updater._LOCK_FILE.write_text(json.dumps({"token": "another-owner"}))
    updater._release_lock()
    assert updater._LOCK_FILE.exists()


def test_dependency_install_checks_pip_install_and_pip_check(isolated_update, monkeypatch):
    calls = []
    def run(command, **kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(command, 0 if len(calls) == 1 else 1, stdout="", stderr="broken dependency")
    monkeypatch.setattr(updater.subprocess, "run", run)
    ok, message = _REAL_INSTALL()
    assert not ok and "Exit 1" in message
    assert calls[0][3] == "install" and calls[1][3] == "check"


def test_migration_runs_new_code_in_subprocess_with_exact_runtime_database(isolated_update, monkeypatch):
    calls = []
    def run(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 1, stdout="", stderr="bad migration")
    monkeypatch.setattr(updater.subprocess, "run", run)
    assert not _REAL_MIGRATE()[0]
    assert "alembic" in calls[0][0]
    assert calls[0][1]["env"]["DATABASE_URL"] == updater.settings.database_url
    assert calls[0][1]["cwd"] == isolated_update["project"]


def test_failed_frontend_restore_retains_previous_assets_for_manual_recovery(isolated_update, monkeypatch):
    monkeypatch.setattr(updater, "_rebuild_frontend", lambda: (False, "compile error"))
    monkeypatch.setattr(updater, "_restore_frontend", lambda saved: False)
    result = updater.apply_update(offline=True)
    assert not result["success"] and not result["startup_ready"]
    assert result["frontend_restore_required"] and result["frontend_backup_name"]
    preserved = updater._UPDATE_DIR / result["frontend_backup_name"] / "dist" / "assets" / "app.js"
    assert "previous UI" in preserved.read_text()


def test_live_rollback_refuses_database_overwrite_and_requires_manual_recovery(isolated_update):
    snapshot = updater._create_db_snapshot()
    with closing(sqlite3.connect(isolated_update["database"])) as connection:
        connection.execute("UPDATE business_data SET value='newer committed records'")
        connection.commit()
    result = {"steps": [], "rollback_performed": False}
    updater._rollback(None, False, result, reset_code=False, db_snapshot=snapshot,
                      database_touched=True, offline=False)
    assert not result["startup_ready"] and result["manual_recovery_required"]
    assert result["database_restore_required"]
    assert value(isolated_update["database"]) == "newer committed records"


def test_stash_does_not_pop_a_previous_user_stash_when_no_new_stash_was_created(isolated_update, monkeypatch):
    calls = []
    def git(*arguments, **kwargs):
        calls.append(arguments)
        output = "?? local-work.txt" if arguments[0] == "status" else "previous-user-stash" if arguments[0] == "rev-parse" else "No local changes to save"
        return subprocess.CompletedProcess(arguments, 0, stdout=output, stderr="")
    monkeypatch.setattr(updater, "_run_git", git)
    assert not _REAL_STASH()
    assert not any(arguments[:2] == ("stash", "pop") for arguments in calls)


def test_check_result_advertises_offline_maintenance_without_network(isolated_update, monkeypatch):
    monkeypatch.setattr(updater.settings, "update_repo_url", "")
    result = updater.check_for_updates()
    assert result["live_apply_supported"] is False
    assert "backend.maintenance" in result["maintenance_hint"]
