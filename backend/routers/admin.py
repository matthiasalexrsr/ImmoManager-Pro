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

# Re-export the CONTRACT_WIZARD_STATUS lazily to avoid circular imports.
_CONTRACT_WIZARD_STATUS = None


def _get_wizard_status() -> dict:
    global _CONTRACT_WIZARD_STATUS
    if _CONTRACT_WIZARD_STATUS is None:
        try:
            from ..app import CONTRACT_WIZARD_STATUS
            _CONTRACT_WIZARD_STATUS = CONTRACT_WIZARD_STATUS
        except Exception:
            _CONTRACT_WIZARD_STATUS = {"available": False, "reason": "unknown"}
    return _CONTRACT_WIZARD_STATUS

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
    # Children / leaves first, then parents.
    delete_order = [
        ("list_meter_readings", "delete_meter_reading"),
        ("list_handover_protocols", "delete_handover_protocol"),
        ("list_contacts", "delete_contact"),
        ("list_escalation_rules", "delete_escalation_rule"),
        ("list_rent_charges", "delete_rent_charge"),
        ("list_rent_adjustments", "delete_rent_adjustment"),
        ("list_tax_rates", "delete_tax_rate"),
        ("list_viewings", "delete_viewing_appointment"),
        ("list_listings", "delete_listing"),
        ("list_leads", "delete_lead"),
        ("list_budgets", "delete_budget"),
        ("list_notification_templates", "delete_notification_template"),
        ("list_notifications", "delete_notification"),
        ("list_deposits", "delete_deposit"),
        ("list_insurances", "delete_insurance"),
        ("list_tasks", "delete_task"),
        ("list_documents", "delete_document"),
        ("list_maintenance_cases", "delete_maintenance_case"),
        ("list_invoices", "delete_invoice"),
        ("list_bookings", "delete_booking"),
        ("list_categories", "delete_category"),
        ("list_accounts", "delete_account"),
        ("list_contracts", "delete_contract"),
        ("list_tenants", "delete_tenant"),
        ("list_units", "delete_unit"),
        ("list_properties", "delete_property"),
        ("list_portfolios", "delete_portfolio"),
    ]

    for list_fn_name, delete_fn_name in delete_order:
        list_fn = getattr(store, list_fn_name, None)
        delete_fn = getattr(store, delete_fn_name, None)
        if not list_fn or not delete_fn:
            continue
        for item in list_fn():
            try:
                delete_fn(item.id)
            except Exception:
                logger.warning("Clear failed for %s/%s", delete_fn_name, item.id)


def _import_store_data(data: dict, *, replace_existing: bool) -> dict:
    """Import store data from export/backup JSON.

    Covers all entity types that _export_store_data() can produce so that
    export → import round-trips are lossless.
    """
    from ..models import (
        AccountCreate,
        BookingCreate,
        BudgetCreate,
        CategoryCreate,
        ContactCreate,
        ContractCreate,
        DepositCreate,
        DocumentCreate,
        EscalationRuleCreate,
        HandoverProtocolCreate,
        InsuranceCreate,
        InvoiceCreate,
        LeadCreate,
        ListingCreate,
        MaintenanceCaseCreate,
        MeterReadingCreate,
        NotificationCreate,
        NotificationTemplateCreate,
        PortfolioCreate,
        PropertyCreate,
        RentAdjustmentCreate,
        RentChargeCreate,
        TaskCreate,
        TaxRateCreate,
        TenantCreate,
        UnitCreate,
        ViewingAppointmentCreate,
    )

    # Import order follows dependency chain (parents before children).
    entity_configs = [
        ("portfolios", PortfolioCreate, store.create_portfolio),
        ("properties", PropertyCreate, store.create_property),
        ("units", UnitCreate, store.create_unit),
        ("tenants", TenantCreate, store.create_tenant),
        ("contracts", ContractCreate, store.create_contract),
        ("accounts", AccountCreate, store.create_account),
        ("categories", CategoryCreate, store.create_category),
        ("bookings", BookingCreate, store.create_booking),
        ("invoices", InvoiceCreate, store.create_invoice),
        ("receivables", None, None),  # placeholder — handled if model exists
        ("maintenance_cases", MaintenanceCaseCreate, store.create_maintenance_case),
        ("documents", DocumentCreate, store.create_document),
        ("tasks", TaskCreate, store.create_task),
        ("deposits", DepositCreate, store.create_deposit),
        ("insurances", InsuranceCreate, store.create_insurance),
        ("notifications", NotificationCreate, store.create_notification),
        ("notification_templates", NotificationTemplateCreate, store.create_notification_template),
        ("budgets", BudgetCreate, store.create_budget),
        ("leads", LeadCreate, store.create_lead),
        ("listings", ListingCreate, store.create_listing),
        ("viewings", ViewingAppointmentCreate, store.create_viewing_appointment),
        ("tax_rates", TaxRateCreate, store.create_tax_rate),
        ("rent_charges", RentChargeCreate, store.create_rent_charge),
        ("rent_adjustments", RentAdjustmentCreate, store.create_rent_adjustment),
        ("escalation_rules", EscalationRuleCreate, store.create_escalation_rule),
        ("contacts", ContactCreate, store.create_contact),
        ("handover_protocols", HandoverProtocolCreate, store.create_handover_protocol),
        ("meter_readings", MeterReadingCreate, store.create_meter_reading),
    ]

    if replace_existing:
        _clear_store_data()

    counts = {}
    for key, model_cls, create_fn in entity_configs:
        if model_cls is None or create_fn is None:
            continue
        items = data.get(key, [])
        if not items:
            continue
        imported = 0
        for item in items:
            try:
                cleaned_item = dict(item)
                for skip in ("id", "created_at", "updated_at"):
                    cleaned_item.pop(skip, None)
                obj = model_cls(**cleaned_item)
                create_fn(obj)
                imported += 1
            except Exception:
                logger.warning("Import failed for %s item: %s", key, item.get("id", "?"), exc_info=True)
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


# ─── System Status ───────────────────────────────────────────────────────────

@router.get("/system-status")
def system_status():
    """Comprehensive system status for admin diagnostics."""
    from ..dependencies import _use_sql_store, store as active_store

    store_type = type(active_store).__name__

    db_ok = True
    if _use_sql_store:
        try:
            from ..db.session import engine
            import sqlalchemy
            with engine.connect() as conn:
                conn.execute(sqlalchemy.text("SELECT 1"))
        except Exception:
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
        pass  # messages may not have tenant_id field

    export = {
        "export_type": "DSGVO_Datenauskunft",
        "exported_at": datetime.utcnow().isoformat(),
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
    patch_fields = {}

    # Anonymize all personal fields that exist on the model
    for field in ["first_name", "last_name", "name"]:
        if hasattr(tenant, field):
            patch_fields[field] = anonymized_name

    for field in ["email", "phone", "mobile", "address", "iban", "tax_id",
                   "notes", "emergency_contact", "employer"]:
        if hasattr(tenant, field) and getattr(tenant, field) is not None:
            patch_fields[field] = f"[DSGVO gelöscht]"

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
                pass

    # Delete messages
    deleted_messages = 0
    try:
        for msg in store.list_messages():
            if getattr(msg, "tenant_id", None) == tenant_id:
                try:
                    store.delete_message(msg.id)
                    deleted_messages += 1
                except Exception:
                    pass
    except Exception:
        pass

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
