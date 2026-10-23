"""Daily reminders of expiring documents as a durable installation job.

A document with `valid_until` (energy certificate, insurance policy, smoke detector
inspection, guarantee …) is reminded once its reminder window has begun: `reminder_days`
before the date, 30 days if none is set. Each expiry becomes one task (due on the day the
document expires, at its property and unit) and one notification, exactly once: the
occurrence ledger keys it by document and expiry date (rule version v1). A new date
(the renewed document, or a corrected one) gives a new reminder; the same date is never
reminded twice, by any worker. Chunks of CHUNK documents commit with their ledger rows
and checkpoint.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from sqlalchemy import select

from ...db.orm_models import DocumentORM
from ...models import NotificationCreate, TaskCreate
from .core import JobContext
from .service_contract_deadlines import _stage

KIND = "documents.expiry"
CHUNK = 200
RULE_VERSION = "v1"
DEFAULT_REMINDER_DAYS = 30


def rule_key(document_id: str) -> str:
    return f"document:{document_id}:expiry"


def _de(value: date) -> str:
    return value.strftime("%d.%m.%Y")


def reminder_start(document: Any) -> date | None:
    """The first day the document is reminded, or None without an expiry date."""
    if document.valid_until is None:
        return None
    lead = document.reminder_days if document.reminder_days is not None else DEFAULT_REMINDER_DAYS
    return document.valid_until - timedelta(days=lead)


def texts(document: Any, as_of: date) -> tuple[str, str, str, str]:
    """(task title, notification content, severity, priority) in German, like the other reminders."""
    kind = f" ({document.document_type})" if document.document_type else ""
    day = document.valid_until
    if day < as_of:
        return (f"Abgelaufen: {document.title}",
                f"Das Dokument „{document.title}“{kind} gilt seit {_de(day)} nicht mehr. Bitte erneuern lassen "
                "(z. B. neue Prüfung, neue Police) und das neue Dokument mit seinem Ablaufdatum ablegen.",
                "warning", "high")
    soon = (day - as_of).days <= 7
    return (f"Läuft ab: {document.title}",
            f"Das Dokument „{document.title}“{kind} gilt bis {_de(day)}. Bitte rechtzeitig erneuern lassen und "
            "das neue Dokument mit seinem Ablaufdatum ablegen.",
            "warning" if soon else "info", "high" if soon else "medium")


def documents_after(store: Any, after: str, limit: int) -> list[Any]:
    """Documents with an expiry date, by id after `after`."""
    if hasattr(store, "db"):
        ids = store.db.scalars(select(DocumentORM.id).where(DocumentORM.valid_until.is_not(None), DocumentORM.id > after)
                               .order_by(DocumentORM.id).limit(limit)).all()
        return [store.get_document(identifier) for identifier in ids]
    rows = sorted((row for row in store.list_documents() if row.valid_until is not None and row.id > after),
                  key=lambda row: row.id)
    return rows[:limit]


def remind(unit: Any, documents: list[Any], as_of: date, progress: dict) -> None:
    for document in documents:
        start = reminder_start(document)
        if start is None or as_of < start:
            continue
        if not unit.ledger.record(rule_key(document.id), RULE_VERSION, document.valid_until.isoformat(),
                                  "created", unit.run.id):
            continue          # reminded already (this or an earlier run, any worker)
        title, content, severity, priority = texts(document, as_of)
        _stage(unit.store, TaskCreate(title=title, description=content, due_date=document.valid_until,
                                      priority=priority, property_id=document.property_id,
                                      unit_id=document.unit_id if document.property_id else None),
               NotificationCreate(notification_type="document_expiry", title=title, content=content,
                                  severity=severity, entity_type="document", entity_id=document.id))
        key = "expired" if document.valid_until < as_of else "expiring"
        progress[key] = progress.get(key, 0) + 1


def make_handler(chunk: int = CHUNK):
    def handle(ctx: JobContext) -> bool:
        as_of = date.fromisoformat(ctx.run.payload["as_of"])
        after = ctx.checkpoint.get("after", "")
        progress = ctx.progress
        with ctx.unit() as unit:
            documents = documents_after(unit.store, after, chunk)
            if not documents:
                unit.save({"after": after, "done": True}, progress)
                return True
            remind(unit, documents, as_of, progress)
            progress["documents"] = progress.get("documents", 0) + len(documents)
            unit.save({"after": documents[-1].id}, progress)
        return False

    return handle
