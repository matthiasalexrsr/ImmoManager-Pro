"""Data export and import router for full system backup/restore.

Delegates to admin._export_store_data / _import_store_data for full entity
coverage and dependency-aware ordering. This ensures export/import parity
between /data/export and /admin/export endpoints.
"""

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
    """Export all data as a single JSON file.

    Uses the canonical export function from admin module for full entity
    coverage and consistent round-trip behaviour.
    """
    from .admin import _export_store_data
    data = _export_store_data()

    json_bytes = json.dumps(data, default=_json_serial, indent=2, ensure_ascii=False).encode("utf-8")
    return StreamingResponse(
        BytesIO(json_bytes),
        media_type="application/json",
        headers={"Content-Disposition": "attachment; filename=immomanager_export.json"},
    )


@router.post("/import", status_code=status.HTTP_200_OK)
async def import_data(file: UploadFile = File(...)) -> dict:
    """Import data from a JSON export file.

    Delegates to the canonical admin import function for full entity coverage
    and dependency-aware ordering. Creates new records (does not overwrite).
    """
    try:
        content = await file.read()
        data = json.loads(content.decode("utf-8"))
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Ungültige JSON-Datei: {exc}") from exc

    if not isinstance(data, dict):
        raise HTTPException(status_code=400, detail="JSON muss ein Objekt sein")

    from .admin import _import_store_data
    try:
        result = _import_store_data(data, replace_existing=False)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Import error: {exc}") from exc

    logger.info("Data imported via /data/import: %s", result.get("imported"))
    return result
