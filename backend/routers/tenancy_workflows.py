"""Internal P1/P2 API contract for versioned tenancy workflows."""

from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy.exc import IntegrityError

from ..auth import require_auth
from ..dependencies import get_store
from ..models import UserRead
from ..services import tenancy_workflow as service
from ..services.tenancy_workflow_types import (
    AddEvidence,
    CompleteTenancyChange,
    CreateStepTask,
    CreateTemplate,
    CreateTemplateVersion,
    PatchTenancyChange,
    PreviewTenancyChange,
    PublishTemplateVersion,
    ReanchorPreview,
    ReanchorTenancyChange,
    RemoveEvidence,
    StartTenancyChange,
    UpdateStep,
    UpdateTemplateVersion,
)
from ..services.workflow_authority_route import WorkflowAuthorityRoute
from ..storage import NotFoundError, ValidationError

router = APIRouter(tags=["Mieterwechsel"], route_class=WorkflowAuthorityRoute)
Actor = Annotated[UserRead, Depends(require_auth)]
Match = Annotated[str | None, Header(alias="If-Match")]


def call(operation, *args, **kwargs):
    try:
        return operation(*args, **kwargs)
    except HTTPException:
        raise
    except NotFoundError:
        raise HTTPException(404, "Datensatz nicht gefunden oder nicht zugänglich.") from None
    except ValidationError as exc:
        raise HTTPException(409, str(exc)) from None
    except IntegrityError:
        raise HTTPException(409, "Stand oder Vorgangsreferenz wurde parallel geändert. Neu laden.") from None


def match(if_match: str | None, kind: str, identifier: str, revision: str) -> None:
    if if_match is not None and if_match != service.workflow_etag(kind, identifier, revision):
        raise HTTPException(412, "If-Match und erwarteter Workflowstand widersprechen sich.")


@router.get("/workflow-templates")
def templates(
    actor: Actor,
    property_id: str | None = Query(None),
    unit_id: str | None = Query(None),
    direction: str | None = Query(None),
    after: str | None = Query(None, max_length=4096),
    limit: int = Query(25, ge=1),
    store=Depends(get_store),
):
    return call(
        service.list_templates,
        store,
        actor.id,
        property_id=property_id,
        unit_id=unit_id,
        direction=direction,
        after=after,
        limit=limit,
    )


@router.post("/workflow-templates", status_code=201)
def create_template(payload: CreateTemplate, actor: Actor, store=Depends(get_store)):
    return call(service.create_template, store, payload, actor.id)


@router.get("/workflow-templates/{template_id}")
def template(template_id: str, actor: Actor, store=Depends(get_store)):
    return call(service.get_template, store, template_id, actor.id)


@router.get("/workflow-templates/{template_id}/versions")
def versions(
    template_id: str,
    actor: Actor,
    after: str | None = Query(None, max_length=4096),
    limit: int = Query(25, ge=1),
    store=Depends(get_store),
):
    return call(service.list_template_versions, store, template_id, actor.id, after=after, limit=limit)


@router.post("/workflow-templates/{template_id}/versions", status_code=201)
def create_version(
    template_id: str,
    payload: CreateTemplateVersion,
    actor: Actor,
    if_match: Match = None,
    store=Depends(get_store),
):
    match(if_match, "template-version", payload.based_on_version_id, payload.expected_revision)
    return call(service.create_template_version, store, template_id, payload, actor.id)


@router.get("/workflow-template-versions/{version_id}")
def version(version_id: str, actor: Actor, store=Depends(get_store)):
    return call(service.get_template_version, store, version_id, actor.id)


@router.put("/workflow-template-versions/{version_id}")
def update_version(
    version_id: str,
    payload: UpdateTemplateVersion,
    actor: Actor,
    if_match: Match = None,
    store=Depends(get_store),
):
    match(if_match, "template-version", version_id, payload.expected_revision)
    return call(service.update_template_version, store, version_id, payload, actor.id)


@router.post("/workflow-template-versions/{version_id}/publish")
def publish_version(
    version_id: str,
    payload: PublishTemplateVersion,
    actor: Actor,
    if_match: Match = None,
    store=Depends(get_store),
):
    match(if_match, "template-version", version_id, payload.expected_revision)
    return call(service.publish_template_version, store, version_id, payload, actor.id)


