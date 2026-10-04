"""Data export and import (Settings → Datensicherung).

Uses the same lossless snapshot format as /admin/export and /admin/import.
"""

import json
import logging
from datetime import date, datetime
from io import BytesIO

from fastapi import APIRouter, File, HTTPException, UploadFile, status
from fastapi.responses import StreamingResponse

from ..dependencies import store
from ..services.data_snapshot import SnapshotError, export_snapshot, import_snapshot

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/data", tags=["Daten-Export/Import"])


def _json_serial(obj):
    """JSON serializer for objects not serializable by default."""
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    raise TypeError(f"Type {type(obj)} not serializable")


@router.get("/export")
def export_all_data() -> StreamingResponse:
    """Export all business data as a single JSON file."""
    data = export_snapshot(store)

    json_bytes = json.dumps(data, default=_json_serial, indent=2, ensure_ascii=False).encode("utf-8")
    return StreamingResponse(
        BytesIO(json_bytes),
        media_type="application/json",
        headers={"Content-Disposition": "attachment; filename=immomanager_export.json"},
    )


@router.post("/import", status_code=status.HTTP_200_OK)
def import_data(file: UploadFile = File(...)) -> dict:
    """Merge a JSON export into the data.

    Records keep their IDs; records that already exist are skipped, so
    importing the same file twice changes nothing. The file is validated
    completely first: on any problem nothing is written.
    """
    try:
        data = json.loads(file.file.read().decode("utf-8"))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"Ungültige JSON-Datei: {exc}") from exc

    try:
        result = import_snapshot(store, data, replace=False)
    except SnapshotError as exc:
        raise HTTPException(status_code=400, detail=f"Import abgebrochen – {exc}") from exc

    logger.info("Data imported via /data/import: %s", result["imported"])
    return result
