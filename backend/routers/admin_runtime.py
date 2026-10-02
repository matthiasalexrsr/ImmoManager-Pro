"""Runtime-safe admin wrappers for local Windows/PyInstaller operation."""

import logging
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException

from ..paths import get_backup_dir, get_data_dir, get_uploads_dir
from . import admin as legacy_admin

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["Admin"])

_BACKUP_DIR = get_backup_dir()


def _resolve_backup_path(backup_name: str) -> Path:
    candidate = Path(backup_name)
    if candidate.is_absolute() or candidate.name != backup_name:
        raise HTTPException(400, "Invalid backup name")
    return _BACKUP_DIR / candidate.name


@router.get("/system-status")
def system_status():
    """Return legacy status plus concrete runtime data directories."""
    status = legacy_admin.system_status()
    status.update({
        "data_dir": str(get_data_dir()),
        "upload_dir": str(get_uploads_dir()),
        "backup_dir": str(_BACKUP_DIR),
    })
    return status


@router.get("/database-info")
def get_database_info():
    """Return legacy database info plus the active upload directory."""
    info = legacy_admin.get_database_info()
    info["upload_directory"] = str(get_uploads_dir())
    return info


@router.post("/backup", response_model=None)
def create_backup():
    return legacy_admin._create_json_backup(_BACKUP_DIR)


@router.get("/backups")
def list_backups():
    """List JSON/SQLite backup files from the configured runtime directory."""
    _BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    backups = []
    for file_path in sorted(_BACKUP_DIR.glob("backup_*.*"), reverse=True):
        backups.append({
            "name": file_path.name,
            "size_bytes": file_path.stat().st_size,
            "created_at": datetime.fromtimestamp(file_path.stat().st_mtime).isoformat(),
        })
    return backups


@router.post("/restore/{backup_name}", response_model=None)
def restore_backup(backup_name: str):
    return legacy_admin._restore_backup_file(_BACKUP_DIR, backup_name)
