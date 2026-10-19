"""Change history router (T18: Historisierung)."""

import base64
import json
from contextlib import nullcontext
from datetime import datetime, timezone
from heapq import nlargest
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import literal, select, tuple_

from ..auth import require_auth
from ..db.orm_models import ChangeHistoryORM
from ..dependencies import store
from ..models import ChangeHistoryEntry, UserRead
from ..services.business_timeline import display_actors
from ..services.workspace_contexts import actor as account_of
from ..services.workspace_contexts import bound_actor, resolve_context

router = APIRouter(prefix="/history", tags=["Änderungshistorie"])
Actor = Annotated[UserRead, Depends(require_auth)]


class ChangeHistoryListEntry(ChangeHistoryEntry):
    """A change as the history page shows it: which record, its page and who changed it."""

    entity_title: Optional[str] = None
    entity_href: Optional[str] = None
    changed_by_name: Optional[str] = None


class HistoryPage(BaseModel):
    items: list[ChangeHistoryListEntry]
    next_cursor: str | None


def _utc(moment: datetime) -> datetime:
    return moment.replace(tzinfo=timezone.utc) if moment.tzinfo is None else moment.astimezone(timezone.utc)


def _key(row: ChangeHistoryEntry) -> tuple[datetime, str]:
    return _utc(row.changed_at), row.id


def _decode_cursor(cursor: str | None, entity_type: str | None, entity_id: str | None) -> tuple[datetime, str] | None:
    if cursor is None:
        return None
    try:
        value = json.loads(base64.b64decode(cursor + "=" * (-len(cursor) % 4), altchars=b"-_", validate=True))
        if (not isinstance(value, dict) or value.get("v") != 1
                or value.get("entity_type") != entity_type or value.get("entity_id") != entity_id):
            raise ValueError("cursor context")
        after = value["after"]
        if (not isinstance(after, list) or len(after) != 2 or not isinstance(after[0], str)
                or not isinstance(after[1], str) or not 1 <= len(after[1]) <= 256):
            raise ValueError("cursor position")
        return _utc(datetime.fromisoformat(after[0])), after[1]
    except (ValueError, TypeError, KeyError, UnicodeError, OverflowError) as error:
        raise HTTPException(422, "Der Verlaufscursor ist ungültig oder gehört zu anderen Filtern.") from error


def _encode_cursor(row: ChangeHistoryEntry, entity_type: str | None, entity_id: str | None) -> str:
    stamp, identifier = _key(row)
    payload = {"v": 1, "after": [stamp.isoformat(), identifier], "entity_type": entity_type, "entity_id": entity_id}
    return base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode()).decode().rstrip("=")


@router.get("/page", response_model=HistoryPage)
def history_page(
    actor: Actor,
    cursor: str | None = Query(None, max_length=4096),
    limit: int = Query(100, ge=1, le=250),
    entity_type: str | None = Query(None, max_length=100),
    entity_id: str | None = Query(None, max_length=256),
):
    entity_type, entity_id = entity_type or None, entity_id or None
    after = _decode_cursor(cursor, entity_type, entity_id)
    if hasattr(store, "db"):
        # Use the request's scoped Session, exactly as the repository does. Its
        # portfolio criteria apply before LIMIT; never fetch private rows first.
        query = select(ChangeHistoryORM)
        if entity_type:
            query = query.where(ChangeHistoryORM.entity_type == entity_type)
        if entity_id:
            query = query.where(ChangeHistoryORM.entity_id == entity_id)
        if after:
            stamp, identifier = after
            stamp = stamp.replace(tzinfo=None)  # ORM stores UTC in a naive DateTime.
            # SQLite and PostgreSQL seek directly into the composite index;
            # expanding this into OR clauses can scan earlier pages repeatedly.
            query = query.where(tuple_(ChangeHistoryORM.changed_at, ChangeHistoryORM.id) < tuple_(literal(stamp), literal(identifier)))
        query = query.order_by(ChangeHistoryORM.changed_at.desc(), ChangeHistoryORM.id.desc()).limit(limit + 1)
        rows = [ChangeHistoryEntry.model_validate(row, from_attributes=True) for row in store.db.scalars(query)]
    else:
        # ScopedCollection.values() already enforces the same memory boundary.
        source = store.change_history.values() if hasattr(store, "change_history") else store.list_change_history()
        rows = nlargest(limit + 1, (row for row in source
            if (not entity_type or row.entity_type == entity_type) and (not entity_id or row.entity_id == entity_id)
            and (after is None or _key(row) < after)), key=_key)
    items = [row.model_copy(update={"changed_at": _utc(row.changed_at)}) for row in rows[:limit]]
    return HistoryPage(items=_described(items, actor.id), next_cursor=_encode_cursor(items[-1], entity_type, entity_id) if len(rows) > limit else None)


def _page(entity_type, entity_id, skip, limit) -> list[ChangeHistoryEntry]:
    # Equal clock ticks have no chronological ordering. IDs provide a stable
    # descending tie break, so repeated queries and adjacent pages agree.
    if hasattr(store, "db"):
        query = select(ChangeHistoryORM)
        if entity_type:
            query = query.where(ChangeHistoryORM.entity_type == entity_type)
        if entity_id:
            query = query.where(ChangeHistoryORM.entity_id == entity_id)
        rows = store.db.scalars(query.order_by(ChangeHistoryORM.changed_at.desc(), ChangeHistoryORM.id.desc())
                                .offset(skip).limit(limit))
        return [ChangeHistoryEntry.model_validate({key: getattr(row, key) for key in ChangeHistoryEntry.model_fields})
                for row in rows]
    results = store.list_change_history()
    if entity_type:
        results = [h for h in results if h.entity_type == entity_type]
    if entity_id:
        results = [h for h in results if h.entity_id == entity_id]
    results.sort(key=lambda h: (h.changed_at, h.id), reverse=True)
    return results[skip: skip + limit]


def _described(entries: list[ChangeHistoryEntry], actor_id: str) -> list[ChangeHistoryListEntry]:
    sources: dict[tuple[str, str], tuple[str | None, str | None]] = {}
    try:
        user = account_of(actor_id, store)
    except HTTPException:
        user = None
    # the account is read once for the whole page, not once per record
    with bound_actor(user) if user else nullcontext():
        for key in ({(entry.entity_type, entry.entity_id) for entry in entries} if user else ()):
            try:
                source = resolve_context(store, key[0], key[1], actor_id)
                sources[key] = (source["title"], source["href"])
            except HTTPException:
                sources[key] = (None, None)      # deleted since, or a kind without a page
    actors = [{"actor": entry.changed_by} for entry in entries]
    if any(entry.changed_by for entry in entries):
        display_actors(store, actors)
    return [ChangeHistoryListEntry(**entry.model_dump(), entity_title=sources.get((entry.entity_type, entry.entity_id), (None, None))[0],
                                   entity_href=sources.get((entry.entity_type, entry.entity_id), (None, None))[1],
                                   changed_by_name=named["actor"])
            for entry, named in zip(entries, actors)]


@router.get("", response_model=list[ChangeHistoryListEntry])
def list_history(
    actor: Actor,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    entity_type: str | None = Query(None),
    entity_id: str | None = Query(None),
):
    return _described(_page(entity_type, entity_id, skip, limit), actor.id)


@router.get("/{entity_type}/{entity_id}", response_model=list[ChangeHistoryEntry])
def get_entity_history(entity_type: str, entity_id: str):
    return sorted(store.get_entity_history(entity_type, entity_id),
                  key=lambda h: (h.changed_at, h.id), reverse=True)
