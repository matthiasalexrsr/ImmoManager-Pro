"""Update management API endpoints.

Provides release discovery and installer guidance from the configured GitHub repository.
Customer source promotion is disabled even for non-production source checkouts.

Security considerations:
- All endpoints are admin-only (enforced via routing.py dependencies)
- The /configure endpoint does NOT persist changes (restart resets them)
- The /apply endpoint always rejects source promotion (409)
- Error responses are sanitized to avoid leaking internal details
"""

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, field_validator

from ..config import settings
from ..updater import (
    INSTALLER_HINT,
    _extract_owner_repo,
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
            from ..updater import _parse_version
            if not _parse_version(v)[0]:
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
            if _extract_owner_repo(v) is None:
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
        "update_repo_url": ("https://github.com/" + repo) if (repo := _extract_owner_repo(settings.update_repo_url)) else None,
        "update_channel": settings.update_channel,
        "repo_configured": bool(settings.update_repo_url),
        "update_in_progress": is_update_locked(),
        "can_apply": False,
        "update_method": "verified_installer",
    }


@router.post("/apply")
def apply_update_endpoint(payload: ApplyUpdateRequest | None = None):
    """Customer source promotion is unavailable; no payload enables developer mode."""
    raise HTTPException(status_code=409, detail=INSTALLER_HINT)


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
