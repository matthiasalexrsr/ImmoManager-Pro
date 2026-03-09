"""Admin API: backup/restore, integrity checks, export/import, version, plugins, bulk ops."""

import json
import logging
import platform
import shutil
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, HTTPException, UploadFile
from fastapi.responses import StreamingResponse

from ..config import settings
from ..dependencies import store
from ..plugins import get_plugins

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["Admin"])

_BACKUP_DIR = Path("backups")


def _safe_list(method_name: str) -> list[dict]:
    """Safely call a store list method and return model_dump results."""
    method = getattr(store, method_name, None)
    if not method:
        return []
    try:
        return [item.model_dump(mode="json") for item in method()]
    except Exception:
        logger.warning("Export failed for %s", method_name, exc_info=True)
        return []


def _export_store_data() -> dict:
    """Build a JSON-serializable snapshot of the active store backend."""
    return {
        "version": settings.app_version,
        "exported_at": datetime.utcnow().isoformat(),
        "portfolios": _safe_list("list_portfolios"),
        "properties": _safe_list("list_properties"),
        "units": _safe_list("list_units"),
        "tenants": _safe_list("list_tenants"),
        "contracts": _safe_list("list_contracts"),
        "accounts": _safe_list("list_accounts"),
        "categories": _safe_list("list_categories"),
        "bookings": _safe_list("list_bookings"),
        "receivables": _safe_list("list_receivables"),
        "invoices": _safe_list("list_invoices"),
        "maintenance_cases": _safe_list("list_maintenance_cases"),
        "documents": _safe_list("list_documents"),
        "tasks": _safe_list("list_tasks"),
        "deposits": _safe_list("list_deposits"),
        "insurances": _safe_list("list_insurances"),
        "notifications": _safe_list("list_notifications"),
        "notification_templates": _safe_list("list_notification_templates"),
        "budgets": _safe_list("list_budgets"),
        "leads": _safe_list("list_leads"),
        "listings": _safe_list("list_listings"),
        "viewings": _safe_list("list_viewings"),
        "tax_rates": _safe_list("list_tax_rates"),
        "rent_charges": _safe_list("list_rent_charges"),
        "escalation_rules": _safe_list("list_escalation_rules"),
        "contacts": _safe_list("list_contacts"),
        "handover_protocols": _safe_list("list_handover_protocols"),
        "meter_readings": _safe_list("list_meter_readings"),
    }


def _clear_store_data() -> None:
    """Delete exported entities in reverse dependency order."""
    delete_order = [
        ("list_tasks", "delete_task"),
        ("list_documents", "delete_document"),
        ("list_maintenance_cases", "delete_maintenance_case"),
        ("list_invoices", "delete_invoice"),
        ("list_bookings", "delete_booking"),
        ("list_accounts", "delete_account"),
        ("list_contracts", "delete_contract"),
        ("list_tenants", "delete_tenant"),
        ("list_units", "delete_unit"),
        ("list_properties", "delete_property"),
        ("list_portfolios", "delete_portfolio"),
    ]

    for list_fn_name, delete_fn_name in delete_order:
        list_fn = getattr(store, list_fn_name)
        delete_fn = getattr(store, delete_fn_name)
        for item in list_fn():
            delete_fn(item.id)


def _import_store_data(data: dict, *, replace_existing: bool) -> dict:
    """Import store data from export/backup JSON."""
    from ..models import (
        AccountCreate,
        BookingCreate,
        ContractCreate,
        DocumentCreate,
        InvoiceCreate,
        MaintenanceCaseCreate,
        PortfolioCreate,
        PropertyCreate,
        TaskCreate,
        TenantCreate,
        UnitCreate,
    )

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

    if replace_existing:
        _clear_store_data()

    counts = {}
    for key, model_cls, create_fn in entity_configs:
        items = data.get(key, [])
        imported = 0
        for item in items:
            cleaned_item = dict(item)
            for skip in ("id", "created_at", "updated_at"):
                cleaned_item.pop(skip, None)
            obj = model_cls(**cleaned_item)
            create_fn(obj)
            imported += 1
        counts[key] = imported

    return {"imported": counts, "replace_existing": replace_existing}


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

@router.post("/backup", response_model=None)
def create_backup():
    """Create a backup of the currently active store backend."""
    _BACKUP_DIR.mkdir(exist_ok=True)

    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    backup_name = f"backup_{timestamp}.json"
    backup_path = _BACKUP_DIR / backup_name
    payload = _export_store_data()
    backup_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    logger.info("Backup created: %s", backup_name)
    return {"backup": backup_name, "size_bytes": backup_path.stat().st_size}


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


@router.post("/restore/{backup_name}", response_model=None)
def restore_backup(backup_name: str):
    """Restore data from a backup file."""
    backup_path = _BACKUP_DIR / backup_name
    if not backup_path.exists():
        raise HTTPException(404, f"Backup not found: {backup_name}")

    if backup_path.suffix == ".json":
        try:
            data = json.loads(backup_path.read_text(encoding="utf-8"))
            return {
                "restored_from": backup_name,
                **_import_store_data(data, replace_existing=True),
            }
        except Exception as exc:
            raise HTTPException(400, f"Invalid JSON backup: {exc}") from exc

    if "sqlite" not in settings.database_url:
        raise HTTPException(400, "Binary DB restore is only supported for SQLite databases")

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
    data = _export_store_data()
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

    try:
        result = _import_store_data(data, replace_existing=False)
    except Exception as exc:
        raise HTTPException(400, f"Import error: {exc}") from exc

    logger.info("Data imported: %s", result["imported"])
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
