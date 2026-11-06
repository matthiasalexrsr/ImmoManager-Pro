"""Pure file readers used only inside the bounded document-text child."""

from __future__ import annotations

import hashlib
import importlib.util
import math
import os
import re
import time
import zipfile
from dataclasses import dataclass, field
from io import BytesIO
from typing import Any

from . import safe_xml

PLAIN = {"txt", "csv", "md", "text"}
OFFICE = {"docx": "word/document.xml", "odt": "content.xml", "ods": "content.xml", "xlsx": "xl/sharedStrings.xml"}
IMAGES = {"png", "jpg", "jpeg", "tif", "tiff", "bmp", "webp"}
CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]")
MAX_OFFICE_MEMBERS = 10_000
MAX_OCR_PIXELS = 20_000_000


@dataclass(frozen=True)
class Budget:
    characters: int = 500_000
    pdf_pages: int = 500
    ocr_pages: int = 20
    file_bytes: int = 50 * 1024 * 1024
    seconds: int = 15


@dataclass
class ExtractionPart:
    text: str = ""
    source: str = "none"
    cursor: dict = field(default_factory=dict)
    indexed_units: int = 0
    total_units: int = 0
    complete: bool = True
    warning: str | None = None
    # Parent-side worker failure is distinct from a successfully empty scan.
    # The index may retain a terminal warning; direct AI reads must reject it.
    failed: bool = False


