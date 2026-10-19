"""Change history router (T18: Historisierung)."""

from contextlib import nullcontext
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select

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
        for key in {(entry.entity_type, entry.entity_id) for entry in entries}:
            try:
                source = resolve_context(store, key[0], key[1], actor_id)
                sources[key] = (source["title"], source["href"])
            except HTTPException:
                sources[key] = (None, None)      # deleted since, or a kind without a page
    actors = [{"actor": entry.changed_by} for entry in entries]
    display_actors(store, actors)
    return [ChangeHistoryListEntry(**entry.model_dump(), entity_title=sources[(entry.entity_type, entry.entity_id)][0],
                                   entity_href=sources[(entry.entity_type, entry.entity_id)][1],
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
