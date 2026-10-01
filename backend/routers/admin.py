"""Admin API: backup/restore, integrity checks, export/import, version, plugins, bulk ops."""

import json
import logging
import os
import platform
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from ..config import settings
from ..dependencies import store
from ..plugins import get_plugins
from ..services.data_transfer import (
    TransferError,
    _atomic_store,
    _clear_supported,
    _specifications,
    decode_snapshot,
    export_store_data,
    import_store_data,
    list_records,
)

# Re-export the CONTRACT_WIZARD_STATUS lazily to avoid circular imports.
_CONTRACT_WIZARD_STATUS = None


def _get_wizard_status() -> dict:
    global _CONTRACT_WIZARD_STATUS
    if _CONTRACT_WIZARD_STATUS is None:
        try:
            from ..app import CONTRACT_WIZARD_STATUS
            _CONTRACT_WIZARD_STATUS = CONTRACT_WIZARD_STATUS
        except Exception:
            logger.debug("Could not import CONTRACT_WIZARD_STATUS", exc_info=True)
            _CONTRACT_WIZARD_STATUS = {"available": False, "reason": "unknown"}
    return _CONTRACT_WIZARD_STATUS

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["Admin"])

_BACKUP_DIR = Path("backups")


def _safe_list(method_name: str, active_store=None) -> list[dict]:
    return list_records(store if active_store is None else active_store, method_name)


def _export_store_data(active_store=None) -> dict:
    try:
        return export_store_data(store if active_store is None else active_store, settings.app_version)
    except TransferError:
        raise
    except Exception as exc:
        raise TransferError("Export fehlgeschlagen; es wurde keine Teilsicherung erzeugt.") from exc


def _clear_store_data(active_store=None, *, strict: bool = False) -> None:
    # Internal test compatibility. Production restore uses import_store_data.
    with _atomic_store(store if active_store is None else active_store) as staged:
        _clear_supported(staged, _specifications())


def _import_store_data(data: dict, *, replace_existing: bool, active_store=None, strict: bool = False) -> dict:
    return import_store_data(store if active_store is None else active_store, data,
                             replace_existing=replace_existing)


def _restore_store_data(data: dict, active_store=None) -> dict:
    return _import_store_data(data, replace_existing=True, active_store=active_store)


# ─── Version ────────────────────────────────────────────────────────────────

@router.get("/version")
def get_version():
    """Return application version and runtime information."""
    db_type = "postgresql" if "postgresql" in settings.database_url else "sqlite"
    plugins = [p.to_dict() for p in get_plugins()]
    return {
        "version": settings.app_version,
        "api_version": "v1",
        "python_version": platform.python_version(),
        "database": db_type,
        "plugins": plugins,
        "default_locale": settings.default_locale,
    }


# ─── System Status ───────────────────────────────────────────────────────────

@router.get("/system-status")
def system_status():
    """Comprehensive system status for admin diagnostics."""
    from ..dependencies import _use_sql_store
    from ..dependencies import store as active_store

    store_type = type(active_store).__name__

    db_ok = True
    if _use_sql_store:
        try:
            import sqlalchemy

            from ..db.session import engine
            with engine.connect() as conn:
                conn.execute(sqlalchemy.text("SELECT 1"))
        except Exception:
            logger.warning("Database connectivity check failed", exc_info=True)
            db_ok = False

    wizard_status = _get_wizard_status()

    return {
        "version": settings.app_version,
        "environment": settings.environment.value,
        "active_store": store_type,
        "persistent": store_type != "InMemoryStore",
        "database_connected": db_ok,
        "allow_inmemory_fallback": settings.allow_inmemory_fallback,
        "auto_seed_demo_data": settings.auto_seed_demo_data,
        "auto_migrate": settings.auto_migrate,
        "contract_wizard_available": wizard_status.get("available", False),
        "contract_wizard_reason": wizard_status.get("reason"),
        "plugin_dirs": settings.plugin_dirs,
        "loaded_plugins": [p.to_dict() for p in get_plugins()],
        "max_upload_size_bytes": settings.max_upload_size_bytes,
        "default_locale": settings.default_locale,
    }


# ─── Database Info ───────────────────────────────────────────────────────────

@router.get("/database-info")
def get_database_info():
    """Return database type, store backend, and operational details."""
    from ..dependencies import store as active_store

    db_url = settings.database_url
    db_type = "postgresql" if "postgresql" in db_url else "sqlite"
    store_type = type(active_store).__name__

    info = {
        "database_type": db_type,
        "store_backend": store_type,
        "persistent": store_type != "InMemoryStore",
        "version": settings.app_version,
        "default_locale": settings.default_locale,
        "upload_directory": "uploads/",
        "plugins_loaded": len(get_plugins()),
    }
    if "sqlite" in db_url:
        db_path = db_url.replace("sqlite:///", "")
        db_file = Path(db_path)
        info["database_file"] = db_path
        info["database_exists"] = db_file.exists()
        if db_file.exists():
            info["database_size_bytes"] = db_file.stat().st_size
    return info


# ─── Config (public-safe subset) ────────────────────────────────────────────

