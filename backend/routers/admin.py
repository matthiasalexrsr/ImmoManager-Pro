"""Admin API: backup/restore, integrity checks, export/import, version, plugins, bulk ops."""

import json
import logging
import platform
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, UploadFile
from fastapi.responses import StreamingResponse

from ..config import settings
from ..dependencies import store
from ..plugins import get_plugins
from ..services.data_snapshot import SnapshotError, export_snapshot, import_snapshot
from ..services.deletion_guard import ensure_deletable

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

# Backup routes (/backup, /backups, /restore) live in admin_runtime.py,
# which is registered first and therefore owns these paths.


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
    """Export all business data as a lossless JSON snapshot."""
    content = json.dumps(export_snapshot(store), ensure_ascii=False, indent=2)

    return StreamingResponse(
        iter([content]),
        media_type="application/json",
        headers={"Content-Disposition": "attachment; filename=immomanager_export.json"},
    )


@router.post("/import", response_model=None)
def import_data(file: UploadFile):
    """Merge a JSON export into the data; records that already exist are skipped."""
    try:
        data = json.loads(file.file.read())
    except ValueError as e:
        raise HTTPException(400, f"Ungültige JSON-Datei: {e}")

    try:
        result = import_snapshot(store, data, replace=False)
    except SnapshotError as exc:
        raise HTTPException(400, f"Import abgebrochen – {exc}") from exc

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

    guarded = {"portfolios": "portfolio", "properties": "property", "units": "unit",
               "tenants": "tenant", "contracts": "contract", "accounts": "account"}

    deleted = 0
    errors = []
    for eid in ids:
        try:
            if entity_type in guarded:
                ensure_deletable(store, guarded[entity_type], eid)
            delete_fn(eid)
            deleted += 1
        except HTTPException as e:
            errors.append({"id": eid, "error": e.detail})
        except Exception as e:
            errors.append({"id": eid, "error": str(e)})

    return {"deleted": deleted, "errors": errors}


# ─── DSGVO / GDPR Compliance ────────────────────────────────────────────────


def _tenant_records(tenant_id: str) -> dict[str, list]:
    """Everything stored about a tenant: by tenant id or through the tenant's contracts."""
    contracts = [c for c in store.list_contracts() if c.tenant_id == tenant_id]
    contract_ids = {c.id for c in contracts}
    threads = [t for t in store.list_message_threads() if t.contract_id in contract_ids]
    thread_ids = {t.id for t in threads}

    def of_contracts(items: list) -> list:
        return [item for item in items if item.contract_id in contract_ids]

    return {
        "contracts": contracts,
        "bookings": [b for b in store.list_bookings() if b.tenant_id == tenant_id],
        "deposits": of_contracts(store.list_deposits()),
        "receivables": of_contracts(store.list_receivables()),
        "rent_charges": of_contracts(store.list_rent_charges()),
        "rent_adjustments": of_contracts(store.list_rent_adjustments()),
        "utility_statements": of_contracts(store.list_utility_statements()),
        "documents": of_contracts(store.list_documents()),
        "handover_protocols": of_contracts(store.list_handover_protocols()),
        "message_threads": threads,
        "messages": [m for m in store.list_messages() if m.thread_id in thread_ids],
    }


@router.get("/dsgvo/tenant/{tenant_id}/export", response_model=None)
def dsgvo_export_tenant_data(tenant_id: str):
    """T11: DSGVO Art. 15 — Export all personal data for a tenant.

    Returns a JSON file with the tenant and every record linked to the tenant
    or to one of the tenant's contracts: bookings, deposits, receivables, rent
    charges and adjustments, utility statements, documents, handover
    protocols and message threads with their messages.
    """
    from io import BytesIO

    try:
        tenant = store.get_tenant(tenant_id)
    except Exception:
        raise HTTPException(404, f"Mieter mit ID {tenant_id} nicht gefunden")

    export = {
        "export_type": "DSGVO_Datenauskunft",
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "tenant": tenant.model_dump(mode="json"),
        **{
            name: [item.model_dump(mode="json") for item in items]
            for name, items in _tenant_records(tenant_id).items()
        },
    }

    content = json.dumps(export, ensure_ascii=False, indent=2, default=str)
    return StreamingResponse(
        BytesIO(content.encode("utf-8")),
        media_type="application/json",
        headers={
            "Content-Disposition": f'attachment; filename="dsgvo_export_tenant_{tenant_id}.json"',
        },
    )


# Personal fields of a tenant that anonymization clears; the name gets a placeholder.
_TENANT_PERSONAL_FIELDS = ("email", "phone", "address_line", "postal_code", "city", "country",
                           "payment_method", "sepa_mandate", "notes")


@router.post("/dsgvo/tenant/{tenant_id}/anonymize", response_model=None)
def dsgvo_anonymize_tenant(tenant_id: str):
    """T11: DSGVO Art. 17 — Right to erasure / anonymization.

    Replaces the tenant's name with a placeholder, clears contact, address,
    payment and note fields and archives the tenant. Contracts, financial
    records, documents and messages stay (retention under § 147 AO and
    § 257 HGB) and are counted in the answer; they refer to the tenant only by id.
    """
    from ..models import TenantPatch

    try:
        tenant = store.get_tenant(tenant_id)
    except Exception:
        raise HTTPException(404, f"Mieter mit ID {tenant_id} nicht gefunden")

    patch: dict[str, Any] = {"full_name": f"Anonymisiert-{tenant_id[:8]}", "archived": True}
    patch.update({field: None for field in _TENANT_PERSONAL_FIELDS if getattr(tenant, field) is not None})
    store._patch_entity("tenant", tenant_id, TenantPatch(**patch))

    retained = {name: len(items) for name, items in _tenant_records(tenant_id).items() if items}
    logger.info("DSGVO anonymization for tenant %s: fields=%s", tenant_id, sorted(patch))

    return {
        "status": "anonymized",
        "tenant_id": tenant_id,
        "anonymized_fields": sorted(field for field in patch if field != "archived"),
        "retained_records": retained,
        "note": "Verträge, Finanzdaten, Dokumente und Nachrichten bleiben wegen der Aufbewahrungspflichten"
                " (§ 147 AO, § 257 HGB) erhalten.",
    }
