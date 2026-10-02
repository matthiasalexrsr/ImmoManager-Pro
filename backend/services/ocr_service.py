"""OCR service for document text extraction.

Provides OCR/text extraction helpers for images and PDFs.
The module is resilient to optional dependencies not being installed.
"""

from __future__ import annotations

import ctypes
import json
import logging
import math
import os
import re
import selectors
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass, field, replace
from fractions import Fraction
from functools import partial
from pathlib import Path
from typing import Callable, Optional, Sequence

from .ocr_process_tree import ProcessTree

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


class OCRProcessingError(RuntimeError):
    """Correctable local OCR failure with a stable machine code."""

    def __init__(self, code: str, message: str, http_status: int = 422):
        self.code = code
        self.message = message
        self.http_status = http_status
        super().__init__(message)


@dataclass(frozen=True)
class OCRLimits:
    languages: str = "deu+eng"
    pdfinfo_path: str = ""
    pdftotext_path: str = ""
    pdftoppm_path: str = ""
    tesseract_path: str = ""
    tessdata_path: str = ""
    render_dpi: int = 200
    max_pdf_pages: int = 80
    max_page_pixels: int = 20_000_000
    max_total_pixels: int = 120_000_000
    max_ram_bytes: int = 256 * 1024 * 1024
    max_temp_bytes: int = 512 * 1024 * 1024
    max_text_bytes: int = 4 * 1024 * 1024
    timeout_seconds: float = 90.0


@dataclass(frozen=True)
class OCRTextResult:
    text: Optional[str]
    page_count: int = 0
    embedded_text_pages: int = 0
    ocr_pages: int = 0


def _validate_limits(limits: OCRLimits) -> None:
    """Accept positive per-operation budgets without product-size ceilings."""
    integer_fields = ("render_dpi", "max_pdf_pages", "max_page_pixels", "max_total_pixels",
                      "max_ram_bytes", "max_temp_bytes", "max_text_bytes")
    if any(type(getattr(limits, field)) is not int or getattr(limits, field) <= 0 for field in integer_fields):
        raise OCRProcessingError("ocr_config_invalid", "OCR-Budgets müssen positive ganze Zahlen sein. Konfiguration korrigieren.", 503)
    try:
        valid_timeout = math.isfinite(limits.timeout_seconds) and limits.timeout_seconds > 0
    except (TypeError, OverflowError):
        valid_timeout = False
    if isinstance(limits.timeout_seconds, bool) or not valid_timeout:
        raise OCRProcessingError("ocr_config_invalid", "OCR-Zeitbudget muss positiv und endlich sein. Konfiguration korrigieren.", 503)
    if os.name == "nt" and limits.max_ram_bytes > (1 << (8 * ctypes.sizeof(ctypes.c_size_t))) - 1:
        # Windows JobMemoryLimit is SIZE_T. ctypes would otherwise truncate it.
        raise OCRProcessingError("ocr_config_invalid", "OCR-RAM-Budget ist für die Windows-Speichergröße nicht darstellbar. Budget senken.", 503)


CommandRunner = Callable[[Sequence[str], float], subprocess.CompletedProcess[bytes]]
_PAGES_RE = re.compile(rb"(?m)^Pages:\s*(\d+)\s*$")
_PAGE_SIZE_RE = re.compile(
    rb"(?:Page\s+\d+\s+size|Page size):\s*([0-9.]+)\s+x\s+([0-9.]+)\s+pts",
    re.IGNORECASE,
)
_LANG_RE = re.compile(r"^[A-Za-z0-9_]+$")
_RAM_BYTES_PER_PIXEL = 8


def _extract_invoice_fields(text: str) -> dict:
    """Extract structured invoice-like fields from OCR text."""
    fields: dict[str, str | float | None] = {}

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

    # Supplier extraction
    supplier_patterns = [
        r"Lieferant\s*:?\s*(.+)",
        r"Rechnungssteller\s*:?\s*(.+)",
        r"Absender\s*:?\s*(.+)",
        r"Von\s*:?\s*(.+)",
        r"Firma\s*:?\s*(.+)",
    ]
    for pat in supplier_patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            supplier = m.group(1).strip()
            if supplier:
                fields["supplier"] = supplier
            break

    # Cost category inference from text content
    fields["cost_category"] = _infer_cost_category(text)

    return fields