@router.get("/config/public")
def get_public_config():
    """Return non-sensitive configuration for the frontend."""
    return {
        "version": settings.app_version,
        "default_locale": settings.default_locale,
        "plugins": [p.to_dict() for p in get_plugins()],
    }


# ─── Plugins ─────────────────────────────────────────────────────────────────

@router.get("/plugins")
def list_plugins():
    """List all installed plugins."""
    return [p.to_dict() for p in get_plugins()]


# ─── Backup / Restore ───────────────────────────────────────────────────────

def _create_json_backup(directory: Path):
    try:
        content = json.dumps(_export_store_data(), ensure_ascii=False, indent=2, allow_nan=False)
    except Exception as exc:
        logger.exception("Business-data export failed")
        raise HTTPException(500, "Sicherung fehlgeschlagen; keine Teilsicherung erstellt.") from exc
    directory.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
    backup_name = f"backup_{timestamp}_{uuid4().hex[:8]}.json"
    handle, temporary = tempfile.mkstemp(prefix=".backup-", suffix=".tmp", dir=directory)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as output:
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, directory / backup_name)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return {"backup": backup_name, "size_bytes": (directory / backup_name).stat().st_size,
            "scope": "business-data-only"}


@router.post("/backup", response_model=None)
def create_backup():
    return _create_json_backup(_BACKUP_DIR)


@router.get("/backups")
def list_backups():
    """List available database backups."""
    _BACKUP_DIR.mkdir(exist_ok=True)
    backups = []
    for f in sorted(_BACKUP_DIR.glob("backup_*.*"), reverse=True):
        backups.append({
            "name": f.name,
            "size_bytes": f.stat().st_size,
            "created_at": datetime.fromtimestamp(f.stat().st_mtime).isoformat(),
        })
    return backups


def _restore_backup_file(directory: Path, backup_name: str):
    if (not backup_name or backup_name in {".", ".."} or "/" in backup_name
            or chr(92) in backup_name or ":" in backup_name):
        raise HTTPException(400, "Ungueltiger Sicherungsname.")
    path = directory / backup_name
    if path.is_symlink() or path.resolve().parent != directory.resolve():
        raise HTTPException(400, "Ungueltiger Sicherungspfad.")
    if not path.is_file():
        raise HTTPException(404, "Sicherung nicht gefunden.")
    if path.suffix != ".json":
        raise HTTPException(409, "Datenbankdateien nur offline wiederherstellen; der Server muss beendet sein.")
    with path.open("rb") as source:
        raw = source.read(settings.max_upload_size_bytes + 1)
    if len(raw) > settings.max_upload_size_bytes:
        raise HTTPException(413, "Sicherung zu gross fuer den JSON-Restore.")
    try:
        data = decode_snapshot(raw)
    except TransferError as exc:
        raise HTTPException(400, str(exc)) from exc
    try:
        result = _restore_store_data(data)
    except TransferError as exc:
        raise HTTPException(409, str(exc)) from exc
    return {"restored_from": backup_name, **result}


@router.post("/restore/{backup_name}", response_model=None)
def restore_backup(backup_name: str):
    return _restore_backup_file(_BACKUP_DIR, backup_name)


# ─── Integrity Check ────────────────────────────────────────────────────────

@router.get("/integrity-check")
def integrity_check():
    """Run database integrity checks and report issues."""
    issues = []

    # Check: orphan contracts (unit or tenant doesn't exist)
    contracts = store.list_contracts()
    unit_ids = {u.id for u in store.list_units()}
    tenant_ids = {t.id for t in store.list_tenants()}
    property_ids = {p.id for p in store.list_properties()}

    for c in contracts:
        if c.unit_id not in unit_ids:
            issues.append({
                "type": "orphan", "entity": "contract", "id": c.id,
                "detail": f"unit_id {c.unit_id} not found",
            })
        if c.tenant_id not in tenant_ids:
            issues.append({
                "type": "orphan", "entity": "contract", "id": c.id,
                "detail": f"tenant_id {c.tenant_id} not found",
            })
        if c.property_id not in property_ids:
            issues.append({
                "type": "orphan", "entity": "contract", "id": c.id,
                "detail": f"property_id {c.property_id} not found",
            })

    # Check: bookings referencing non-existent accounts
    account_ids = {a.id for a in store.list_accounts()}
    for b in store.list_bookings():
        if b.account_id not in account_ids:
            issues.append({
                "type": "orphan", "entity": "booking", "id": b.id,
                "detail": f"account_id {b.account_id} not found",
            })

    return {
        "status": "ok" if not issues else "issues_found",
        "issues_count": len(issues),
        "issues": issues[:50],  # limit response size
    }


# ─── Export / Import ─────────────────────────────────────────────────────────

@router.get("/export", response_model=None)
def export_data():
    """Export all data as JSON."""
    try:
        data = _export_store_data()
        content = json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False)
    except Exception as exc:
        raise HTTPException(500, "Export fehlgeschlagen; keine Teildatei erstellt.") from exc

    return StreamingResponse(
        iter([content]),
        media_type="application/json",
        headers={"Content-Disposition": "attachment; filename=immomanager_export.json"},
    )


