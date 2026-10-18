"""Owner predicates, encrypted payloads and account-fenced assistant transactions."""
from contextlib import contextmanager
from datetime import datetime
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import and_, or_, select, text

from ..db.assistant_models import AssistantConversationORM as Conversation
from . import business_qol as commands
from . import document_versions as archive
from .integrations import connection_storage as dbs
from .portfolio_scope import scope_context, scope_from_user
from .workspace_contexts import bound_actor


@contextmanager
def work(store, actor_id: str, *, write: bool = False, key: str | None = None):
    with archive.work(store, actor_id, write_areas=("/assistant",) if write else ()) as unit:
        with bound_actor(unit.user), scope_context(scope_from_user(unit.user)):
            if key and unit.db is not None and unit.db.get_bind().dialect.name == "postgresql":
                import hashlib
                digest = hashlib.sha256(("assistant:" + actor_id + ":" + key).encode()).digest()
                unit.db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": int.from_bytes(digest[:8], "big", signed=True)})
            yield unit


def payload(row) -> dict:
    return dbs.unseal(row.payload_token, f"assistant/{row.__tablename__}/{row.owner_id}/{row.id}/"
                      + (row.conversation_id if hasattr(row, "conversation_id") else ""))


def get(unit, model, identifier: str, *, lock: bool = False):
    if unit.db is None:
        row = dbs.memory(unit, model).get(identifier)
        if row is not None and row.owner_id != unit.actor_id:
            row = None
    else:
        query = select(model).where(model.id == identifier, model.owner_id == unit.actor_id)
        row = unit.db.scalar(query.with_for_update() if lock else query)
    if row is None:
        raise HTTPException(404, "Gespräch oder Vorgang nicht gefunden.")
    return row


def public(row) -> dict:
    data = payload(row)
    return {**{key: value for key, value in data.items() if not key.startswith("_")}, "id": row.id,
            "revision": row.revision, "state": row.state, "created_at": dbs.stamp(row.created_at),
            "updated_at": dbs.stamp(row.updated_at),
            **({"conversation_id": row.conversation_id} if hasattr(row, "conversation_id") else {})}


def conversation_public(unit, row):
    result = public(row)
    identifier = result.get("active_run_id")
    if identifier:
        from ..db.assistant_models import AssistantRunORM
        active = get(unit, AssistantRunORM, identifier)
        if active.state not in ("queued", "running"):
            result["active_run_id"] = None
    return result


def put(unit, model, data: dict, *, row=None, state: str | None = None, conversation_id: str | None = None):
    identifier = row.id if row is not None else str(uuid4())
    parent = (row.conversation_id if row is not None else conversation_id) if model is not Conversation else ""
    values = dict(id=identifier, owner_id=unit.actor_id, revision=row.revision + 1 if row is not None else 1,
                  state=state or (row.state if row is not None else "active"),
                  created_at=row.created_at if row is not None else dbs.now(), updated_at=dbs.now(),
                  payload_token=dbs.seal(data, f"assistant/{model.__tablename__}/{unit.actor_id}/{identifier}/{parent}"))
    if model is not Conversation:
        values["conversation_id"] = row.conversation_id if row is not None else conversation_id
    return dbs.put(unit, model, values)


def conversation(unit, identifier: str, *, lock: bool = False):
    row = get(unit, Conversation, identifier, lock=lock)
    from .assistant_context import assert_context_access
    for bundle in payload(row).get("_contexts", []):
        try:
            assert_context_access(unit.store, bundle, unit.actor_id)
        except HTTPException:
            raise HTTPException(404, "Gespräch aufgrund geänderter Quellenrechte nicht verfügbar.") from None
    return row


def owned_child(unit, model, identifier: str, *, lock=False):
    row = get(unit, model, identifier, lock=lock)
    conversation(unit, row.conversation_id, lock=lock)
    return row


def revision(row, expected: int):
    dbs.revision(row, expected)


def replay(unit, operation, command):
    from . import workspace
    key = commands.command_id(unit.actor_id, "assistant:" + command.idempotency_key)
    receipt = workspace._command(unit, key)
    if receipt is not None:
        if receipt.request_hash != commands.fingerprint("assistant:" + operation, command):
            raise HTTPException(409, "Diese Vorgangskennung wurde bereits mit anderen Angaben verwendet.")
        # Only identifiers are journalled; resolve contents through current ownership and source checks.
        return receipt.response["result"]["id"]
    return None


def receipt(unit, operation, command, row):
    from . import workspace
    # Personal commands must also work for an account without any portfolio.
    # The namespace leaves a handoff's workspace command key independent, while
    # draft, proposal decision and both receipts share this transaction.
    key = commands.command_id(unit.actor_id, "assistant:" + command.idempotency_key)
    workspace._remember(unit, key, commands.fingerprint("assistant:" + operation, command),
                        {"id": row.id}, {"assistant_id": row.id})


def page(unit, model, *, conversation_id: str | None = None, cursor=None, limit=50) -> dict:
    if not 1 <= limit <= 100:
        raise HTTPException(422, "Seitengröße muss zwischen 1 und 100 liegen.")
    namespace = ["assistant-page", unit.actor_id, model.__tablename__, conversation_id]
    anchor = commands.cursor_decode(cursor, namespace)
    before: tuple[datetime, str] | None = None
    if anchor:
        try:
            if len(anchor) != 2 or not isinstance(anchor[1], str):
                raise ValueError
            before = (datetime.fromisoformat(anchor[0]).replace(tzinfo=None), anchor[1])
        except (ValueError, TypeError):
            raise HTTPException(422, "Ungültige Fortsetzung.") from None
    if unit.db is None:
        rows = [row for row in dbs.memory(unit, model).values() if row.owner_id == unit.actor_id
                and (conversation_id is None or row.conversation_id == conversation_id)
                and (before is None or (row.created_at, row.id) < before)]
        rows = sorted(rows, key=lambda row: (row.created_at, row.id), reverse=True)[:limit + 1]
    else:
        query = select(model).where(model.owner_id == unit.actor_id)
        if conversation_id:
            query = query.where(model.conversation_id == conversation_id)
        if before:
            query = query.where(or_(model.created_at < before[0], and_(model.created_at == before[0], model.id < before[1])))
        rows = list(unit.db.scalars(query.order_by(model.created_at.desc(), model.id.desc()).limit(limit + 1)))
    more = len(rows) > limit
    chosen = rows[:limit]
    # Conversation titles can also contain now-revoked source information.
    visible = []
    for row in chosen:
        if model is Conversation:
            try:
                conversation(unit, row.id)
            except HTTPException as exc:
                if exc.status_code == 404:
                    continue
                raise
        visible.append(conversation_public(unit, row) if model is Conversation else public(row))
    return {"items": visible, "has_more": more,
            "next_cursor": commands.cursor_encode(namespace, [dbs.stamp(chosen[-1].created_at), chosen[-1].id]) if more else None}
