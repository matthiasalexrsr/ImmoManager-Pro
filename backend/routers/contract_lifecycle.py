"""Explicit authorized lifecycle commands, separate from legacy contract CRUD."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.exc import IntegrityError

from ..auth import require_auth
from ..dependencies import get_store
from ..models import UserRead
from ..services import contract_lifecycle as service
from ..services.contract_lifecycle_types import Confirmation, DraftCreate, DraftEdit, RevisionCommand
from ..storage import NotFoundError, ValidationError

router = APIRouter(prefix="/contracts/{contract_id}/lifecycle", tags=["Vertragsabläufe"])
Actor = Annotated[UserRead, Depends(require_auth)]


def call(operation, *args, **kwargs):
    try:
        return operation(*args, **kwargs)
    except NotFoundError:
        raise HTTPException(404, "Vertrag nicht gefunden oder nicht zugänglich.") from None
    except ValidationError as error:
        raise HTTPException(409, str(error)) from None
    except IntegrityError:
        raise HTTPException(409, "Vorgangsreferenz oder Vertragsnummer wurde bereits gespeichert. Stand erneut laden.") from None


@router.post("/drafts", status_code=201)
def create(contract_id: str, payload: DraftCreate, actor: Actor, store=Depends(get_store)):
    return call(service.create_draft, store, contract_id, payload, actor.id)


@router.get("/drafts")
def listing(contract_id: str, actor: Actor, before: str | None = Query(None, max_length=512),
            limit: int = Query(25, ge=1, le=1000), store=Depends(get_store)):
    return call(service.list_drafts, store, contract_id, actor.id, before=before, limit=limit)


@router.get("/history")
def history(contract_id: str, actor: Actor, before: str | None = Query(None, max_length=512),
            limit: int = Query(25, ge=1, le=1000), store=Depends(get_store)):
    return call(service.list_drafts, store, contract_id, actor.id, before=before, limit=limit, history=True)


@router.get("/drafts/{draft_id}")
def read(contract_id: str, draft_id: str, actor: Actor, store=Depends(get_store)):
    return call(service.get_draft, store, contract_id, draft_id, actor.id)


@router.post("/drafts/{draft_id}/edit")
def edit(contract_id: str, draft_id: str, payload: DraftEdit, actor: Actor, store=Depends(get_store)):
    return call(service.edit_draft, store, contract_id, draft_id, payload, actor.id)


@router.post("/drafts/{draft_id}/review")
def review(contract_id: str, draft_id: str, payload: RevisionCommand, actor: Actor, store=Depends(get_store)):
    return call(service.review_draft, store, contract_id, draft_id, payload, actor.id)


@router.post("/drafts/{draft_id}/confirm")
def confirm(contract_id: str, draft_id: str, payload: Confirmation, actor: Actor, store=Depends(get_store)):
    return call(service.confirm_draft, store, contract_id, draft_id, payload, actor.id)


@router.post("/drafts/{draft_id}/finalize")
def finalize(contract_id: str, draft_id: str, payload: Confirmation, actor: Actor, store=Depends(get_store)):
    return call(service.finalize_draft, store, contract_id, draft_id, payload, actor.id)
