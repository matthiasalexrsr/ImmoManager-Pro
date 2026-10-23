"""Invoice review (Rechnungsprüfung): inbox, receipt, checks, decision, dispute, payment proposals
and the transfer into the utility billing (services.invoice_review).

The existing /invoices API is unchanged; the review lives beside it under
/invoices/{id}/review and /invoice-review. Every handler is a plain function: FastAPI runs it
in a worker thread, never on the event loop.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.exc import IntegrityError

from ..auth import require_auth
from ..dependencies import store
from ..invoice_review_models import (
    CheckRequest,
    CostTransferRequest,
    DecisionRequest,
    DisputeResolution,
    ReceiptPatch,
    ReceiptRequest,
    SettingsUpdate,
)
from ..models import UserRead
from ..services import invoice_review as service
from ..storage import NotFoundError, ValidationError

Actor = Annotated[UserRead, Depends(require_auth)]
router = APIRouter(prefix="/invoice-review", tags=["Rechnungsprüfung"])
invoice_router = APIRouter(prefix="/invoices/{invoice_id}/review", tags=["Rechnungsprüfung"])


def _call(operation, *args, **kwargs) -> Any:
    try:
        return operation(*args, **kwargs)
    except NotFoundError as error:
        raise HTTPException(404, str(error).strip("'\"") or "Nicht gefunden") from None
    except ValidationError as error:
        raise HTTPException(409, str(error)) from None
    except IntegrityError:
        raise HTTPException(409, "Die Rechnung wurde gleichzeitig geändert. Bitte neu laden.") from None


def _reader(actor: UserRead) -> dict:
    return {"id": actor.id, "role": actor.role, "full_name": actor.full_name, "username": actor.username}


# ─── inbox, proposals, settings ──────────────────────────────────────────────

@router.get("/inbox")
def inbox(actor: Actor,
          status_filter: Literal["legacy", "received", "query", "approved", "partially_approved", "rejected",
                                 "pending", "dispute"] | None = Query(None, alias="status"),
          due: Literal["overdue", "week", "month"] | None = Query(None),
          skonto: bool = Query(False), property_id: str | None = Query(None),
          q: str | None = Query(None, max_length=200), skip: int = Query(0, ge=0),
          limit: int = Query(50, ge=1, le=200)) -> dict:
    """Invoices with their review state; filters apply before paging, `total` counts all matches."""
    return _call(service.inbox, store, status=status_filter, due=due, skonto=skonto, property_id=property_id,
                 q=q, skip=skip, limit=limit)


@router.get("/payment-proposals")
def payment_proposals(actor: Actor, until: date | None = Query(None), skip: int = Query(0, ge=0),
                      limit: int = Query(100, ge=1, le=500)) -> dict:
    """Approved invoices with an open amount, by payment deadline (Skonto first). No bank file."""
    return _call(service.payment_proposals, store, until=until, skip=skip, limit=limit)


@router.get("/duplicates")
def duplicates(actor: Actor, supplier: str = Query(..., min_length=1, max_length=300),
               gross_amount: float = Query(...), invoice_date: date = Query(...),
               invoice_number: str | None = Query(None, max_length=100),
               exclude_invoice_id: str | None = Query(None)) -> dict:
    return _call(service.duplicate_check, store, supplier=supplier, invoice_number=invoice_number,
                 gross_amount=gross_amount, invoice_date=invoice_date, exclude_invoice_id=exclude_invoice_id)


@router.get("/settings")
def read_settings(actor: Actor) -> dict:
    return _call(service.read_settings, store)


@router.put("/settings")
def update_settings(payload: SettingsUpdate, actor: Actor) -> dict:
    return _call(service.update_settings, store, payload, actor.id)


@router.post("/receipts", status_code=status.HTTP_201_CREATED)
def new_receipt(payload: ReceiptRequest, actor: Actor) -> dict:
    """Record a new invoice and its receipt together (all or nothing)."""
    return _call(service.start_review, store, None, payload, actor.id)


# ─── one invoice ─────────────────────────────────────────────────────────────

@invoice_router.get("")
def read_review(invoice_id: str, actor: Actor) -> dict:
    return _call(service.review_view, store, invoice_id, _reader(actor))


@invoice_router.post("", status_code=status.HTTP_201_CREATED)
def start_review(invoice_id: str, payload: ReceiptRequest, actor: Actor) -> dict:
    return _call(service.start_review, store, invoice_id, payload, actor.id)


@invoice_router.patch("")
def patch_review(invoice_id: str, payload: ReceiptPatch, actor: Actor) -> dict:
    return _call(service.patch_review, store, invoice_id, payload, actor.id)


@invoice_router.post("/factual-check")
def factual_check(invoice_id: str, payload: CheckRequest, actor: Actor) -> dict:
    return _call(service.factual_check, store, invoice_id, payload, actor.id)


@invoice_router.post("/arithmetic-check")
def arithmetic_check(invoice_id: str, payload: CheckRequest, actor: Actor) -> dict:
    return _call(service.arithmetic_check, store, invoice_id, payload, actor.id)


@invoice_router.post("/decision")
def decide(invoice_id: str, payload: DecisionRequest, actor: Actor) -> dict:
    return _call(service.decide, store, invoice_id, payload, actor.id)


@invoice_router.post("/dispute")
def resolve_dispute(invoice_id: str, payload: DisputeResolution, actor: Actor) -> dict:
    return _call(service.resolve_dispute, store, invoice_id, payload, actor.id)


@invoice_router.post("/cost-transfer", status_code=status.HTTP_201_CREATED)
def transfer_cost(invoice_id: str, payload: CostTransferRequest, actor: Actor) -> dict:
    return _call(service.transfer_cost, store, invoice_id, payload, actor.id)
