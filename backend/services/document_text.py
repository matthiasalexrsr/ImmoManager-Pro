"""Full-text search in documents: read the text of each document's file, keep it, search it.

The indexing job reads a document's archived original (the head version) or its
uploaded file, extracts the text locally and stores it in ``document_texts``:

* PDF: the text layer (pypdf, shipped with the application); a scanned PDF without
  one is recognized page by page when PyMuPDF and Tesseract are installed;
* images: Tesseract, when installed;
* plain text (txt, csv, md) and office files (docx, odt, xlsx, ods): their text.

Nothing leaves the computer. A document is indexed when it has no text yet or was
changed after it was indexed; a file without readable text gets an empty row
(source "none") so it is not read again until it changes. The search compares the
lower-cased text as a literal substring, like the global search, and only ever
returns documents the account may see (SQL: the portfolio boundary of every SELECT;
memory: the already scoped document collection).
"""
from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from io import BytesIO
from typing import Any
from xml.etree import ElementTree

from sqlalchemy import func, or_, select

from ..db.orm_models import DocumentORM, DocumentTextORM
from ..store_errors import NotFoundError

KIND = "documents.text_index"
CHUNK = 50
MAX_CHARACTERS = 500_000
MAX_PDF_PAGES = 500
MAX_OCR_PAGES = 20
MAX_BYTES = 50 * 1024 * 1024
SNIPPET = 90
SYSTEM_USER = {"id": "system:document-text", "role": "eigentuemer", "is_active": True, "portfolio_access": "all"}
PLAIN = {"txt", "csv", "md", "text"}
OFFICE = {"docx": "word/document.xml", "odt": "content.xml", "ods": "content.xml", "xlsx": "xl/sharedStrings.xml"}
IMAGES = {"png", "jpg", "jpeg", "tif", "tiff", "bmp", "webp"}


def now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _naive(value: datetime | None) -> datetime | None:
    if value is None or value.tzinfo is None:
        return value
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def normalize(text: str) -> str:
    """Readable stored text: no control characters, single spaces, at most two line breaks."""
    text = text.replace("\x00", " ").replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[^\S\n]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()[:MAX_CHARACTERS]


# ─── Extraction ──────────────────────────────────────────────────────────────

def _pdf_text(content: bytes) -> str:
    from pypdf import PdfReader

    reader = PdfReader(BytesIO(content), strict=False)
    if reader.is_encrypted and not reader.decrypt(""):
        return ""
    parts = []
    for page in reader.pages[:MAX_PDF_PAGES]:
        try:
            parts.append(page.extract_text() or "")
        except Exception:          # one damaged page must not lose the others
            continue
        if sum(len(part) for part in parts) > MAX_CHARACTERS:
            break
    return "\n\n".join(parts)


def _pdf_ocr(content: bytes) -> str:
    """A scanned PDF: render the first pages and recognize them (only with PyMuPDF and Tesseract)."""
    import importlib.util

    if importlib.util.find_spec("pymupdf") is None or importlib.util.find_spec("pytesseract") is None:
        return ""
    import pymupdf
    import pytesseract
    from PIL import Image

    parts = []
    with pymupdf.open(stream=content, filetype="pdf") as document:
        for page in list(document)[:MAX_OCR_PAGES]:
            pixmap = page.get_pixmap(dpi=200)
            image = Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)
            parts.append(pytesseract.image_to_string(image, lang="deu+eng"))
    return "\n\n".join(parts)


def _office_text(content: bytes, member: str) -> str:
    with zipfile.ZipFile(BytesIO(content)) as archive:
        info = archive.getinfo(member)
        if info.file_size > MAX_BYTES:
            return ""
        root = ElementTree.fromstring(archive.read(member))
    parts: list[str] = []
    for element in root.iter():
        tag = element.tag.rsplit("}", 1)[-1]
        if element.text and tag in ("t", "p", "span", "h", "s", "v"):
            parts.append(element.text)
        if tag in ("p", "h", "si", "tr", "table-row"):
            parts.append("\n")
    return " ".join(parts)


