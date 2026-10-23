"""Dunning (Mahnwesen): settings, preview and runs, letters, case files, outbox, replies.

All endpoints are synchronous (thread pool): no database work on the event loop.
Writing needs the dunning area (backend/permissions.py: owner, manager, bookkeeping);
finalizing a letter also needs documents, both checked again under the account lock
until the commit. Reads follow the portfolio boundary of the contract.
"""

from datetime import date
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.exc import IntegrityError

from ..auth import require_auth
from ..dependencies import store
from ..models import UserRead
from ..models_dunning import (
    AssignRequest,
    BaseRateRequest,
    BlockRequest,
    CancelLetterRequest,
    DisputeDecision,
    DisputeRequest,
    FinalizeRequest,
    LiftBlockRequest,
    MarkSentRequest,
    NoteRequest,
    ReplyRequest,
    ResultRequest,
    RunRequest,
    RunScope,
    StageSettingsRequest,
)
from ..services import dunning as service
from ..storage import NotFoundError, ValidationError

router = APIRouter(prefix="/dunning", tags=["Mahnwesen"])
Actor = Annotated[UserRead, Depends(require_auth)]
_PRIVATE = {"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"}


def _call(operation, *args, **kwargs):
    try:
        return operation(*args, **kwargs)
    except NotFoundError:
        raise HTTPException(404, "Datensatz nicht vorhanden.") from None
    except ValidationError as error:
        raise HTTPException(409, str(error)) from None
    except IntegrityError:
        raise HTTPException(409, "Der Vorgang wurde gleichzeitig geändert oder wiederholt. "
                                 "Bitte den aktuellen Stand neu laden.") from None


# ─── Settings ────────────────────────────────────────────────────────────────

@router.get("/settings")
def get_settings(actor: Actor):
    return _call(service.settings, store, actor.id)


@router.put("/settings/stages")
def put_stages(payload: StageSettingsRequest, actor: Actor):
    return _call(service.save_stages, store, payload, actor.id)


@router.post("/settings/base-rates", status_code=status.HTTP_201_CREATED)
def add_base_rate(payload: BaseRateRequest, actor: Actor):
    return _call(service.add_base_rate, store, payload, actor.id)


@router.delete("/settings/base-rates/{rate_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_base_rate(rate_id: str, actor: Actor):
    _call(service.delete_base_rate, store, rate_id, actor.id)


# ─── Preview and runs ────────────────────────────────────────────────────────

@router.post("/preview")
def preview(payload: RunScope, actor: Actor):
    """Which claims, stage, fee and interest a run would cover; nothing is stored."""
    return _call(service.preview, store, payload, actor.id)


@router.post("/runs", status_code=status.HTTP_201_CREATED)
def create_run(payload: RunRequest, actor: Actor):
    return _call(service.create_run, store, payload, actor.id)


@router.get("/overview")
def overview(actor: Actor, status_filter: str = Query("open", alias="status"), portfolio_id: str | None = None,
             offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=500), as_of: date | None = None):
    return _call(service.overview, store, actor.id, status=status_filter, portfolio_id=portfolio_id, offset=offset,
                 limit=limit, as_of=as_of)


# ─── Case file of a contract ─────────────────────────────────────────────────

@router.get("/contracts/{contract_id}")
def contract_file(contract_id: str, actor: Actor, as_of: date | None = None):
    return _call(service.contract_file, store, contract_id, actor.id, as_of)


@router.post("/contracts/{contract_id}/blocks", status_code=status.HTTP_201_CREATED)
def add_block(contract_id: str, payload: BlockRequest, actor: Actor):
    return _call(service.add_block, store, contract_id, payload, actor.id)


@router.post("/blocks/{block_id}/lift")
def lift_block(block_id: str, payload: LiftBlockRequest, actor: Actor):
    return _call(service.lift_block, store, block_id, payload, actor.id)


@router.post("/contracts/{contract_id}/disputes", status_code=status.HTTP_201_CREATED)
def add_dispute(contract_id: str, payload: DisputeRequest, actor: Actor):
    return _call(service.add_dispute, store, contract_id, payload, actor.id)


