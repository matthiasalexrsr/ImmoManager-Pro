"""OCR service for document text extraction.

Provides OCR/text extraction helpers for images and PDFs.
The module is resilient to optional dependencies not being installed.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "tiff", "tif", "bmp", "webp"}
_PDF_EXTENSIONS = {"pdf"}


@dataclass
class OCRResult:
    """Result of an OCR extraction."""

    success: bool
    text: str = ""
    confidence: float = 0.0
    invoice_number: Optional[str] = None
    invoice_date: Optional[str] = None
    total_amount: Optional[float] = None
    supplier: Optional[str] = None
    errors: list[str] = field(default_factory=list)


def _extract_invoice_fields(text: str) -> dict:
    """Extract structured invoice-like fields from OCR text."""
    fields: dict[str, str | float] = {}

    inv_patterns = [
        r"Rechnungsnr\.?\s*:?\s*(\S+)",
        r"Rechnung\s*Nr\.?\s*:?\s*(\S+)",
        r"Invoice\s*(?:No\.?|Number)\s*:?\s*(\S+)",
        r"RE-?\s*(\d+)",
    ]
    for pat in inv_patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            fields["invoice_number"] = m.group(1)
            break

    date_patterns = [
        r"Rechnungsdatum\s*:?\s*(\d{1,2}[./]\d{1,2}[./]\d{2,4})",
        r"Datum\s*:?\s*(\d{1,2}[./]\d{1,2}[./]\d{2,4})",
        r"(\d{1,2}\.\d{1,2}\.\d{4})",
    ]
    for pat in date_patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            fields["invoice_date"] = m.group(1)
            break

    amount_patterns = [
        r"Gesamtbetrag\s*:?\s*€?\s*([\d.,]+)",
        r"Bruttobetrag\s*:?\s*€?\s*([\d.,]+)",
        r"Gesamt\s*:?\s*€?\s*([\d.,]+)",
        r"Total\s*:?\s*€?\s*([\d.,]+)",
        r"Summe\s*:?\s*€?\s*([\d.,]+)",
    ]
    for pat in amount_patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            amount_str = m.group(1).replace(".", "").replace(",", ".")
            try:
                fields["total_amount"] = float(amount_str)
            except ValueError:
                pass
            break

    return fields


def _image_ocr_bytes(content: bytes, languages: str = "deu+eng") -> Optional[str]:
    try:
        from io import BytesIO

        import pytesseract
        from PIL import Image

        image = Image.open(BytesIO(content))
        text = pytesseract.image_to_string(image, lang=languages)
        return text.strip() or None
    except ImportError:
        logger.info("pytesseract/Pillow not installed - image OCR skipped")
        return None
    except Exception:
        logger.warning("Image OCR failed", exc_info=True)
        return None


def _pdf_text_bytes(content: bytes) -> Optional[str]:
    try:
        from io import BytesIO

        import pdfplumber

        pages_text: list[str] = []
        with pdfplumber.open(BytesIO(content)) as pdf:
            for page in pdf.pages:
                text = page.extract_text()
                if text:
                    pages_text.append(text)
        return "\n\n".join(pages_text).strip() or None
    except ImportError:
        logger.info("pdfplumber not installed - PDF text extraction skipped")
        return None
    except Exception:
        logger.warning("PDF text extraction failed", exc_info=True)
        return None


def extract_text_from_bytes(content: bytes, extension: str, languages: str = "deu+eng") -> Optional[str]:
    """Extract OCR/text from file bytes based on extension."""
    ext = extension.lower().lstrip(".")
    if ext in _IMAGE_EXTENSIONS:
        return _image_ocr_bytes(content, languages=languages)
    if ext in _PDF_EXTENSIONS:
        return _pdf_text_bytes(content)
    return None


def process_document(file_path: str) -> OCRResult:
    """Process a local document through OCR/text extraction and field parsing."""
    path = Path(file_path)
    if not path.exists():
        return OCRResult(success=False, errors=[f"Datei nicht gefunden: {file_path}"])

    ext = path.suffix.lower().lstrip(".")
    if ext not in _IMAGE_EXTENSIONS | _PDF_EXTENSIONS:
        return OCRResult(
            success=False,
            errors=[
                f"Nicht unterstütztes Dateiformat: .{ext}. Unterstützt: PNG, JPG, TIFF, BMP, WEBP, PDF"
            ],
        )

    text = extract_text_from_bytes(path.read_bytes(), ext)
    if text is None:
        return OCRResult(
            success=False,
            errors=[
                "Kein OCR-Engine verfügbar oder kein Text extrahierbar. "
                "Installieren Sie optional pytesseract/Pillow bzw. pdfplumber."
            ],
        )

    fields = _extract_invoice_fields(text)
    return OCRResult(
        success=True,
        text=text,
        confidence=0.85,
        invoice_number=fields.get("invoice_number"),
        invoice_date=fields.get("invoice_date"),
        total_amount=fields.get("total_amount"),
        supplier=fields.get("supplier"),
    )
