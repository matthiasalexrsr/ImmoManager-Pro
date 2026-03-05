"""File upload, download, OCR processing router."""

import logging
import uuid

from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from fastapi.responses import Response

from ..services.file_storage import get_file_storage

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/files", tags=["Dateien"])


@router.post("/upload")
async def upload_file(
    file: UploadFile = File(...),
    folder: str = Query("documents", description="Storage folder"),
) -> dict:
    """Upload a file and return its URL. Triggers OCR for eligible files."""
    storage = get_file_storage()
    ext = (file.filename or "file").rsplit(".", 1)[-1].lower()
    key = f"{folder}/{uuid.uuid4().hex}.{ext}"
    storage.save(key, file.file, content_type=file.content_type or "application/octet-stream")
    file_url = storage.get_url(key)

    result = {
        "file_url": file_url,
        "filename": file.filename,
        "content_type": file.content_type,
        "ocr_url": None,
    }

    # OCR for image/PDF files
    ocr_extensions = {"pdf", "png", "jpg", "jpeg", "tiff", "tif", "bmp"}
    if ext in ocr_extensions:
        try:
            ocr_text = _perform_ocr(storage, key, ext)
            if ocr_text:
                ocr_key = f"{folder}/{key.rsplit('.', 1)[0]}_ocr.txt"
                from io import BytesIO
                ocr_bytes = BytesIO(ocr_text.encode("utf-8"))
                storage.save(ocr_key, ocr_bytes, content_type="text/plain")
                result["ocr_url"] = storage.get_url(ocr_key)
                logger.info("OCR completed for %s", key)
        except Exception:
            logger.warning("OCR failed for %s", key, exc_info=True)

    return result


@router.get("/download")
def download_file(key: str = Query(...)) -> Response:
    """Download a file by its storage key."""
    storage = get_file_storage()
    data = storage.get(key)
    if data is None:
        raise HTTPException(status_code=404, detail="Datei nicht gefunden")

    ext = key.rsplit(".", 1)[-1].lower()
    content_types = {
        "pdf": "application/pdf", "png": "image/png",
        "jpg": "image/jpeg", "jpeg": "image/jpeg",
        "txt": "text/plain", "json": "application/json",
    }
    ct = content_types.get(ext, "application/octet-stream")
    return Response(content=data, media_type=ct)


@router.get("/ocr-text")
def get_ocr_text(file_url: str = Query(...)) -> dict:
    """Get OCR text for a file if available."""
    storage = get_file_storage()
    # Derive OCR key from file URL
    base = file_url.replace("/uploads/", "")
    name, ext = base.rsplit(".", 1) if "." in base else (base, "")
    ocr_key = f"{name}_ocr.txt"

    ocr_data = storage.get(ocr_key)
    if ocr_data is None:
        return {"has_ocr": False, "text": None}
    return {"has_ocr": True, "text": ocr_data.decode("utf-8", errors="replace")}


def _perform_ocr(storage, key: str, ext: str) -> str | None:
    """Attempt OCR on the given file. Returns extracted text or None."""
    file_bytes = storage.get(key)
    if not file_bytes:
        return None

    # Try pytesseract for images
    try:
        if ext in {"png", "jpg", "jpeg", "tiff", "tif", "bmp"}:
            from io import BytesIO

            import pytesseract
            from PIL import Image
            img = Image.open(BytesIO(file_bytes))
            text = pytesseract.image_to_string(img, lang="deu+eng")
            return text.strip() if text.strip() else None
    except ImportError:
        logger.info("pytesseract/Pillow not installed — OCR skipped for images")
    except Exception:
        logger.warning("Image OCR failed for %s", key, exc_info=True)

    # Try pdfplumber for PDFs (text extraction, not OCR)
    try:
        if ext == "pdf":
            from io import BytesIO

            import pdfplumber
            pages_text = []
            with pdfplumber.open(BytesIO(file_bytes)) as pdf:
                for page in pdf.pages:
                    t = page.extract_text()
                    if t:
                        pages_text.append(t)
            if pages_text:
                return "\n\n".join(pages_text)
            # PDF has no text layer — would need OCR via tesseract on rendered pages
            logger.info("PDF has no text layer: %s", key)
    except ImportError:
        logger.info("pdfplumber not installed — PDF text extraction skipped")
    except Exception:
        logger.warning("PDF text extraction failed for %s", key, exc_info=True)

    return None
