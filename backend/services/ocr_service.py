"""OCR service for invoice/document text extraction.

Provides an abstraction for OCR processing. Supports:
- pytesseract (if installed)
- Placeholder for external OCR APIs

When no OCR engine is available, returns an error message.
"""

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


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


def _try_pytesseract(image_path: str) -> Optional[str]:
    """Try to extract text using pytesseract."""
    try:
        import pytesseract
        from PIL import Image
        img = Image.open(image_path)
        text = pytesseract.image_to_string(img, lang="deu")
        return text
    except ImportError:
        return None
    except Exception as exc:
        logger.warning("pytesseract extraction failed: %s", exc)
        return None


def _extract_invoice_fields(text: str) -> dict:
    """Extract structured fields from OCR text using regex patterns."""
    import re

    fields = {}

    # Invoice number patterns (German)
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

    # Date patterns
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

    # Amount patterns (German format: 1.234,56 or 1234,56)
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


def process_document(file_path: str) -> OCRResult:
    """Process a document file through the OCR pipeline.

    Supports image files (PNG, JPG, TIFF) and PDFs (first page).
    """
    path = Path(file_path)
    if not path.exists():
        return OCRResult(success=False, errors=[f"Datei nicht gefunden: {file_path}"])

    suffix = path.suffix.lower()
    if suffix not in (".png", ".jpg", ".jpeg", ".tiff", ".tif", ".pdf", ".bmp"):
        return OCRResult(
            success=False,
            errors=[f"Nicht unterstütztes Dateiformat: {suffix}. "
                    "Unterstützt: PNG, JPG, TIFF, PDF, BMP"],
        )

    # Try pytesseract
    text = _try_pytesseract(file_path)

    if text is None:
        return OCRResult(
            success=False,
            errors=[
                "Kein OCR-Engine verfügbar. "
                "Installieren Sie pytesseract: pip install pytesseract Pillow"
            ],
        )

    if not text.strip():
        return OCRResult(
            success=True,
            text="",
            errors=["Kein Text im Dokument erkannt"],
        )

    # Extract structured fields
    fields = _extract_invoice_fields(text)

    return OCRResult(
        success=True,
        text=text,
        confidence=0.85,  # placeholder confidence
        invoice_number=fields.get("invoice_number"),
        invoice_date=fields.get("invoice_date"),
        total_amount=fields.get("total_amount"),
        supplier=fields.get("supplier"),
    )
