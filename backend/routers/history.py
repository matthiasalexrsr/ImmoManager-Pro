"""Change history router (T18: Historisierung)."""

from fastapi import APIRouter, Query

from ..dependencies import store
from ..models import ChangeHistoryEntry

router = APIRouter(prefix="/history", tags=["Änderungshistorie"])


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
    # Sort by changed_at descending
    results.sort(key=lambda h: h.changed_at, reverse=True)
    return results[skip: skip + limit]


@router.get("/{entity_type}/{entity_id}", response_model=list[ChangeHistoryEntry])
def get_entity_history(entity_type: str, entity_id: str):
    return store.get_entity_history(entity_type, entity_id)
