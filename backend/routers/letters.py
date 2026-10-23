"""Letters: the shared letterhead, letter templates and letters to a contract's tenant."""

from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Response, UploadFile, status
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from ..auth import require_auth
from ..dependencies import store
from ..models import UserRead
from ..services import contract_letters, letter_templates, letterhead, price_index
from ..services.contract_letter_types import ComposeRequest, LetterPreview, LetterPublish
from ..storage import NotFoundError

Actor = Annotated[UserRead, Depends(require_auth)]
_PRIVATE = {"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"}

letterhead_router = APIRouter(prefix="/letterhead", tags=["Briefkopf"])
templates_router = APIRouter(prefix="/letter-templates", tags=["Briefvorlagen"])
contract_router = APIRouter(prefix="/contracts/{contract_id}/letters", tags=["Briefe"])


def _call(operation, *args, **kwargs):
    try:
        return operation(*args, **kwargs)
    except NotFoundError:
        raise HTTPException(404, "Nicht gefunden.") from None
    except IntegrityError:
        raise HTTPException(409, "Gleichzeitig geändert. Bitte den aktuellen Stand neu laden.") from None
    except SQLAlchemyError:
        raise HTTPException(503, "Speicherung nicht bestätigt. Bitte denselben Vorgang erneut versuchen.") from None


def _pdf(content: bytes, filename: str, **headers: str) -> Response:
    return Response(content, media_type="application/pdf",
                    headers={**_PRIVATE, **headers, "Content-Disposition": f'inline; filename="{filename}"'})


# ─── Briefkopf ───────────────────────────────────────────────────────────────

@letterhead_router.get("")
def letterhead_view(actor: Actor, response: Response, property_id: str | None = Query(None, max_length=120)):
    response.headers.update(_PRIVATE)
    return _call(letterhead.view, store, actor.id, property_id)


@letterhead_router.get("/logo")
def letterhead_logo(actor: Actor, scope: str = Query("global", max_length=160)):
    content = _call(letterhead.logo_png, store, actor.id, scope)
    return Response(content, media_type="image/png", headers=_PRIVATE)


@letterhead_router.post("/logo")
def letterhead_logo_put(actor: Actor, file: UploadFile = File(...), scope: str = Form("global", max_length=160),
                        base_revision: int = Form(...), idempotency_key: str = Form(..., max_length=120)):
    raw = file.file.read(letterhead.MAX_UPLOAD_BYTES + 1)
    return _call(letterhead.put_logo, store, actor.id, scope, raw, file.filename, base_revision, idempotency_key)


@letterhead_router.delete("/logo")
def letterhead_logo_delete(actor: Actor, base_revision: int = Query(...), idempotency_key: str = Query(..., max_length=120),
                           scope: str = Query("global", max_length=160)):
    return _call(letterhead.delete_logo, store, actor.id, scope, base_revision, idempotency_key)


@letterhead_router.get("/sample-pdf")
def letterhead_sample(actor: Actor, property_id: str | None = Query(None, max_length=120)):
    return _pdf(_call(letterhead.sample_pdf, store, actor.id, property_id), "musterbrief.pdf")


# ─── Briefvorlagen ───────────────────────────────────────────────────────────

@templates_router.get("")
def templates_listing(actor: Actor, archived: bool = False):
    return _call(letter_templates.listing, store, actor.id, archived=archived)


@templates_router.post("", status_code=status.HTTP_201_CREATED)
def templates_create(payload: dict[str, Any], actor: Actor):
    if "id" in payload:
        raise HTTPException(422, "Eine neue Vorlage hat noch keine Kennung.")
    return _call(letter_templates.save, store, actor.id, payload)


@templates_router.get("/price-index")
def price_index_view(actor: Actor, response: Response):
    """The consumer price index series kept for index rents (entered by hand, never fetched)."""
    response.headers.update(_PRIVATE)
    return _call(price_index.view, store, actor.id)


@templates_router.put("/price-index")       # before /{template_id}, which would take the path
def price_index_save(payload: dict[str, Any], actor: Actor):
    return _call(price_index.save, store, actor.id, payload)


@templates_router.put("/{template_id}")
def templates_update(template_id: str, payload: dict[str, Any], actor: Actor):
    return _call(letter_templates.save, store, actor.id, {**payload, "id": template_id})


# ─── Briefe eines Vertrags ───────────────────────────────────────────────────

@contract_router.get("/context")
def letter_context(contract_id: str, actor: Actor, response: Response):
    response.headers.update(_PRIVATE)
    return _call(contract_letters.context, store, contract_id, actor.id)


@contract_router.post("/compose")
def letter_compose(contract_id: str, payload: ComposeRequest, actor: Actor, response: Response):
    response.headers.update(_PRIVATE)
    return _call(contract_letters.compose, store, contract_id, payload, actor.id)


@contract_router.post("/preview")
def letter_preview(contract_id: str, payload: LetterPreview, actor: Actor, response: Response):
    response.headers.update(_PRIVATE)
    return _call(contract_letters.preview, store, contract_id, payload, actor.id)


@contract_router.post("/preview-pdf")
def letter_preview_pdf(contract_id: str, payload: LetterPreview, actor: Actor):
    raw, checksum, review_hash = _call(contract_letters.preview_pdf, store, contract_id, payload, actor.id)
    return _pdf(raw, "brief-vorschau.pdf", **{"X-Content-SHA256": checksum, "X-Review-SHA256": review_hash})


@contract_router.post("", status_code=status.HTTP_201_CREATED)
def letter_publish(contract_id: str, payload: LetterPublish, actor: Actor, response: Response):
    response.headers.update(_PRIVATE)
    return _call(contract_letters.publish, store, contract_id, payload, actor.id)
