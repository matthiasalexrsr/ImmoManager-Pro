"""Bounded conversation pages and replayable, revision-checked internal replies.

The old list/create routes remain compatible. New browser replies use the
existing business-command receipt and archive transaction, not a second outbox.
This module does not perform external delivery.
"""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

from fastapi import HTTPException
from pydantic import Field, model_validator
from sqlalchemy import and_, func, or_, select

from ..db.orm_models import MessageORM, MessageThreadORM
from ..domain.revision_time import next_updated_at
from ..models import Message, MessageCreate, MessageThread
from ..storage import NotFoundError
from . import business_qol as office
from . import document_versions as archive
from .portfolio_scope import scope_context, scope_from_user
from .workspace_contexts import actor, bound_actor, resolve_context, validate_references


class MessageSubmission(MessageCreate):
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=128)
    base_revision: str | None = Field(default=None, min_length=1, max_length=200)

    @model_validator(mode="after")
    def command_pair(self):
        if (self.idempotency_key is None) != (self.base_revision is None):
            raise ValueError("Vorgangskennung und Quellrevision werden gemeinsam benötigt.")
        if not self.body.strip():
            raise ValueError("Bitte eine Nachricht eingeben.")
        return self


def message_page(store, thread_id: str, actor_id: str, *, cursor: str | None = None, limit: int = 100) -> dict:
    """Newest page first; within each page messages are in reading order.

    Paging is live, not a frozen export. Refresh exposes newly added messages;
    seeking to older (sent_at, id) pairs cannot duplicate unchanged older rows.
    Count means the currently visible total, independent of stored thread stats.
    Every page rechecks the actor, thread and attachment visibility.
    """
    if not 1 <= limit <= 250:
        raise HTTPException(422, "Die Seitengröße muss zwischen 1 und 250 liegen.")
    # User/grants may have changed since this request's Session was populated.
    # Read the actor afresh and select the thread through the scoped source query,
    # never through Session.get's identity-map fast path.
    user = actor(actor_id)
    with bound_actor(user), scope_context(scope_from_user(user)):
        context = resolve_context(store, "message_thread", thread_id, actor_id)
        thread = MessageThread.model_validate(context["values"])
        namespace = ["message-page-v1", actor_id, thread_id]
        before = office.cursor_decode(cursor, namespace)
        anchor = None
        if before is not None:
            try:
                if len(before) != 2 or not all(isinstance(value, str) for value in before) or not 1 <= len(before[1]) <= 120:
                    raise ValueError
                anchor = (office.utc(datetime.fromisoformat(before[0])), before[1])
            except (ValueError, TypeError):
                raise HTTPException(422, "Ungültige Fortsetzung. Bitte die Konversation neu laden.") from None
        if hasattr(store, "db"):
            query = select(MessageORM).where(MessageORM.thread_id == thread_id)
            if anchor:
                stamp, identifier = anchor
                stamp = stamp.replace(tzinfo=None)
                query = query.where(or_(MessageORM.sent_at < stamp,
                                       and_(MessageORM.sent_at == stamp, MessageORM.id < identifier)))
            rows = store.db.scalars(query.order_by(MessageORM.sent_at.desc(), MessageORM.id.desc()).limit(limit + 1)).all()
            total = store.db.scalar(select(func.count(MessageORM.id)).where(MessageORM.thread_id == thread_id))
            values = [Message.model_validate({column.key: getattr(row, column.key) for column in MessageORM.__table__.c})
                      for row in rows]
        else:
            all_values = store.list_messages(thread_id=thread_id)
            total = len(all_values)
            values = [row for row in all_values if anchor is None or (office.utc(row.sent_at), row.id) < anchor]
            values = sorted(values, key=lambda row: (office.utc(row.sent_at), row.id), reverse=True)[:limit + 1]
        more = len(values) > limit
        chosen = [row.model_copy(update={"sent_at": office.utc(row.sent_at)}) for row in values[:limit]]
        next_cursor = office.cursor_encode(namespace, [office.utc(chosen[-1].sent_at).isoformat(), chosen[-1].id]) \
            if more else None
        return {"items": list(reversed(chosen)), "next_cursor": next_cursor, "has_more": more,
                "total": total, "thread": thread, "order": "newest-pages/chronological-items"}


def send_message(store, thread_id: str, payload: MessageSubmission, actor_id: str) -> Message:
    """Commit message, thread counters/revision and command receipt together."""
    if payload.thread_id != thread_id:
        raise HTTPException(422, "Nachricht und ausgewählte Konversation stimmen nicht überein.")
    if payload.idempotency_key is None or payload.base_revision is None:
        raise HTTPException(422, "Vorgangskennung und Quellrevision fehlen.")
    operation = "message_send:" + thread_id
    with archive.work(store, actor_id, write_areas=("/messages",)) as unit:
        with bound_actor(unit.user), scope_context(scope_from_user(unit.user)):
            context = resolve_context(unit.store, "message_thread", thread_id, actor_id, lock=True)
            # Access is checked before a receipt can reveal the original response.
            prior = office.replay(unit, actor_id, operation, payload)
            if prior:
                try:
                    message = unit.store.get_message(prior["message_id"])
                except NotFoundError:
                    raise HTTPException(409, "Die bestätigte Nachricht wurde inzwischen entfernt. Sie wird nicht erneut angelegt.") from None
                if message.thread_id != thread_id:
                    raise HTTPException(409, "Der gespeicherte Vorgang passt nicht mehr zur Konversation.")
                return message.model_copy(update={"sent_at": office.utc(message.sent_at)})
            office.check_revision(payload.base_revision, context["revision"])
            values = payload.model_dump(include=set(MessageCreate.model_fields))
            validate_references(unit.store, values, actor_id)
            # New authenticated commands record the real account, not a claimed sender.
            values["sender_name"] = unit.user.get("full_name") or unit.user["username"]
            stamp = office.timestamp()
            message = Message(id=str(uuid4()), sent_at=stamp, **values)
            thread = MessageThread.model_validate(context["values"])
            revised = thread.model_copy(update={"last_message_at": stamp, "message_count": thread.message_count + 1,
                                                "updated_at": next_updated_at(thread.updated_at, stamp)})
            if unit.db is None:
                unit.insert(unit.store.messages, message.id, message)
                unit.insert(unit.store.message_threads, thread.id, revised)
            else:
                row = unit.db.scalar(select(MessageThreadORM).where(MessageThreadORM.id == thread_id).with_for_update())
                if row is None:
                    raise HTTPException(404, "Konversation nicht gefunden.")
                unit.db.add(MessageORM(**{**message.model_dump(), "sent_at": stamp.replace(tzinfo=None)}))
                row.last_message_at = stamp.replace(tzinfo=None)
                row.message_count = revised.message_count
                row.updated_at = office.utc(revised.updated_at).replace(tzinfo=None)
                unit.db.flush()
            # The receipt contains identity only. Access/recovery never duplicates
            # private message bodies into a second historical response store.
            office.save_command(unit, actor_id, operation, payload, context, {"message_id": message.id})
            return message
