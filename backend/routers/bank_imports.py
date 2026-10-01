"""Account-scoped reviewed file imports, under existing finance permissions."""
import json
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from ..auth import get_user_by_id, require_auth
from ..dependencies import get_store
from ..models import UserRead
from ..permissions import may_write_resource
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
from ..services.bank_import_parser import BankMapping
from ..services.portfolio_scope import scope_from_user

router = APIRouter(prefix="/bookings/imports", tags=["Bankimport"])


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
