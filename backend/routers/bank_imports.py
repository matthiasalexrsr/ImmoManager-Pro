"""Account-scoped reviewed file imports, under existing finance permissions."""
import json
from typing import Annotated

import anyio
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import ValidationError

from ..auth import decode_token, get_user_by_id, require_auth
from ..dependencies import get_store
from ..models import UserRead
from ..permissions import may_write_resource
from ..services.bank_discovery import check_authority, prepare_discovery
from ..services.bank_import import (
    BankConfirm,
    BankImportError,
    commit_import,
    get_import,
    import_receipts,
    list_imports,
    preview_import,
    stage_import,
)
from ..services.bank_import_download import prepare_source_download, source_chunks
from ..services.bank_import_parser import BankMapping
from ..services.portfolio_scope import scope_from_user
from .datev import PrivateDownloadResponse

router = APIRouter(prefix="/bookings/imports", tags=["Bankimport"])


class DiscoveryDownloadResponse(PrivateDownloadResponse):
    async def stream_response(self, send):
        async def checked_send(message):
            if message["type"] == "http.response.body" and message.get("body") and self.before_start is not None:
                # A token/grant can change after a worker read but before ASGI
                # forwards its buffer. Fence that publication boundary too.
                await anyio.to_thread.run_sync(self.before_start)
            await send(message)

        await super().stream_response(checked_send)


def actor(user: Annotated[UserRead, Depends(require_auth)]):
    record = get_user_by_id(user.id)
    if not record or not record["is_active"]:
        raise HTTPException(401, "Benutzerkonto nicht mehr aktiv.")
    return scope_from_user(record)


def writer(scope=Depends(actor)):
    if not may_write_resource(scope.role, "bookings"):
        raise HTTPException(403, "Keine Berechtigung zum Bankimport.")
    return scope


def call(operation, *args, **kwargs):
    try:
        return operation(*args, **kwargs)
    except BankImportError as error:
        return JSONResponse(status_code=error.status, content={"error": {
            "code": error.code, "message": str(error), "details": [error.detail]}})


@router.post("", status_code=201)
def upload(account_id: Annotated[str, Form()], mapping: Annotated[str, Form()],
           file: Annotated[UploadFile, File()], store=Depends(get_store), scope=Depends(writer)):
    try:
        selection = BankMapping.model_validate(json.loads(mapping))
    except (ValueError, TypeError, ValidationError):
        raise HTTPException(422, "Dateiformat-/Spaltenzuordnung ist ungültig.") from None
    try:
        return call(stage_import, store, file.file, account_id, selection,
            filename=file.filename or "bank-file", actor_id=scope.user_id, scope=scope)
    finally:
        file.file.close()


@router.get("")
def listing(account_id: str, cursor: str | None = Query(None, max_length=100),
            page_size: int = Query(25, ge=1), store=Depends(get_store), scope=Depends(actor)):
    return call(list_imports, store, account_id, before=cursor, page_size=page_size, scope=scope)


@router.get("/{import_id}")
def get(import_id: str, store=Depends(get_store), scope=Depends(actor)):
    return call(get_import, store, import_id, scope=scope)


@router.get("/{import_id}/preview")
def preview(import_id: str, cursor: str | None = Query(None, max_length=4096),
            page_size: int = Query(100, ge=1), errors_only: bool = False,
            store=Depends(get_store), scope=Depends(actor)):
    return call(preview_import, store, import_id, cursor=cursor, page_size=page_size, errors_only=errors_only, scope=scope)


@router.post("/{import_id}/confirm")
def confirm(import_id: str, payload: BankConfirm, store=Depends(get_store), scope=Depends(writer)):
    return call(commit_import, store, import_id, payload, scope=scope)


@router.get("/{import_id}/receipts")
def receipts(import_id: str, after: int = Query(0, ge=0), page_size: int = Query(100, ge=1),
             store=Depends(get_store), scope=Depends(actor)):
    return call(import_receipts, store, import_id, after=after, page_size=page_size, scope=scope)


@router.get("/{import_id}/source")
def source(import_id: str, store=Depends(get_store), scope=Depends(actor)):
    plan = call(prepare_source_download, store, import_id, scope=scope)
    if isinstance(plan, JSONResponse):
        return plan
    return StreamingResponse(source_chunks(store, plan, scope=scope), media_type="application/octet-stream", headers=plan.headers)


@router.get("/{import_id}/discovery")
def discovery(import_id: str, request: Request, store=Depends(get_store), scope=Depends(actor)):
    plan = call(prepare_discovery, store, import_id, scope=scope)
    if isinstance(plan, JSONResponse):
        return plan
    bearer = request.headers.get("authorization", "")[7:]

    def publication_guard(*_byte_range):
        token = decode_token(bearer)
        if token.type != "access" or token.sub != scope.user_id:
            raise HTTPException(401, "Authentifizierung nicht mehr gültig.")
        try:
            check_authority(store, plan, scope=scope)
        except BankImportError as error:
            raise HTTPException(error.status, error.detail) from None

    try:
        publication_guard()  # Also covers a change during snapshot construction.
        return DiscoveryDownloadResponse(plan, scope, before_start=publication_guard, before_chunk=publication_guard,
            media_type="application/x-ndjson", headers={
                "Content-Disposition": 'attachment; filename="bank-discovery.jsonl"',
                "Content-Length": str(plan.manifest["size"]), "X-Content-SHA256": plan.manifest["sha256"],
                "X-Bank-Source-SHA256": plan.source.sha256, "X-Bank-Mapping-Hash": plan.mapping_hash,
                "Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"})
    except BaseException:
        plan.close()
        raise
