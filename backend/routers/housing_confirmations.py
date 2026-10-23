"""Wohnungsgeberbestätigungen of one contract: source, preview, publication, list, original."""

from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.exc import IntegrityError

from ..auth import require_auth
from ..dependencies import store
from ..models import UserRead
from ..services import housing_confirmation as service
from ..services.housing_confirmation_types import PreviewRequest, SaveRequest
from ..storage import NotFoundError, ValidationError

router = APIRouter(prefix="/contracts/{contract_id}/housing-confirmations", tags=["Wohnungsgeberbestätigung"])
Actor = Annotated[UserRead, Depends(require_auth)]
_PRIVATE = {"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"}


def _call(operation, *args, **kwargs):
    try:
        return operation(*args, **kwargs)
    except NotFoundError:
        raise HTTPException(404, "Vertrag oder Bestätigung nicht vorhanden.") from None
    except ValidationError as error:
        raise HTTPException(409, str(error)) from None
    except IntegrityError:
        raise HTTPException(409, "Bestand oder Vorgangsreferenz wurde gleichzeitig geändert. "
                                 "Bitte den aktuellen Stand neu laden.") from None


@router.get("/source")
def source(contract_id: str, actor: Actor):
    return _call(service.source, store, contract_id, actor.id)


@router.post("/preview")
def preview(contract_id: str, payload: PreviewRequest, actor: Actor):
    return _call(service.preview, store, contract_id, payload, actor.id)


@router.post("/preview-pdf")
def preview_pdf(contract_id: str, payload: PreviewRequest, actor: Actor):
    content, sha256, review_hash = _call(service.preview_pdf, store, contract_id, payload, actor.id)
    return Response(content, media_type="application/pdf",
                    headers={**_PRIVATE, "X-Content-SHA256": sha256, "X-Review-SHA256": review_hash})


@router.post("", status_code=status.HTTP_201_CREATED)
def publish(contract_id: str, payload: SaveRequest, actor: Actor):
    return _call(service.publish, store, contract_id, payload, actor.id)


@router.get("")
def listing(contract_id: str, actor: Actor, after: str | None = Query(None, max_length=4096),
            limit: int = Query(25, ge=1, le=500)):
    return _call(service.listing, store, contract_id, actor.id, after=after, limit=limit)


@router.get("/{document_id}/download")
def download(contract_id: str, document_id: str, actor: Actor):
    content, row = _call(service.read_original, store, contract_id, document_id, actor.id)
    return Response(content, media_type="application/pdf", headers={
        **_PRIVATE,
        "Content-Disposition": "attachment; filename*=UTF-8''" + quote(row.filename, safe=""),
        "X-Content-SHA256": row.sha256,
    })
