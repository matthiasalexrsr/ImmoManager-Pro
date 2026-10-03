"""Communication center API: templates, blocks, reviewed documents and dispatch."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response

from ..auth import UserRead, require_auth, require_role
from ..communication_models import (
    CommunicationBlockCreate,
    CommunicationBlockUpdate,
    CommunicationDraftCreate,
    CommunicationDraftUpdate,
    CommunicationTemplateCreate,
    CommunicationTemplateUpdate,
    DispatchCommand,
    RenderRequest,
    ReviewCommand,
)
from ..dependencies import store
from ..services import communication_center as service
from ..services.integrations.manager import integration_manager

router = APIRouter(prefix="/communication-center", tags=["Kommunikationszentrum"])
Reader = Annotated[UserRead, Depends(require_auth)]
Writer = Annotated[
    UserRead,
    Depends(require_role("eigentuemer", "verwalter", "buchhaltung", "techniker")),
]
LibraryAdmin = Annotated[UserRead, Depends(require_role("eigentuemer", "verwalter"))]


@router.get("/catalog")
def catalog(actor: Reader):
    return service.catalog(store)


@router.get("/templates")
def templates(actor: Reader):
    return service.list_templates(store)


@router.post("/templates", status_code=201)
def create_template(body: CommunicationTemplateCreate, actor: LibraryAdmin):
    return service.create_template(store, body)


@router.put("/templates/{identifier}")
def update_template(identifier: str, body: CommunicationTemplateUpdate, actor: LibraryAdmin):
    return service.update_template(store, identifier, body)


@router.delete("/templates/{identifier}", status_code=204)
def delete_template(identifier: str, actor: LibraryAdmin):
    service.delete_template(store, identifier)
    return Response(status_code=204)


@router.get("/blocks")
def blocks(actor: Reader):
    return service.list_blocks(store)


@router.post("/blocks", status_code=201)
def create_block(body: CommunicationBlockCreate, actor: LibraryAdmin):
    return service.create_block(store, body)


@router.put("/blocks/{identifier}")
def update_block(identifier: str, body: CommunicationBlockUpdate, actor: LibraryAdmin):
    return service.update_block(store, identifier, body)


@router.delete("/blocks/{identifier}", status_code=204)
def delete_block(identifier: str, actor: LibraryAdmin):
    service.delete_block(store, identifier)
    return Response(status_code=204)


@router.post("/starter-library")
def starter_library(actor: LibraryAdmin):
    return service.install_starter_library(store)


@router.post("/preview")
def preview(portfolio_id: str, body: RenderRequest, actor: Reader):
    return service.preview(store, portfolio_id, body)


@router.get("/drafts")
def drafts(portfolio_id: str, actor: Reader):
    return service.list_drafts(store, portfolio_id)


@router.post("/drafts", status_code=201)
def create_draft(body: CommunicationDraftCreate, actor: Writer):
    return service.create_draft(store, body, actor.id)


@router.get("/drafts/{identifier}")
def draft(identifier: str, actor: Reader):
    return service._as_draft(service.get_draft(store, identifier))


@router.put("/drafts/{identifier}")
def update_draft(identifier: str, body: CommunicationDraftUpdate, actor: Writer):
    return service.update_draft(store, identifier, body)


@router.post("/drafts/{identifier}/review")
def review_draft(identifier: str, body: ReviewCommand, actor: Writer):
    return service.review_draft(store, identifier, body.expected_revision, actor.id)


@router.get("/drafts/{identifier}/pdf")
def download_pdf(identifier: str, actor: Reader):
    content, filename = service.pdf_bytes(store, identifier)
    return Response(
        content=content,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Cache-Control": "private, no-store",
        },
    )


@router.post("/drafts/{identifier}/dispatch")
def dispatch(identifier: str, body: DispatchCommand, actor: Writer):
    row = service.get_draft(store, identifier)
    if row.revision != body.expected_revision:
        from fastapi import HTTPException
        raise HTTPException(412, "Korrespondenz wurde zwischenzeitlich geändert")
    if row.channel != body.action:
        from fastapi import HTTPException
        raise HTTPException(409, "Freigegebener Kanal und Versandaktion stimmen nicht überein")
    if body.action == "email":
        result = service.dispatch_email(store, row, actor.id)
        return {"draft": service._as_draft(row), "provider": "smtp-outbox", "result": result}
    provider, result = service.dispatch_external(store, row, body.action, body.test_mode)
    return {"draft": service._as_draft(row), "provider": provider, "result": result}


@router.post("/drafts/{identifier}/post-status")
def refresh_post_status(
    identifier: str,
    actor: Writer,
    confirmed: bool = Query(False),
):
    from fastapi import HTTPException
    row = service.get_draft(store, identifier)
    if row.channel != "post" or not row.external_reference:
        raise HTTPException(409, "Kein E-POST-Auftrag für diese Korrespondenz vorhanden")
    if not confirmed:
        raise HTTPException(422, "Explizite Statusabfrage bestätigen")
    result = integration_manager.run("deutsche-post", {
        "action": "status", "letter_id": row.external_reference,
    })
    if not result.get("success"):
        raise HTTPException(502, result)
    details = result.get("details") or {}
    response = details.get("response") or {}
    row.external_status = str(response.get("status") or response.get("statusDetails") or "queried")
    service._commit(service.database(store))
    return {"draft": service._as_draft(row), "result": result}