# Cost category keyword mapping for German utility bill terms
_CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "water": ["wasser", "abwasser", "trinkwasser", "wasserversorgung", "kanalgebühr"],
    "heating": ["heizung", "heizkosten", "fernwärme", "gas", "brennstoff", "wärme", "heizöl"],
    "garbage": ["müll", "abfall", "müllabfuhr", "entsorgung", "wertstoff", "restmüll"],
    "electricity": ["strom", "elektr", "allgemeinstrom", "beleuchtung", "hausstrom"],
    "insurance": ["versicherung", "gebäudeversicherung", "haftpflicht", "feuerversicherung"],
    "cleaning": ["reinigung", "hausreinigung", "treppenhausreinigung", "gebäudereinigung"],
    "garden": ["garten", "gartenpflege", "grünanlagen", "winterdienst", "außenanlage"],
    "elevator": ["aufzug", "fahrstuhl", "lift", "aufzugswartung"],
    "chimney": ["schornstein", "schornsteinfeger", "kaminkehrer", "abgasmessung"],
    "property_tax": ["grundsteuer"],
    "cable_tv": ["kabel", "kabelanschluss", "antenne", "sat"],
    "caretaker": ["hausmeister", "hauswart"],
}


def _infer_cost_category(text: str) -> Optional[str]:
    """Infer cost category from OCR text by matching German utility keywords."""
    text_lower = text.lower()
    best_category = None
    best_count = 0

    for category, keywords in _CATEGORY_KEYWORDS.items():
        count = sum(1 for kw in keywords if kw in text_lower)
        if count > best_count:
            best_count = count
            best_category = category

    return best_category


def _image_ocr_bytes(content: bytes, languages: str = "deu+eng") -> Optional[str]:
    """Compatibility entry point using the same limits and runner as PDFs."""
    return extract_image_text_local(content, limits=_settings_limits(languages)).text


def _settings_limits(languages: str | None = None) -> OCRLimits:
    from ..config import settings

    return OCRLimits(
        languages=languages or settings.ocr_languages,
        pdfinfo_path=settings.ocr_pdfinfo_path,
        pdftotext_path=settings.ocr_pdftotext_path,
        pdftoppm_path=settings.ocr_pdftoppm_path,
        tesseract_path=settings.ocr_tesseract_path,
        tessdata_path=getattr(settings, "ocr_tessdata_path", ""),
        render_dpi=settings.ocr_render_dpi,
        max_pdf_pages=settings.ocr_max_pdf_pages,
        max_page_pixels=settings.ocr_max_page_pixels,
        max_total_pixels=settings.ocr_max_total_pixels,
        max_ram_bytes=settings.ocr_max_ram_bytes,
        max_temp_bytes=settings.ocr_max_temp_bytes,
        max_text_bytes=settings.ocr_max_text_bytes,
        timeout_seconds=float(settings.ocr_timeout_seconds),
    )


@dataclass
class _CommandBudget:
    directory: Path | None = None
    temp_bytes: int = 512 * 1024 * 1024
    text_bytes: int = 4 * 1024 * 1024
    ram_bytes: int = 256 * 1024 * 1024
    retained_bytes: int = 0


def _check_command_files(budget: _CommandBudget) -> None:
    if budget.directory is None:
        return
    total = 0
    for path in budget.directory.iterdir():
        if not path.is_file():
            continue
        size = path.stat().st_size
        total += size
        if path.suffix == ".txt" and size > budget.text_bytes:
            raise OCRProcessingError("ocr_text_budget", "OCR-Textbudget überschritten. Dokument aufteilen.")
    if total > budget.temp_bytes:
        raise OCRProcessingError("ocr_temp_budget", "OCR-Temporärspeicherbudget überschritten. Dokument aufteilen.")


