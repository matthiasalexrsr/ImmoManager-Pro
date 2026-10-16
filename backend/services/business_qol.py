"""Shared office workflows with current permissions, atomic receipts and optimistic edits."""

from __future__ import annotations

import base64
import hashlib
import json
from datetime import date, datetime, timezone
from typing import Any
from urllib.parse import urlencode
from uuid import NAMESPACE_URL, uuid4, uuid5

from fastapi import HTTPException
from pydantic import BaseModel
from sqlalchemy import and_, or_, select
from sqlalchemy.exc import IntegrityError

from ..business_qol_models import BusinessCommand, ConversationNote, NoteCreate, QuickEdit, Undo
from ..db.business_qol_models import BusinessCommandORM, ConversationNoteORM
from ..db.dunning_models import DunningEventORM
from ..db.invoice_review_models import InvoiceReviewEventORM
from ..db.orm_models import ChangeHistoryORM, TaskORM
from ..domain.revision_time import next_updated_at
from ..models import Task, TaskCreate
from ..permissions import may_write
from . import document_versions as archive
from . import workspace_work_items as work_items
from .business_field_history import record_unit_changes
from .jobs.schedule import local_today
from .portfolio_scope import scope_context, scope_from_user
from .workspace_contexts import actor, resolve_context, same_revision

RECORDS: dict[str, tuple[Any, Any]] = {"business_qol_commands": (BusinessCommandORM, BusinessCommand),
           "business_conversation_notes": (ConversationNoteORM, ConversationNote)}


def utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def timestamp() -> datetime:
    return datetime.now(timezone.utc)


