"""Private workspace endpoints; users never supply the state owner."""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from ..auth import require_auth
from ..dependencies import store
from ..models import UserRead
from ..services import workspace
from ..services import workspace_contexts as contexts
from ..workspace_models import (
    DeferralWrite,
    DraftRebase,
    DraftWrite,
    EntityWrite,
    RecentEvent,
    ViewStateWrite,
    ViewWrite,
    WorkspaceMutation,
)


def private_response(response: Response):
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["Pragma"] = "no-cache"


router = APIRouter(prefix="/workspace", tags=["Personal workspace"], dependencies=[Depends(private_response)])
Actor = Annotated[UserRead, Depends(require_auth)]
PageSize = Annotated[int, Query(ge=1, le=200)]
Cursor = Annotated[str | None, Query(max_length=2048)]


@router.get("/contexts")
def get_contexts(actor: Actor):
    return {"items": contexts.registry(actor.id)}


@router.get("/source/{kind}/{entity_id}")
def get_source(kind: str, entity_id: str, actor: Actor):
    resolved = contexts.resolve_context(store, kind, entity_id, actor.id, include_dependencies=True)
    return {"kind": resolved["kind"], "id": entity_id, "revision": resolved["revision"],
            "title": resolved["title"], "href": resolved["href"], "values": resolved["values"],
            "dependency_etags": resolved["dependencies"]}


@router.get("/drafts")
def list_drafts(actor: Actor, context: str | None = None, form_key: str | None = None,
                cursor: Cursor = None, limit: PageSize = 50):
    return workspace.list_records(store, actor.id, "drafts", context=context, form_key=form_key, cursor=cursor, limit=limit)


@router.get("/drafts/{identifier}")
def get_draft(identifier: str, actor: Actor):
    return workspace.get_record(store, actor.id, "drafts", identifier)


@router.put("/drafts/{identifier}")
def put_draft(identifier: str, payload: DraftWrite, actor: Actor):
    return workspace.mutate(store, actor.id, "drafts", identifier, payload.model_dump())


@router.post("/drafts/{identifier}/rebase")
def rebase_draft(identifier: str, payload: DraftRebase, actor: Actor):
    return workspace.mutate(store, actor.id, "drafts", identifier, payload.model_dump(), rebase=True)


@router.delete("/drafts/{identifier}")
def delete_draft(identifier: str, payload: WorkspaceMutation, actor: Actor):
    return workspace.mutate(store, actor.id, "drafts", identifier, payload.model_dump(), delete=True)


@router.get("/views")
def list_views(actor: Actor, context: str | None = None, cursor: Cursor = None, limit: PageSize = 50):
    return workspace.list_records(store, actor.id, "views", context=context, cursor=cursor, limit=limit)


@router.get("/views/{identifier}")
def get_view(identifier: str, actor: Actor):
    return workspace.get_record(store, actor.id, "views", identifier)


@router.put("/views/{identifier}")
def put_view(identifier: str, payload: ViewWrite, actor: Actor):
    return workspace.mutate(store, actor.id, "views", identifier, payload.model_dump())


@router.delete("/views/{identifier}")
def delete_view(identifier: str, payload: WorkspaceMutation, actor: Actor):
    return workspace.mutate(store, actor.id, "views", identifier, payload.model_dump(), delete=True)


@router.get("/recents")
def list_recents(actor: Actor, cursor: Cursor = None, limit: PageSize = 50):
    return workspace.list_records(store, actor.id, "recents", cursor=cursor, limit=limit)


@router.post("/recents/events")
def recent_event(payload: RecentEvent, actor: Actor):
    identifier = workspace.entity_key(payload.kind, payload.entity_id)
    return workspace.mutate(store, actor.id, "recents", identifier,
                            {"idempotency_key": payload.idempotency_key}, touch=True)


@router.get("/favorites")
def list_favorites(actor: Actor, cursor: Cursor = None, limit: PageSize = 50):
    return workspace.list_records(store, actor.id, "favorites", cursor=cursor, limit=limit)


@router.get("/favorites/{kind}/{entity_id}")
def get_favorite(kind: str, entity_id: str, actor: Actor):
    return workspace.get_record(store, actor.id, "favorites", workspace.entity_key(kind, entity_id))


@router.put("/favorites/{kind}/{entity_id}")
def put_favorite(kind: str, entity_id: str, payload: EntityWrite, actor: Actor):
    return workspace.mutate(store, actor.id, "favorites", workspace.entity_key(kind, entity_id), payload.model_dump())


@router.delete("/favorites/{kind}/{entity_id}")
def delete_favorite(kind: str, entity_id: str, payload: WorkspaceMutation, actor: Actor):
    return workspace.mutate(store, actor.id, "favorites", workspace.entity_key(kind, entity_id), payload.model_dump(), delete=True)


@router.get("/recents/{kind}/{entity_id}")
def get_recent(kind: str, entity_id: str, actor: Actor):
    return workspace.get_record(store, actor.id, "recents", workspace.entity_key(kind, entity_id))


@router.delete("/recents/{kind}/{entity_id}")
def delete_recent(kind: str, entity_id: str, payload: WorkspaceMutation, actor: Actor):
    return workspace.mutate(store, actor.id, "recents", workspace.entity_key(kind, entity_id), payload.model_dump(), delete=True)


@router.get("/view-state/{context:path}")
def get_view_state(context: str, actor: Actor, missing_ok: bool = False):
    # A list's first visit has no saved state yet; missing_ok answers that with null
    # instead of a 404, so the browser does not log a failed request on every new list.
    try:
        return workspace.get_record(store, actor.id, "view-state", contexts.context_identity(context))
    except HTTPException as error:
        if missing_ok and error.status_code == 404:
            return None
        raise


@router.put("/view-state/{context:path}")
def put_view_state(context: str, payload: ViewStateWrite, actor: Actor):
    return workspace.mutate(store, actor.id, "view-state", contexts.context_identity(context), payload.model_dump())


@router.delete("/view-state/{context:path}")
def delete_view_state(context: str, payload: WorkspaceMutation, actor: Actor):
    return workspace.mutate(store, actor.id, "view-state", contexts.context_identity(context), payload.model_dump(), delete=True)


@router.get("/deferrals")
def list_deferrals(actor: Actor, cursor: Cursor = None, limit: PageSize = 50, due_before: date | None = None):
    return workspace.list_records(store, actor.id, "deferrals", cursor=cursor, limit=limit, due_before=due_before)


@router.get("/deferrals/{key}")
def get_deferral(key: str, actor: Actor):
    return workspace.get_record(store, actor.id, "deferrals", key)


@router.put("/deferrals/{key}")
def put_deferral(key: str, payload: DeferralWrite, actor: Actor):
    return workspace.mutate(store, actor.id, "deferrals", key, payload.model_dump())


@router.delete("/deferrals/{key}")
def delete_deferral(key: str, payload: WorkspaceMutation, actor: Actor):
    return workspace.mutate(store, actor.id, "deferrals", key, payload.model_dump(), delete=True)