def _run_command(
    args: Sequence[str], timeout: float, *, budget: _CommandBudget | None = None,
) -> subprocess.CompletedProcess[bytes]:
    """Drain bounded diagnostic pipes and observe output files during native execution.

    File/RAM observation is sampled; Windows additionally enforces committed
    worker-tree memory. This is not a filesystem quota or arbitrary-code sandbox.
    """
    active = budget or _CommandBudget()
    deadline = time.monotonic() + timeout
    tree = None
    process = None
    try:
        tree = ProcessTree(active.ram_bytes - active.retained_bytes)
        process = subprocess.Popen(
            list(args), stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            shell=False, **tree.creation_options,
        )
        tree.attach(process)
    except OSError as exc:
        if tree is not None:
            tree.close(process)
        if process is not None:
            process.kill()
            process.wait()
            if process.stdout is not None:
                process.stdout.close()
            if process.stderr is not None:
                process.stderr.close()
        raise OCRProcessingError(
            "ocr_tool_unavailable", "Lokales OCR-Werkzeug kann nicht gestartet werden. Pfad und Berechtigungen prüfen.", 503,
        ) from exc
    assert process.stdout is not None and process.stderr is not None
    outputs: list[bytes] = [b"", b""]
    excessive = threading.Event()
    # Tool metadata/diagnostics are not extracted document text. Neither stream
    # may accumulate unbounded bytes in communicate()/PIPE before its deadline.
    pipe_limit = min(256 * 1024, max(4096, active.text_bytes))

    def drain(pipe, index):
        chunks = []
        length = 0
        while chunk := pipe.read(4096):
            length += len(chunk)
            if length > pipe_limit:
                excessive.set()
                break
            chunks.append(chunk)
        outputs[index] = b"".join(chunks)

    readers = [threading.Thread(target=drain, args=(pipe, index), daemon=True)
               for index, pipe in enumerate((process.stdout, process.stderr))] if os.name == "nt" else []
    selector = None
    collected = [bytearray(), bytearray()]
    started_readers = []

    def pump() -> bool:
        if selector is None:
            return False
        events = selector.select(0)
        for key, _ in events:
            try:
                chunk = os.read(key.fd, 4096)
            except BlockingIOError:
                continue
            if not chunk:
                selector.unregister(key.fileobj)
                continue
            target = collected[key.data]
            if len(target) + len(chunk) > pipe_limit:
                excessive.set()
                selector.unregister(key.fileobj)
            else:
                target.extend(chunk)
        return bool(events)

    try:
        if os.name != "nt":
            # POSIX selectors do not block on EOF from an escaped/detached writer.
            # Windows anonymous pipes use the threads owned by its native job.
            selector = selectors.DefaultSelector()
            for index, pipe in enumerate((process.stdout, process.stderr)):
                getattr(os, "set_blocking")(pipe.fileno(), False)
                selector.register(pipe, selectors.EVENT_READ, index)
        for reader in readers:
            try:
                reader.start()
            except RuntimeError as exc:
                raise OCRProcessingError("ocr_worker_unavailable", "Lokaler OCR-Worker kann nicht gestartet werden. Betriebssystemressourcen prüfen.", 503) from exc
            started_readers.append(reader)
        while True:
            pump()
            if excessive.is_set():
                raise OCRProcessingError(
                    "ocr_tool_output_budget", "OCR-Werkzeugausgabe überschreitet das Diagnosebudget. Dokument prüfen.",
                )
            _check_command_files(active)
            memory = tree.memory(process)
            if memory is not None and memory + active.retained_bytes > active.ram_bytes:
                raise OCRProcessingError(
                    "ocr_ram_budget", "OCR-Werkzeug überschreitet das Arbeitsspeicherbudget. Dokument aufteilen oder Budget erhöhen.",
                )
            if process.poll() is not None:
                break
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise subprocess.TimeoutExpired(args, timeout)
            time.sleep(min(0.01, remaining))
    except OSError as exc:
        raise OCRProcessingError("ocr_worker_unavailable", "Lokaler OCR-Worker ist nicht verfügbar. Betriebssystemressourcen prüfen.", 503) from exc
    finally:
        tree.close(process)
        if process.poll() is None:
            process.kill()
        process.wait()
        while pump():
            pass  # Drain only immediately readable, individually bounded bytes.
        for reader in started_readers:
            reader.join()
        if selector is not None:
            selector.close()
            outputs = [bytes(item) for item in collected]
        if process.stdout is not None:
            process.stdout.close()
        if process.stderr is not None:
            process.stderr.close()
    if excessive.is_set():
        raise OCRProcessingError("ocr_tool_output_budget", "OCR-Werkzeugausgabe überschreitet das Diagnosebudget.")
    _check_command_files(active)
    if process.returncode and re.search(rb"MemoryError|bad_alloc|out of memory|cannot allocate memory", outputs[1], re.IGNORECASE):
        raise OCRProcessingError("ocr_ram_budget", "OCR-Werkzeug konnte Arbeitsspeicher nicht reservieren. Budget prüfen.")
    return subprocess.CompletedProcess(args, process.returncode, *outputs)


