"""Closed normal-action facade for API/MCP clients, with no installation token or gateway."""
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from ..auth import require_auth
from ..dependencies import store
from ..models import UserRead
from ..services import workspace, workspace_contexts

router = APIRouter(prefix="/workspace/actions", tags=["Freigegebene Aktionen"])


class Action(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["source.read", "favorite.set", "favorite.remove"]
    source_kind: str = Field(min_length=1, max_length=80)
    source_id: str = Field(min_length=1, max_length=120)
    source_revision: str = Field(min_length=1, max_length=120)
    base_revision: int = Field(ge=0)
    idempotency_key: str = Field(min_length=8, max_length=120)
    confirmed: Literal[True]


@router.get("")
def catalog(actor: UserRead = Depends(require_auth)):
    return {"api_version": 1, "actions": ["source.read", "favorite.set", "favorite.remove"],
            "financial_writes": False, "explicit_confirmation_required": True,
            "input_schema": Action.model_json_schema()}


@router.post("")
def execute(payload: Action, actor: UserRead = Depends(require_auth)):
    if payload.action == "source.read":
        result = workspace_contexts.resolve_context(store, payload.source_kind, payload.source_id, actor.id)
        if not workspace_contexts.same_revision(payload.source_revision, result["revision"]):
            raise HTTPException(409, "Quelle wurde geändert. Bitte neu laden.")
        return result
    return workspace.mutate(store, actor.id, "favorites",
        workspace.entity_key(payload.source_kind, payload.source_id),
        {"base_revision": payload.base_revision, "idempotency_key": payload.idempotency_key},
        delete=payload.action == "favorite.remove",
        source_guard=(payload.source_kind, payload.source_id, payload.source_revision))
