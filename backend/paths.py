"""Runtime path helpers.

Source and Docker runs keep the historical project-root paths. Frozen Windows
bundles and the Windows starter scripts can point DATA_DIR at a persistent
per-user location so SQLite data, uploads, logs, and backups survive restarts.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from .config import settings

APP_DIR_NAME = "ImmoManagerPro"
PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def _default_user_data_dir() -> Path:
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA")
        if base:
            return Path(base) / APP_DIR_NAME
        return Path.home() / "AppData" / "Local" / APP_DIR_NAME

    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / APP_DIR_NAME

    base = os.environ.get("XDG_DATA_HOME")
    if base:
        return Path(base) / APP_DIR_NAME
    return Path.home() / ".local" / "share" / APP_DIR_NAME


def _resolve_configured_path(value: str) -> Path | None:
    if not value:
        return None
    return Path(value).expanduser().resolve()


def get_data_dir() -> Path:
    configured = _resolve_configured_path(settings.data_dir)
    if configured is not None:
        return configured
    if _is_frozen():
        return _default_user_data_dir().resolve()
    return PROJECT_ROOT


def get_uploads_dir() -> Path:
    configured = _resolve_configured_path(settings.uploads_dir)
    if configured is not None:
        return configured
    return get_data_dir() / "uploads"


def get_backup_dir() -> Path:
    configured = _resolve_configured_path(settings.backup_dir)
    if configured is not None:
        return configured
    return get_data_dir() / "backups"


def get_logs_dir() -> Path:
    return get_data_dir() / "logs"


def ensure_runtime_dirs() -> None:
    for path in (get_data_dir(), get_uploads_dir(), get_backup_dir(), get_logs_dir()):
        path.mkdir(parents=True, exist_ok=True)


def sqlite_url_for_path(path: Path) -> str:
    return f"sqlite:///{path.expanduser().resolve().as_posix()}"