def _remaining(deadline: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise OCRProcessingError(
            "ocr_timeout",
            "OCR-Zeitbudget überschritten. Dokument aufteilen oder OCR-Zeitbudget erhöhen.",
            504,
        )
    return remaining


def _call(runner: CommandRunner, args: Sequence[str], deadline: float) -> subprocess.CompletedProcess[bytes]:
    try:
        return runner(args, _remaining(deadline))
    except subprocess.TimeoutExpired as exc:
        raise OCRProcessingError(
            "ocr_timeout",
            "OCR-Zeitbudget überschritten. Dokument aufteilen oder OCR-Zeitbudget erhöhen.",
            504,
        ) from exc


def _resolve_tool(configured: str, executable: str, label: str) -> str:
    def native_path(value: str) -> str:
        # Windows can invoke cmd.exe for .bat/.cmd even with shell=False.
        if os.name == "nt" and Path(value).suffix.lower() in {".bat", ".cmd"}:
            raise OCRProcessingError("ocr_config_invalid", f"{label} muss eine native ausführbare Datei sein, kein Batchskript.", 503)
        return value

    if configured.strip():
        candidate = Path(configured).expanduser()
        if candidate.is_file():
            return native_path(str(candidate))
        raise OCRProcessingError(
            "ocr_tool_missing",
            f"Konfiguriertes {label}-Werkzeug wurde nicht gefunden. OCR-Pfad prüfen.",
            503,
        )
    found = shutil.which(executable)
    if found:
        return native_path(found)
    raise OCRProcessingError(
        "ocr_tool_missing",
        f"{label} ist lokal nicht installiert oder nicht im PATH verfügbar.",
        503,
    )


def _page_count(pdfinfo: str, pdf_path: Path, runner: CommandRunner, deadline: float) -> int:
    result = _call(runner, [pdfinfo, str(pdf_path)], deadline)
    if result.returncode != 0:
        raise OCRProcessingError("ocr_invalid_pdf", "PDF-Metadaten konnten nicht gelesen werden.")
    match = _PAGES_RE.search(result.stdout)
    if not match:
        raise OCRProcessingError("ocr_invalid_pdf", "PDF-Seitenzahl konnte nicht bestimmt werden.")
    return int(match.group(1))


def _page_points(
    pdfinfo: str,
    pdf_path: Path,
    page_number: int,
    runner: CommandRunner,
    deadline: float,
) -> tuple[float, float]:
    result = _call(
        runner,
        [pdfinfo, "-f", str(page_number), "-l", str(page_number), "-box", str(pdf_path)],
        deadline,
    )
    if result.returncode != 0:
        raise OCRProcessingError("ocr_invalid_pdf", f"PDF-Seite {page_number} konnte nicht geprüft werden.")
    match = _PAGE_SIZE_RE.search(result.stdout)
    if not match:
        raise OCRProcessingError(
            "ocr_invalid_pdf",
            f"Seitengröße von PDF-Seite {page_number} konnte nicht bestimmt werden.",
        )
    return float(match.group(1)), float(match.group(2))


def _read_text_file(path: Path, remaining_bytes: int) -> tuple[str, int]:
    if remaining_bytes < 0:
        raise OCRProcessingError(
            "ocr_text_budget",
            "OCR-Textbudget überschritten. Dokument aufteilen oder Textbudget erhöhen.",
        )
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise OCRProcessingError("ocr_tool_failed", "Lokale OCR-Ausgabe fehlt.") from exc
    if size > remaining_bytes:
        raise OCRProcessingError(
            "ocr_text_budget",
            "OCR-Textbudget überschritten. Dokument aufteilen oder Textbudget erhöhen.",
        )
    data = path.read_bytes()
    return data.decode("utf-8", errors="replace").strip(), len(data)


def _extract_embedded_page(
    pdftotext: str,
    pdf_path: Path,
    page_number: int,
    output_path: Path,
    remaining_text_bytes: int,
    runner: CommandRunner,
    deadline: float,
) -> tuple[str, int]:
    result = _call(
        runner,
        [
            pdftotext,
            "-f",
            str(page_number),
            "-l",
            str(page_number),
            "-layout",
            "-enc",
            "UTF-8",
            str(pdf_path),
            str(output_path),
        ],
        deadline,
    )
    if result.returncode != 0:
        raise OCRProcessingError(
            "ocr_text_extract_failed",
            f"Vorhandener PDF-Text auf Seite {page_number} konnte nicht gelesen werden.",
        )
    try:
        return _read_text_file(output_path, remaining_text_bytes)
    finally:
        output_path.unlink(missing_ok=True)


def _png_dimensions(path: Path) -> tuple[int, int]:
    with path.open("rb") as handle:
        header = handle.read(24)
    if len(header) != 24 or header[:8] != b"\x89PNG\r\n\x1a\n" or header[12:16] != b"IHDR":
        raise OCRProcessingError("ocr_render_failed", "PDF-Renderer erzeugte kein gültiges PNG.")
    return int.from_bytes(header[16:20], "big"), int.from_bytes(header[20:24], "big")


def _required_languages(value: str) -> tuple[str, ...]:
    languages = tuple(part.strip() for part in value.split("+") if part.strip())
    if not languages or any(not _LANG_RE.fullmatch(part) for part in languages):
        raise OCRProcessingError("ocr_config_invalid", "OCR-Sprachkonfiguration ist ungültig.", 500)
    return languages


def _tessdata_arguments(value: str) -> list[str]:
    if not value.strip():
        return []
    path = Path(value).expanduser()
    if not path.is_dir():
        raise OCRProcessingError(
            "ocr_language_missing", "Konfiguriertes Tesseract-Sprachdatenverzeichnis fehlt. OCR-Sprachdatenpfad prüfen.", 503,
        )
    return ["--tessdata-dir", str(path)]


def _check_tesseract_languages(
    tesseract: str,
    languages: str,
    runner: CommandRunner,
    deadline: float,
    tessdata_path: str = "",
) -> None:
    result = _call(runner, [tesseract, *_tessdata_arguments(tessdata_path), "--list-langs"], deadline)
    if result.returncode != 0:
        raise OCRProcessingError(
            "ocr_tesseract_unavailable",
            "Tesseract konnte seine lokalen Sprachdaten nicht lesen.",
            503,
        )
    available = {
        line.strip()
        for line in result.stdout.decode("utf-8", errors="replace").splitlines()
        if _LANG_RE.fullmatch(line.strip())
    }
    missing = [language for language in _required_languages(languages) if language not in available]
    if missing:
        raise OCRProcessingError(
            "ocr_language_missing",
            "Tesseract-Sprachdaten fehlen: " + ", ".join(missing) + ". Sprachpakete lokal installieren.",
            503,
        )


def _ocr_rendered_page(
    png_path: Path,
    output_base: Path,
    tesseract: str,
    languages: str,
    remaining_text_bytes: int,
    remaining_temp_bytes: int,
    runner: CommandRunner,
    deadline: float,
    tessdata_path: str = "",
) -> tuple[str, int]:
    result = _call(
        runner,
        [tesseract, str(png_path), str(output_base), "-l", languages, "--psm", "6", *_tessdata_arguments(tessdata_path)],
        deadline,
    )
    if result.returncode != 0:
        stderr = result.stderr.decode("utf-8", errors="replace").lower()
        if "failed loading language" in stderr or "error opening data file" in stderr:
            raise OCRProcessingError(
                "ocr_language_missing",
                "Tesseract-Sprachdaten fehlen oder sind nicht lesbar.",
                503,
            )
        raise OCRProcessingError(
            "ocr_tesseract_failed",
            "Tesseract konnte das vorbereitete Bild nicht lesen.",
        )
    text_path = output_base.with_suffix(".txt")
    try:
        try:
            temp_size = png_path.stat().st_size + text_path.stat().st_size
        except OSError as exc:
            raise OCRProcessingError("ocr_tool_failed", "Lokale OCR-Ausgabe fehlt.") from exc
        if temp_size > remaining_temp_bytes:
            raise OCRProcessingError(
                "ocr_temp_budget",
                "OCR-Temporärspeicherbudget überschritten. Dokument aufteilen.",
            )
        return _read_text_file(text_path, remaining_text_bytes)
    finally:
        text_path.unlink(missing_ok=True)


def extract_pdf_text_local(
    content: bytes,
    *,
    limits: OCRLimits | None = None,
    runner: CommandRunner = _run_command,
) -> OCRTextResult:
    """Bounded local PDF text-first extraction with page-wise raster OCR fallback."""
    active = limits or _settings_limits()
    _validate_limits(active)
    if not content.startswith(b"%PDF-"):
        raise OCRProcessingError("ocr_invalid_pdf", "Datei ist kein unterstütztes PDF.")
    if len(content) > active.max_temp_bytes:
        raise OCRProcessingError("ocr_temp_budget", "PDF überschreitet das OCR-Temporärspeicherbudget.")
    if len(content) > active.max_ram_bytes:
        raise OCRProcessingError("ocr_ram_budget", "PDF überschreitet das OCR-Arbeitsspeicherbudget.")
    deadline = time.monotonic() + active.timeout_seconds
    pdfinfo = _resolve_tool(active.pdfinfo_path, "pdfinfo", "Poppler pdfinfo")
    pdftotext = _resolve_tool(active.pdftotext_path, "pdftotext", "Poppler pdftotext")

    with tempfile.TemporaryDirectory(prefix="immo-ocr-") as temp_name:
        temp = Path(temp_name)
        command_budget = _CommandBudget(
            directory=temp, temp_bytes=active.max_temp_bytes, text_bytes=active.max_text_bytes,
            ram_bytes=active.max_ram_bytes, retained_bytes=len(content),
        )
        if runner is _run_command:
            runner = partial(_run_command, budget=command_budget)
        pdf_path = temp / "input.pdf"
        pdf_path.write_bytes(content)
        count = _page_count(pdfinfo, pdf_path, runner, deadline)
        if count < 1:
            raise OCRProcessingError("ocr_invalid_pdf", "PDF enthält keine Seiten.")
        if count > active.max_pdf_pages:
            raise OCRProcessingError(
                "ocr_page_budget",
                f"PDF hat {count} Seiten; OCR-Seitenbudget ist {active.max_pdf_pages}. Dokument aufteilen.",
            )

        page_text: list[str] = []
        missing_pages: list[int] = []
        text_bytes = 0
        embedded_pages = 0
        for page_number in range(1, count + 1):
            command_budget.text_bytes = active.max_text_bytes - text_bytes
            command_budget.retained_bytes = len(content) + 4 * text_bytes
            output_path = temp / f"embedded-{page_number}.txt"
            text, used = _extract_embedded_page(
                pdftotext,
                pdf_path,
                page_number,
                output_path,
                active.max_text_bytes - text_bytes,
                runner,
                deadline,
            )
            text_bytes += used
            page_text.append(text)
            if text:
                embedded_pages += 1
            else:
                missing_pages.append(page_number)

        if not missing_pages:
            combined = "\n\n".join(page_text).strip() or None
            return OCRTextResult(combined, count, embedded_pages, 0)

        pdftoppm = _resolve_tool(active.pdftoppm_path, "pdftoppm", "Poppler pdftoppm")
        tesseract = _resolve_tool(active.tesseract_path, "tesseract", "Tesseract")
        _check_tesseract_languages(tesseract, active.languages, runner, deadline, active.tessdata_path)

        total_pixels = 0
        ocr_pages = 0
        for page_number in missing_pages:
            command_budget.text_bytes = active.max_text_bytes - text_bytes
            command_budget.retained_bytes = len(content) + 4 * text_bytes
            width_points, height_points = _page_points(
                pdfinfo, pdf_path, page_number, runner, deadline
            )
            # Integer/Fraction arithmetic keeps even an explicitly huge DPI
            # inside the corrective pixel-budget boundary, without float overflow.
            width_px = max(1, math.ceil(Fraction(width_points) * active.render_dpi / 72))
            height_px = max(1, math.ceil(Fraction(height_points) * active.render_dpi / 72))
            estimated_pixels = width_px * height_px
            if estimated_pixels > active.max_page_pixels:
                raise OCRProcessingError(
                    "ocr_pixel_budget",
                    f"PDF-Seite {page_number} überschreitet das Pixelbudget. DPI reduzieren oder Dokument aufteilen.",
                )
            if total_pixels + estimated_pixels > active.max_total_pixels:
                raise OCRProcessingError(
                    "ocr_pixel_budget",
                    "Gesamtes OCR-Pixelbudget überschritten. Dokument aufteilen.",
                )
            estimated_ram = len(content) + text_bytes + estimated_pixels * _RAM_BYTES_PER_PIXEL
            if estimated_ram > active.max_ram_bytes:
                raise OCRProcessingError(
                    "ocr_ram_budget",
                    f"PDF-Seite {page_number} überschreitet das OCR-Arbeitsspeicherbudget.",
                )

            prefix = temp / f"raster-{page_number}"
            png_path = prefix.with_suffix(".png")
            result = _call(
                runner,
                [
                    pdftoppm,
                    "-f",
                    str(page_number),
                    "-l",
                    str(page_number),
                    "-singlefile",
                    "-png",
                    "-r",
                    str(active.render_dpi),
                    str(pdf_path),
                    str(prefix),
                ],
                deadline,
            )
            if result.returncode != 0 or not png_path.is_file():
                raise OCRProcessingError(
                    "ocr_render_failed",
                    f"PDF-Seite {page_number} konnte nicht gerendert werden.",
                )
            width, height = _png_dimensions(png_path)
            actual_pixels = width * height
            if actual_pixels > active.max_page_pixels or total_pixels + actual_pixels > active.max_total_pixels:
                raise OCRProcessingError(
                    "ocr_pixel_budget",
                    f"Gerenderte PDF-Seite {page_number} überschreitet das Pixelbudget.",
                )
            if len(content) + text_bytes + actual_pixels * _RAM_BYTES_PER_PIXEL > active.max_ram_bytes:
                raise OCRProcessingError(
                    "ocr_ram_budget",
                    f"Gerenderte PDF-Seite {page_number} überschreitet das OCR-Arbeitsspeicherbudget.",
                )
            if len(content) + png_path.stat().st_size > active.max_temp_bytes:
                raise OCRProcessingError(
                    "ocr_temp_budget",
                    "OCR-Temporärspeicherbudget überschritten. Dokument aufteilen.",
                )

            output_base = temp / f"ocr-{page_number}"
            try:
                text, used = _ocr_rendered_page(
                    png_path,
                    output_base,
                    tesseract,
                    active.languages,
                    active.max_text_bytes - text_bytes,
                    active.max_temp_bytes - len(content),
                    runner,
                    deadline,
                    active.tessdata_path,
                )
            finally:
                png_path.unlink(missing_ok=True)
            text_bytes += used
            page_text[page_number - 1] = text
            total_pixels += actual_pixels
            ocr_pages += 1

        combined = "\n\n".join(page_text).strip() or None
        return OCRTextResult(combined, count, embedded_pages, ocr_pages)


def _image_worker_args(input_path: Path, max_pages: int, *, frame: int | None = None, output: Path | None = None) -> list[str]:
    if getattr(sys, "frozen", False):
        args = [sys.executable, "--ocr-image-worker"]
    else:
        args = [sys.executable, "-I", str(Path(__file__).with_name("ocr_image_worker.py"))]
    args.extend(["--input", str(input_path), "--max-pages", str(max_pages)])
    if frame is not None and output is not None:
        args.extend(["--frame", str(frame), "--output", str(output)])
    return args


def _image_worker_result(result: subprocess.CompletedProcess[bytes]) -> dict:
    try:
        data = json.loads(result.stdout)
    except (ValueError, UnicodeDecodeError) as exc:
        raise OCRProcessingError("ocr_image_worker_failed", "Bild-Worker lieferte keine gültige Ausgabe. Lokale Installation prüfen.", 503) from exc
    if result.returncode or not isinstance(data, dict) or data.get("error"):
        code = data.get("error") if isinstance(data, dict) else None
        if code == "ocr_image_dependency_missing":
            raise OCRProcessingError(code, "Pillow für Bild-OCR fehlt. Lokale OCR-Abhängigkeiten installieren.", 503)
        if code == "ocr_ram_budget":
            raise OCRProcessingError(code, "Bild überschreitet das OCR-Arbeitsspeicherbudget. Auflösung reduzieren oder Budget erhöhen.")
        raise OCRProcessingError("ocr_invalid_image", "Bilddatei kann nicht gelesen werden. Original prüfen oder in PNG/JPEG umwandeln.")
    return data


def extract_image_text_local(content: bytes, *, limits: OCRLimits | None = None,
                             runner: CommandRunner = _run_command) -> OCRTextResult:
    """Bounded header inspection, one-frame normalization and native Tesseract.

    No raster is decoded in the API process. Original bytes are copied unchanged
    to private temporary storage; no business records are created here.
    """
    active = limits or _settings_limits()
    _validate_limits(active)
    if len(content) > active.max_temp_bytes:
        raise OCRProcessingError("ocr_temp_budget", "Bild überschreitet das OCR-Temporärspeicherbudget. Datei verkleinern.")
    if len(content) >= active.max_ram_bytes:
        raise OCRProcessingError("ocr_ram_budget", "Bild überschreitet das OCR-Arbeitsspeicherbudget. Datei verkleinern.")
    deadline = time.monotonic() + active.timeout_seconds
    with tempfile.TemporaryDirectory(prefix="immo-image-ocr-") as temp_name:
        temp = Path(temp_name)
        source = temp / "original"
        source.write_bytes(content)
        budget = _CommandBudget(directory=temp, temp_bytes=active.max_temp_bytes,
                                text_bytes=active.max_text_bytes, ram_bytes=active.max_ram_bytes,
                                retained_bytes=len(content))
        if runner is _run_command:
            runner = partial(_run_command, budget=budget)
        metadata = _image_worker_result(_call(runner, _image_worker_args(source, active.max_pdf_pages), deadline))
        sizes = metadata.get("sizes")
        if not isinstance(sizes, list) or not sizes or any(not isinstance(size, list) or len(size) != 2
                or any(type(value) is not int or value < 1 for value in size) for size in sizes):
            raise OCRProcessingError("ocr_invalid_image", "Bildgröße konnte nicht bestimmt werden. Original prüfen.")
        if len(sizes) > active.max_pdf_pages:
            raise OCRProcessingError("ocr_page_budget", f"Bild hat mehr als {active.max_pdf_pages} Seiten; OCR-Seitenbudget überschritten. Dokument aufteilen.")
        total_pixels = 0
        for width, height in sizes:
            pixels = width * height
            total_pixels += pixels
            if pixels > active.max_page_pixels or total_pixels > active.max_total_pixels:
                raise OCRProcessingError("ocr_pixel_budget", f"Bild überschreitet das OCR-Pixelbudget ({active.max_page_pixels} je Seite, {active.max_total_pixels} gesamt). Auflösung reduzieren oder Dokument aufteilen.")
            # Decode + color conversion + native OCR buffers; actual worker RAM
            # remains observed/enforced independently of this conservative check.
            if len(content) + pixels * 32 > active.max_ram_bytes:
                raise OCRProcessingError("ocr_ram_budget", f"Bild überschreitet das OCR-Arbeitsspeicherbudget ({active.max_ram_bytes} Bytes). Auflösung reduzieren oder Budget erhöhen.")
        tesseract = _resolve_tool(active.tesseract_path, "tesseract", "Tesseract")
        _check_tesseract_languages(tesseract, active.languages, runner, deadline, active.tessdata_path)
        texts = []
        text_bytes = 0
        for index, (width, height) in enumerate(sizes):
            budget.text_bytes = active.max_text_bytes - text_bytes
            budget.retained_bytes = len(content) + 4 * text_bytes
            if budget.retained_bytes + width * height * 32 > active.max_ram_bytes:
                raise OCRProcessingError("ocr_ram_budget", "Bild und bereits erkannter Text überschreiten das OCR-Arbeitsspeicherbudget. Dokument aufteilen.")
            png = temp / f"frame-{index}.png"
            try:
                normalized = _image_worker_result(_call(runner, _image_worker_args(source, active.max_pdf_pages, frame=index, output=png), deadline))
                if normalized.get("normalized") is not True or _png_dimensions(png) != (width, height):
                    raise OCRProcessingError("ocr_invalid_image", "Normalisiertes Bild entspricht nicht der geprüften Bildgröße.")
                text, used = _ocr_rendered_page(png, temp / f"text-{index}", tesseract, active.languages,
                        active.max_text_bytes - text_bytes, active.max_temp_bytes - len(content), runner,
                        deadline, active.tessdata_path)
                text_bytes += used
                texts.append(text)
            finally:
                png.unlink(missing_ok=True)
        return OCRTextResult("\n\n".join(texts).strip() or None, len(sizes), 0, len(sizes))


def extract_text_with_details(
    content: bytes,
    extension: str,
    languages: str | None = None,
    *,
    limits: OCRLimits | None = None,
    runner: CommandRunner = _run_command,
) -> OCRTextResult:
    ext = extension.lower().lstrip(".")
    if ext in _IMAGE_EXTENSIONS | _PDF_EXTENSIONS:
        active = limits or _settings_limits(languages)
        if languages and active.languages != languages:
            active = replace(active, languages=languages)
        extractor = extract_image_text_local if ext in _IMAGE_EXTENSIONS else extract_pdf_text_local
        return extractor(content, limits=active, runner=runner)
    return OCRTextResult(text=None)


def extract_text_from_bytes(content: bytes, extension: str, languages: str | None = None) -> Optional[str]:
    """Compatibility wrapper: callers needing error detail should use extract_text_with_details."""
    try:
        return extract_text_with_details(content, extension, languages).text
    except OCRProcessingError as exc:
        logger.info("Local OCR unavailable: %s", exc.code)
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

    try:
        extraction = extract_text_with_details(path.read_bytes(), ext)
    except OCRProcessingError as exc:
        return OCRResult(success=False, errors=[exc.message])
    text = extraction.text
    if text is None:
        return OCRResult(
            success=False,
            errors=["Kein Text aus dem Dokument extrahierbar."],
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
