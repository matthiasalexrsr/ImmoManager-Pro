"""Data export and import router for full system backup/restore."""

import json
import logging
from datetime import date, datetime
from io import BytesIO

from fastapi import APIRouter, File, HTTPException, UploadFile, status
from fastapi.responses import StreamingResponse

from ..dependencies import store

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/data", tags=["Daten-Export/Import"])


def _json_serial(obj):
    """JSON serializer for objects not serializable by default."""
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    raise TypeError(f"Type {type(obj)} not serializable")


@router.get("/export")
def export_all_data() -> StreamingResponse:
    """Export all data as a single JSON file."""
    data = {}
    entity_methods = {
        "portfolios": "list_portfolios",
        "properties": "list_properties",
        "units": "list_units",
        "tenants": "list_tenants",
        "contracts": "list_contracts",
        "accounts": "list_accounts",
        "categories": "list_categories",
        "bookings": "list_bookings",
        "receivables": "list_receivables",
        "invoices": "list_invoices",
        "maintenance_cases": "list_maintenance_cases",
        "documents": "list_documents",
        "tasks": "list_tasks",
        "calendar_events": "list_calendar_events",
        "deposits": "list_deposits",
        "insurances": "list_insurances",
        "notifications": "list_notifications",
        "handover_protocols": "list_handover_protocols",
        "meter_readings": "list_meter_readings",
        "budgets": "list_budgets",
    }

    for key, method_name in entity_methods.items():
        try:
            method = getattr(store, method_name, None)
            if method:
                items = method()
                data[key] = [item.model_dump() for item in items]
            else:
                data[key] = []
        except Exception:
            logger.warning("Export failed for %s", key, exc_info=True)
            data[key] = []

    json_bytes = json.dumps(data, default=_json_serial, indent=2, ensure_ascii=False).encode("utf-8")
    return StreamingResponse(
        BytesIO(json_bytes),
        media_type="application/json",
        headers={"Content-Disposition": "attachment; filename=immomanager_export.json"},
    )


@router.post("/import", status_code=status.HTTP_200_OK)
async def import_data(file: UploadFile = File(...)) -> dict:
    """Import data from a JSON export file. Creates new records (does not overwrite existing)."""
    try:
        content = await file.read()
        data = json.loads(content.decode("utf-8"))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Ungültige JSON-Datei: {exc}") from exc

    if not isinstance(data, dict):
        raise HTTPException(status_code=400, detail="JSON muss ein Objekt sein")

    results = {"imported": {}, "errors": {}}

    # Map entity keys to (create_method, create_model_class)
    from ..models import (
        AccountCreate,
        BookingCreate,
        CategoryCreate,
        ContractCreate,
        DepositCreate,
        DocumentCreate,
        InsuranceCreate,
        InvoiceCreate,
        MaintenanceCaseCreate,
        PortfolioCreate,
        PropertyCreate,
        TaskCreate,
        TenantCreate,
        UnitCreate,
    )

    entity_map = {
        "portfolios": ("create_portfolio", PortfolioCreate),
        "properties": ("create_property", PropertyCreate),
        "units": ("create_unit", UnitCreate),
        "tenants": ("create_tenant", TenantCreate),
        "contracts": ("create_contract", ContractCreate),
        "accounts": ("create_account", AccountCreate),
        "categories": ("create_category", CategoryCreate),
        "bookings": ("create_booking", BookingCreate),
        "invoices": ("create_invoice", InvoiceCreate),
        "maintenance_cases": ("create_maintenance_case", MaintenanceCaseCreate),
        "documents": ("create_document", DocumentCreate),
        "tasks": ("create_task", TaskCreate),
        "deposits": ("create_deposit", DepositCreate),
        "insurances": ("create_insurance", InsuranceCreate),
    }

    # Import in dependency order
    import_order = [
        "portfolios", "properties", "units", "tenants", "contracts",
        "accounts", "categories", "bookings", "invoices",
        "maintenance_cases", "documents", "tasks", "deposits", "insurances",
    ]

    for key in import_order:
        if key not in data or key not in entity_map:
            continue
        method_name, model_class = entity_map[key]
        method = getattr(store, method_name, None)
        if not method:
            continue

        imported_count = 0
        errors = []
        for item in data[key]:
            try:
                # Remove read-only fields
                for rm_key in ("id", "created_at", "updated_at"):
                    item.pop(rm_key, None)
                model = model_class(**item)
                method(model)
                imported_count += 1
            except Exception as exc:
                errors.append(str(exc))
                if len(errors) >= 10:
                    errors.append("... weitere Fehler ausgelassen")
                    break

        results["imported"][key] = imported_count
        if errors:
            results["errors"][key] = errors

    return results
