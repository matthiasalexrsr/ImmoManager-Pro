"""Reviewed privacy decisions, subject requests and restore reconciliation."""
import json
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response

from ..auth import require_auth
from ..dependencies import store
from ..models import UserRead
from ..privacy_models import (
    CompleteRestoreReview,
    ControlChange,
    DecideRequest,
    ImportJournal,
    OpenRequest,
    ResourceKind,
)
from ..services.privacy import controls, journal, requests
from .invoice_review import _call

router = APIRouter(prefix="/privacy", tags=["Datenschutz"])
Actor = Annotated[UserRead, Depends(require_auth)]


def download(value, filename):
    return Response(json.dumps(value, ensure_ascii=False, indent=2).encode(), media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}.json"', "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff", "Content-Security-Policy": "sandbox; default-src 'none'"})


@router.get("/resources/{kind}/{identifier}")
def resource(kind: ResourceKind, identifier: str, actor: Actor):
    return _call(controls.detail, store, actor.id, kind, identifier)


@router.post("/resources/{kind}/{identifier}")
def change(kind: ResourceKind, identifier: str, command: ControlChange, actor: Actor):
    return _call(controls.change, store, actor.id, kind, identifier, command)


@router.get("/journal")
def export(actor: Actor):
    return download(_call(journal.export, store, actor.id), "Datenschutzjournal")


@router.post("/journal/import")
def import_journal(command: ImportJournal, actor: Actor):
    return _call(journal.merge, store, actor.id, command)


@router.get("/restore-review")
def restore_status(actor: Actor):
    return _call(journal.status, store, actor.id)


@router.post("/restore-review")
def restore_complete(command: CompleteRestoreReview, actor: Actor):
    return _call(journal.complete, store, actor.id, command)


@router.get("/decisions")
def decisions(actor: Actor, skip: int = Query(0, ge=0), limit: int = Query(25, ge=1, le=100)):
    return _call(journal.decisions, store, actor.id, skip=skip, limit=limit)


@router.get("/requests")
def request_list(actor: Actor, skip: int = Query(0, ge=0), limit: int = Query(25, ge=1, le=100)):
    return _call(requests.listing, store, actor.id, skip=skip, limit=limit)


@router.post("/requests", status_code=201)
def request_create(command: OpenRequest, actor: Actor):
    return _call(requests.create, store, actor.id, command)


@router.get("/requests/{identifier}")
def request_detail(identifier: str, actor: Actor):
    return _call(requests.detail, store, actor.id, identifier)


@router.get("/requests/{identifier}/export")
def request_export(identifier: str, actor: Actor):
    return download(_call(requests.detail, store, actor.id, identifier), "Datenauskunft")


@router.post("/requests/{identifier}/decision")
def request_decide(identifier: str, command: DecideRequest, actor: Actor):
    return _call(requests.decide, store, actor.id, identifier, command)
