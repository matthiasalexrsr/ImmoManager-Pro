"""Runtime-safe admin wrappers for local Windows/PyInstaller operation."""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException

from ..config import settings
from ..paths import get_backup_dir, get_data_dir, get_uploads_dir
from ..services.data_snapshot import SnapshotError, export_snapshot, prepare_import
from ..services.document_version_validation import ArchiveIntegrityError
from ..services.sqlite_backup import (
    copy_database,
    ensure_access_schema,
    ensure_archive_schema,
    ensure_job_schema,
    is_sqlite_database,
    sqlite_path_from_url,
    verify_archived_originals,
)
from ..storage import InMemoryStore
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


def _live_sqlite_path() -> Path | None:
    """The SQLite file holding the live data, or None for other stores."""
    from ..dependencies import store

    if isinstance(store, InMemoryStore):
        return None
    return sqlite_path_from_url(settings.database_url)


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")


@router.post("/backup", response_model=None)
def create_backup():
    """Back up all data into the runtime backup directory.

    SQLite: a complete copy of the database (also user accounts) via the
    online backup API. Other stores: a JSON snapshot of the business data.
    """
    from ..dependencies import store

    _BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    db_path = _live_sqlite_path()
    if db_path is not None:
        backup_path = _BACKUP_DIR / f"backup_{_timestamp()}.db"
        copy_database(db_path, backup_path)
    else:
        backup_path = _BACKUP_DIR / f"backup_{_timestamp()}.json"
        payload = export_snapshot(store)
        backup_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    logger.info("Backup created: %s", backup_path.name)
    return {"backup": backup_path.name, "size_bytes": backup_path.stat().st_size}


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
    """Restore a JSON snapshot or SQLite backup without allowing path traversal.

    The backup is validated first and the current data is saved as a
    safety backup; on any problem the live data stays untouched.
    """
    from ..dependencies import store

    backup_path = _resolve_backup_path(backup_name)
    if not backup_path.exists():
        raise HTTPException(404, f"Backup not found: {backup_name}")

    db_path = _live_sqlite_path()
    if backup_path.suffix == ".json":
        try:
            data = json.loads(backup_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise HTTPException(400, f"Invalid JSON backup: {exc}") from exc
        try:
            prepared = prepare_import(store, data, replace=True)
        except SnapshotError as exc:
            raise HTTPException(400, f"Wiederherstellung abgebrochen – {exc}") from exc
        safety = _safety_backup(store, db_path)
        result = prepared.apply()
        logger.info("Data restored from %s", backup_name)
        return {"restored_from": backup_name, "safety_backup": safety.name, **result}

    if db_path is None:
        raise HTTPException(400, "Binary DB restore is only supported for SQLite databases")
    if not is_sqlite_database(backup_path):
        raise HTTPException(400, f"Not a SQLite database: {backup_name}")

    try:
        verify_archived_originals(backup_path)
    except ArchiveIntegrityError as exc:
        raise HTTPException(400, f"Wiederherstellung abgebrochen – {exc}") from exc

    # Online backup API, not file copies: the live database runs in WAL mode
    # and stays open, so a file copy would be overridden by the old WAL.
    safety = _safety_backup(store, db_path)
    copy_database(backup_path, db_path)
    from ..db.session import engine

    ensure_archive_schema(engine)
    ensure_access_schema(engine)
    ensure_job_schema(engine)
    logger.info("Database restored from %s", backup_name)
    return {"restored_from": backup_name, "safety_backup": safety.name}


def _safety_backup(store, db_path: Path | None) -> Path:
    """Save the current data before it is replaced."""
    _BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    if db_path is not None:
        safety = _BACKUP_DIR / f"pre_restore_{_timestamp()}.db"
        copy_database(db_path, safety)
    else:
        safety = _BACKUP_DIR / f"pre_restore_{_timestamp()}.json"
        safety.write_text(json.dumps(export_snapshot(store), ensure_ascii=False, indent=2), encoding="utf-8")
    return safety
