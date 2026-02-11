"""Admin API: backup/restore, integrity checks, export/import, version, plugins, bulk ops."""

import json
import logging
import platform
import shutil
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException, UploadFile, status
from fastapi.responses import JSONResponse, StreamingResponse

from ..config import settings
from ..dependencies import store
from ..plugins import get_plugins

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["Admin"])

_BACKUP_DIR = Path("backups")


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

@router.post("/backup", response_model=None)
def create_backup():
    """Create a database backup (SQLite only)."""
    if "sqlite" not in settings.database_url:
        raise HTTPException(400, "Backup is only supported for SQLite databases")

    _BACKUP_DIR.mkdir(exist_ok=True)
    # Extract DB file path from URL
    db_path = settings.database_url.replace("sqlite:///", "")
    if not Path(db_path).exists():
        raise HTTPException(404, "Database file not found")

    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    backup_name = f"backup_{timestamp}.db"
    backup_path = _BACKUP_DIR / backup_name
    shutil.copy2(db_path, backup_path)
    logger.info("Backup created: %s", backup_name)
    return {"backup": backup_name, "size_bytes": backup_path.stat().st_size}


@router.get("/backups")
def list_backups():
    """List available database backups."""
    _BACKUP_DIR.mkdir(exist_ok=True)
    backups = []
    for f in sorted(_BACKUP_DIR.glob("backup_*.db"), reverse=True):
        backups.append({
            "name": f.name,
            "size_bytes": f.stat().st_size,
            "created_at": datetime.fromtimestamp(f.stat().st_mtime).isoformat(),
        })
    return backups


@router.post("/restore/{backup_name}", response_model=None)
def restore_backup(backup_name: str):
    """Restore a database from a backup file (SQLite only)."""
    if "sqlite" not in settings.database_url:
        raise HTTPException(400, "Restore is only supported for SQLite databases")

    backup_path = _BACKUP_DIR / backup_name
    if not backup_path.exists():
        raise HTTPException(404, f"Backup not found: {backup_name}")

    db_path = settings.database_url.replace("sqlite:///", "")
    # Create a safety backup before restoring
    safety = _BACKUP_DIR / f"pre_restore_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.db"
    if Path(db_path).exists():
        shutil.copy2(db_path, safety)
    shutil.copy2(backup_path, db_path)
    logger.info("Database restored from %s", backup_name)
    return {"restored_from": backup_name, "safety_backup": safety.name}


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
            issues.append({"type": "orphan", "entity": "contract", "id": c.id, "detail": f"unit_id {c.unit_id} not found"})
        if c.tenant_id not in tenant_ids:
            issues.append({"type": "orphan", "entity": "contract", "id": c.id, "detail": f"tenant_id {c.tenant_id} not found"})
        if c.property_id not in property_ids:
            issues.append({"type": "orphan", "entity": "contract", "id": c.id, "detail": f"property_id {c.property_id} not found"})

    # Check: bookings referencing non-existent accounts
    account_ids = {a.id for a in store.list_accounts()}
    for b in store.list_bookings():
        if b.account_id not in account_ids:
            issues.append({"type": "orphan", "entity": "booking", "id": b.id, "detail": f"account_id {b.account_id} not found"})

    return {
        "status": "ok" if not issues else "issues_found",
        "issues_count": len(issues),
        "issues": issues[:50],  # limit response size
    }


# ─── Export / Import ─────────────────────────────────────────────────────────

@router.get("/export", response_model=None)
def export_data():
    """Export all data as JSON."""
    data = {
        "version": settings.app_version,
        "exported_at": datetime.utcnow().isoformat(),
        "portfolios": [p.model_dump(mode="json") for p in store.list_portfolios()],
        "properties": [p.model_dump(mode="json") for p in store.list_properties()],
        "units": [u.model_dump(mode="json") for u in store.list_units()],
        "tenants": [t.model_dump(mode="json") for t in store.list_tenants()],
        "contracts": [c.model_dump(mode="json") for c in store.list_contracts()],
        "accounts": [a.model_dump(mode="json") for a in store.list_accounts()],
        "bookings": [b.model_dump(mode="json") for b in store.list_bookings()],
        "invoices": [i.model_dump(mode="json") for i in store.list_invoices()],
        "maintenance_cases": [m.model_dump(mode="json") for m in store.list_maintenance_cases()],
        "documents": [d.model_dump(mode="json") for d in store.list_documents()],
        "tasks": [t.model_dump(mode="json") for t in store.list_tasks()],
    }
    content = json.dumps(data, ensure_ascii=False, indent=2)

    return StreamingResponse(
        iter([content]),
        media_type="application/json",
        headers={"Content-Disposition": "attachment; filename=immomanager_export.json"},
    )


@router.post("/import", response_model=None)
def import_data(file: UploadFile):
    """Import data from a JSON export file."""
    try:
        raw = file.file.read()
        data = json.loads(raw)
    except (json.JSONDecodeError, Exception) as e:
        raise HTTPException(400, f"Ungültige JSON-Datei: {e}")

    from ..models import (
        PortfolioCreate, PropertyCreate, UnitCreate, TenantCreate,
        ContractCreate, AccountCreate, BookingCreate, InvoiceCreate,
        MaintenanceCaseCreate, DocumentCreate, TaskCreate,
    )

    counts = {}
    # Import in dependency order
    entity_configs = [
        ("portfolios", PortfolioCreate, store.create_portfolio),
        ("properties", PropertyCreate, store.create_property),
        ("units", UnitCreate, store.create_unit),
        ("tenants", TenantCreate, store.create_tenant),
        ("contracts", ContractCreate, store.create_contract),
        ("accounts", AccountCreate, store.create_account),
        ("bookings", BookingCreate, store.create_booking),
        ("invoices", InvoiceCreate, store.create_invoice),
        ("maintenance_cases", MaintenanceCaseCreate, store.create_maintenance_case),
        ("documents", DocumentCreate, store.create_document),
        ("tasks", TaskCreate, store.create_task),
    ]

    for key, model_cls, create_fn in entity_configs:
        items = data.get(key, [])
        imported = 0
        for item in items:
            try:
                # Remove read-only fields
                for skip in ("id", "created_at", "updated_at"):
                    item.pop(skip, None)
                obj = model_cls(**item)
                create_fn(obj)
                imported += 1
            except Exception as e:
                logger.warning("Import skip %s item: %s", key, e)
        counts[key] = imported

    logger.info("Data imported: %s", counts)
    return {"imported": counts}


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