@router.post("/disputes/{dispute_id}/decide")
def decide_dispute(dispute_id: str, payload: DisputeDecision, actor: Actor):
    return _call(service.decide_dispute, store, dispute_id, payload, actor.id)


@router.get("/cases/{case_id}/timeline")
def timeline(case_id: str, actor: Actor, after: str | None = Query(None, max_length=512),
             limit: int = Query(50, ge=1, le=500)):
    return _call(service.timeline, store, case_id, actor.id, after=after, limit=limit)


@router.post("/cases/{case_id}/notes", status_code=status.HTTP_201_CREATED)
def add_note(case_id: str, payload: NoteRequest, actor: Actor):
    return _call(service.add_note, store, case_id, payload, actor.id)


@router.post("/cases/{case_id}/result")
def set_result(case_id: str, payload: ResultRequest, actor: Actor):
    return _call(service.set_result, store, case_id, payload, actor.id)


# ─── Letters ─────────────────────────────────────────────────────────────────

@router.get("/letters/{letter_id}")
def letter(letter_id: str, actor: Actor):
    return _call(service.letter_detail, store, letter_id, actor.id)


@router.get("/letters/{letter_id}/pdf")
def letter_pdf(letter_id: str, actor: Actor, download: bool = False):
    content, name, original = _call(service.letter_pdf, store, letter_id, actor.id)
    disposition = "attachment" if download else "inline"
    return Response(content, media_type="application/pdf", headers={
        **_PRIVATE, "Content-Disposition": f"{disposition}; filename*=UTF-8''" + quote(name, safe=""),
        "X-Archived-Original": "true" if original else "false"})


@router.post("/letters/{letter_id}/refresh")
def refresh_letter(letter_id: str, actor: Actor):
    return _call(service.refresh_letter, store, letter_id, actor.id)


@router.post("/letters/{letter_id}/cancel")
def cancel_letter(letter_id: str, payload: CancelLetterRequest, actor: Actor):
    return _call(service.cancel_letter, store, letter_id, payload, actor.id)


@router.post("/letters/{letter_id}/finalize")
def finalize_letter(letter_id: str, payload: FinalizeRequest, actor: Actor):
    return _call(service.finalize_letter, store, letter_id, payload, actor.id)


# ─── Outbox ──────────────────────────────────────────────────────────────────

@router.get("/outbox")
def outbox(actor: Actor, status_filter: str | None = Query(None, alias="status"), contract_id: str | None = None,
           offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=500)):
    return _call(service.outbox, store, actor.id, status=status_filter, contract_id=contract_id, offset=offset,
                 limit=limit)


@router.post("/outbox/{entry_id}/mark-sent")
def mark_sent(entry_id: str, payload: MarkSentRequest, actor: Actor):
    return _call(service.mark_sent, store, entry_id, payload, actor.id)


@router.get("/outbox/{entry_id}/eml")
def email_draft(entry_id: str, actor: Actor):
    content, name = _call(service.email_draft, store, entry_id, actor.id)
    return Response(content, media_type="message/rfc822", headers={
        **_PRIVATE, "Content-Disposition": "attachment; filename*=UTF-8''" + quote(name, safe="")})


# ─── Replies ─────────────────────────────────────────────────────────────────

@router.get("/replies")
def replies(actor: Actor, status_filter: str | None = Query("review", alias="status"),
            offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=500)):
    return _call(service.replies, store, actor.id, status=status_filter or None, offset=offset, limit=limit)


@router.post("/replies", status_code=status.HTTP_201_CREATED)
def record_reply(payload: ReplyRequest, actor: Actor):
    return _call(service.record_reply, store, payload, actor.id)


@router.post("/replies/{reply_id}/assign")
def assign_reply(reply_id: str, payload: AssignRequest, actor: Actor):
    return _call(service.assign_reply, store, reply_id, payload, actor.id)


@router.post("/replies/{reply_id}/unassign")
def unassign_reply(reply_id: str, actor: Actor):
    return _call(service.unassign_reply, store, reply_id, actor.id)


@router.post("/replies/{reply_id}/dismiss")
def dismiss_reply(reply_id: str, actor: Actor):
    return _call(service.dismiss_reply, store, reply_id, actor.id)
