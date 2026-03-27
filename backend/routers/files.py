"""File upload, download and OCR access router."""

from __future__ import annotations

import logging
import mimetypes
import posixpath
import uuid
from io import BytesIO
from urllib.parse import unquote, urlparse

from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from fastapi.responses import Response

from ..config import settings
from ..services.ai.document_ai import analyze_document
from ..services.file_storage import get_file_storage
from ..services.ocr_service import extract_text_from_bytes

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/files", tags=["Dateien"])


SUPPORTED_OCR_EXTENSIONS = {"pdf", "png", "jpg", "jpeg", "tiff", "tif", "bmp", "webp"}
_DEFAULT_EXTENSION = "bin"

# Allowed MIME type prefixes for upload.
_ALLOWED_MIME_PREFIXES = (
    "application/pdf",
    "image/",
    "text/",
    "application/json",
    "application/xml",
    "application/vnd.openxmlformats",
    "application/vnd.ms-",
    "application/msword",
    "application/zip",
)

# Dangerous extensions that should never be accepted.
_BLOCKED_EXTENSIONS = {
    "exe", "bat", "cmd", "com", "msi", "scr", "pif", "vbs", "vbe",
    "js", "jse", "wsf", "wsh", "ps1", "sh", "bash", "cgi", "php",
    "py", "rb", "pl", "dll", "so", "dylib",
}


def _normalize_storage_key(value: str) -> str:
    normalized = posixpath.normpath((value or "").replace("\\", "/").strip())
    if normalized in {"", ".", "/"}:
        return ""
    normalized = normalized.lstrip("/")
    if normalized.startswith("../") or normalized == "..":
        return ""
    return normalized


def _safe_extension(filename: str | None) -> str:
    name = (filename or "").strip()
    if "." not in name or name.endswith("."):
        return _DEFAULT_EXTENSION
    ext = name.rsplit(".", 1)[-1].lower().strip()
    return ext if ext.isalnum() else _DEFAULT_EXTENSION


def _file_url_to_key(file_url: str) -> str:
    """Convert a public/local file URL to a storage key."""
    decoded = unquote(file_url or "").strip()
    if not decoded:
        return ""

    parsed = urlparse(decoded)
    if parsed.scheme in {"http", "https"}:
        path = parsed.path or ""
        marker = "/uploads/"
        if marker not in path:
            return ""
        return _normalize_storage_key(path.split(marker, 1)[1])
    if parsed.scheme == "s3":
        bucket = parsed.netloc.strip("/")
        path = (parsed.path or "").lstrip("/")
        if bucket and path:
            return _normalize_storage_key(path)
        return ""
    if parsed.scheme:
        return ""

    for prefix in ("/uploads/", "uploads/"):
        if decoded.startswith(prefix):
            return _normalize_storage_key(decoded[len(prefix) :])

    marker = "/uploads/"
    if marker in decoded:
        return _normalize_storage_key(decoded.split(marker, 1)[1])

    return _normalize_storage_key(decoded)


def _ocr_key_from_file_key(file_key: str) -> str:
    key = _normalize_storage_key(file_key)
    if not key:
        return ""
    stem = key.rsplit(".", 1)[0] if "." in key else key
    return f"{stem}_ocr.txt"


def _perform_ocr(storage, key: str, ext: str) -> str | None:
    """Attempt OCR/text extraction on the given file key."""
    file_bytes = storage.get(key)
    if not file_bytes:
        return None
    return extract_text_from_bytes(file_bytes, ext)


def _validate_upload(file: UploadFile) -> None:
    """Validate file upload for size, extension, and MIME type."""
    ext = _safe_extension(file.filename)
    if ext in _BLOCKED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Dateityp '.{ext}' ist nicht erlaubt",
        )

    # MIME type sniffing: check declared content type
    declared_ct = (file.content_type or "application/octet-stream").lower()
    if not any(declared_ct.startswith(prefix) for prefix in _ALLOWED_MIME_PREFIXES):
        # Also check by extension as a fallback
        guessed_ct, _ = mimetypes.guess_type(file.filename or "")
        if not guessed_ct or not any(guessed_ct.startswith(p) for p in _ALLOWED_MIME_PREFIXES):
            raise HTTPException(
                status_code=400,
                detail=f"MIME-Typ '{declared_ct}' ist nicht erlaubt",
            )


@router.post("/upload")
async def upload_file(
    file: UploadFile = File(...),
    folder: str = Query("documents", description="Storage folder"),
) -> dict:
    """Upload a file and return URLs. Triggers OCR for eligible files."""
    # Enforce file size limit by reading up to the limit + 1 byte
    max_size = settings.max_upload_size_bytes
    contents = await file.read(max_size + 1)
    if len(contents) > max_size:
        raise HTTPException(
            status_code=413,
            detail=f"Datei überschreitet das Limit von {max_size // (1024 * 1024)} MB",
        )

    _validate_upload(file)

    storage = get_file_storage()
    safe_folder = _normalize_storage_key(folder) or "documents"
    ext = _safe_extension(file.filename)
    key = f"{safe_folder}/{uuid.uuid4().hex}.{ext}"
    storage.save(key, BytesIO(contents), content_type=file.content_type or "application/octet-stream")
    file_url = storage.get_url(key)

    result = {
        "file_url": file_url,
        "filename": file.filename,
        "content_type": file.content_type,
        "ocr_url": None,
        "has_ocr": False,
    }

    if ext in SUPPORTED_OCR_EXTENSIONS:
        try:
            ocr_text = _perform_ocr(storage, key, ext)
            if ocr_text:
                ocr_key = _ocr_key_from_file_key(key)
                storage.save(ocr_key, BytesIO(ocr_text.encode("utf-8")), content_type="text/plain")
                result["ocr_url"] = storage.get_url(ocr_key)
                result["has_ocr"] = True
        except Exception:
            logger.warning("OCR failed for %s", key, exc_info=True)

    return result


