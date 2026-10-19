"""Change history router (T18: Historisierung)."""

import base64
import json
from datetime import datetime, timezone
from heapq import nlargest

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import literal, select, tuple_

from ..db.orm_models import ChangeHistoryORM
from ..dependencies import store
from ..models import ChangeHistoryEntry

router = APIRouter(prefix="/history", tags=["Änderungshistorie"])


class HistoryPage(BaseModel):
    items: list[ChangeHistoryEntry]
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
    return HistoryPage(items=items, next_cursor=_encode_cursor(items[-1], entity_type, entity_id) if len(rows) > limit else None)


@router.get("", response_model=list[ChangeHistoryEntry])
def list_history(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    entity_type: str | None = Query(None),
    entity_id: str | None = Query(None),
):
    results = store.list_change_history()
    if entity_type:
        results = [h for h in results if h.entity_type == entity_type]
    if entity_id:
        results = [h for h in results if h.entity_id == entity_id]
    # Equal clock ticks have no chronological ordering. IDs provide a stable
    # descending tie break, so repeated queries and adjacent pages agree.
    results.sort(key=lambda h: (h.changed_at, h.id), reverse=True)
    return results[skip: skip + limit]


@router.get("/{entity_type}/{entity_id}", response_model=list[ChangeHistoryEntry])
def get_entity_history(entity_type: str, entity_id: str):
    return sorted(store.get_entity_history(entity_type, entity_id),
                  key=lambda h: (h.changed_at, h.id), reverse=True)
