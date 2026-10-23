"""Re-letting projects (Neuvermietung): offer, exposé, applicants, viewings, takeover, deletion.

The work happens in services/reletting.py. Endpoints are synchronous (thread pool) except the
upload, which only reads the request body on the event loop and hands everything else to the
thread pool: no database or file work on the event loop.
"""

import logging
import uuid
from io import BytesIO
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile, status
from sqlalchemy.exc import IntegrityError
from starlette.concurrency import run_in_threadpool

from ..auth import require_auth
from ..dependencies import store
from ..models import UserRead
from ..models_reletting import (
    AcceptRequest,
    ApplicantInput,
    CloseRequest,
    PurgeRequest,
    RejectRequest,
    RelettingStart,
    RelettingUpdate,
    ViewingInput,
)
from ..services import reletting as service
from ..services.file_storage import get_file_storage
from ..services.upload_policy import DOCUMENT_EXTENSIONS, IMAGE_EXTENSIONS, read_limited, require_allowed_extension
from ..storage import NotFoundError, ValidationError

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/reletting", tags=["Neuvermietung"])
Actor = Annotated[UserRead, Depends(require_auth)]
_PRIVATE = {"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"}


def _call(operation, *args, **kwargs):
    try:
        return operation(*args, **kwargs)
    except NotFoundError:
        raise HTTPException(404, "Projekt, Bewerber oder Einheit nicht vorhanden.") from None
    except ValidationError as error:
        raise HTTPException(409, str(error)) from None
    except IntegrityError:
        raise HTTPException(409, "Der Stand wurde gleichzeitig geändert. Bitte neu laden.") from None


def remove_files(urls: list[str]) -> None:
    """Delete stored files of removed attachments; a file already gone is fine."""
    from .files import _file_url_to_key

    storage = get_file_storage()
    for url in urls:
        try:
            key = _file_url_to_key(url)
            if key:
                storage.delete(key)
        except Exception:  # noqa: BLE001 - the record is gone; a leftover file is logged, not fatal
            logger.warning("Bewerberunterlage %s konnte nicht gelöscht werden", url, exc_info=True)


@router.get("")
def overview(actor: Actor) -> dict:
    return _call(service.overview, store, actor.id)


@router.post("", status_code=status.HTTP_201_CREATED)
def start(payload: RelettingStart, actor: Actor) -> dict:
    return _call(service.start, store, payload, actor.id)


@router.get("/{project_id}")
def detail(project_id: str, actor: Actor) -> dict:
    return _call(service.detail, store, project_id, actor.id)


@router.put("/{project_id}")
def update(project_id: str, payload: RelettingUpdate, actor: Actor) -> dict:
    return _call(service.update, store, project_id, payload, actor.id)


@router.post("/{project_id}/close")
def close(project_id: str, payload: CloseRequest, actor: Actor) -> dict:
    return _call(service.close, store, project_id, payload, actor.id)


@router.post("/{project_id}/cancel")
def cancel(project_id: str, actor: Actor) -> dict:
    return _call(service.cancel, store, project_id, actor.id)


@router.post("/{project_id}/applicants", status_code=status.HTTP_201_CREATED)
def add_applicant(project_id: str, payload: ApplicantInput, actor: Actor) -> dict:
    return _call(service.add_applicant, store, project_id, payload, actor.id)


@router.put("/{project_id}/applicants/{lead_id}")
def update_applicant(project_id: str, lead_id: str, payload: ApplicantInput, actor: Actor) -> dict:
    return _call(service.update_applicant, store, project_id, lead_id, payload, actor.id)


@router.post("/{project_id}/reject")
def reject(project_id: str, payload: RejectRequest, actor: Actor) -> dict:
    return _call(service.reject, store, project_id, payload, actor.id)


@router.post("/{project_id}/viewings", status_code=status.HTTP_201_CREATED)
def add_viewing(project_id: str, payload: ViewingInput, actor: Actor) -> dict:
    return _call(service.add_viewing, store, project_id, payload, actor.id)


@router.put("/{project_id}/viewings/{viewing_id}")
def update_viewing(project_id: str, viewing_id: str, payload: ViewingInput, actor: Actor) -> dict:
    return _call(service.update_viewing, store, project_id, viewing_id, payload, actor.id)


@router.post("/{project_id}/accept")
def accept(project_id: str, payload: AcceptRequest, actor: Actor) -> dict:
    return _call(service.accept, store, project_id, payload, actor.id)


@router.post("/{project_id}/purge")
def purge(project_id: str, payload: PurgeRequest, actor: Actor) -> dict:
    result, files = _call(service.purge, store, project_id, payload, actor.id)
    remove_files(files)
    return result


def _store_attachment(project_id: str, lead_id: str, actor_id: str, contents: bytes, ext: str,
                      content_type: str | None, title: str) -> dict:
    service.attachment_target(store, project_id, lead_id, actor_id)
    storage = get_file_storage()
    key = f"applicants/{lead_id}/{uuid.uuid4().hex}.{ext}"
    storage.save(key, BytesIO(contents), content_type=content_type or "application/octet-stream")
    url = storage.get_url(key)
    try:
        return _call(service.add_attachment, store, project_id, lead_id,
                     kind="photo" if ext in IMAGE_EXTENSIONS else "document", title=title, file_url=url,
                     size=len(contents), actor_id=actor_id)
    except BaseException:
        remove_files([url])
        raise


@router.post("/{project_id}/applicants/{lead_id}/attachments", status_code=status.HTTP_201_CREATED)
async def upload_attachment(project_id: str, lead_id: str, actor: Actor, file: UploadFile = File(...),
                            title: str = Form("")) -> dict:
    ext = require_allowed_extension(file.filename, DOCUMENT_EXTENSIONS)
    contents = await read_limited(file)
    name = (title or file.filename or "Unterlage").strip()
    return await run_in_threadpool(_store_attachment, project_id, lead_id, actor.id, contents, ext,
                                   file.content_type, name)


@router.delete("/{project_id}/attachments/{attachment_id}")
def delete_attachment(project_id: str, attachment_id: str, actor: Actor) -> dict:
    result, url = _call(service.remove_attachment, store, project_id, attachment_id, actor.id)
    remove_files([url])
    return result


@router.get("/{project_id}/portal-text")
def portal_text(project_id: str, actor: Actor) -> dict:
    return _call(service.portal_text, store, project_id, actor.id)


@router.get("/{project_id}/expose")
def expose(project_id: str, actor: Actor) -> Response:
    content, name = _call(service.expose, store, project_id, actor.id)
    return Response(content, media_type="application/pdf", headers={
        **_PRIVATE, "Content-Disposition": f"inline; filename*=UTF-8''{quote(name)}"})


@router.post("/{project_id}/listing")
def link_listing(project_id: str, actor: Actor) -> dict:
    return _call(service.link_listing, store, project_id, actor.id)


@router.get("/{project_id}/ai-question")
def ai_question(project_id: str, actor: Actor) -> dict:
    return _call(service.ai_question, store, project_id, actor.id)
