"""Authenticated durable onboarding, separate from the existing PDF builder."""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy.exc import IntegrityError

from ..auth import require_auth
from ..dependencies import get_store
from ..models import UserRead
from ..services import contract_wizard as service
from ..services.contract_wizard_types import (
    DraftCommit,
    DraftCreate,
    DraftEdit,
    RevisionCommand,
    SignatureCreate,
    TemplateCreate,
)
from ..storage import NotFoundError, ValidationError
from .datev import PrivateDownloadResponse

router = APIRouter(prefix="/contract-wizard", tags=["Vertragsassistent"])
Actor = Annotated[UserRead, Depends(require_auth)]


def call(operation, *args, **kwargs):
    try:
        return operation(*args, **kwargs)
    except NotFoundError:
        raise HTTPException(404, "Bestand nicht gefunden oder nicht mehr zugänglich.") from None
    except ValidationError as error:
        raise HTTPException(422, str(error)) from None
    except IntegrityError:
        raise HTTPException(409, "Dieser Vorgang oder diese Vertragsnummer wurde zwischenzeitlich gespeichert. Gespeicherten Stand erneut laden.") from None


@router.get("/choices/{kind}")
def choices(kind: Literal["properties", "units", "tenants", "documents"], actor: Actor,
            search: str = Query("", max_length=200), property_id: str | None = None,
            selected_id: str | None = None, offset: int = Query(0, ge=0), limit: int = Query(25, ge=1, le=1000),
            store=Depends(get_store)):
    return call(service.choices, store, actor.id, kind, search=search, property_id=property_id,
        selected_id=selected_id, offset=offset, limit=limit)


@router.get("/drafts")
def listing(actor: Actor, offset: int = Query(0, ge=0), limit: int = Query(25, ge=1, le=1000), store=Depends(get_store)):
    return call(service.list_drafts, store, actor.id, offset, limit)


@router.post("/drafts", status_code=201)
def create(payload: DraftCreate, actor: Actor, store=Depends(get_store)):
    return call(service.create_draft, store, payload, actor.id)


@router.get("/drafts/{draft_id}")
def get(draft_id: str, actor: Actor, store=Depends(get_store)):
    return call(service.get_draft, store, draft_id, actor.id)


@router.post("/drafts/{draft_id}/edit")
def edit(draft_id: str, payload: DraftEdit, actor: Actor, store=Depends(get_store)):
    return call(service.edit_draft, store, draft_id, payload, actor.id)


@router.post("/drafts/{draft_id}/review")
def review(draft_id: str, payload: RevisionCommand, actor: Actor, store=Depends(get_store)):
    return call(service.review_draft, store, draft_id, payload, actor.id)


@router.post("/drafts/{draft_id}/publish")
def publish(draft_id: str, payload: DraftCommit, actor: Actor, store=Depends(get_store)):
    return call(service.publish_draft, store, draft_id, payload, actor.id)


@router.get("/drafts/{draft_id}/pdf")
def pdf(draft_id: str, actor: Actor, store=Depends(get_store)):
    content = call(service.read_pdf, store, draft_id, actor.id)
    return Response(content, media_type="application/pdf", headers={"Cache-Control": "private, no-store",
        "Content-Disposition": 'attachment; filename="mietvertrag.pdf"', "X-Content-Type-Options": "nosniff"})


@router.get("/drafts/{draft_id}/review-pdf")
def preview_pdf(draft_id: str, actor: Actor, store=Depends(get_store)):
    content = call(service.read_review_pdf, store, draft_id, actor.id)
    return Response(content, media_type="application/pdf", headers={"Cache-Control": "private, no-store",
        "Content-Disposition": 'attachment; filename="mietvertrag-vorschau.pdf"', "X-Content-Type-Options": "nosniff"})


@router.get("/drafts/{draft_id}/attachments")
def attachments(draft_id: str, actor: Actor, offset: int = Query(0, ge=0), limit: int = Query(25, ge=1, le=1000), store=Depends(get_store)):
    return call(service.attachment_evidence, store, draft_id, actor.id, offset=offset, limit=limit)


@router.get("/drafts/{draft_id}/attachments/{attachment_id}/download")
def attachment(draft_id: str, attachment_id: str, actor: Actor, store=Depends(get_store)):
    compiled, captured = call(service.prepare_attachment_download, store, draft_id, attachment_id, actor.id)
    try:
        service.refresh_scope(captured)
        return PrivateDownloadResponse(compiled, captured, media_type="application/octet-stream",
            headers={"Cache-Control": "private, no-store", "Content-Disposition": 'attachment; filename="anlage.bin"',
                "Content-Length": str(compiled.manifest["size"]), "X-Content-SHA256": compiled.manifest["sha256"],
                "X-Content-Type-Options": "nosniff"})
    except BaseException:
        compiled.close()
        raise


@router.post("/drafts/{draft_id}/signatures")
def signature(draft_id: str, payload: SignatureCreate, actor: Actor, store=Depends(get_store)):
    return call(service.record_signature, store, draft_id, payload, actor.id)


@router.get("/drafts/{draft_id}/signatures")
def signatures(draft_id: str, actor: Actor, offset: int = Query(0, ge=0), limit: int = Query(25, ge=1, le=1000), store=Depends(get_store)):
    return call(service.signature_evidence, store, draft_id, actor.id, offset=offset, limit=limit)


@router.get("/templates")
def templates(portfolio_id: str, actor: Actor, offset: int = Query(0, ge=0), limit: int = Query(25, ge=1, le=1000), store=Depends(get_store)):
    return call(service.list_templates, store, actor.id, portfolio_id, offset, limit)


@router.post("/templates", status_code=201)
def template(payload: TemplateCreate, actor: Actor, store=Depends(get_store)):
    return call(service.create_template, store, payload, actor.id)
