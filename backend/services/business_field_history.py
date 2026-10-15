"""Transaction-bound, source-scoped field history for office entity timelines."""

import json
from datetime import date, datetime, timezone
from uuid import uuid4

from sqlalchemy import event, inspect, select
from sqlalchemy.orm import Session

from ..db.orm_models import ChangeHistoryORM
from ..models import ChangeHistoryEntry
from .portfolio_scope import current_scope
from .workspace_contexts import SENSITIVE

KINDS = {"properties": "property", "units": "unit", "tenants": "tenant", "contracts": "contract",
         "tasks": "task", "maintenance_cases": "maintenance", "documents": "document", "bookings": "booking",
         "invoices": "invoice", "receivables": "receivable", "contacts": "contact",
         "handover_protocols": "handover_protocol", "handover_defects": "handover_protocol"}
IGNORED = {"id", "created_at", "updated_at"}


def _value(value):
    if value is None:
        return None
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return json.dumps(value, ensure_ascii=False, default=str) if isinstance(value, (dict, list)) else str(value)


def entries(collection, before: dict, after: dict):
    scope = current_scope()
    if collection not in KINDS or not scope:
        return []
    kind = KINDS[collection]
    identifier = after.get("protocol_id") if collection == "handover_defects" else after.get("id")
    if not isinstance(identifier, str):
        return []
    result = []
    for field in sorted(set(before) & set(after) - IGNORED):
        if SENSITIVE.search(field) or before[field] == after[field]:
            continue
        name = f"defect:{after['id']}:{field}" if collection == "handover_defects" else field
        result.append(ChangeHistoryEntry(id=str(uuid4()), entity_type=kind, entity_id=identifier,
                                         field_name=name, old_value=_value(before[field]), new_value=_value(after[field]),
                                         changed_by=scope.user_id, reason="Feld geändert"))
    return result


def record_memory_changes(store, collection, before, after):
    """Called under atomic_memory_update's existing memory archive writer lock."""
    if before is None or after is None or not hasattr(before, "model_dump") or not hasattr(after, "model_dump"):
        return
    staged = entries(collection, before.model_dump(), after.model_dump())
    history, journal = store.change_history, []
    try:
        for entry in staged:
            journal.append((entry.id, entry.id in history, history.get(entry.id)))
            history[entry.id] = entry
    except BaseException:
        for identifier, existed, previous in reversed(journal):
            if existed:
                history[identifier] = previous
            else:
                history.pop(identifier, None)
        raise


def record_unit_changes(unit, collection, before, after):
    if unit.db is not None:
        return  # SQL's observer adds the history in the same transaction.
    for entry in entries(collection, before.model_dump(), after.model_dump()):
        unit.insert(unit.store.change_history, entry.id, entry)


@event.listens_for(Session, "before_flush")
def _capture_fields(db, _context, _instances):
    if not current_scope():
        return
    for record in list(db.dirty):
        table = record.__table__
        if table.name not in KINDS or record in db.new or record in db.deleted:
            continue
        state = inspect(record)
        changed = [col.key for col in table.c if col.key not in IGNORED and state.attrs[col.key].history.has_changes()]
        if not changed:
            continue
        # One bounded source-row read supplies unloaded prior values; never a
        # full audit or entity collection. The write guard checks this row too.
        stored = db.connection().execute(select(table).where(table.c.id == record.id)).mappings().first()
        if stored is None:
            continue
        before = dict(stored)
        after = {col.key: getattr(record, col.key) for col in table.c}
        for field in changed:
            history = state.attrs[field].history
            if history.deleted:
                before[field] = history.deleted[0]
        for entry in entries(table.name, before, after):
            values = entry.model_dump()
            values["changed_at"] = entry.changed_at.astimezone(timezone.utc).replace(tzinfo=None)
            db.add(ChangeHistoryORM(**values))
