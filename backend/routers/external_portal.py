"""External endpoints have no internal auth dependency and expose no internal store."""
import json
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, Response, UploadFile
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool

from ..auth import require_auth
from ..dependencies import store
from ..external_portal_models import (
    AcceptInvitation,
    ChangeAccess,
    InviteParty,
    PortalLogin,
    PublishDocument,
    ReportDamage,
    SendMessage,
    ShareCase,
)
from ..models import UserRead
from ..services.external_portal import admin, authentication, common, service
from .invoice_review import _call

HEADERS = {"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer"}


def transport(request: Request, response: Response):
    common.check_transport(request, write=request.method not in ("GET", "HEAD"))
    response.headers.update(HEADERS)


def private_headers(response: Response):
    response.headers.update(HEADERS)


public_router = APIRouter(prefix="/portal", tags=["Externes Portal"], dependencies=[Depends(transport)])
router = APIRouter(prefix="/portal-admin", tags=["Portalverwaltung"], dependencies=[Depends(private_headers)])
Actor = Annotated[UserRead, Depends(require_auth)]


def token(request):
    return request.cookies.get(common.COOKIE, "")


def session_response(result):
    session, body = result
    response = JSONResponse(body, headers=HEADERS)
    response.set_cookie(common.COOKIE, session, max_age=8 * 3600, path=common.COOKIE_PATH,
        secure=common.origin().startswith("https://"), httponly=True, samesite="strict")
    return response


@public_router.post("/accept")
def accept(command: AcceptInvitation, request: Request):
    return session_response(_call(authentication.accept, store, command, request.client.host if request.client else "unknown"))


@public_router.post("/login")
def login(command: PortalLogin, request: Request):
    return session_response(_call(authentication.login, store, command, request.client.host if request.client else "unknown"))


@public_router.post("/logout", status_code=204)
def logout(request: Request):
    try:
        _call(authentication.logout, store, token(request))
    except HTTPException as error:
        if error.status_code != 401:
            raise
    response = Response(status_code=204, headers=HEADERS)
    response.delete_cookie(common.COOKIE, path=common.COOKIE_PATH, secure=common.origin().startswith("https://"), httponly=True, samesite="strict")
    return response


@public_router.get("/me")
def me(request: Request):
    return _call(service.me, store, token(request))


@public_router.get("/me/documents")
def documents(request: Request, search: str = Query("", max_length=200), skip: int = Query(0, ge=0), limit: int = Query(25, ge=1, le=100)):
    return _call(service.documents, store, token(request), search=search, skip=skip, limit=limit)


def download(result, *, inline=False):
    content, filename, media_type = result
    safe = inline and media_type in ("application/pdf", "image/jpeg", "image/png", "image/webp")
    return Response(content, media_type=media_type, headers={**HEADERS, "Content-Security-Policy": "sandbox; default-src 'none'",
        "Content-Disposition": ("inline" if safe else "attachment") + "; filename*=UTF-8''" + quote(filename)})


@public_router.get("/me/documents/{identifier}/download")
def document_download(identifier: str, request: Request):
    return download(_call(service.document_file, store, token(request), identifier))


@public_router.get("/me/documents/{identifier}/preview")
def document_preview(identifier: str, request: Request):
    return download(_call(service.document_file, store, token(request), identifier), inline=True)


@public_router.get("/me/cases")
def cases(request: Request, skip: int = Query(0, ge=0), limit: int = Query(25, ge=1, le=100)):
    return _call(service.cases, store, token(request), skip=skip, limit=limit)


@public_router.get("/me/cases/{identifier}")
def case_detail(identifier: str, request: Request, skip: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100)):
    return _call(service.detail, store, token(request), identifier, skip=skip, limit=limit)


async def read_command(command, model, files):
    try:
        parsed = model.model_validate(json.loads(command))
    except (ValidationError, ValueError):
        raise HTTPException(422, "Bitte alle Pflichtangaben vollständig und gültig ausfüllen.") from None
    raw, total = [], 0
    if len(files) > 5:
        raise HTTPException(413, "Höchstens fünf Bilder zulässig.")
    for file in files:
        content = await file.read(8 * 1024 * 1024 + 1)
        total += len(content)
        if len(content) > 8 * 1024 * 1024 or total > 20 * 1024 * 1024:
            raise HTTPException(413, "Höchstens 8 MiB je Bild und 20 MiB zusammen.")
        raw.append((file.filename or "Bild", content))
    return parsed, raw