def dump(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    return json.loads(json.dumps(value, default=lambda item: item.isoformat() if isinstance(item, (date, datetime)) else str(item)))


def conflict(message: str = "Der Datensatz wurde inzwischen geändert. Bitte neu laden.") -> HTTPException:
    return HTTPException(409, message)


def check_revision(expected: str, actual: str) -> None:
    if not same_revision(expected, actual):
        raise conflict()


def cursor_encode(namespace: Any, key: Any) -> str:
    return base64.urlsafe_b64encode(json.dumps({"query": dump(namespace), "key": dump(key)},
                                              separators=(",", ":")).encode()).decode().rstrip("=")


def cursor_decode(value: str | None, namespace: Any):
    if not value:
        return None
    try:
        if len(value) > 4096:
            raise ValueError
        data = json.loads(base64.urlsafe_b64decode(value + "=" * (-len(value) % 4)))
        if data["query"] != dump(namespace) or not isinstance(data["key"], list):
            raise ValueError
        return data["key"]
    except (ValueError, KeyError, TypeError, UnicodeError):
        raise HTTPException(422, "Ungültige Fortsetzung. Bitte die Liste neu laden.") from None


def page(values: list[dict], limit: int, namespace: Any, key) -> dict:
    more = len(values) > limit
    selected = values[:limit]
    return {"items": selected, "has_more": more,
            "next_cursor": cursor_encode(namespace, key(selected[-1])) if more and selected else None}


def get_record(unit, table: str, identifier: str):
    orm, model = RECORDS[table]
    if unit.db is not None:
        row = unit.db.scalar(select(orm).where(orm.id == identifier))
        return None if row is None else model.model_validate({col.key: getattr(row, col.key) for col in orm.__table__.c})
    return getattr(unit.store, table).get(identifier)


def put_record(unit, table: str, record: Any) -> None:
    orm, _model = RECORDS[table]
    if unit.db is None:
        unit.insert(getattr(unit.store, table), record.id, record)
        return
    values = record.model_dump()
    for column in orm.__table__.c:
        if isinstance(values.get(column.key), datetime):
            values[column.key] = utc(values[column.key]).replace(tzinfo=None)
    existing = unit.db.scalar(select(orm).where(orm.id == record.id))
    if existing is None:
        unit.db.add(orm(**values))
    else:
        for name, value in values.items():
            setattr(existing, name, value)
    unit.db.flush()


def command_id(actor_id: str, key: Any) -> str:
    return str(uuid5(NAMESPACE_URL, f"immo:business-qol:v1:{actor_id}:{key}"))


def fingerprint(operation: str, payload: Any) -> str:
    canonical = payload.model_dump(mode="json", exclude_unset=True) if isinstance(payload, BaseModel) else dump(payload)
    return hashlib.sha256(json.dumps({"operation": operation, "payload": canonical}, sort_keys=True,
                                     separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def replay(unit, actor_id: str, operation: str, payload: Any) -> dict | None:
    receipt = get_record(unit, "business_qol_commands", command_id(actor_id, payload.idempotency_key))
    if receipt is None:
        return None
    if receipt.actor_id != actor_id or receipt.fingerprint != fingerprint(operation, payload):
        raise conflict("Diese Vorgangskennung wurde bereits mit anderen Angaben verwendet.")
    if receipt.response.get("status") == "processing":
        raise conflict("Die Dokumentanalyse läuft bereits. Bitte die Warteschlange aktualisieren.")
    return {**receipt.response, "replayed": True}


def save_command(unit, actor_id: str, operation: str, payload: Any, context: dict,
                 response: dict, *, inverse: dict | None = None, post_revision: str | None = None) -> BusinessCommand:
    stamp = timestamp()
    receipt = BusinessCommand(id=command_id(actor_id, payload.idempotency_key), actor_id=actor_id,
                              operation=operation, entity_type=context["kind"], entity_id=context["entity_id"],
                              property_id=context["property_id"], fingerprint=fingerprint(operation, payload),
                              response=dump(response), inverse=inverse, post_revision=post_revision,
                              created_at=stamp, updated_at=stamp)
    # A command is an immutable creation receipt, not an upsert. A concurrent
    # writer must roll back its domain mutation rather than overwrite a receipt
    # that was committed after its replay check. Undo markers use put_record
    # explicitly and are not new command creation.
    if unit.db is None:
        if receipt.id in unit.store.business_qol_commands:
            raise conflict("Die Vorgangskennung wurde gleichzeitig verwendet. Bitte den gespeicherten Stand abgleichen.")
        unit.insert(unit.store.business_qol_commands, receipt.id, receipt)
    else:
        values = receipt.model_dump()
        for key, value in values.items():
            if isinstance(value, datetime):
                values[key] = utc(value).replace(tzinfo=None)
        unit.db.add(BusinessCommandORM(**values))
        try:
            unit.db.flush()
        except IntegrityError:
            raise conflict("Die Vorgangskennung wurde gleichzeitig verwendet. Bitte den gespeicherten Stand abgleichen.") from None
    return receipt


def advance_command(unit, actor_id: str, operation: str, payload: Any,
                    expected_revision: str, response: dict) -> BusinessCommand:
    """Advance one already issued receipt; never replace its identity/request.

    A long-running action owns the expected revision of its claim. A different
    request, a later claim, or a missing receipt is a conflict, not an upsert.
    Its caller must additionally fence the domain-specific processing lease.
    """
    identifier = command_id(actor_id, payload.idempotency_key)
    if unit.db is not None:
        locked = unit.db.scalar(select(BusinessCommandORM).where(BusinessCommandORM.id == identifier).with_for_update())
        if locked is None:
            raise conflict("Der gespeicherte Vorgang ist nicht mehr vorhanden.")
    current = get_record(unit, "business_qol_commands", identifier)
    if (current is None or current.actor_id != actor_id or current.operation != operation
            or current.fingerprint != fingerprint(operation, payload)
            or not same_revision(expected_revision, current.updated_at.isoformat())):
        raise conflict("Der gespeicherte Vorgang wurde inzwischen geändert.")
    updated = current.model_copy(update={"response": dump(response),
                                         "updated_at": next_updated_at(current.updated_at, timestamp())})
    put_record(unit, "business_qol_commands", updated)
    return updated


def list_items(store, actor_id: str, *, kind=None, property_id=None, due_before=None, cursor=None, limit=50,
               deferred="all") -> dict:
    query = ["work", actor_id, kind, property_id, due_before, deferred]
    after = cursor_decode(cursor, query)
    if after and (len(after) != 3 or not all(isinstance(value, str) for value in after)):
        raise HTTPException(422, "Ungültige Fortsetzung.")
    if after:
        try:
            date.fromisoformat(after[0])
        except ValueError:
            raise HTTPException(422, "Ungültige Fortsetzung.") from None
    user = actor(actor_id, store)
    with scope_context(scope_from_user(user)):
        values = work_items.items(store, actor_id, kind=kind, property_id=property_id, due_before=due_before,
                                 after=tuple(after) if after else None, limit=limit, deferred=deferred)
        from .workspace import deferrals_for
        deferrals = deferrals_for(store, [item["work_item_key"] for item in values], actor_id)
        for item in values:
            deferred = deferrals.get(item["work_item_key"])
            item["deferral"] = deferred
            item["deferred_until"] = deferred["due_on"] if deferred else None
            item["due_again"] = bool(deferred and date.fromisoformat(deferred["due_on"]) <= local_today())
    return page(values, limit, query, work_items.sort_key)


def summary(store, actor_id: str, *, property_id=None, due_before=None, deferred="all") -> dict:
    user = actor(actor_id, store)
    with scope_context(scope_from_user(user)):
        result = work_items.counts(store, actor_id, property_id=property_id, due_before=due_before, deferred=deferred)
    query = {key: value.isoformat() if isinstance(value, date) else value for key, value in
             {"property_id": property_id, "due_before": due_before, "deferred": deferred}.items() if value is not None}
    as_of = local_today().isoformat()
    return {"as_of": as_of, "counts": result,
            "drilldowns": {kind: {"href": "/work-center?" + urlencode({**query, "kind": kind}),
                                  "query": {**query, "kind": kind}, "source_kind": kind, "as_of": as_of}
                           for kind in result}}


def _context_property(context: dict) -> str | None:
    return context["entity_id"] if context["kind"] == "property" else context["property_id"]


def _task_write(unit, identifier: str, values: dict) -> Task:
    current = unit.store.get_task(identifier)
    merged = {**current.model_dump(include=set(TaskCreate.model_fields)), **values}
    if merged.get("status") == "done":
        merged["status"] = "completed"
    data = TaskCreate.model_validate(merged)
    updated = Task(id=current.id, created_at=current.created_at,
                   updated_at=next_updated_at(current.updated_at, timestamp()), **data.model_dump())
    if unit.db is None:
        unit.insert(unit.store.tasks, identifier, updated)
    else:
        row = unit.db.scalar(select(TaskORM).where(TaskORM.id == identifier).with_for_update())
        if row is None:
            raise HTTPException(404, "Aufgabe nicht vorhanden.")
        for name, value in updated.model_dump().items():
            setattr(row, name, utc(value).replace(tzinfo=None) if isinstance(value, datetime) else value)
        unit.db.flush()
    record_unit_changes(unit, "tasks", current, updated)
    return updated


def create_note(store, payload: NoteCreate, actor_id: str) -> dict:
    with archive.work(store, actor_id, write_areas=("/tasks",)) as unit:
        context = resolve_context(unit.store, payload.entity_type, payload.entity_id, actor_id, lock=True)
        prior = replay(unit, actor_id, "note", payload)
        if prior:
            return prior
        check_revision(payload.base_revision, context["revision"])
        stamp = timestamp()
        task = None
        if payload.follow_up:
            properties = _context_property(context)
            task = Task(id=str(uuid4()), title=payload.follow_up.title,
                        description=f"Wiedervorlage zur Gesprächsnotiz: {payload.body[:1000]}",
                        assignee=payload.follow_up.assignee, due_date=payload.follow_up.due_date,
                        priority=payload.follow_up.priority, property_id=properties,
                        unit_id=context["entity_id"] if context["kind"] == "unit" else context["values"].get("unit_id"),
                        created_at=stamp, updated_at=stamp)
            if unit.db is None:
                unit.store.validate_task(task)
            else:
                # Reuse the repository validator on this writer's transaction;
                # SQLAlchemyStore exposes task mutations, not validate_task.
                unit.store.communication.validate_task(task)
            if unit.db is None:
                unit.insert(unit.store.tasks, task.id, task)
            else:
                values = task.model_dump()
                values.update(created_at=stamp.replace(tzinfo=None), updated_at=stamp.replace(tzinfo=None))
                unit.db.add(TaskORM(**values))
                unit.db.flush()
        note = ConversationNote(id=str(uuid4()), entity_type=context["kind"], entity_id=context["entity_id"],
                                property_id=_context_property(context), body=payload.body,
                                conversation_kind=payload.conversation_kind, occurred_at=utc(payload.occurred_at),
                                actor_id=actor_id, task_id=task.id if task else None, created_at=stamp, updated_at=stamp)
        put_record(unit, "business_conversation_notes", note)
        response = {"note": {**dump(note), "revision": note.updated_at.isoformat()},
                    "task": dump(task) if task else None, "replayed": False}
        save_command(unit, actor_id, "note", payload, context, response)
        return response


def quick_edit(store, payload: QuickEdit, actor_id: str) -> dict:
    changes = payload.changes.model_dump(exclude_unset=True)
    if changes.get("status") == "done":
        changes["status"] = "completed"
    if not changes or any(changes.get(key) is None for key in ("status", "priority") if key in changes):
        raise HTTPException(422, "Bitte eine gültige Änderung auswählen.")
    with archive.work(store, actor_id, write_areas=("/tasks",)) as unit:
        context = resolve_context(unit.store, "task", payload.entity_id, actor_id, lock=True)
        prior = replay(unit, actor_id, "quick_edit", payload)
        if prior:
            return prior
        check_revision(payload.base_revision, context["revision"])
        inverse = dump({key: context["values"].get(key) for key in changes})
        record = _task_write(unit, payload.entity_id, changes)
        revision = record.updated_at.isoformat()
        response = {"record": dump(record), "revision": revision,
                    "undo_id": command_id(actor_id, payload.idempotency_key), "replayed": False}
        save_command(unit, actor_id, "quick_edit", payload, context, response, inverse=inverse, post_revision=revision)
        return response


def undo_edit(store, identifier: str, payload: Undo, actor_id: str) -> dict:
    with archive.work(store, actor_id) as read:
        receipt = get_record(read, "business_qol_commands", identifier)
        document_undo = bool(receipt and receipt.actor_id == actor_id and receipt.operation.startswith("document_review:"))
    if document_undo:
        from .business_documents import undo_document
        return undo_document(store, identifier, payload, actor_id)
    with archive.work(store, actor_id, write_areas=("/tasks",)) as unit:
        original = get_record(unit, "business_qol_commands", identifier)
        if original is None or original.actor_id != actor_id or original.operation != "quick_edit":
            raise HTTPException(404, "Rückgängig-Vorgang nicht vorhanden.")
        context = resolve_context(unit.store, original.entity_type, original.entity_id, actor_id, lock=True)
        operation = "undo:" + identifier
        prior = replay(unit, actor_id, operation, payload)
        if prior:
            return prior
        if original.undone_by:
            raise conflict("Diese Änderung wurde bereits rückgängig gemacht.")
        check_revision(payload.base_revision, context["revision"])
        check_revision(original.post_revision or "", context["revision"])
        record = _task_write(unit, original.entity_id, original.inverse or {})
        response = {"record": dump(record), "revision": record.updated_at.isoformat(), "replayed": False}
        receipt = save_command(unit, actor_id, operation, payload, context, response)
        put_record(unit, "business_qol_commands", original.model_copy(update={"undone_by": receipt.id,
                                                                            "updated_at": timestamp()}))
        return response


def _events(store, orm, collection: str, filters: dict, at: str, before, limit: int):
    if hasattr(store, "db"):
        query = select(orm)
        for name, value in filters.items():
            query = query.where(getattr(orm, name) == value)
        if before:
            moment, identifier = before
            stamp = utc(datetime.fromisoformat(moment)).replace(tzinfo=None)
            query = query.where(or_(getattr(orm, at) < stamp,
                                   and_(getattr(orm, at) == stamp, orm.id < identifier)))
        return store.db.scalars(query.order_by(getattr(orm, at).desc(), orm.id.desc()).limit(limit))
    records = [record for record in getattr(store, collection).values()
               if all(getattr(record, key) == value for key, value in filters.items())]
    if before:
        moment, identifier = before
        records = [record for record in records if (utc(getattr(record, at)).isoformat(), record.id) < (moment, identifier)]
    return sorted(records, key=lambda record: (utc(getattr(record, at)), record.id), reverse=True)[:limit]


def timeline(store, entity_type: str, entity_id: str, actor_id: str, *, cursor=None, limit=50) -> dict:
    user = actor(actor_id, store)
    query = ["timeline", actor_id, entity_type, entity_id]
    before = cursor_decode(cursor, query)
    if before and (len(before) != 2 or not all(isinstance(value, str) for value in before)):
        raise HTTPException(422, "Ungültige Fortsetzung.")
    if before:
        try:
            datetime.fromisoformat(before[0])
        except ValueError:
            raise HTTPException(422, "Ungültige Fortsetzung.") from None
    with scope_context(scope_from_user(user)):
        context = resolve_context(store, entity_type, entity_id, actor_id)
        source = {"type": context["kind"], "id": entity_id, "title": context["title"], "href": context["href"]}
        values = []
        for row in _events(store, ConversationNoteORM, "business_conversation_notes",
                           {"entity_type": context["kind"], "entity_id": entity_id}, "occurred_at", before, limit + 1):
            values.append({"id": row.id, "occurred_at": utc(row.occurred_at).isoformat(), "kind": "conversation",
                           "title": {"phone": "Telefonat", "email": "E-Mail", "meeting": "Gespräch"}.get(
                               row.conversation_kind, "Notiz"), "body": row.body, "actor": row.actor_id,
                           "entity": source, "task_id": row.task_id})
        for row in _events(store, ChangeHistoryORM, "change_history",
                           {"entity_type": context["kind"], "entity_id": entity_id}, "changed_at", before, limit + 1):
            values.append({"id": row.id, "occurred_at": utc(row.changed_at).isoformat(), "kind": "change",
                           "title": "Änderung: " + row.field_name, "body": row.reason or "",
                           "field_name": row.field_name, "old_value": row.old_value, "new_value": row.new_value,
                           "actor": row.changed_by, "entity": source})
        if context["kind"] == "invoice":
            for row in _events(store, InvoiceReviewEventORM, "invoice_review_events", {"invoice_id": entity_id},
                               "created_at", before, limit + 1):
                values.append({"id": row.id, "occurred_at": utc(row.created_at).isoformat(), "kind": "invoice_review",
                               "title": row.action, "body": row.reason or "", "actor": row.actor_name or row.actor_id,
                               "actor_is_name": bool(row.actor_name),
                               "entity": source})
        if context["kind"] == "contract":
            for row in _events(store, DunningEventORM, "dunning_events", {"contract_id": entity_id},
                               "at", before, limit + 1):
                values.append({"id": row.id, "occurred_at": utc(row.at).isoformat(), "kind": "dunning",
                               "title": row.kind, "body": row.summary, "actor": row.actor_id, "entity": source})
        created = context["values"].get("created_at")
        if created:
            created = utc(created if isinstance(created, datetime) else datetime.fromisoformat(created)).isoformat()
            identity = "created:" + entity_id
            if not before or (created, identity) < tuple(before):
                values.append({"id": identity, "occurred_at": created, "kind": "created", "title": "Angelegt",
                               "body": context["title"], "actor": None, "entity": source})
        from .business_timeline import display_actors, related_events
        values.extend(related_events(store, context, actor_id, before, limit + 1))
        values.sort(key=lambda row: (row["occurred_at"], row["id"]), reverse=True)
        display_actors(store, values[:limit + 1])
        result = page(values[:limit + 1], limit, query, lambda row: [row["occurred_at"], row["id"]])
        return {**result, "entity": source, "entity_revision": context["revision"],
                "can_note": may_write(user["role"], "/tasks")}
