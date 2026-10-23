"""Shared work center; private workspace preferences and deferrals have their own router."""

from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query

from ..auth import require_auth
from ..business_qol_models import (
    DuplicateAccept,
    DuplicateCheck,
    NoteCreate,
    ProcessDocument,
    QuickEdit,
    ReviewDocument,
    Undo,
)
from ..dependencies import store
from ..models import UserRead
from ..services import business_documents as documents
from ..services import business_qol as service
from ..storage import NotFoundError, ValidationError

router = APIRouter(prefix="/work-center", tags=["Arbeitsplatz"])
Actor = Annotated[UserRead, Depends(require_auth)]
Deferred = Literal["active", "due", "all"]
DocumentStatus = Literal["pending", "processing", "review", "done", "failed"]


def call(operation, *args, **kwargs):
    try:
        return operation(*args, **kwargs)
    except NotFoundError:
        raise HTTPException(404, "Datensatz nicht vorhanden.") from None
    except ValidationError as error:
        raise HTTPException(422, str(error)) from None


@router.get("/items")
def items(actor: Actor, kind: str | None = None, property_id: str | None = None,
          due_before: date | None = None, deferred: Deferred = "all", cursor: str | None = None,
          limit: int = Query(50, ge=1, le=100)):
    return call(service.list_items, store, actor.id, kind=kind, property_id=property_id, due_before=due_before,
                deferred=deferred, cursor=cursor, limit=limit)


@router.get("/summary")
def summary(actor: Actor, property_id: str | None = None, due_before: date | None = None, deferred: Deferred = "all"):
    return call(service.summary, store, actor.id, property_id=property_id, due_before=due_before, deferred=deferred)


@router.get("/timeline")
def timeline(actor: Actor, entity_type: str, entity_id: str, cursor: str | None = None,
             limit: int = Query(50, ge=1, le=100)):
    return call(service.timeline, store, entity_type, entity_id, actor.id, cursor=cursor, limit=limit)


@router.post("/notes", status_code=201)
def create_note(payload: NoteCreate, actor: Actor):
    return call(service.create_note, store, payload, actor.id)


@router.post("/quick-edits")
def quick_edit(payload: QuickEdit, actor: Actor):
    return call(service.quick_edit, store, payload, actor.id)


@router.post("/quick-edits/{identifier}/undo")
def undo(identifier: str, payload: Undo, actor: Actor):
    return call(service.undo_edit, store, identifier, payload, actor.id)


@router.get("/documents")
def document_queue(actor: Actor, status: DocumentStatus | None = None, cursor: str | None = None,
                   limit: int = Query(50, ge=1, le=100)):
    return call(documents.document_queue, store, actor.id, status=status, cursor=cursor, limit=limit)


@router.get("/documents/{identifier}")
def document_detail(identifier: str, actor: Actor):
    return call(documents.document_detail, store, identifier, actor.id)


@router.post("/documents/{identifier}/process")
def process_document(identifier: str, payload: ProcessDocument, actor: Actor):
    return call(documents.process_document, store, identifier, payload, actor.id)


@router.post("/documents/{identifier}/review")
def review_document(identifier: str, payload: ReviewDocument, actor: Actor):
    return call(documents.review_document, store, identifier, payload, actor.id)


@router.post("/duplicates/check")
def duplicate_check(payload: DuplicateCheck, actor: Actor):
    return call(documents.duplicate_check, store, payload, actor.id)


@router.post("/duplicates/exceptions", status_code=201)
def duplicate_exception(payload: DuplicateAccept, actor: Actor):
    return call(documents.accept_duplicate, store, payload, actor.id)