@public_router.post("/me/cases", status_code=201)
async def report(request: Request, command: Annotated[str, Form(max_length=20000)], files: Annotated[list[UploadFile] | None, File()] = None):
    await run_in_threadpool(_call, service.me, store, token(request))
    parsed, raw = await read_command(command, ReportDamage, files or [])
    return await run_in_threadpool(_call, service.report, store, token(request), parsed, raw)


@public_router.post("/me/cases/{identifier}/messages", status_code=201)
async def reply(identifier: str, request: Request, command: Annotated[str, Form(max_length=20000)], files: Annotated[list[UploadFile] | None, File()] = None):
    await run_in_threadpool(_call, service.detail, store, token(request), identifier)
    parsed, raw = await read_command(command, SendMessage, files or [])
    return await run_in_threadpool(_call, service.reply, store, token(request), identifier, parsed, raw)


@public_router.get("/me/attachments/{identifier}")
def attachment(identifier: str, request: Request):
    return download(_call(service.attachment, store, token(request), identifier), inline=True)


@public_router.get("/me/export")
def own_export(request: Request):
    return download(_call(service.own_export, store, token(request)))


@router.get("/configuration")
def configuration(actor: Actor):
    with common.admin_work(store, actor.id):
        try:
            return {"available": True, "url": common.origin(), "local_test_mode": common.settings.portal_local_test_mode}
        except HTTPException as error:
            return {"available": False, "reason": error.detail}


@router.get("/grants")
def grants(actor: Actor, skip: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100)):
    return _call(admin.listing, store, actor.id, skip=skip, limit=limit)


@router.post("/invitations", status_code=201)
def invite(command: InviteParty, actor: Actor):
    return _call(admin.invite, store, actor.id, command)


@router.put("/grants/{identifier}")
def change_grant(identifier: str, command: ChangeAccess, actor: Actor):
    return _call(admin.change_access, store, actor.id, identifier, command)


@router.put("/grants/{identifier}/identity")
def change_identity(identifier: str, command: ChangeAccess, actor: Actor):
    return _call(admin.change_identity, store, actor.id, identifier, command)


@router.get("/grants/{identifier}/documents")
def eligible_documents(identifier: str, actor: Actor, skip: int = Query(0, ge=0), limit: int = Query(25, ge=1, le=100)):
    return _call(admin.eligible_documents, store, actor.id, identifier, skip=skip, limit=limit)


@router.get("/grants/{identifier}/publications")
def publications(identifier: str, actor: Actor):
    return _call(admin.publications, store, actor.id, identifier)


@router.post("/grants/{identifier}/publications", status_code=201)
def publish(identifier: str, command: PublishDocument, actor: Actor):
    return _call(admin.publish, store, actor.id, identifier, command)


@router.put("/publications/{identifier}")
def change_publication(identifier: str, command: ChangeAccess, actor: Actor):
    return _call(admin.change_publication, store, actor.id, identifier, command)


@router.get("/cases")
def internal_cases(actor: Actor, case_id: str | None = Query(None, max_length=100), skip: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100)):
    return _call(service.internal_cases, store, actor.id, case_id=case_id, skip=skip, limit=limit)


@router.post("/grants/{identifier}/cases", status_code=201)
def share_case(identifier: str, command: ShareCase, actor: Actor):
    return _call(service.share_case, store, actor.id, identifier, command)


@router.put("/cases/{identifier}")
def change_case(identifier: str, command: ChangeAccess, actor: Actor):
    return _call(service.change_case, store, actor.id, identifier, command)


@router.get("/cases/{identifier}")
def internal_detail(identifier: str, actor: Actor, skip: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=100)):
    return _call(service.internal_detail, store, actor.id, identifier, skip=skip, limit=limit)


@router.post("/cases/{identifier}/messages", status_code=201)
def internal_reply(identifier: str, command: SendMessage, actor: Actor):
    return _call(service.internal_reply, store, actor.id, identifier, command)


@router.get("/attachments/{identifier}")
def internal_attachment(identifier: str, actor: Actor):
    return download(_call(service.internal_attachment, store, actor.id, identifier), inline=True)
