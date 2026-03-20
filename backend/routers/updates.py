"""Update management API endpoints.

Provides endpoints for checking, applying, and monitoring application updates
from GitHub. All endpoints require admin role (eigentuemer/verwalter).
"""

import logging

from fastapi import APIRouter, HTTPException

from ..config import settings
from ..updater import (
    apply_update,
    check_for_updates,
    get_update_history,
    is_update_locked,
    signal_restart,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/updates", tags=["Updates"])


@router.get("/check")
def check_updates():
    """Check GitHub for available updates.

    Returns version comparison, release notes, and whether an update
    is available.  Does NOT modify anything.
    """
    return check_for_updates()


@router.get("/status")
def update_status():
    """Return the current update status.

    Includes whether an update is in progress, current version info,
    and configuration.
    """
    return {
        "current_version": settings.app_version,
        "update_repo_url": settings.update_repo_url or None,
        "update_channel": settings.update_channel,
        "repo_configured": bool(settings.update_repo_url),
        "update_in_progress": is_update_locked(),
    }


@router.post("/apply")
def apply_update_endpoint(payload: dict | None = None):
    """Apply an available update.

    Optional body: {"target_version": "1.2.0"} to update to a specific version.
    If omitted, updates to the latest version on the current branch.

    This endpoint:
    1. Creates a full data backup
    2. Creates a database snapshot (SQLite)
    3. Pulls updates from GitHub
    4. Runs database migrations
    5. Rebuilds the frontend
    6. Rolls back automatically on failure

    Returns detailed step-by-step progress and result.
    """
    if not settings.update_repo_url:
        raise HTTPException(
            status_code=400,
            detail="Kein GitHub-Repository konfiguriert. Setzen Sie UPDATE_REPO_URL in der .env Datei.",
        )

    target = None
    if payload and isinstance(payload, dict):
        target = payload.get("target_version")

    result = apply_update(target_version=target)
    return result


@router.post("/restart")
def restart_endpoint():
    """Signal that the application should restart after an update.

    Creates a restart marker file. The actual restart must be handled
    by the process manager (systemd, supervisor, etc.) or manually.
    """
    return signal_restart()


@router.get("/history")
def update_history():
    """Return the update history (newest first, max 50 entries)."""
    return {"history": get_update_history()}


@router.post("/configure")
def configure_update(payload: dict):
    """Update the update configuration at runtime.

    Accepts: {"repo_url": "...", "channel": "stable|preview", "token": "..."}

    Note: These changes are NOT persisted to .env — they only last until restart.
    To persist, edit .env manually.
    """
    changed = []

    if "repo_url" in payload:
        settings.update_repo_url = payload["repo_url"]
        changed.append("update_repo_url")

    if "channel" in payload:
        if payload["channel"] not in ("stable", "preview"):
            raise HTTPException(400, "Ungültiger Kanal. Erlaubt: 'stable', 'preview'")
        settings.update_channel = payload["channel"]
        changed.append("update_channel")

    if "token" in payload:
        settings.update_github_token = payload["token"]
        changed.append("update_github_token")

    return {
        "message": f"Konfiguration aktualisiert: {', '.join(changed)}" if changed else "Keine Änderungen",
        "current": {
            "update_repo_url": settings.update_repo_url or None,
            "update_channel": settings.update_channel,
            "token_set": bool(settings.update_github_token),
        },
    }
