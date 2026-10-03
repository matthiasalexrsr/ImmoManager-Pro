"""Change history router (T18: Historisierung)."""

from fastapi import APIRouter, Query

from ..dependencies import store
from ..models import ChangeHistoryEntry
from ..services.history_inventory import legacy_history_list
from .history_inventory import router as inventory_router

router = APIRouter(prefix="/history", tags=["Änderungshistorie"])
router.include_router(inventory_router)


@router.get("", response_model=list[ChangeHistoryEntry])
def list_history(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    entity_type: str | None = Query(None),
    entity_id: str | None = Query(None),
):
    return legacy_history_list(store, skip=skip, limit=limit,
        entity_type=entity_type if isinstance(entity_type, str) else None,
        entity_id=entity_id if isinstance(entity_id, str) else None)


@router.get("/{entity_type}/{entity_id}", response_model=list[ChangeHistoryEntry])
def get_entity_history(entity_type: str, entity_id: str):
    return store.get_entity_history(entity_type, entity_id)
