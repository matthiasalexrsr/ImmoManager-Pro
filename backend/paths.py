"""Runtime path helpers.

Source and Docker runs keep the historical project-root paths. Frozen Windows
bundles and the Windows starter scripts can point DATA_DIR at a persistent
per-user location so SQLite data, uploads, logs, and backups survive restarts.
"""

from __future__ import annotations

import sys
from pathlib import Path

from .config import settings
from .platform_paths import APP_DIR_NAME as APP_DIR_NAME
from .platform_paths import default_user_data_dir

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def _default_user_data_dir() -> Path:
    return default_user_data_dir()


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
