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

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import String, and_, case, cast, func, literal, or_, select

from ..db.document_version_models import DocumentVersionORM
from ..db.orm_models import DocumentORM, DocumentTextORM
from ..domain.clock import local_today
from ..store_errors import NotFoundError
from . import document_context
from .document_text_reader import Budget, ExtractionPart, normalize

KIND = "documents.text_index"
CHUNK = 1
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


def extract_part(content: bytes, name: str, cursor: dict | None = None) -> ExtractionPart:
    """A bounded reader process returns one restartable file-text step."""
    from .document_text_process import read_isolated

    extension = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if extension not in PLAIN | IMAGES | set(OFFICE) | {"pdf"} and not content.startswith(b"%PDF-"):
        return ExtractionPart()
    budget = Budget(characters=MAX_CHARACTERS, pdf_pages=MAX_PDF_PAGES, ocr_pages=MAX_OCR_PAGES, file_bytes=MAX_BYTES)
    return read_isolated(content, name, cursor or {}, budget)


def extract(content: bytes, name: str) -> tuple[str, str]:
    """One bounded direct extraction; resumable or partial results fail explicitly.

    The persisted production index uses extract_part and stores its warning and
    continuation. A successfully empty file still returns ("", "none"); a
    failed worker is never mistaken for a successfully empty scan.
    """
    part = extract_part(content, name)
    if part.failed or not part.complete or (part.warning and part.text):
        raise ValueError("Die Dokumentauswertung ist unvollständig; bitte den fortsetzbaren Suchindex verwenden.")
    text = normalize(part.text)
    return text, part.source if text else "none"


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
        _, binding = archive.bind_document(unit, document.id)
        row = archive.authorized_version(unit, document.id, row.id, binding)
        return f"version:{row.id}", archive.original_bytes(unit, row), row.filename or document.file_url
    url = document.file_url or ""
    if not url.startswith("/uploads/"):
        return None
    key = url[len("/uploads/") :]
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
    complete: bool = False
    cursor: dict = field(default_factory=dict)
    source_sha256: str | None = None
    indexed_units: int = 0
    total_units: int = 0
    warning: str | None = None
    source_updated_at: datetime | None = None


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


def index_document(store, document, *, retry_limited: bool = False) -> TextRow:
    # An edit made while the bounded reader runs must remain pending afterwards.
    sampled_at = now()
    source_updated_at = _naive(document.updated_at)
    found = source(store, document)
    if found is None:
        reference, text, kind = f"file:{document.file_url or ''}", "", "none"
        row = TextRow(document.id, reference, kind, text, text, 0, sampled_at, complete=True,
                      source_updated_at=source_updated_at)
    else:
        reference, content, name = found
        fingerprint = hashlib.sha256(content).hexdigest()
        previous = get(store, document.id)
        if previous is not None and (
            previous.source_ref != reference
            or previous.source_sha256 != fingerprint
            or previous.source_updated_at is None
            or _naive(previous.source_updated_at) != source_updated_at
        ):
            previous = None
        if retry_limited and previous is not None and previous.complete and previous.warning:
            previous = None
        part = extract_part(content, name, previous.cursor if previous is not None else {})
        text = (previous.text if previous is not None else "") + part.text
        warning = (previous.warning if previous is not None else None) or part.warning
        if len(text) >= MAX_BYTES and not part.complete:
            part.complete = True
            warning = "Das Dokument überschreitet das Indexbudget von 50 Millionen Zeichen. Die Suche ist ausdrücklich unvollständig."
        if part.complete:
            # Checkpoints retain whitespace at file edges; only the completed
            # text can use the same canonical form as whole-file extraction.
            text = text.strip()
        row = TextRow(
            document.id,
            reference,
            ("ocr" if previous is not None and previous.source == "ocr" else part.source) if text else "none",
            text,
            text.lower(),
            len(text),
            sampled_at,
            part.complete,
            part.cursor,
            fingerprint,
            part.indexed_units,
            part.total_units,
            warning,
            source_updated_at,
        )
    save(store, row)
    return row


def _revision_sql(column):
    # SQLite CURRENT_TIMESTAMP omits fractional seconds; DateTime bindings
    # include six digits. Right-padding their stored representation preserves
    # every microsecond, unlike SQLite's millisecond date/time functions.
    stamp = cast(column, String)
    return case(
        (func.length(stamp) == 19, stamp + literal(".000000")),
        *((func.length(stamp) == size, stamp + literal("0" * (26 - size))) for size in range(21, 26)),
        else_=stamp,
    )


