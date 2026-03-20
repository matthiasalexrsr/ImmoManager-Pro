"""Autotest API — comprehensive self-testing and report generation.

Runs the full autotest suite against the running application and returns
structured results. Reports can be downloaded as Markdown (designed for
Claude Code consumption) or JSON. Reports can also be committed directly
to the GitHub repository for automated CI/agent consumption.

Restricted to admin users. Blocked in production by default.
"""

import base64
import logging
import time
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, Depends, HTTPException

from ..config import settings
from ..services.autotest.runner import (
    AutotestRunner,
    format_report_json,
    format_report_markdown,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/autotest", tags=["Autotest"])

_HTTP_TIMEOUT = 30.0

# Cache last report to avoid re-running expensive tests
_last_report = None
_last_report_md = None


def _check_autotest_allowed():
    """Block autotest in production unless diagnostics are explicitly enabled."""
    if settings.is_production and not settings.diagnostics_allow_in_production:
        raise HTTPException(
            status_code=403,
            detail="Autotest ist in der Produktionsumgebung deaktiviert.",
        )


@router.post("/run", dependencies=[Depends(_check_autotest_allowed)])
def run_autotest():
    """Run the full autotest suite and return JSON results."""
    global _last_report, _last_report_md

    runner = AutotestRunner()
    report = runner.run()

    _last_report = report
    _last_report_md = format_report_markdown(report)

    return format_report_json(report)


@router.get("/report", dependencies=[Depends(_check_autotest_allowed)])
def get_last_report():
    """Return the last autotest report as JSON (without re-running)."""
    if _last_report is None:
        raise HTTPException(
            status_code=404,
            detail="Noch kein Autotest-Bericht vorhanden. Bitte zuerst /autotest/run ausführen.",
        )
    return format_report_json(_last_report)


@router.get("/report/markdown", dependencies=[Depends(_check_autotest_allowed)])
def get_last_report_markdown():
    """Return the last autotest report as Markdown text."""
    if _last_report_md is None:
        raise HTTPException(
            status_code=404,
            detail="Noch kein Autotest-Bericht vorhanden. Bitte zuerst /autotest/run ausführen.",
        )
    from fastapi.responses import PlainTextResponse
    return PlainTextResponse(content=_last_report_md, media_type="text/markdown")


@router.post("/upload-report", dependencies=[Depends(_check_autotest_allowed)])
def upload_report_to_github():
    """Upload the latest autotest report to the GitHub repository.

    Commits AUTOTEST_REPORT.md to the repo root so that Claude Code
    and other agents can discover and act on it automatically.

    Requires:
    - update_repo_url to be configured
    - update_github_token to be set (needs repo write access)
    """
    if _last_report_md is None:
        raise HTTPException(
            status_code=400,
            detail="Kein Bericht vorhanden. Bitte zuerst /autotest/run ausführen.",
        )

    repo_url = settings.update_repo_url
    token = settings.update_github_token

    if not repo_url:
        raise HTTPException(
            status_code=400,
            detail="Kein GitHub-Repository konfiguriert (UPDATE_REPO_URL).",
        )
    if not token:
        raise HTTPException(
            status_code=400,
            detail="Kein GitHub-Token konfiguriert (UPDATE_GITHUB_TOKEN). Benötigt Schreibzugriff.",
        )

    # Extract owner/repo from URL
    owner_repo = _extract_owner_repo(repo_url)
    if not owner_repo:
        raise HTTPException(
            status_code=400,
            detail=f"Ungültige Repository-URL: {repo_url}",
        )

    file_path = "AUTOTEST_REPORT.md"
    commit_message = (
        f"chore: update autotest report ({_last_report.total_passed}/{_last_report.total_tests} passed)\n\n"
        f"Generated: {_last_report.timestamp}\n"
        f"Failed: {_last_report.total_failed} | Warnings: {_last_report.total_warnings}"
    )

    try:
        result = _commit_file_to_github(
            owner_repo=owner_repo,
            token=token,
            file_path=file_path,
            content=_last_report_md,
            commit_message=commit_message,
        )
        return {
            "success": True,
            "message": "Autotest-Bericht erfolgreich hochgeladen.",
            "file_path": file_path,
            "commit_sha": result.get("commit_sha"),
            "html_url": result.get("html_url"),
        }
    except httpx.HTTPStatusError as exc:
        logger.error("GitHub API error: %s", exc.response.text[:500])
        raise HTTPException(
            status_code=502,
            detail=f"GitHub API Fehler: {exc.response.status_code} — {exc.response.text[:200]}",
        )
    except Exception as exc:
        logger.error("Failed to upload report: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Upload fehlgeschlagen: {type(exc).__name__}: {exc}",
        )


def _extract_owner_repo(url: str) -> str | None:
    """Extract 'owner/repo' from a GitHub URL."""
    import re
    url = url.rstrip("/").removesuffix(".git")
    match = re.search(r"github\.com/([a-zA-Z0-9._-]+/[a-zA-Z0-9._-]+)", url)
    return match.group(1) if match else None


def _commit_file_to_github(
    owner_repo: str,
    token: str,
    file_path: str,
    content: str,
    commit_message: str,
) -> dict:
    """Create or update a file in a GitHub repo via the Contents API.

    Uses PUT /repos/{owner}/{repo}/contents/{path} which handles both
    create and update (update requires the existing file's SHA).
    """
    api_url = f"https://api.github.com/repos/{owner_repo}/contents/{file_path}"
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    # Check if file already exists to get its SHA (required for updates)
    existing_sha = None
    with httpx.Client(timeout=_HTTP_TIMEOUT) as client:
        check_resp = client.get(api_url, headers=headers)
        if check_resp.status_code == 200:
            existing_sha = check_resp.json().get("sha")

        # Prepare the file content
        encoded_content = base64.b64encode(content.encode("utf-8")).decode("ascii")

        payload = {
            "message": commit_message,
            "content": encoded_content,
        }
        if existing_sha:
            payload["sha"] = existing_sha

        # Commit the file
        resp = client.put(api_url, json=payload, headers=headers)
        resp.raise_for_status()

        data = resp.json()
        return {
            "commit_sha": data.get("commit", {}).get("sha", ""),
            "html_url": data.get("content", {}).get("html_url", ""),
        }