def normalize(text: str, *, trim: bool = True) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = CONTROL.sub(" ", text)
    text = re.sub(r"[^\S\n]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip() if trim else text


def normalize_part(raw: str, cursor: dict, complete: bool) -> tuple[str, dict]:
    """Carry only trailing whitespace/CR, so chunking cannot split a phrase."""
    if cursor.get("normalization_cr"):
        raw = "\n" + (raw[1:] if raw.startswith("\n") else raw)
    pending_cr = bool(raw.endswith("\r") and not complete)
    if pending_cr:
        raw = raw[:-1]
    value = normalize(cursor.get("normalization_tail", "") + raw, trim=False)
    if complete:
        return value, {}
    trailing = re.search(r"[ \n]*$", value)
    assert trailing is not None
    tail = trailing.group()
    state: dict[str, Any] = {}
    if tail:
        state["normalization_tail"] = tail
    if pending_cr:
        state["normalization_cr"] = True
    return value[: trailing.start()], state


def _archive(content: bytes) -> zipfile.ZipFile:
    archive = zipfile.ZipFile(BytesIO(content))
    names = archive.namelist()
    if len(names) > MAX_OFFICE_MEMBERS or len(set(names)) != len(names):
        archive.close()
        raise ValueError("Zu viele oder mehrdeutige Office-Bestandteile.")
    return archive


def _office_text(content: bytes, member: str, budget: Budget) -> str:
    with _archive(content) as archive:
        if archive.getinfo(member).file_size > budget.file_bytes:
            raise ValueError("Der entpackte Dokumentinhalt überschreitet das Lesebudget.")
        root = safe_xml.fromstring(archive.read(member))
    parts = []

    def walk(element, odt_text=False):
        local = element.tag.rsplit("}", 1)[-1]
        namespace = element.tag.split("}", 1)[0]
        odt_text = odt_text or (local in {"p", "h"} and "opendocument" in namespace)
        if odt_text:
            if local in {"s", "tab"}:
                parts.append(" ")
            elif local == "line-break":
                parts.append("\n")
            if element.text:
                parts.append(element.text)
        elif local in {"t", "v"} and element.text:
            parts.append(element.text)
        elif local in {"tab", "br"}:
            parts.append("\t" if local == "tab" else "\n")
        for child in element:
            walk(child, odt_text)
            if odt_text and child.tail:
                parts.append(child.tail)
        if local in {"p", "h", "tr", "table-row"}:
            parts.append("\n")

    walk(root)
    return "".join(parts)


def _xlsx_text(content: bytes, budget: Budget) -> str:
    with _archive(content) as archive:
        names = [
            info
            for info in archive.infolist()
            if info.filename == "xl/sharedStrings.xml" or re.fullmatch(r"xl/worksheets/[^/]+\.xml", info.filename)
        ]
        if sum(info.file_size for info in names) > budget.file_bytes:
            raise ValueError("Die entpackten Tabelleninhalte überschreiten das Lesebudget.")
        shared = []
        if "xl/sharedStrings.xml" in archive.namelist():
            root = safe_xml.fromstring(archive.read("xl/sharedStrings.xml"))
            shared = [
                "".join(node.text or "" for node in item.iter() if node.tag.rsplit("}", 1)[-1] == "t")
                for item in root
                if item.tag.rsplit("}", 1)[-1] == "si"
            ]
        parts, size = [], 0
        for info in sorted(names, key=lambda entry: entry.filename):
            if info.filename == "xl/sharedStrings.xml":
                continue
            root = safe_xml.fromstring(archive.read(info))
            for cell in root.iter():
                if cell.tag.rsplit("}", 1)[-1] != "c":
                    continue
                if cell.get("t") == "inlineStr":
                    value = "".join(node.text or "" for node in cell.iter() if node.tag.rsplit("}", 1)[-1] == "t")
                else:
                    value = next((node.text or "" for node in cell if node.tag.rsplit("}", 1)[-1] == "v"), "")
                    if cell.get("t") == "s":
                        index = int(value)
                        if index < 0 or index >= len(shared):
                            raise ValueError("Ungültiger Tabellen-Textverweis.")
                        value = shared[index]
                size += len(value) + 1
                if size > budget.file_bytes:
                    raise ValueError("Die aufgelösten Tabellenwerte überschreiten das Lesebudget.")
                parts.append(value)
            parts.append("\n")
        return " ".join(parts)


def _ocr_ready(*, pdf=False):
    executable = os.environ.get("IMMO_TEXT_TESSERACT", "")
    return (
        bool(executable and os.path.isfile(executable))
        and importlib.util.find_spec("pytesseract") is not None
        and (not pdf or importlib.util.find_spec("pymupdf") is not None)
    )


def _recognize(image) -> str:
    import pytesseract

    if image.width <= 0 or image.height <= 0 or image.width * image.height > MAX_OCR_PIXELS:
        raise ValueError("Das Seitenbild überschreitet das Pixelbudget der Texterkennung.")
    pytesseract.pytesseract.tesseract_cmd = os.environ["IMMO_TEXT_TESSERACT"]
    return pytesseract.image_to_string(image, lang="deu+eng", timeout=15)


def _pdf_images(page):
    seen = set()

    def images(resources, depth=0):
        if depth > 8:
            return True
        resources = resources.get_object() if hasattr(resources, "get_object") else resources
        if not resources:
            return False
        objects = resources.get("/XObject", {})
        objects = objects.get_object() if hasattr(objects, "get_object") else objects
        for reference in objects.values():
            obj = reference.get_object()
            key = id(obj)
            if key in seen:
                continue
            seen.add(key)
            if obj.get("/Subtype") == "/Image":
                return True
            if obj.get("/Subtype") == "/Form" and images(obj.get("/Resources", {}), depth + 1):
                return True
        return False

    try:
        return images(page.get("/Resources", {}))
    except Exception:
        return True


def _pdf_part(content: bytes, cursor: dict, budget: Budget) -> ExtractionPart:
    from pypdf import PdfReader

    started = time.monotonic()
    reader = PdfReader(BytesIO(content), strict=False)
    if reader.is_encrypted and not reader.decrypt(""):
        return ExtractionPart(warning="Das PDF ist kennwortgeschützt; sein Inhalt ist nicht vollständig durchsuchbar.")
    page, offset = cursor.get("page", 0), cursor.get("offset", 0)
    first, total = page, len(reader.pages)
    stop = min(total, page + budget.pdf_pages)
    parts, length, ocr_count, used_ocr, warning = [], 0, 0, False, None
    ocr_document = None
    try:
        while page < stop and length < budget.characters:
            if page > first and (time.monotonic() - started >= budget.seconds or ocr_count >= budget.ocr_pages):
                break
            raw = ""
            try:
                current = reader.pages[page]
                raw = current.extract_text() or ""
                needs_ocr = _pdf_images(current) or (not raw.strip() and current.get("/Contents") is not None)
                if needs_ocr:
                    if _ocr_ready(pdf=True):
                        import pymupdf
                        from PIL import Image

                        if ocr_document is None:
                            ocr_document = pymupdf.open(stream=content, filetype="pdf")
                        visual = ocr_document[page]
                        pixels = visual.rect.width * visual.rect.height * (200 / 72) ** 2
                        if not math.isfinite(pixels) or pixels <= 0 or pixels > MAX_OCR_PIXELS:
                            raise ValueError("Das Seitenbild überschreitet das Pixelbudget der Texterkennung.")
                        pixmap = visual.get_pixmap(dpi=200, alpha=False)
                        recognized = _recognize(Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples))
                        if recognized.strip():
                            raw += "\n\n" + recognized
                            used_ocr = True
                        ocr_count += 1
                    else:
                        warning = "Bildanteile oder PDF-Seiten ohne Textebene wurden nicht texterkannt. Für die vollständige Inhaltssuche ist die optionale Texterkennung erforderlich."
            except Exception:
                warning = (
                    "Mindestens eine PDF-Seite konnte nicht vollständig gelesen werden; Suchtreffer können fehlen."
                )
            raw = ("\n\n" if page else "") + raw
            page_sha = hashlib.sha256(raw.encode("utf8")).hexdigest()
            if offset and cursor.get("page_sha256") and cursor["page_sha256"] != page_sha:
                return ExtractionPart(
                    warning="Die Lesefassung einer begonnenen PDF-Seite hat sich geändert. Bitte das begrenzte Dokument erneut lesen."
                )
            selected = raw[offset : offset + budget.characters - length]
            parts.append(selected)
            length += len(selected)
            offset += len(selected)
            if offset < len(raw):
                break
            page += 1
            offset = 0
    finally:
        if ocr_document is not None:
            ocr_document.close()
    next_cursor = {"phase": "pdf", "page": page, "offset": offset}
    if offset:
        next_cursor["page_sha256"] = page_sha
    return ExtractionPart(
        "".join(parts), "ocr" if used_ocr else "pdf_text", next_cursor, page, total, page >= total, warning
    )


