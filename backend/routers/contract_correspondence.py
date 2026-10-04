"""Local letters, user-confirmed dates and explicitly manual observations."""

from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.exc import IntegrityError

from ..auth import require_auth
from ..dependencies import get_store
from ..models import UserRead
from ..services import contract_correspondence as service
from ..services.contract_correspondence_types import (
    ApproveLetter,
    CreateLetter,
    EditLetter,
    ManualEvent,
    RevisionCommand,
)
from ..storage import NotFoundError, ValidationError
from .datev import PrivateDownloadResponse

router = APIRouter(prefix="/contracts/{contract_id}/correspondence", tags=["Lokale Vertragskorrespondenz"])
Actor = Annotated[UserRead, Depends(require_auth)]


def call(operation, *args, **kwargs):
    try:
        return operation(*args, **kwargs)
    except NotFoundError:
        raise HTTPException(404, "Vertrag oder Schreiben nicht zugänglich.") from None
    except ValidationError as error:
        raise HTTPException(409, str(error)) from None
    except IntegrityError:
        raise HTTPException(409, "Stand oder Vorgangsreferenz geändert. Aktuellen Stand erneut prüfen.") from None


@router.post("/drafts", status_code=201)
def create(contract_id: str, payload: CreateLetter, actor: Actor, store=Depends(get_store)):
    return call(service.create_draft, store, contract_id, payload, actor.id)


@router.get("/drafts")
def listing(contract_id: str, actor: Actor, before: str | None = Query(None, max_length=512),
            limit: int = Query(25, ge=1), store=Depends(get_store)):
    return call(service.listing, store, contract_id, actor.id, before=before, limit=limit)


@router.get("/history")
def history(contract_id: str, actor: Actor, before: str | None = Query(None, max_length=512),
            limit: int = Query(25, ge=1), store=Depends(get_store)):
    return call(service.listing, store, contract_id, actor.id, before=before, limit=limit, history=True)


@router.get("/deadlines")
def deadlines(contract_id: str, actor: Actor, before: str | None = Query(None, max_length=512),
              limit: int = Query(25, ge=1), store=Depends(get_store)):
    return call(service.deadline_projection, store, contract_id, actor.id, before=before, limit=limit)


@router.get("/drafts/{draft_id}")
def read(contract_id: str, draft_id: str, actor: Actor, store=Depends(get_store)):
    return call(service.get_draft, store, contract_id, draft_id, actor.id)


@router.post("/drafts/{draft_id}/edit")
def edit(contract_id: str, draft_id: str, payload: EditLetter, actor: Actor, store=Depends(get_store)):
    return call(service.edit_draft, store, contract_id, draft_id, payload, actor.id)


@router.post("/drafts/{draft_id}/review")
def review(contract_id: str, draft_id: str, payload: RevisionCommand, actor: Actor, store=Depends(get_store)):
    return call(service.review_draft, store, contract_id, draft_id, payload, actor.id)


@router.get("/drafts/{draft_id}/review-pdf")
def preview(contract_id: str, draft_id: str, actor: Actor, store=Depends(get_store)):
    content, sha256 = call(service.review_pdf, store, contract_id, draft_id, actor.id)
    return Response(content, media_type="application/pdf", headers={"Cache-Control": "private, no-store",
        "X-Content-Type-Options": "nosniff", "X-Content-SHA256": sha256})


@router.post("/drafts/{draft_id}/approve")
def approve(contract_id: str, draft_id: str, payload: ApproveLetter, actor: Actor, store=Depends(get_store)):
    return call(service.approve_draft, store, contract_id, draft_id, payload, actor.id)


@router.post("/drafts/{draft_id}/events", status_code=201)
def event(contract_id: str, draft_id: str, payload: ManualEvent, actor: Actor, store=Depends(get_store)):
    return call(service.record_event, store, contract_id, draft_id, payload, actor.id)


@router.get("/drafts/{draft_id}/events")
def events(contract_id: str, draft_id: str, actor: Actor, before: int | None = Query(None, ge=1),
           limit: int = Query(25, ge=1), store=Depends(get_store)):
    return call(service.events, store, contract_id, draft_id, actor.id, before=before, limit=limit)


@router.get("/drafts/{draft_id}/download")
def download(contract_id: str, draft_id: str, actor: Actor, store=Depends(get_store)):
    compiled, captured = call(service.prepare_download, store, contract_id, draft_id, actor.id)
    try:
        service.refresh_scope(captured)
        return PrivateDownloadResponse(compiled, captured, media_type="application/pdf", headers={
            "Cache-Control": "private, no-store", "Content-Disposition": "attachment; filename*=UTF-8''" + quote(compiled.manifest["filename"], safe=""),
            "Content-Length": str(compiled.manifest["size"]), "X-Content-SHA256": compiled.manifest["sha256"], "X-Content-Type-Options": "nosniff"})
    except BaseException:
        compiled.close()
        raise
