"""Runtime-safe admin wrappers for local Windows/PyInstaller operation."""

import json
import logging
import secrets
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException

from ..config import settings
from ..paths import get_backup_dir, get_data_dir, get_uploads_dir
from ..services.data_snapshot import SnapshotError, export_snapshot, prepare_import
from ..services.filesystem_paths import filesystem_path
from ..services.sqlite_backup import (
    copy_database,
    sqlite_path_from_url,
)
from ..storage import InMemoryStore
from . import admin as legacy_admin

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["Admin"])

_BACKUP_DIR = get_backup_dir()


def _resolve_backup_path(backup_name: str) -> Path:
    candidate = Path(backup_name)
    if candidate.is_absolute() or candidate.name != backup_name:
        raise HTTPException(400, "Ungültiger Name der Sicherung")
    path = filesystem_path(_BACKUP_DIR / candidate.name)
    if path.is_symlink() or not path.resolve().is_relative_to(filesystem_path(_BACKUP_DIR).resolve()):
        raise HTTPException(400, "Die Sicherung muss eine eigene Datei im Sicherungsordner sein")
    return path


@router.get("/system-status")
def system_status():
    """Return legacy status plus concrete runtime data directories."""
    status = legacy_admin.system_status()
    status.update({
        "data_dir": str(get_data_dir()),
        "upload_dir": str(get_uploads_dir()),
        "backup_dir": str(_BACKUP_DIR),
        "backup_restore_capabilities": {
            "raw_sqlite_http_restore": False,
            "full_archive_restore": "offline_new_directory",
            "json_snapshot_restore": "guarded_business_only",
            "json_merge_import": True,
        },
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
    return datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f") + "_" + secrets.token_hex(4)


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
        backup_path = filesystem_path(_BACKUP_DIR / f"backup_{_timestamp()}.db")
        copy_database(db_path, backup_path)
    else:
        backup_path = filesystem_path(_BACKUP_DIR / f"backup_{_timestamp()}.json")
        payload = export_snapshot(store)
        from ..services.secret_box import write_private_file
        write_private_file(backup_path, json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8"))
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
    """Guarded business JSON only; whole databases are never swapped live."""
    from ..dependencies import store

    candidate = Path(backup_name)
    if candidate.is_absolute() or candidate.name != backup_name:
        raise HTTPException(400, "Ungültiger Name der Sicherung")
    if candidate.suffix.lower() != ".json":
        raise HTTPException(409, "Eine vollständige Datenbank wird nicht im laufenden Programm ersetzt. "
            "Anwendung vollständig schließen und ein geprüftes Vollarchiv offline in ein NEUES leeres "
            "Datenverzeichnis wiederherstellen; anschließend Upgrade und Datenschutzprüfung ausführen. "
            "Eine einzelne DB-Datei enthält keine vollständige Sicherung der Anhänge und Schlüssel.")
    backup_path = _resolve_backup_path(backup_name)
    if not backup_path.exists():
        raise HTTPException(404, f"Sicherung nicht gefunden: {backup_name}")

    db_path = _live_sqlite_path()
    if backup_path.suffix.lower() == ".json":
        try:
            data = json.loads(backup_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise HTTPException(400, f"Die JSON-Sicherung ist nicht lesbar: {exc}") from exc
        try:
            prepared = prepare_import(store, data, replace=True)
        except SnapshotError as exc:
            raise HTTPException(400, f"Wiederherstellung abgebrochen – {exc}") from exc
        safety = _safety_backup(store, db_path)
        result = prepared.apply()
        logger.info("Data restored from %s", backup_name)
        return {"restored_from": backup_name, "safety_backup": safety.name, **result}



def _safety_backup(store, db_path: Path | None) -> Path:
    """Save the current data before it is replaced."""
    _BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    if db_path is not None:
        safety = filesystem_path(_BACKUP_DIR / f"pre_restore_{_timestamp()}.db")
        copy_database(db_path, safety)
    else:
        safety = filesystem_path(_BACKUP_DIR / f"pre_restore_{_timestamp()}.json")
        from ..services.secret_box import write_private_file
        write_private_file(safety, json.dumps(export_snapshot(store), ensure_ascii=False, indent=2).encode("utf-8"))
    return safety
