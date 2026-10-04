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


@router.get("/dsgvo/tenant/{tenant_id}/export", response_model=None)
def dsgvo_export_tenant_data(tenant_id: str):
    """T11: DSGVO Art. 15 — Export all personal data for a tenant.

    Returns a JSON file containing all data associated with the given tenant,
    including contracts, bookings, deposits, documents, maintenance cases,
    messages, and handover protocols.
    """
    from io import BytesIO

    from fastapi.responses import StreamingResponse

    # Get the tenant
    try:
        tenant = store.get_tenant(tenant_id)
    except Exception:
        raise HTTPException(404, f"Mieter mit ID {tenant_id} nicht gefunden")

    tenant_data = tenant.model_dump(mode="json")

    # Collect all related data
    contracts = [c.model_dump(mode="json") for c in store.list_contracts()
                 if c.tenant_id == tenant_id]
    contract_ids = {c["id"] for c in contracts}

    bookings = [b.model_dump(mode="json") for b in store.list_bookings()
                if getattr(b, "contract_id", None) in contract_ids]

    deposits = [d.model_dump(mode="json") for d in store.list_deposits()
                if getattr(d, "contract_id", None) in contract_ids]

    documents = [d.model_dump(mode="json") for d in store.list_documents()
                 if getattr(d, "tenant_id", None) == tenant_id]

    maintenance = [m.model_dump(mode="json") for m in store.list_maintenance_cases()
                   if getattr(m, "tenant_id", None) == tenant_id]

    receivables = [r.model_dump(mode="json") for r in store.list_receivables()
                   if getattr(r, "contract_id", None) in contract_ids]

    handover_protocols = [h.model_dump(mode="json") for h in store.list_handover_protocols()
                          if getattr(h, "contract_id", None) in contract_ids]

    messages = []
    try:
        for msg in store.list_messages():
            if getattr(msg, "tenant_id", None) == tenant_id:
                messages.append(msg.model_dump(mode="json"))
    except Exception:
        logger.debug("Could not collect messages for DSGVO export of tenant %s", tenant_id, exc_info=True)

    export = {
        "export_type": "DSGVO_Datenauskunft",
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "tenant": tenant_data,
        "contracts": contracts,
        "bookings": bookings,
        "deposits": deposits,
        "receivables": receivables,
        "documents": documents,
        "maintenance_cases": maintenance,
        "handover_protocols": handover_protocols,
        "messages": messages,
    }

    content = json.dumps(export, ensure_ascii=False, indent=2, default=str)
    return StreamingResponse(
        BytesIO(content.encode("utf-8")),
        media_type="application/json",
        headers={
            "Content-Disposition": f'attachment; filename="dsgvo_export_tenant_{tenant_id}.json"',
        },
    )


@router.post("/dsgvo/tenant/{tenant_id}/anonymize", response_model=None)
def dsgvo_anonymize_tenant(tenant_id: str):
    """T11: DSGVO Art. 17 — Right to erasure / anonymization.

    Anonymizes all personal data for a tenant while preserving financial
    records required for tax retention periods (§ 147 AO: 10 years for
    bookings/invoices). Replaces personal identifiers with anonymized
    placeholders.
    """
    try:
        tenant = store.get_tenant(tenant_id)
    except Exception:
        raise HTTPException(404, f"Mieter mit ID {tenant_id} nicht gefunden")

    # Anonymize tenant personal data
    from ..models import TenantPatch

    anonymized_name = f"Anonymisiert-{tenant_id[:8]}"
    patch_fields: dict[str, Any] = {}

    # Anonymize all personal fields that exist on the model
    for field in ["first_name", "last_name", "name"]:
        if hasattr(tenant, field):
            patch_fields[field] = anonymized_name

    for field in ["email", "phone", "mobile", "address", "iban", "tax_id",
                   "notes", "emergency_contact", "employer"]:
        if hasattr(tenant, field) and getattr(tenant, field) is not None:
            patch_fields[field] = "[DSGVO gelöscht]"

    if patch_fields:
        try:
            patch = TenantPatch(**patch_fields)
            store._patch_entity("tenant", tenant_id, patch)
        except Exception as exc:
            logger.warning("Tenant patch failed during anonymization: %s", exc)

    # Anonymize related documents (remove references, keep financial records)
    anonymized_docs = 0
    for doc in store.list_documents():
        if getattr(doc, "tenant_id", None) == tenant_id:
            try:
                store.delete_document(doc.id)
                anonymized_docs += 1
            except Exception:
                logger.warning("Failed to delete document %s during DSGVO anonymization", doc.id, exc_info=True)

    # Delete messages
    deleted_messages = 0
    try:
        for msg in store.list_messages():
            if getattr(msg, "tenant_id", None) == tenant_id:
                try:
                    store.delete_message(msg.id)
                    deleted_messages += 1
                except Exception:
                    logger.warning("Failed to delete message %s during DSGVO anonymization", msg.id, exc_info=True)
    except Exception:
        logger.debug("Could not list messages for DSGVO anonymization of tenant %s", tenant_id, exc_info=True)

    logger.info(
        "DSGVO anonymization for tenant %s: fields=%d, docs=%d, messages=%d",
        tenant_id, len(patch_fields), anonymized_docs, deleted_messages,
    )

    return {
        "status": "anonymized",
        "tenant_id": tenant_id,
        "anonymized_fields": list(patch_fields.keys()),
        "deleted_documents": anonymized_docs,
        "deleted_messages": deleted_messages,
        "note": "Finanzdaten (Buchungen, Rechnungen) bleiben gemäß § 147 AO erhalten.",
    }