def _text_part(value: str, kind: str, cursor: dict, budget: Budget):
    offset = cursor.get("offset", 0)
    end = min(len(value), offset + budget.characters)
    return ExtractionPart(value[offset:end], kind, {"offset": end}, end, len(value), end >= len(value))


def read_part(content: bytes, name: str, cursor: dict, budget: Budget) -> ExtractionPart:
    extension = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if not content:
        return ExtractionPart()
    if len(content) > budget.file_bytes:
        return ExtractionPart(warning="Die Datei überschreitet das Lesebudget; der Inhalt ist nicht indiziert.")
    try:
        if extension == "pdf" or content.startswith(b"%PDF-"):
            part = _pdf_part(content, cursor, budget)
        elif extension in IMAGES:
            if not _ocr_ready():
                return ExtractionPart(
                    warning="Das Bild wurde nicht texterkannt. Für die Inhaltssuche ist die optionale Texterkennung erforderlich."
                )
            from PIL import Image

            with Image.open(BytesIO(content)) as image:
                text = _recognize(image)
            part = _text_part(text, "ocr", cursor, budget)
        elif extension in PLAIN:
            if content.startswith((b"\xff\xfe\0\0", b"\0\0\xfe\xff")):
                value = content.decode("utf-32")
            elif content.startswith((b"\xff\xfe", b"\xfe\xff")):
                value = content.decode("utf-16")
            else:
                try:
                    value = content.decode("utf-8-sig")
                except UnicodeDecodeError:
                    value = content.decode("cp1252")
            part = _text_part(value, "plain", cursor, budget)
        elif extension in OFFICE:
            value = (
                _xlsx_text(content, budget) if extension == "xlsx" else _office_text(content, OFFICE[extension], budget)
            )
            part = _text_part(value, "office", cursor, budget)
        else:
            return ExtractionPart()
    except Exception:
        part = ExtractionPart(warning="Die Datei konnte nicht vollständig gelesen werden; Suchtreffer können fehlen.")
    part.text, continuation = normalize_part(part.text, cursor, part.complete)
    part.cursor.update(continuation)
    return part