def extract(content: bytes, name: str) -> tuple[str, str]:
    """(text, source) of a file; ("", "none") if nothing readable came out."""
    extension = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if not content or len(content) > MAX_BYTES:
        return "", "none"
    try:
        if extension == "pdf" or content.startswith(b"%PDF-"):
            text = normalize(_pdf_text(content))
            if len(re.sub(r"\s", "", text)) >= 20:
                return text, "pdf_text"
            recognized = normalize(_pdf_ocr(content))
            return (recognized, "ocr") if recognized else (text, "pdf_text" if text else "none")
        if extension in IMAGES:
            from .ocr_service import _image_ocr_bytes
            recognized = normalize(_image_ocr_bytes(content) or "")
            return (recognized, "ocr") if recognized else ("", "none")
        if extension in PLAIN:
            for encoding in ("utf-8-sig", "cp1252"):
                try:
                    return normalize(content.decode(encoding)), "plain"
                except UnicodeDecodeError:
                    continue
        if extension in OFFICE:
            text = normalize(_office_text(content, OFFICE[extension]))
            return (text, "office") if text else ("", "none")
    except Exception:                 # an unreadable file is "no text", never a failed run
        return "", "none"
    return "", "none"


# ─── Reading a document's bytes ──────────────────────────────────────────────

def _archive_unit(store):
    from . import document_versions as archive
    if hasattr(store, "db"):
        return archive.Unit(store, store.db, SYSTEM_USER, None)
    return archive.Unit(store, None, SYSTEM_USER, archive.memory_archive(store))


def source(store, document) -> tuple[str, bytes, str] | None:
    """(reference, bytes, file name) of what the index reads, or None (no local file)."""
    from . import document_versions as archive
    unit = _archive_unit(store)
    row = archive.head(unit, document.id)
    if row is not None:
        return f"version:{row.id}", archive.original_bytes(unit, row), row.filename or document.file_url
    url = document.file_url or ""
    if not url.startswith("/uploads/"):
        return None
    key = url[len("/uploads/"):]
    from .upload_policy import ARCHIVED_PREFIXES
    if key.startswith(ARCHIVED_PREFIXES) or ".." in key.split("/"):
        return None
    from .file_storage import get_file_storage
    content = get_file_storage().get(key)
    if content is None:
        return None
    return f"file:{url}", content, key


# ─── Storage ─────────────────────────────────────────────────────────────────

@dataclass
class TextRow:
    document_id: str
    source_ref: str
    source: str
    text: str
    search_text: str
    characters: int
    indexed_at: datetime


def memory_rows(store) -> dict[str, TextRow]:
    return store.__dict__.setdefault("_document_texts", {})


def save(store, row: TextRow) -> None:
    if hasattr(store, "db"):
        store.db.merge(DocumentTextORM(**row.__dict__))
        store.db.flush()
    else:
        memory_rows(store)[row.document_id] = row


def get(store, document_id: str) -> TextRow | None:
    if hasattr(store, "db"):
        found = store.db.get(DocumentTextORM, document_id)
        return None if found is None else TextRow(**{key: getattr(found, key) for key in TextRow.__dataclass_fields__})
    return memory_rows(store).get(document_id)


def forget(store, document_id: str) -> None:
    """Memory: drop a deleted document's text (SQL deletes it with the document)."""
    if not hasattr(store, "db"):
        memory_rows(store).pop(document_id, None)


def index_document(store, document) -> TextRow:
    found = source(store, document)
    if found is None:
        reference, text, kind = f"file:{document.file_url or ''}", "", "none"
    else:
        reference, content, name = found
        text, kind = extract(content, name)
    row = TextRow(document.id, reference, kind, text, text.lower(), len(text), now())
    save(store, row)
    return row


def pending(store, after: str, limit: int) -> list[Any]:
    """Documents after `after` (by id) without text or changed since they were indexed."""
    if hasattr(store, "db"):
        ids = store.db.scalars(
            select(DocumentORM.id).outerjoin(DocumentTextORM, DocumentTextORM.document_id == DocumentORM.id)
            .where(DocumentORM.id > after, or_(DocumentTextORM.document_id.is_(None),
                                               DocumentORM.updated_at > DocumentTextORM.indexed_at))
            .order_by(DocumentORM.id).limit(limit)).all()
        result = []
        for identifier in ids:
            try:
                result.append(store.get_document(identifier))
            except NotFoundError:
                continue
        return result
    rows = memory_rows(store)
    documents = sorted((document for document in store.list_documents() if document.id > after
                        and (document.id not in rows
                             or (_naive(document.updated_at) or now()) > rows[document.id].indexed_at)),
                       key=lambda document: document.id)
    return documents[:limit]


