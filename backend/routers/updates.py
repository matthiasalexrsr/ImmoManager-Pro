"""Update management API endpoints.

Provides endpoints for checking, applying, and monitoring application updates
from GitHub. All endpoints require admin role (eigentuemer/verwalter).

Security considerations:
- All endpoints are admin-only (enforced via routing.py dependencies)
- The /configure endpoint does NOT persist changes (restart resets them)
- The /apply endpoint validates target_version format before delegating
- Error responses are sanitized to avoid leaking internal details
"""

import logging
import re

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, field_validator

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


class ApplyUpdateRequest(BaseModel):
    target_version: str | None = None

    @field_validator("target_version")
    @classmethod
    def validate_version(cls, v):
        if v is not None:
            cleaned = v.lstrip("vV").strip()
            if not re.match(r"^\d+\.\d+\.\d+([a-zA-Z0-9._-]*)?$", cleaned):
                raise ValueError("Ungültiges Versionsformat")
        return v


class ConfigureUpdateRequest(BaseModel):
    repo_url: str | None = None
    channel: str | None = None
    token: str | None = None

    @field_validator("channel")
    @classmethod
    def validate_channel(cls, v):
        if v is not None and v not in ("stable", "preview"):
            raise ValueError("Ungültiger Kanal. Erlaubt: 'stable', 'preview'")
        return v

    @field_validator("repo_url")
    @classmethod
    def validate_repo_url(cls, v):
        if v is not None and v != "":
            if not re.match(r"^https?://github\.com/[a-zA-Z0-9._-]+/[a-zA-Z0-9._-]+", v):
                raise ValueError("Nur GitHub-Repository-URLs sind erlaubt")
        return v


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
def apply_update_endpoint(payload: ApplyUpdateRequest | None = None):
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
    if settings.is_production and not settings.update_allow_in_production:
        raise HTTPException(
            status_code=403,
            detail="Updates sind in der Produktionsumgebung deaktiviert. Setzen Sie UPDATE_ALLOW_IN_PRODUCTION=true.",
        )

    if not settings.update_repo_url:
        raise HTTPException(
            status_code=400,
            detail="Kein GitHub-Repository konfiguriert. Setzen Sie UPDATE_REPO_URL in der .env Datei.",
        )

    if is_update_locked():
        raise HTTPException(
            status_code=409,
            detail="Ein Update läuft bereits. Bitte warten Sie.",
        )

    target = payload.target_version if payload else None

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
def configure_update(payload: ConfigureUpdateRequest):
    """Update the update configuration at runtime.

    Accepts: {"repo_url": "...", "channel": "stable|preview", "token": "..."}

    Note: These changes are NOT persisted to .env — they only last until restart.
    To persist, edit .env manually.

    Security: Only GitHub URLs are accepted for repo_url. Token values are
    never returned in responses (only whether one is set).
    """
    changed = []

    if payload.repo_url is not None:
        settings.update_repo_url = payload.repo_url
        changed.append("update_repo_url")

    if payload.channel is not None:
        settings.update_channel = payload.channel
        changed.append("update_channel")

    if payload.token is not None:
        settings.update_github_token = payload.token
        changed.append("update_github_token")

    logger.info("Update configuration changed: %s", ", ".join(changed) if changed else "none")

    return {
        "message": f"Konfiguration aktualisiert: {', '.join(changed)}" if changed else "Keine Änderungen",
        "current": {
            "update_repo_url": settings.update_repo_url or None,
            "update_channel": settings.update_channel,
            "token_set": bool(settings.update_github_token),
        },
    }