def _stale_sql():
    head = (
        select(DocumentVersionORM.id)
        .where(DocumentVersionORM.document_id == DocumentORM.id)
        .order_by(DocumentVersionORM.number.desc())
        .limit(1)
        .correlate(DocumentORM)
        .scalar_subquery()
    )
    return or_(
        DocumentTextORM.document_id.is_(None),
        DocumentTextORM.complete.is_(False),
        DocumentTextORM.source_updated_at.is_(None),
        _revision_sql(DocumentORM.updated_at) != _revision_sql(DocumentTextORM.source_updated_at),
        and_(head.is_not(None), DocumentTextORM.source_ref != literal("version:").concat(head)),
        and_(
            head.is_(None),
            DocumentTextORM.source_ref != literal("file:").concat(func.coalesce(DocumentORM.file_url, "")),
        ),
    )


def _memory_heads(store) -> dict[str, Any]:
    from . import document_versions as archive

    heads: dict[str, Any] = {}
    for version in archive.memory_archive(store).versions.values():
        if version.document_id not in heads or version.number > heads[version.document_id].number:
            heads[version.document_id] = version
    return heads


def _stale(document, row: TextRow | None, head) -> bool:
    reference = f"version:{head.id}" if head is not None else f"file:{document.file_url or ''}"
    return (
        row is None
        or not row.complete
        or row.source_updated_at is None
        or _naive(document.updated_at) != _naive(row.source_updated_at)
        or row.source_ref != reference
    )


def pending(store, after: str, limit: int, *, retry_limited: bool = False) -> list[Any]:
    """Documents after `after` (by id) without text, changed since they were indexed, or with an archived
    version newer than the one read (an edit in the document workbench, a new version uploaded)."""
    if hasattr(store, "db"):
        ids = store.db.scalars(
            select(DocumentORM.id)
            .outerjoin(DocumentTextORM, DocumentTextORM.document_id == DocumentORM.id)
            .where(
                DocumentORM.id > after,
                or_(
                    _stale_sql(),
                    DocumentTextORM.warning.is_not(None) if retry_limited else literal(False),
                ),
            )
            .order_by(DocumentORM.id)
            .limit(limit)
        ).all()
        result = []
        for identifier in ids:
            try:
                result.append(store.get_document(identifier))
            except NotFoundError:
                continue
        return result
    rows = memory_rows(store)
    heads = _memory_heads(store)

    def stale(document) -> bool:
        row = rows.get(document.id)
        return _stale(document, row, heads.get(document.id)) or bool(retry_limited and row and row.warning)

    documents = sorted(
        (document for document in store.list_documents() if document.id > after and stale(document)),
        key=lambda document: document.id,
    )
    return documents[:limit]


def index_pending(store, after: str = "", limit: int = CHUNK, *, retry_limited: bool = False) -> tuple[int, str | None]:
    """Index one chunk; (indexed, the last id or None when nothing was pending)."""
    documents = pending(store, after, limit, retry_limited=retry_limited)
    completed, cursor = 0, after
    for document in documents:
        row = index_document(store, document, retry_limited=retry_limited)
        if not row.complete:
            return completed, cursor
        completed += 1
        cursor = document.id
    return completed, cursor if documents else None


# ─── Search ──────────────────────────────────────────────────────────────────


def snippet(text: str, needle: str) -> str:
    position = text.lower().find(needle)
    if position < 0:
        return text[: 2 * SNIPPET].strip()
    start, end = max(0, position - SNIPPET), min(len(text), position + len(needle) + SNIPPET)
    return ("…" if start else "") + text[start:end].replace("\n", " ").strip() + ("…" if end < len(text) else "")


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def search(store, q: str, *, limit: int = 25, skip: int = 0, property_id=None, unit_id=None, contract_id=None) -> dict:
    """Documents whose text contains `q`, newest first, each with a snippet around the first hit."""
    needle = q.strip().lower()
    scope = {"property_id": property_id, "unit_id": unit_id, "contract_id": contract_id}
    if len(needle) < 2:
        return {"items": [], "total": 0, "has_more": False, "next_skip": None, "index": status(store, **scope)}
    if hasattr(store, "db"):
        conditions = document_context.sql_filters(**scope)
        match = DocumentTextORM.search_text.like(f"%{_escape(needle)}%", escape="\\")
        query = (
            select(DocumentORM, DocumentTextORM.text, DocumentTextORM.source)
            .join(DocumentTextORM, DocumentTextORM.document_id == DocumentORM.id)
            .where(match, *conditions)
        )
        total = store.db.scalar(
            select(func.count())
            .select_from(DocumentORM)
            .join(DocumentTextORM, DocumentTextORM.document_id == DocumentORM.id)
            .where(match, *conditions)
        )
        rows = store.db.execute(
            query.order_by(DocumentORM.created_at.desc(), DocumentORM.id.desc()).offset(skip).limit(limit)
        ).all()
        found = [(store.get_document(row[0].id), row[1], row[2]) for row in rows]
    else:
        texts = memory_rows(store)
        documents = document_context.filter_records(store, store.list_documents(), **scope)
        matches = [
            (document, texts[document.id].text, texts[document.id].source)
            for document in documents
            if document.id in texts and needle in texts[document.id].search_text
        ]
        matches.sort(key=lambda item: (_naive(item[0].created_at) or now(), item[0].id), reverse=True)
        total, found = len(matches), matches[skip : skip + limit]
    items = [
        {
            **document.model_dump(
                mode="json",
                include={
                    "id",
                    "title",
                    "document_type",
                    "document_date",
                    "property_id",
                    "unit_id",
                    "contract_id",
                    "tenant_id",
                    "file_url",
                    "valid_until",
                },
            ),
            "snippet": snippet(text, needle),
            "text_source": kind,
        }
        for document, text, kind in found
    ]
    has_more = skip + len(items) < (total or 0)
    return {
        "items": items,
        "total": total or 0,
        "has_more": has_more,
        "next_skip": skip + len(items) if has_more else None,
        "index": status(store, **scope),
    }


