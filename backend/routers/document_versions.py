"""Authenticated explicit document version publication and completed downloads."""

from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, HTTPException, Query, UploadFile
from pydantic import ValidationError as ModelError
from sqlalchemy.exc import IntegrityError

from ..auth import require_auth
from ..dependencies import get_store
from ..models import UserRead
from ..services import document_versions as service
from ..services.document_version_types import OriginalCommand, RestoreCommand, VersionCommand
from ..storage import NotFoundError, ValidationError
from .datev import PrivateDownloadResponse

router = APIRouter(prefix="/documents", tags=["Dokumentversionen"])
Actor = Annotated[UserRead, Depends(require_auth)]


def call(operation, *args, **kwargs):
    try:
        return operation(*args, **kwargs)
    except NotFoundError:
        raise HTTPException(404, "Dokument oder Zuordnung nicht gefunden.") from None
    except ValidationError as error:
        raise HTTPException(422, str(error)) from None
    except IntegrityError:
        raise HTTPException(409, "Eine andere Dokumentfassung wurde gespeichert. Verlauf neu laden.") from None


@router.get("/{document_id}/versions")
def history(document_id: str, actor: Actor, before: int | None = Query(None, ge=1),
        limit: int = Query(25, ge=1, le=1000), store=Depends(get_store)):
    return call(service.history, store, document_id, actor.id, before=before, limit=limit)


@router.get("/{document_id}/version-source")
def source(document_id: str, actor: Actor, store=Depends(get_store)):
    return call(service.source_preview, store, document_id, actor.id)


@router.post("/{document_id}/versions/archive-original", status_code=201)
def archive(document_id: str, payload: OriginalCommand, actor: Actor, store=Depends(get_store)):
    return call(service.publish, store, document_id, payload, actor.id)


@router.post("/{document_id}/versions", status_code=201)
def upload(document_id: str, file: UploadFile, actor: Actor, command: Annotated[str, Form()], store=Depends(get_store)):
    try:
        try:
            payload = VersionCommand.model_validate_json(command)
        except ModelError:
            raise HTTPException(422, "Ungültiger Versionsauftrag. Vorschau und Bestätigung prüfen.") from None
        return call(service.publish, store, document_id, payload, actor.id,
            source=file.file, upload_name=file.filename)
    finally:
        file.file.close()


@router.post("/{document_id}/versions/restore", status_code=201)
def restore(document_id: str, payload: RestoreCommand, actor: Actor, store=Depends(get_store)):
    return call(service.publish, store, document_id, payload, actor.id, restore=True)


@router.get("/{document_id}/versions/{version_id}/download")
def download(document_id: str, version_id: str, actor: Actor, store=Depends(get_store)):
    compiled, captured = call(service.prepare_download, store, document_id, version_id, actor.id)
    try:
        service.refresh_scope(captured)
        return PrivateDownloadResponse(compiled, captured, media_type="application/octet-stream", headers={
            "Cache-Control": "private, no-store", "Content-Disposition": "attachment; filename*=UTF-8''" + quote(compiled.manifest["filename"], safe=""),
            "Content-Length": str(compiled.manifest["size"]), "X-Content-SHA256": compiled.manifest["sha256"],
            "X-Content-Type-Options": "nosniff"})
    except BaseException:
        compiled.close()
        raise