@router.get("/tenancy-changes")
def changes(
    actor: Actor,
    property_id: str | None = Query(None),
    unit_id: str | None = Query(None),
    state: str | None = Query(None),
    after: str | None = Query(None, max_length=4096),
    limit: int = Query(25, ge=1),
    store=Depends(get_store),
):
    return call(
        service.list_changes,
        store,
        actor.id,
        property_id=property_id,
        unit_id=unit_id,
        state=state,
        after=after,
        limit=limit,
    )


@router.post("/tenancy-changes/preview")
def preview_change(payload: PreviewTenancyChange, actor: Actor, store=Depends(get_store)):
    return call(service.preview_change, store, payload, actor.id)


@router.post("/tenancy-changes", status_code=201)
def start_change(payload: StartTenancyChange, actor: Actor, store=Depends(get_store)):
    return call(service.start_change, store, payload, actor.id)


@router.get("/tenancy-changes/{change_id}")
def change(change_id: str, actor: Actor, store=Depends(get_store)):
    return call(service.get_change, store, change_id, actor.id)


@router.patch("/tenancy-changes/{change_id}")
def patch_change(
    change_id: str,
    payload: PatchTenancyChange,
    actor: Actor,
    if_match: Match = None,
    store=Depends(get_store),
):
    match(if_match, "tenancy-change", change_id, payload.expected_revision)
    return call(service.patch_change, store, change_id, payload, actor.id)


@router.post("/tenancy-changes/{change_id}/reanchor-preview")
def reanchor_preview(
    change_id: str,
    payload: ReanchorPreview,
    actor: Actor,
    if_match: Match = None,
    store=Depends(get_store),
):
    match(if_match, "tenancy-change", change_id, payload.expected_revision)
    return call(service.reanchor_preview, store, change_id, payload, actor.id)


@router.post("/tenancy-changes/{change_id}/reanchor")
def reanchor(
    change_id: str,
    payload: ReanchorTenancyChange,
    actor: Actor,
    if_match: Match = None,
    store=Depends(get_store),
):
    match(if_match, "tenancy-change", change_id, payload.expected_revision)
    return call(service.reanchor_change, store, change_id, payload, actor.id)


@router.patch("/tenancy-changes/{change_id}/steps/{step_id}")
def update_step(
    change_id: str,
    step_id: str,
    payload: UpdateStep,
    actor: Actor,
    if_match: Match = None,
    store=Depends(get_store),
):
    match(if_match, "step", step_id, payload.expected_revision)
    return call(service.update_step, store, change_id, step_id, payload, actor.id)


@router.post("/tenancy-changes/{change_id}/steps/{step_id}/task", status_code=201)
def create_task(
    change_id: str,
    step_id: str,
    payload: CreateStepTask,
    actor: Actor,
    if_match: Match = None,
    store=Depends(get_store),
):
    match(if_match, "step", step_id, payload.expected_revision)
    return call(service.create_step_task, store, change_id, step_id, payload, actor.id)


@router.post("/tenancy-changes/{change_id}/steps/{step_id}/evidence", status_code=201)
def add_evidence(
    change_id: str,
    step_id: str,
    payload: AddEvidence,
    actor: Actor,
    if_match: Match = None,
    store=Depends(get_store),
):
    match(if_match, "step", step_id, payload.expected_revision)
    return call(service.add_evidence, store, change_id, step_id, payload, actor.id)


@router.delete("/tenancy-changes/{change_id}/steps/{step_id}/evidence/{link_id}")
def remove_evidence(
    change_id: str,
    step_id: str,
    link_id: str,
    payload: RemoveEvidence,
    actor: Actor,
    if_match: Match = None,
    store=Depends(get_store),
):
    match(if_match, "step", step_id, payload.expected_revision)
    return call(service.remove_evidence, store, change_id, step_id, link_id, payload, actor.id)


@router.post("/tenancy-changes/{change_id}/complete")
def complete_change(
    change_id: str,
    payload: CompleteTenancyChange,
    actor: Actor,
    if_match: Match = None,
    store=Depends(get_store),
):
    match(if_match, "tenancy-change", change_id, payload.expected_revision)
    return call(service.complete_change, store, change_id, payload, actor.id)
