"""Internal structured intake API. All reads and writes use current source rights."""
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, Header, Query, UploadFile
from fastapi.responses import Response
from starlette.concurrency import run_in_threadpool

from ..auth import require_auth
from ..dependencies import store
from ..e_invoice_models import AcceptIntake, RetryValidation
from ..models import UserRead
from ..services.e_invoice import service
from ..services.upload_policy import read_limited
from .invoice_review import _call

router = APIRouter(prefix="/e-invoice-intakes", tags=["E-Rechnungseingang"])
Actor = Annotated[UserRead, Depends(require_auth)]


@router.get("")
def listing(actor: Actor, skip: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100)):
    return _call(service.listing, store, actor.id, skip=skip, limit=limit)


@router.post("", status_code=201)
async def upload(actor: Actor, property_id: Annotated[str, Form(min_length=1)],
                 file: Annotated[UploadFile, File()], idempotency_key: Annotated[str, Header()]):
    content = await read_limited(file)
    return await run_in_threadpool(_call, service.create, store, actor.id, property_id, content,
                                   file.filename or "", idempotency_key)


@router.get("/{identifier}")
def detail(identifier: str, actor: Actor):
    return _call(service.detail, store, actor.id, identifier)


@router.post("/{identifier}/validate")
def retry(identifier: str, command: RetryValidation, actor: Actor):
    return _call(service.retry, store, actor.id, identifier, command)


@router.post("/{identifier}/accept")
def accept(identifier: str, command: AcceptIntake, actor: Actor):
    return _call(service.accept, store, actor.id, identifier, command)


def _download(actor, identifier, kind, number=None):
    content, name, media_type = _call(service.download, store, actor.id, identifier, kind, number)
    return Response(content, media_type=media_type, headers={"Content-Disposition": "attachment; filename*=UTF-8''" + quote(name),
        "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff", "Content-Security-Policy": "sandbox; default-src 'none'"})


@router.get("/{identifier}/original")
def original(identifier: str, actor: Actor):
    return _download(actor, identifier, "original")


@router.get("/{identifier}/xml")
def xml(identifier: str, actor: Actor):
    return _download(actor, identifier, "xml")


@router.get("/{identifier}/validations/{number}/report")
def report(identifier: str, number: int, actor: Actor):
    return _download(actor, identifier, "report", number)