def status(store, *, property_id=None, unit_id=None, contract_id=None) -> dict:
    """How many visible documents are indexed, and how many have no readable text."""
    if hasattr(store, "db"):
        conditions = document_context.sql_filters(property_id=property_id, unit_id=unit_id, contract_id=contract_id)
        documents = store.db.scalar(select(func.count()).select_from(DocumentORM).where(*conditions)) or 0
        joined = (
            select(func.count())
            .select_from(DocumentORM)
            .join(DocumentTextORM, DocumentTextORM.document_id == DocumentORM.id)
            .where(*conditions)
        )
        indexed = store.db.scalar(joined) or 0
        unreadable = store.db.scalar(joined.where(DocumentTextORM.source == "none")) or 0
        stale = _stale_sql()
        incomplete = or_(stale, DocumentTextORM.warning.is_not(None))
        partial = store.db.scalar(joined.where(incomplete)) or 0
        in_progress = store.db.scalar(joined.where(stale)) or 0
        limited = store.db.scalar(joined.where(DocumentTextORM.warning.is_not(None))) or 0
        details = store.db.execute(
            select(
                DocumentTextORM.document_id,
                DocumentTextORM.indexed_units,
                DocumentTextORM.total_units,
                DocumentTextORM.source,
                DocumentTextORM.warning,
                DocumentORM.title,
            )
            .join(DocumentORM, DocumentORM.id == DocumentTextORM.document_id)
            .where(incomplete, *conditions)
            .order_by(case((DocumentTextORM.warning.is_not(None), 0), else_=1), DocumentTextORM.document_id)
            .limit(25)
        ).all()
        details = [
            dict(zip(["document_id", "indexed_units", "total_units", "source", "warning", "title"], row)) for row in details
        ]
    else:
        rows = memory_rows(store)
        visible = {
            document.id: document
            for document in document_context.filter_records(
                store, store.list_documents(), property_id=property_id, unit_id=unit_id, contract_id=contract_id
            )
        }
        heads = _memory_heads(store)
        documents = len(visible)
        indexed = sum(1 for identifier in visible if identifier in rows)
        unreadable = sum(1 for identifier in visible if identifier in rows and rows[identifier].source == "none")
        partial_rows = [
            rows[identifier]
            for identifier in visible
            if identifier in rows and (_stale(visible[identifier], rows[identifier], heads.get(identifier)) or rows[identifier].warning)
        ]
        partial_rows.sort(key=lambda row: (not bool(row.warning), row.document_id))
        partial = len(partial_rows)
        in_progress = sum(_stale(visible[row.document_id], row, heads.get(row.document_id)) for row in partial_rows)
        limited = sum(bool(row.warning) for row in partial_rows)
        details = [
            {
                **{key: getattr(row, key) for key in ["document_id", "indexed_units", "total_units", "source", "warning"]},
                "title": visible[row.document_id].title,
            }
            for row in partial_rows[:25]
        ]
    return {
        "documents": documents,
        "indexed": indexed,
        "unreadable": unreadable,
        "partial": partial,
        "in_progress": in_progress,
        "limited": limited,
        "details": details,
    }


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

        get_job_store().enqueue(
            KIND,
            f"{KIND}@{reason}",
            {"as_of": local_today().isoformat(), "retry_limited": reason.startswith("manual:")},
            max_attempts=3,
        )
        request_wakeup()
    except Exception:  # the daily run catches up
        pass
