"""Installing an update in a git checkout: pinned dependencies, no merge commits, nothing saved in between."""

import subprocess
import sys

import pytest
from fastapi.testclient import TestClient

from backend import updater
from backend.config import settings


class Checkout:
    """git, pip, npm and the upgrade answered locally; records what ran."""

    def __init__(self):
        self.commits = ["old", "new"]
        self.calls: list[list[str]] = []
        self.fail: set[str] = set()

    def git(self, *args, cwd=None):
        self.calls.append(["git", *args])
        code = 1 if args[0] in self.fail or " ".join(args[:2]) in self.fail else 0
        if args[:2] == ("rev-parse", "HEAD"):
            return subprocess.CompletedProcess(args, 0, self.commits[0], "")
        if args[:2] == ("rev-parse", "--abbrev-ref"):
            return subprocess.CompletedProcess(args, 0, "main", "")
        if args[0] == "merge" and not code:
            self.commits.pop(0)
        if args[:2] == ("reset", "--hard"):
            self.commits = [args[2]]
        return subprocess.CompletedProcess(args, code, "", "kein Vorspulen" if code else "")

    def run(self, command, **kwargs):
        self.calls.append(list(command))
        tool = "pip" if "pip" in command else "upgrade" if "backend.upgrade" in command else command[0]
        if tool == "node":
            return subprocess.CompletedProcess(command, 0, "v24", "")
        code = 1 if tool in self.fail else 0
        return subprocess.CompletedProcess(command, code, "Upgrade abgeschlossen" if tool == "upgrade" else "",
                                           "Fehler" if code else "")

    def ran(self, tool: str) -> list[list[str]]:
        return [call for call in self.calls if tool in " ".join(call)]


@pytest.fixture
def checkout(tmp_path, monkeypatch):
    fake = Checkout()
    monkeypatch.setattr(updater, "_UPDATE_DIR", tmp_path / ".updates")
    monkeypatch.setattr(updater, "_LOCK_FILE", tmp_path / ".updates" / "update.lock")
    monkeypatch.setattr(updater, "_HISTORY_FILE", tmp_path / ".updates" / "history.json")
    monkeypatch.setattr(updater, "_run_git", fake.git)
    monkeypatch.setattr(updater.subprocess, "run", fake.run)
    monkeypatch.setattr(updater, "_is_git_repo", lambda: True)
    monkeypatch.setattr(updater, "_has_uncommitted_changes", lambda: False)
    monkeypatch.setattr(updater, "_create_pre_update_backup", lambda: "pre_update.json")
    monkeypatch.setattr(updater, "_create_db_snapshot", lambda: None)
    monkeypatch.setattr(updater, "_restart_pending", False)
    monkeypatch.setattr(settings, "update_repo_url", "https://github.com/o/r")
    monkeypatch.delattr(sys, "frozen", raising=False)
    return fake


def test_dependencies_come_from_the_pinned_tree(checkout):
    result = updater.apply_update()

    assert result["success"], result
    (pip,) = checkout.ran("pip")
    assert pip[pip.index("-c") + 1].endswith("constraints.txt")
    # exactly the locked frontend packages, as in CI
    assert checkout.ran("npm ci") and not checkout.ran("npm install")


def test_a_failed_pip_stops_the_update_before_the_migration(checkout):
    """Regression: a pip failure counted as "nicht kritisch"; the migration ran on missing packages."""
    checkout.fail.add("pip")

    result = updater.apply_update()

    assert not result["success"] and result["rollback_performed"]
    assert not checkout.ran("backend.upgrade")
    assert ["git", "reset", "--hard", "old"] in checkout.calls
    # the previous commit's dependencies are installed again
    assert len(checkout.ran("pip")) == 2


def test_local_commits_are_never_merged(checkout):
    """Regression: without a fast-forward the updater made a merge commit of local and remote changes."""
    checkout.fail.add("merge")

    result = updater.apply_update()

    assert not result["success"] and "eigene Commits" in result["message"]
    assert [call for call in checkout.calls if call[:2] == ["git", "merge"]] == [
        ["git", "merge", "origin/main", "--ff-only"]]
    assert not checkout.ran("pip")


def test_a_failed_migration_restores_code_and_dependencies(checkout):
    checkout.fail.add("upgrade")

    result = updater.apply_update()

    assert not result["success"] and result["rollback_performed"]
    assert ["git", "reset", "--hard", "old"] in checkout.calls
    assert len(checkout.ran("pip")) == 2
    assert updater.writes_blocked() is None          # the old code runs on the old schema again


@pytest.fixture
def client(checkout):
    from backend.app import app
    from backend.auth import clear_users, create_access_token, register_user

    clear_users()
    user = register_user("owner", "owner@example.com", "eigentuemer", "Secret123", "eigentuemer")
    yield TestClient(app), {"Authorization": f"Bearer {create_access_token(user.id)}"}
    clear_users()


def test_nothing_is_saved_while_an_update_runs_or_before_the_restart(client, checkout):
    """Regression: a failed step restored the database snapshot of the update's start and dropped
    what users saved meanwhile; after the update the old code kept writing into the new schema."""
    http, owner = client
    assert updater._acquire_lock()
    refused = http.post("/api/v1/portfolios", headers=owner, json={"name": "Neu"})
    assert refused.status_code == 503 and "Update läuft" in refused.json()["detail"]
    assert http.get("/api/v1/portfolios", headers=owner).status_code == 200
    assert http.get("/api/v1/updates/status", headers=owner).status_code == 200
    updater._release_lock()

    assert updater.apply_update()["success"]
    refused = http.post("/api/v1/portfolios", headers=owner, json={"name": "Neu"})
    assert refused.status_code == 503 and "neu starten" in refused.json()["detail"]
    assert http.post("/api/v1/updates/restart", headers=owner).status_code == 200


def test_the_update_script_follows_the_installed_branch():
    """Regression: scripts/update.sh pulled origin/main; the repository's branch is master, every run failed."""
    from pathlib import Path

    script = (Path(__file__).resolve().parents[2] / "scripts" / "update.sh").read_text(encoding="utf-8")
    assert "origin main" not in script and 'git pull --ff-only origin "$branch"' in script
    assert "-c constraints.txt" in script and "npm ci" in script and "python -m backend.upgrade" in script


def test_only_the_owner_decides_where_updates_come_from(client):
    """Installing was the owner's alone, but a manager could point the update source elsewhere."""
    from backend.auth import create_access_token, register_user

    http, owner = client
    manager = register_user("manager", "manager@example.com", "verwalter", "Secret123", "verwalter")
    refused = http.post("/api/v1/updates/configure", json={"channel": "preview"},
                        headers={"Authorization": f"Bearer {create_access_token(manager.id)}"})
    assert refused.status_code == 403
    assert http.post("/api/v1/updates/configure", json={"channel": "stable"}, headers=owner).status_code == 200
