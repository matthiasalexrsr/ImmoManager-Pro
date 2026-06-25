"""Runtime-safe admin wrappers for local Windows/PyInstaller operation."""

import json
import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException

from ..config import settings
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
    """Create a JSON backup in the configured runtime backup directory."""
    _BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    backup_name = f"backup_{timestamp}.json"
    backup_path = _BACKUP_DIR / backup_name
    payload = legacy_admin._export_store_data()
    backup_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("Backup created: %s", backup_name)
    return {"backup": backup_name, "size_bytes": backup_path.stat().st_size}


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
    """Restore a JSON backup or SQLite file without allowing path traversal."""
    backup_path = _resolve_backup_path(backup_name)
    if not backup_path.exists():
        raise HTTPException(404, f"Backup not found: {backup_name}")

    if backup_path.suffix == ".json":
        try:
            data = json.loads(backup_path.read_text(encoding="utf-8"))
            return {
                "restored_from": backup_name,
                **legacy_admin._import_store_data(data, replace_existing=True),
            }
        except Exception as exc:
            raise HTTPException(400, f"Invalid JSON backup: {exc}") from exc

    if "sqlite" not in settings.database_url:
        raise HTTPException(400, "Binary DB restore is only supported for SQLite databases")

    db_path = settings.database_url.replace("sqlite:///", "")
    safety = _BACKUP_DIR / f"pre_restore_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}.db"
    if Path(db_path).exists():
        shutil.copy2(db_path, safety)
    shutil.copy2(backup_path, db_path)
    logger.info("Database restored from %s", backup_name)
    return {"restored_from": backup_name, "safety_backup": safety.name}