@router.post("/import", response_model=None)
def import_data(file: UploadFile):
    raw = file.file.read(settings.max_upload_size_bytes + 1)
    if len(raw) > settings.max_upload_size_bytes:
        raise HTTPException(413, "Importdatei zu gross.")
    try:
        result = _import_store_data(decode_snapshot(raw), replace_existing=False)
    except TransferError as exc:
        raise HTTPException(400, str(exc)) from exc
    return result


# ─── Bulk Operations ─────────────────────────────────────────────────────────

@router.post("/bulk-delete/{entity_type}", response_model=None)
def bulk_delete(entity_type: str, payload: dict):
    """Delete multiple entities by IDs.

    Body: {"ids": ["id1", "id2", ...]}
    """
    ids = payload.get("ids", [])
    if not ids:
        raise HTTPException(400, "Keine IDs angegeben")

    delete_fns = {
        "portfolios": store.delete_portfolio,
        "properties": store.delete_property,
        "units": store.delete_unit,
        "tenants": store.delete_tenant,
        "contracts": store.delete_contract,
        "accounts": store.delete_account,
        "bookings": store.delete_booking,
        "invoices": store.delete_invoice,
        "maintenance_cases": store.delete_maintenance_case,
        "documents": store.delete_document,
        "tasks": store.delete_task,
    }

    delete_fn = delete_fns.get(entity_type)
    if not delete_fn:
        raise HTTPException(400, f"Unbekannter Entitätstyp: {entity_type}")

    deleted = 0
    errors = []
    for eid in ids:
        try:
            delete_fn(eid)
            deleted += 1
        except Exception as e:
            errors.append({"id": eid, "error": str(e)})

    return {"deleted": deleted, "errors": errors}


# ─── Tenant privacy: explicit relationship metadata and profile scope ──────


def _privacy_read(action, tenant_id: str):
    from ..services.tenant_data_graph import TenantExportError, TenantNotFoundError
    try:
        return action(store, tenant_id)
    except TenantNotFoundError as exc:
        raise HTTPException(404, "Mieter nicht gefunden.") from exc
    except TenantExportError as exc:
        raise HTTPException(503, "Die Datenauskunft konnte nicht vollständig erstellt werden.") from exc


@router.get("/dsgvo/tenant/{tenant_id}/export", response_model=None)
def dsgvo_export_tenant_data(tenant_id: str):
    """Export explicitly related metadata; excluded files/records are listed."""
    import hashlib

    from starlette.background import BackgroundTask

    from ..services.tenant_privacy import export_tenant_metadata, metadata_download
    graph = _privacy_read(export_tenant_metadata, tenant_id)
    graph["exported_at"] = datetime.now(timezone.utc).isoformat()
    filename_id = hashlib.sha256(tenant_id.encode("utf-8")).hexdigest()[:16]
    try:
        output = metadata_download(graph)
    except Exception as exc:
        raise HTTPException(503, "Export konnte nicht gespeichert werden. Freien Speicher prüfen und erneut versuchen.") from exc
    output.seek(0, 2)
    size = output.tell()
    output.seek(0)
    return StreamingResponse(iter(lambda: output.read(64 * 1024), b""),
                             background=BackgroundTask(output.close),
                             media_type="application/json", headers={
        "Content-Length": str(size),
        "Content-Disposition": f'attachment; filename="tenant_metadata_{filename_id}.json"',
        "Cache-Control": "private, no-store",
        "X-Content-Type-Options": "nosniff",
    })


@router.get("/dsgvo/tenant/{tenant_id}/anonymization-preview", response_model=None)
def dsgvo_anonymization_preview(tenant_id: str):
    from ..services.tenant_privacy import preview_tenant_anonymization
    return _privacy_read(preview_tenant_anonymization, tenant_id)


class TenantAnonymizationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    plan_hash: str = Field(pattern=r"^[a-f0-9]{64}$")
    confirm_tenant_id: str = Field(min_length=1, max_length=128)


@router.post("/dsgvo/tenant/{tenant_id}/anonymize", response_model=None)
def dsgvo_anonymize_tenant(tenant_id: str, body: TenantAnonymizationRequest):
    """Atomically anonymize the reviewed, inactive tenant profile only."""
    from ..services.tenant_data_graph import TenantExportError, TenantNotFoundError
    from ..services.tenant_privacy import PrivacyConflict, anonymize_tenant_profile
    try:
        return anonymize_tenant_profile(store, tenant_id, plan_hash=body.plan_hash,
                                         confirm_tenant_id=body.confirm_tenant_id)
    except TenantNotFoundError as exc:
        raise HTTPException(404, "Mieter nicht gefunden.") from exc
    except PrivacyConflict as exc:
        raise HTTPException(409, str(exc)) from exc
    except HTTPException:
        raise
    except (TenantExportError, TransferError) as exc:
        raise HTTPException(503, "Anonymisierung abgebrochen; keine Teiländerung gespeichert.") from exc
    except Exception as exc:
        raise HTTPException(503, "Anonymisierung abgebrochen; keine Teiländerung gespeichert.") from exc
