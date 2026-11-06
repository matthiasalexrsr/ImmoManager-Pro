"""Release boundary and recoverability; all data/processes belong to this test."""
from __future__ import annotations

import inspect
import json
import os
import sqlite3
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Barrier

import pytest

from backend import updater
from backend.config import Environment, settings

OLD, NEW = "a" * 40, "b" * 40


def developer_apply():
    # Before the safety change there was no explicit developer-only contract.
    # Keep that baseline runnable so the same data-loss assertions reproduce red.
    if "developer_mode" in inspect.signature(updater.apply_update).parameters:
        return updater.apply_update("v2.1.0", developer_mode=True, expected_commit=NEW)
    return updater.apply_update("v2.1.0")


@pytest.fixture
def pipeline(tmp_path, monkeypatch):
    db = tmp_path / "own.db"
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE marker(value TEXT)")
        conn.execute("INSERT INTO marker VALUES ('before')")
    state = {"commit": OLD, "calls": [], "db": db}
    directory = tmp_path / "updates"
    monkeypatch.setattr(updater, "_UPDATE_DIR", directory)
    monkeypatch.setattr(updater, "_LOCK_FILE", directory / "update.lock")
    monkeypatch.setattr(updater, "_HISTORY_FILE", directory / "history.json")
    monkeypatch.setattr(updater, "_BACKUP_DIR", tmp_path / "backups")
    monkeypatch.setattr(updater, "_restart_pending", False)
    monkeypatch.setattr(updater, "_is_git_repo", lambda: True)
    monkeypatch.setattr(updater, "_stash_changes", lambda: False)
    monkeypatch.setattr(updater, "_has_uncommitted_changes", lambda: False)
    monkeypatch.setattr(updater, "_create_pre_update_backup", lambda: "verified-full.zip")
    monkeypatch.setattr(updater, "_install_dependencies", lambda: (True, "dependencies"))
    monkeypatch.setattr(updater, "_run_migrations", lambda: (True, "migrated"))
    monkeypatch.setattr(updater, "_rebuild_frontend", lambda: (True, "built"))
    monkeypatch.setattr(settings, "database_url", "sqlite:///" + db.as_posix())
    monkeypatch.setattr(settings, "environment", Environment.development)
    monkeypatch.setattr(settings, "update_repo_url", "https://github.com/test-owner/test-repo")
    monkeypatch.setattr(settings, "app_version", "2.0.0")
    monkeypatch.delattr(sys, "frozen", raising=False)

    def git(*args, **kwargs):
        state["calls"].append(tuple(args))
        output = ""
        if args[:2] == ("remote", "get-url"):
            output = "https://github.com/test-owner/test-repo.git"
        elif args[:2] == ("rev-parse", "--abbrev-ref"):
            output = "main"
        elif args[:2] == ("rev-parse", "HEAD"):
            output = state["commit"]
        elif args and args[0] == "rev-parse":
            output = NEW
        elif args and args[0] == "show":
            output = '[project]\nversion = "2.1.0"\n'
        elif args and args[0] in {"checkout", "merge"}:
            state["commit"] = NEW
        elif args[:2] == ("reset", "--hard"):
            state["commit"] = args[2]
        return subprocess.CompletedProcess(args, 0, output, "")
    monkeypatch.setattr(updater, "_run_git", git)
    return state


def values(path):
    with sqlite3.connect(path) as conn:
        return [row[0] for row in conn.execute("SELECT value FROM marker")]


def mutate(path):
    with sqlite3.connect(path) as conn:
        conn.execute("INSERT INTO marker VALUES ('after')")
    return True, "migrated"


def test_customer_apply_never_runs_source_promotion(pipeline):
    result = updater.apply_update()
    assert not result["success"] and pipeline["commit"] == OLD
    assert not pipeline["calls"]


