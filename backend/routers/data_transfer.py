"""Owner-only migration commands; multipart parsing has explicit byte limits."""
import io
import json
import zipfile
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Query, UploadFile
from fastapi.responses import Response
from pydantic import ValidationError
from starlette.concurrency import run_in_threadpool

from ..auth import require_auth
from ..data_transfer_models import BatchOptions, CommitImport, CreatePortabilityExport, PreviewChange
from ..dependencies import store
from ..models import UserRead
from ..services.data_transfer import csv_templates, exports, imports
from ..services.data_transfer.common import work
from .invoice_review import _call

router = APIRouter(prefix="/data/import-batches", tags=["Datenübernahme"])
exports_router = APIRouter(prefix="/data/portability-exports", tags=["Kundenexport"])
Actor = Annotated[UserRead, Depends(require_auth)]
DOWNLOAD_HEADERS = {"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff", "Content-Security-Policy": "sandbox; default-src 'none'"}


@router.get("/schema")
def schema(actor: Actor):
    with work(store, actor.id):
        return {"version": csv_templates.VERSION, "entities": csv_templates.SCHEMAS}


@router.get("/templates")
def templates(actor: Actor):
    from ..services.data_transfer.instructions import CSV_INSTRUCTIONS
    with work(store, actor.id):
        content = io.BytesIO()
        with zipfile.ZipFile(content, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for entity in csv_templates.SCHEMAS:
                archive.writestr(entity + ".csv", csv_templates.template(entity))
            archive.writestr("Anleitung.md", CSV_INSTRUCTIONS)
        return Response(content.getvalue(), media_type="application/zip",
                        headers={**DOWNLOAD_HEADERS, "Content-Disposition": 'attachment; filename="ImmoManager-CSV-Vorlagen-v1.zip"'})


@router.get("")
def listing(actor: Actor, skip: int = Query(0, ge=0), limit: int = Query(25, ge=1, le=100)):
    return _call(imports.listing, store, actor.id, skip=skip, limit=limit)


@router.post("", status_code=201)
async def create(actor: Actor, files: Annotated[list[UploadFile], File()],
                 options: Annotated[str, Form(max_length=2_000_000)], idempotency_key: Annotated[str, Header()]):
    # Authorize before reading potentially large sources; the service rechecks at commit.
    await run_in_threadpool(_authorize, actor.id)
    if not 1 <= len(files) <= 6:
        raise HTTPException(422, "Bitte eine bis sechs Dateien auswählen.")
    try:
        command = BatchOptions.model_validate(json.loads(options))
    except (ValueError, ValidationError):
        raise HTTPException(422, "Ungültige Importoptionen oder Feldzuordnungen.") from None
    content, total = [], 0
    for file in files:
        parts, size = [], 0
        while block := await file.read(1024 * 1024):
            size += len(block)
            total += len(block)
            if size > imports.MAX_FILE or total > imports.MAX_TOTAL:
                raise HTTPException(413, "Höchstens 64 MiB pro Datei und 128 MiB insgesamt.")
            parts.append(block)
        content.append((file.filename or "", b"".join(parts)))
    return await run_in_threadpool(_call, imports.create, store, actor.id, content, command, idempotency_key)


def _authorize(actor_id):
    with work(store, actor_id):
        pass


@router.get("/{identifier}")
def detail(identifier: str, actor: Actor):
    return _call(imports.detail, store, actor.id, identifier)


@router.post("/{identifier}/preview")
def preview(identifier: str, command: PreviewChange, actor: Actor):
    return _call(imports.repreview, store, actor.id, identifier, command)


@router.post("/{identifier}/commit")
def commit(identifier: str, command: CommitImport, actor: Actor):
    return _call(imports.commit, store, actor.id, identifier, command)


@exports_router.post("", status_code=202)
def create_export(command: CreatePortabilityExport, actor: Actor):
    return _call(exports.create, store, actor.id, command)


@exports_router.get("")
def list_exports(actor: Actor, skip: int = Query(0, ge=0), limit: int = Query(25, ge=1, le=100)):
    return _call(exports.listing, store, actor.id, skip=skip, limit=limit)


@exports_router.get("/{identifier}")
def export_detail(identifier: str, actor: Actor):
    return _call(exports.detail, store, actor.id, identifier)


@exports_router.get("/{identifier}/download")
def export_download(identifier: str, actor: Actor):
    content = _call(exports.download, store, actor.id, identifier)
    return Response(content, media_type="application/zip", headers={**DOWNLOAD_HEADERS,
        "Content-Disposition": 'attachment; filename="ImmoManager-Kundenexport-' + identifier + '.zip"'})
