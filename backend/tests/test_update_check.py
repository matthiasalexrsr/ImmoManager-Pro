"""The update check: it tells every installation about a newer release, the Windows package how to get it."""

import subprocess
import sys

import httpx
import pytest

from backend import updater
from backend.config import Environment, settings


def release(tag="v2.1.0"):
    return {"tag_name": tag, "body": "Neu: …", "html_url": f"https://github.com/o/r/releases/tag/{tag}",
            "published_at": "2026-11-02T10:00:00Z"}


@pytest.fixture
def github(monkeypatch):
    """GitHub's release API answered locally; records the requested URLs."""
    calls = []
    answer = {"status": 200, "json": release()}

    def handler(request):
        calls.append(str(request.url))
        return httpx.Response(answer["status"], json=answer["json"])

    real_client = httpx.Client
    monkeypatch.setattr(updater.httpx, "Client", lambda **kwargs: real_client(transport=httpx.MockTransport(handler)))
    monkeypatch.setattr(settings, "update_repo_url", "https://github.com/o/r")
    monkeypatch.setattr(settings, "update_channel", "stable")
    monkeypatch.setattr(settings, "app_version", "2.0.0")
    return {"calls": calls, "answer": answer}


def cloned_from(monkeypatch, url):
    """A git checkout whose origin is ``url``."""
    monkeypatch.delattr(sys, "frozen", raising=False)
    monkeypatch.setattr(updater, "_is_git_repo", lambda: True)
    monkeypatch.setattr(updater, "_run_git", lambda *args, **kwargs: subprocess.CompletedProcess(args, 0, url, ""))


def test_the_project_repository_is_checked_by_default():
    assert settings.update_repo_url == "https://github.com/matthiasalexrsr/ImmoManager-Pro"


def test_the_windows_package_learns_about_a_newer_release_and_how_to_install_it(github, monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    result = updater.check_for_updates()
    assert github["calls"] == ["https://api.github.com/repos/o/r/releases/latest"]
    assert (result["update_available"], result["latest_version"], result["error"]) == (True, "2.1.0", None)
    assert result["release_url"].endswith("/v2.1.0")
    assert result["can_apply"] is False
    assert "Vollbackup" in result["download_hint"]


def test_a_current_installation_gets_no_hint(github, monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    github["answer"]["json"] = release("v2.0.0")
    result = updater.check_for_updates()
    assert (result["update_available"], result["download_hint"]) == (False, None)


def test_a_git_checkout_outside_production_installs_itself(github, monkeypatch):
    cloned_from(monkeypatch, "git@github.com:O/R.git")
    monkeypatch.setattr(settings, "environment", Environment.development)
    result = updater.check_for_updates()
    assert (result["update_available"], result["can_apply"], result["download_hint"]) == (True, True, None)


def test_production_checkouts_install_only_when_allowed(github, monkeypatch):
    cloned_from(monkeypatch, "https://github.com/o/r.git")
    monkeypatch.setattr(settings, "environment", Environment.production)
    monkeypatch.setattr(settings, "update_allow_in_production", False)
    assert updater.check_for_updates()["can_apply"] is False
    monkeypatch.setattr(settings, "update_allow_in_production", True)
    assert updater.check_for_updates()["can_apply"] is True


def test_a_checkout_of_another_repository_is_not_offered_an_update_it_cannot_fetch(github, monkeypatch):
    """The check reads the releases of UPDATE_REPO_URL, the update fetches from origin: they must agree."""
    cloned_from(monkeypatch, "https://user:geheim@github.com/someone/fork.git")
    monkeypatch.setattr(settings, "environment", Environment.development)

    result = updater.check_for_updates()

    assert (result["update_available"], result["can_apply"]) == (True, False)
    assert "o/r" in result["download_hint"] and "someone/fork" in result["download_hint"]
    assert "geheim" not in result["download_hint"]
    refused = updater.apply_update()
    assert not refused["success"] and refused["message"] == result["download_hint"] and not refused["steps"]


def test_no_release_yet_is_reported_plainly(github, monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    github["answer"].update(status=404, json={"message": "Not Found"})
    result = updater.check_for_updates()
    assert (result["update_available"], result["error"]) == (False, "Repository oder Releases nicht gefunden")


def test_the_version_is_the_one_of_the_code_not_of_an_old_installation(tmp_path, monkeypatch):
    """Regression: an editable install (install.sh/.bat) keeps the version metadata of its installation.
    After an update to 2.1.0 the program still said 2.0.0 and offered the installed update again."""
    import importlib.metadata

    from backend import config

    monkeypatch.setattr(importlib.metadata, "version", lambda name: "2.0.0")
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text('[tool.other]\nversion = "9.9"\n\n[project]\nname = "immomanager-pro"\nversion = "2.1.0"\n',
                         encoding="utf-8")
    assert config._get_version(pyproject) == "2.1.0"
    # an installed wheel has no pyproject.toml next to the code: its metadata counts
    assert config._get_version(tmp_path / "missing.toml") == "2.0.0"