def test_failed_required_snapshot_stops_before_fetch(pipeline, monkeypatch):
    monkeypatch.setattr(updater, "_create_db_snapshot", lambda: None)
    result = developer_apply()
    assert not result["success"]
    assert not any(call[0] == "fetch" for call in pipeline["calls"])
    assert pipeline["commit"] == OLD and values(pipeline["db"]) == ["before"]


def test_exception_after_migration_never_reopens_old_code_on_new_data(pipeline, monkeypatch):
    def interrupted_migration():
        mutate(pipeline["db"])
        raise RuntimeError("synthetic interruption after mutation")
    monkeypatch.setattr(updater, "_run_migrations", interrupted_migration)
    result = developer_apply()
    assert not result["success"]
    assert pipeline["commit"] == OLD and values(pipeline["db"]) == ["before"]


def test_history_failure_has_a_consistent_commit_point(pipeline, monkeypatch):
    monkeypatch.setattr(updater, "_run_migrations", lambda: mutate(pipeline["db"]))
    monkeypatch.setattr(updater, "_record_update", lambda entry: (_ for _ in ()).throw(OSError("synthetic history")))
    result = developer_apply()
    assert result["success"] and result["restart_required"]
    assert pipeline["commit"] == NEW and values(pipeline["db"]) == ["before", "after"]
    assert updater.writes_blocked() and updater._transaction_state()["phase"] == "installed"


def test_failed_database_rollback_keeps_writes_fenced(pipeline, monkeypatch):
    monkeypatch.setattr(updater, "_run_migrations", lambda: (False, "synthetic migration failure"))
    monkeypatch.setattr(updater, "_restore_db_snapshot", lambda _: False)
    result = developer_apply()
    assert not result["success"] and updater.writes_blocked()


def test_postgres_is_not_automatically_reverted_to_old_code(pipeline, monkeypatch):
    monkeypatch.setattr(settings, "database_url", "postgresql://synthetic.invalid/never-connect")
    result = developer_apply()
    assert not result["success"] and not pipeline["calls"]


@pytest.mark.parametrize("bad_commit", [None, "b" * 39, "b" * 41, "B" * 40, "origin/main", "--help"])
def test_developer_commit_must_be_an_explicit_immutable_sha(pipeline, bad_commit):
    result = updater.apply_update("v2.1.0", developer_mode=True, expected_commit=bad_commit)
    assert not result["success"] and not pipeline["calls"]


@pytest.mark.parametrize("tag", ["main", "v1.9.9", "v2.0.0", "../v2.1.0", "v2.1.0 --all", "v2.1.0+../bad"])
def test_developer_tag_cannot_be_a_branch_option_or_downgrade(pipeline, tag):
    result = updater.apply_update(tag, developer_mode=True, expected_commit=NEW)
    assert not result["success"] and not pipeline["calls"]


@pytest.mark.parametrize("change", ["wrong_commit", "wrong_version", "not_fast_forward"])
def test_fetched_tag_commit_version_and_ancestry_are_all_checked(pipeline, monkeypatch, change):
    original = updater._run_git

    def git(*args, **kwargs):
        result = original(*args, **kwargs)
        if change == "wrong_commit" and args[:2] == ("rev-parse", "--verify"):
            return subprocess.CompletedProcess(args, 0, "c" * 40, "")
        if change == "wrong_version" and args[0] == "show":
            return subprocess.CompletedProcess(args, 0, '[project]\nversion = "9.9.9"\n', "")
        if change == "not_fast_forward" and args[0] == "merge-base":
            return subprocess.CompletedProcess(args, 1, "", "")
        return result
    monkeypatch.setattr(updater, "_run_git", git)
    result = developer_apply()
    assert not result["success"] and pipeline["commit"] == OLD
    assert not any(call[0] == "merge" for call in pipeline["calls"])
    assert values(pipeline["db"]) == ["before"] and updater.writes_blocked() is None


