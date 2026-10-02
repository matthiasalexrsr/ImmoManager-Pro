"""Reviewed local Wohnungsgeberbestätigungen bound to one exact contract."""

from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.exc import IntegrityError

from ..auth import require_auth
from ..dependencies import get_store
from ..models import UserRead
from ..services import housing_confirmation as service
from ..services.housing_confirmation_types import PreviewRequest, SaveRequest
from ..storage import NotFoundError, ValidationError
from .datev import PrivateDownloadResponse

router = APIRouter(
    prefix="/contracts/{contract_id}/housing-confirmations",
    tags=["Wohnungsgeberbestätigung"],
)
Actor = Annotated[UserRead, Depends(require_auth)]


def call(operation, *args, **kwargs):
    try:
        return operation(*args, **kwargs)
    except NotFoundError:
        raise HTTPException(404, "Vertrag oder Bestätigung nicht zugänglich.") from None
    except ValidationError as error:
        raise HTTPException(409, str(error)) from None
    except IntegrityError:
        raise HTTPException(
            409,
            "Bestand oder Vorgangsreferenz wurde parallel geändert. Aktuellen Stand erneut laden.",
        ) from None


@router.get("/source")
def source(contract_id: str, actor: Actor, store=Depends(get_store)):
    return call(service.source, store, contract_id, actor.id)


@router.post("/preview")
def preview(
    contract_id: str,
    payload: PreviewRequest,
    actor: Actor,
    store=Depends(get_store),
):
    return call(service.preview, store, contract_id, payload, actor.id)


@router.post("/preview-pdf")
def preview_pdf(
    contract_id: str,
    payload: PreviewRequest,
    actor: Actor,
    store=Depends(get_store),
):
    content, sha256, review_hash = call(
        service.preview_pdf, store, contract_id, payload, actor.id
    )
    return Response(
        content,
        media_type="application/pdf",
        headers={
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
            "X-Content-SHA256": sha256,
            "X-Review-SHA256": review_hash,
        },
    )


@router.post("", status_code=status.HTTP_201_CREATED)
def publish(
    contract_id: str,
    payload: SaveRequest,
    actor: Actor,
    store=Depends(get_store),
):
    return call(service.publish, store, contract_id, payload, actor.id)


@router.get("")
def listing(
    contract_id: str,
    actor: Actor,
    after: str | None = Query(None, max_length=4096),
    limit: int = Query(25, ge=1, le=500),
    store=Depends(get_store),
):
    return call(
        service.listing,
        store,
        contract_id,
        actor.id,
        after=after,
        limit=limit,
    )


@router.get("/{document_id}/download")
def download(
    contract_id: str,
    document_id: str,
    actor: Actor,
    store=Depends(get_store),
):
    compiled, captured = call(
        service.prepare_download,
        store,
        contract_id,
        document_id,
        actor.id,
    )
    try:
        service.refresh_scope(captured)
        filename = compiled.manifest["filename"]
        return PrivateDownloadResponse(
            compiled,
            captured,
            media_type="application/pdf",
            headers={
                "Cache-Control": "private, no-store",
                "Content-Disposition": (
                    "attachment; filename*=UTF-8''"
                    + quote(filename, safe="")
                ),
                "Content-Length": str(compiled.manifest["size"]),
                "X-Content-SHA256": compiled.manifest["sha256"],
                "X-Content-Type-Options": "nosniff",
            },
        )
    except BaseException:
        compiled.close()
        raise