@router.post("/ocr-process")
def process_ocr(file_url: str = Query(..., description="Public file URL")) -> dict:
    """Process OCR for an already uploaded file and persist OCR text file."""
    storage = get_file_storage()
    key = _file_url_to_key(file_url)
    if not key:
        raise HTTPException(status_code=400, detail="Ungültige Datei-URL")

    ext = key.rsplit(".", 1)[-1].lower() if "." in key else ""
    if ext not in SUPPORTED_OCR_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Dateityp nicht für OCR unterstützt")

    if storage.get(key) is None:
        raise HTTPException(status_code=404, detail="Datei nicht gefunden")

    text = _perform_ocr(storage, key, ext)
    if not text:
        return {"processed": False, "has_ocr": False, "ocr_url": None}

    ocr_key = _ocr_key_from_file_key(key)
    storage.save(ocr_key, BytesIO(text.encode("utf-8")), content_type="text/plain")
    return {"processed": True, "has_ocr": True, "ocr_url": storage.get_url(ocr_key)}


@router.get("/download")
def download_file(key: str = Query(...)) -> Response:
    """Download a file by its storage key."""
    storage = get_file_storage()
    safe_key = _normalize_storage_key(key)
    if not safe_key:
        raise HTTPException(status_code=400, detail="Ungültiger Dateischlüssel")

    # Additional path traversal protection
    if ".." in safe_key or safe_key.startswith("/"):
        raise HTTPException(status_code=400, detail="Ungültiger Dateischlüssel")

    data = storage.get(safe_key)
    if data is None:
        raise HTTPException(status_code=404, detail="Datei nicht gefunden")

    ext = safe_key.rsplit(".", 1)[-1].lower() if "." in safe_key else ""

    # Block download of dangerous file types
    if ext in _BLOCKED_EXTENSIONS:
        raise HTTPException(status_code=403, detail="Dateityp nicht erlaubt")

    content_types = {
        "pdf": "application/pdf",
        "png": "image/png",
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "txt": "text/plain",
        "json": "application/json",
        "xml": "application/xml",
        "csv": "text/csv",
    }
    ct = content_types.get(ext, "application/octet-stream")

    # Extract safe filename for Content-Disposition
    filename = safe_key.rsplit("/", 1)[-1] if "/" in safe_key else safe_key
    # Sanitize filename to prevent header injection
    filename = filename.replace('"', "").replace("\n", "").replace("\r", "")

    headers = {
        "Content-Disposition": f'attachment; filename="{filename}"',
        "X-Content-Type-Options": "nosniff",
    }
    return Response(content=data, media_type=ct, headers=headers)


@router.get("/ocr-text")
def get_ocr_text(file_url: str = Query(...)) -> dict:
    """Get OCR text for a file if available."""
    storage = get_file_storage()
    file_key = _file_url_to_key(file_url)
    if not file_key:
        return {"has_ocr": False, "text": None}

    ocr_key = _ocr_key_from_file_key(file_key)
    if not ocr_key:
        return {"has_ocr": False, "text": None}

    ocr_data = storage.get(ocr_key)
    if ocr_data is None:
        return {"has_ocr": False, "text": None}

    return {"has_ocr": True, "text": ocr_data.decode("utf-8", errors="replace")}


@router.post("/analyze")
def analyze_file(
    file_url: str = Query(..., description="URL of an already-uploaded file"),
    use_ai: bool = Query(True, description="Use AI models (False = regex only)"),
) -> dict:
    """AI-powered document analysis: classification, summarization, entity extraction.

    Reads the OCR text of a previously uploaded file and runs it through
    HF models (zero-shot classification, summarization, NER). Falls back
    gracefully to regex-based extraction when models are unavailable.
    """
    storage = get_file_storage()
    file_key = _file_url_to_key(file_url)
    if not file_key:
        raise HTTPException(status_code=400, detail="Ungültige Datei-URL")

    # Try to get existing OCR text first
    ocr_key = _ocr_key_from_file_key(file_key)
    ocr_text = None
    if ocr_key:
        ocr_data = storage.get(ocr_key)
        if ocr_data is not None:
            ocr_text = ocr_data.decode("utf-8", errors="replace")

    # If no OCR text, try to extract it now
    if not ocr_text:
        ext = file_key.rsplit(".", 1)[-1].lower() if "." in file_key else ""
        if ext not in SUPPORTED_OCR_EXTENSIONS:
            raise HTTPException(status_code=400, detail="Dateityp nicht für Analyse unterstützt")
        ocr_text = _perform_ocr(storage, file_key, ext)

    if not ocr_text:
        return {
            "analyzed": False,
            "message": "Kein Text extrahierbar",
            "result": None,
        }

    result = analyze_document(ocr_text, use_ai=use_ai)

    return {
        "analyzed": True,
        "message": "Analyse abgeschlossen",
        "result": {
            "document_type": result.document_type,
            "document_type_confidence": result.document_type_confidence,
            "summary": result.summary,
            "entities": result.entities,
            "invoice_number": result.invoice_number,
            "invoice_date": result.invoice_date,
            "total_amount": result.total_amount,
            "supplier": result.supplier,
            "cost_category": result.cost_category,
            "ai_model": result.ai_model,
        },
    }