def index_pending(store, after: str = "", limit: int = CHUNK) -> tuple[int, str | None]:
    """Index one chunk; (indexed, the last id or None when nothing was pending)."""
    documents = pending(store, after, limit)
    for document in documents:
        index_document(store, document)
    return len(documents), documents[-1].id if documents else None


# ─── Search ──────────────────────────────────────────────────────────────────

def snippet(text: str, needle: str) -> str:
    position = text.lower().find(needle)
    if position < 0:
        return text[:2 * SNIPPET].strip()
    start, end = max(0, position - SNIPPET), min(len(text), position + len(needle) + SNIPPET)
    return ("…" if start else "") + text[start:end].replace("\n", " ").strip() + ("…" if end < len(text) else "")


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def search(store, q: str, *, limit: int = 25) -> dict:
    """Documents whose text contains `q`, newest first, each with a snippet around the first hit."""
    needle = q.strip().lower()
    if len(needle) < 2:
        return {"items": [], "total": 0, "index": status(store)}
    if hasattr(store, "db"):
        match = DocumentTextORM.search_text.like(f"%{_escape(needle)}%", escape="\\")
        query = (select(DocumentORM, DocumentTextORM.text, DocumentTextORM.source)
                 .join(DocumentTextORM, DocumentTextORM.document_id == DocumentORM.id).where(match))
        total = store.db.scalar(select(func.count()).select_from(DocumentORM)
                                .join(DocumentTextORM, DocumentTextORM.document_id == DocumentORM.id).where(match))
        rows = store.db.execute(query.order_by(DocumentORM.created_at.desc(), DocumentORM.id).limit(limit)).all()
        found = [(store.get_document(row[0].id), row[1], row[2]) for row in rows]
    else:
        texts = memory_rows(store)
        matches = [(document, texts[document.id].text, texts[document.id].source) for document in store.list_documents()
                   if document.id in texts and needle in texts[document.id].search_text]
        matches.sort(key=lambda item: (_naive(item[0].created_at) or now(), item[0].id), reverse=True)
        total, found = len(matches), matches[:limit]
    items = [{**document.model_dump(mode="json", include={"id", "title", "document_type", "document_date",
                                                          "property_id", "unit_id", "contract_id", "tenant_id",
                                                          "file_url", "valid_until"}),
              "snippet": snippet(text, needle), "text_source": kind} for document, text, kind in found]
    return {"items": items, "total": total, "index": status(store)}


def status(store) -> dict:
    """How many visible documents are indexed, and how many have no readable text."""
    if hasattr(store, "db"):
        documents = store.db.scalar(select(func.count()).select_from(DocumentORM)) or 0
        joined = select(func.count()).select_from(DocumentORM).join(DocumentTextORM,
                                                                    DocumentTextORM.document_id == DocumentORM.id)
        indexed = store.db.scalar(joined) or 0
        unreadable = store.db.scalar(joined.where(DocumentTextORM.source == "none")) or 0
    else:
        rows = memory_rows(store)
        visible = [document.id for document in store.list_documents()]
        documents = len(visible)
        indexed = sum(1 for identifier in visible if identifier in rows)
        unreadable = sum(1 for identifier in visible if identifier in rows and rows[identifier].source == "none")
    return {"documents": documents, "indexed": indexed, "unreadable": unreadable}


def memory_match_ids(store, needle: str) -> set[str]:
    """Ids of documents whose text contains the lower-cased needle (memory store)."""
    return {identifier for identifier, row in memory_rows(store).items() if needle in row.search_text}


# ─── Scheduling ──────────────────────────────────────────────────────────────

def schedule(reason: str) -> None:
    """Index soon (a durable run, plus a wake-up of the local scheduler); never blocks a request."""
    from ..config import settings
    if not settings.job_scheduler_enabled:
        return
    try:
        from .jobs.scheduler import get_job_store, request_wakeup
        get_job_store().enqueue(KIND, f"{KIND}@{reason}", {"as_of": now().date().isoformat()}, max_attempts=3)
        request_wakeup()
    except Exception:                 # the daily run catches up
        pass
