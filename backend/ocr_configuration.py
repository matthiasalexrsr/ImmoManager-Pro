"""Configuration-only OCR defaults; safe before private environment loading."""
import math
import re

OCR_DEFAULTS = {
    "OCR_LANGUAGES": "deu+eng",
    "OCR_PDFINFO_PATH": "", "OCR_PDFTOTEXT_PATH": "", "OCR_PDFTOPPM_PATH": "",
    "OCR_TESSERACT_PATH": "", "OCR_TESSDATA_PATH": "",
    "OCR_RENDER_DPI": "200", "OCR_MAX_PDF_PAGES": "80",
    "OCR_MAX_PAGE_PIXELS": "20000000", "OCR_MAX_TOTAL_PIXELS": "120000000",
    "OCR_MAX_RAM_BYTES": "268435456", "OCR_MAX_TEMP_BYTES": "536870912",
    "OCR_MAX_TEXT_BYTES": "4194304", "OCR_TIMEOUT_SECONDS": "90",
}
OCR_PATH_KEYS = frozenset(key for key in OCR_DEFAULTS if key.endswith("_PATH"))
OCR_INTEGER_BUDGETS = frozenset({
    "OCR_RENDER_DPI",
    "OCR_MAX_PDF_PAGES", "OCR_MAX_PAGE_PIXELS", "OCR_MAX_TOTAL_PIXELS",
    "OCR_MAX_RAM_BYTES", "OCR_MAX_TEMP_BYTES", "OCR_MAX_TEXT_BYTES",
})


def validate_ocr_environment(values: dict[str, str]) -> None:
    """Validate supplied optional OCR settings without importing app config."""
    if "OCR_LANGUAGES" in values and not re.fullmatch(r"[A-Za-z0-9_]+(?:\+[A-Za-z0-9_]+)*", values["OCR_LANGUAGES"]):
        raise ValueError("Invalid OCR languages")
    for key in values.keys() & OCR_INTEGER_BUDGETS:
        if not re.fullmatch(r"[0-9]+", values[key]) or int(values[key]) <= 0:
            raise ValueError("Invalid OCR budget")
    if "OCR_TIMEOUT_SECONDS" in values:
        try:
            timeout = float(values["OCR_TIMEOUT_SECONDS"])
        except ValueError:
            raise ValueError("Invalid OCR timeout") from None
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("Invalid OCR timeout")
    if any(any(character in values[key] for character in "\0\r\n") for key in values.keys() & OCR_PATH_KEYS):
        raise ValueError("Invalid OCR path")