def test_developer_fetch_and_merge_are_bound_to_exact_tag_and_commit(pipeline):
    result = developer_apply()
    assert result["success"]
    assert ("fetch", "--no-tags", "origin", "refs/tags/v2.1.0") in pipeline["calls"]
    assert ("merge", "--ff-only", NEW) in pipeline["calls"]
    assert not any("origin/main" in call or "pull" in call for call in pipeline["calls"])


def test_local_changes_are_never_stashed_or_replaced(pipeline, monkeypatch):
    monkeypatch.setattr(updater, "_has_uncommitted_changes", lambda: True)
    result = developer_apply()
    assert not result["success"] and not any(call[0] in {"fetch", "stash", "reset", "merge"} for call in pipeline["calls"])


def test_tampered_snapshot_cannot_replace_the_current_database(pipeline):
    snapshot = updater._create_db_snapshot()
    assert snapshot
    mutate(pipeline["db"])
    with (updater._BACKUP_DIR / snapshot).open("ab") as handle:
        handle.write(b"synthetic tampering")
    assert not updater._restore_db_snapshot(snapshot)
    assert values(pipeline["db"]) == ["before", "after"]


@pytest.mark.parametrize("metadata", [{"unexpected": "object"}, ["wrong entry"], None])
def test_corrupt_optional_history_does_not_break_status(lock_directory, monkeypatch, metadata):
    monkeypatch.setattr(updater, "_HISTORY_FILE", lock_directory / "history.json")
    updater._HISTORY_FILE.write_text(json.dumps(metadata))
    assert updater.get_update_history() == []


@pytest.fixture
def lock_directory(tmp_path, monkeypatch):
    path = tmp_path / "updates"
    path.mkdir()
    monkeypatch.setattr(updater, "_UPDATE_DIR", path)
    monkeypatch.setattr(updater, "_LOCK_FILE", path / "update.lock")
    monkeypatch.setattr(updater, "_restart_pending", False)
    return path


def test_a_long_running_live_update_lock_cannot_be_stolen(lock_directory):
    updater._LOCK_FILE.write_text(json.dumps({"pid": os.getpid(), "locked_at":
        (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()}))
    assert not updater._acquire_lock()


def test_corrupt_update_lock_fails_closed(lock_directory):
    updater._LOCK_FILE.write_text("interrupted metadata")
    assert updater.is_update_locked() and updater.writes_blocked()
    assert not updater._acquire_lock()


def test_concurrent_acquisition_has_exactly_one_owner(lock_directory, monkeypatch):
    barrier = Barrier(6)
    original = Path.write_text

    def delayed(path, *args, **kwargs):
        if path == updater._LOCK_FILE:
            barrier.wait(timeout=5)
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, "write_text", delayed)
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(lambda _: updater._acquire_lock(), range(6)))
    assert sum(results) == 1
    updater._release_lock()


def test_another_live_process_lock_does_not_expire(lock_directory):
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(20)"],
        stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    try:
        updater._LOCK_FILE.write_text(json.dumps({"pid": child.pid, "locked_at":
            (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()}))
        assert updater.is_update_locked() and not updater._acquire_lock()
    finally:
        child.terminate()
        child.wait(timeout=10)


@pytest.mark.parametrize("url", [
    "https://evil.invalid/github.com/owner/repo", "https://github.com.evil.invalid/owner/repo",
    "http://github.com/owner/repo", "ftp://github.com/owner/repo",
    "https://github.com/owner/repo/extra", "https://github.com/owner/repo?other=x",
    "https://github.com/owner/repo#fragment", "https://github.com/../repo",
])
def test_update_repository_is_an_exact_https_github_identity(url):
    assert updater._extract_owner_repo(url) is None


def test_missing_node_is_a_failed_required_frontend_build(tmp_path, monkeypatch):
    front = tmp_path / "frontend"
    front.mkdir()
    (front / "package.json").write_text("{}")
    monkeypatch.setattr(updater, "_PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(updater.subprocess, "run", lambda *a, **kw: (_ for _ in ()).throw(FileNotFoundError()))
    assert updater._rebuild_frontend()[0] is False
