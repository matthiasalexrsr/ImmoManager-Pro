"""Project file of a maintenance case: work packages, dependencies, appointments, craftsmen,
quotes → orders → change orders → invoices, protocols and documents (services.maintenance_projects).

Every handler is a plain function: FastAPI runs it in a worker thread, never on the event loop.
"""

from __future__ import annotations

from typing import Annotated, Any
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.exc import IntegrityError

from .. import maintenance_models as mm
from ..auth import require_auth
from ..dependencies import store
from ..models import UserRead
from ..services import maintenance_projects as service
from ..storage import NotFoundError, ValidationError

router = APIRouter(prefix="/maintenance/{case_id}", tags=["Instandhaltung – Projektakte"])
Actor = Annotated[UserRead, Depends(require_auth)]
_PRIVATE = {"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"}


def _call(operation, *args, **kwargs) -> Any:
    try:
        return operation(*args, **kwargs)
    except NotFoundError as error:
        raise HTTPException(404, str(error).strip("'\"") or "Nicht gefunden") from None
    except ValidationError as error:
        raise HTTPException(409, str(error)) from None
    except IntegrityError:
        raise HTTPException(409, "Die Akte wurde gleichzeitig geändert. Bitte neu laden.") from None


def _dump(value: Any) -> Any:
    return value.model_dump(mode="json") if hasattr(value, "model_dump") else value


def _reader(actor: UserRead) -> dict:
    return {"id": actor.id, "role": actor.role, "full_name": actor.full_name, "username": actor.username}


@router.get("/project")
def read_project(case_id: str, actor: Actor) -> dict:
    return _call(service.read_project, store, case_id, _reader(actor))


@router.get("/costs")
def read_costs(case_id: str, actor: Actor) -> dict:
    return _call(service.costs, store, case_id)


@router.post("/transition")
def transition(case_id: str, payload: mm.StatusTransition, actor: Actor) -> dict:
    return _dump(_call(service.transition, store, case_id, payload, actor.id))


# ─── work packages and dependencies ──────────────────────────────────────────

@router.post("/work-packages", status_code=status.HTTP_201_CREATED)
def add_work_package(case_id: str, payload: mm.WorkPackageCreate, actor: Actor) -> dict:
    return _dump(_call(service.add_work_package, store, case_id, payload, actor.id))


@router.patch("/work-packages/{package_id}")
def update_work_package(case_id: str, package_id: str, payload: mm.WorkPackagePatch, actor: Actor) -> dict:
    return _dump(_call(service.update_work_package, store, case_id, package_id, payload, actor.id))


@router.delete("/work-packages/{package_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_work_package(case_id: str, package_id: str, actor: Actor) -> None:
    _call(service.delete_work_package, store, case_id, package_id, actor.id)


@router.post("/dependencies", status_code=status.HTTP_201_CREATED)
def add_dependency(case_id: str, payload: mm.DependencyCreate, actor: Actor) -> dict:
    return _dump(_call(service.add_dependency, store, case_id, payload, actor.id))


@router.delete("/dependencies/{dependency_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_dependency(case_id: str, dependency_id: str, actor: Actor) -> None:
    _call(service.delete_dependency, store, case_id, dependency_id, actor.id)


# ─── craftsmen and appointments ──────────────────────────────────────────────

@router.post("/participants", status_code=status.HTTP_201_CREATED)
def add_participant(case_id: str, payload: mm.ParticipantCreate, actor: Actor) -> dict:
    return _dump(_call(service.add_participant, store, case_id, payload, actor.id))


@router.delete("/participants/{participant_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_participant(case_id: str, participant_id: str, actor: Actor) -> None:
    _call(service.delete_participant, store, case_id, participant_id, actor.id)


@router.post("/appointments", status_code=status.HTTP_201_CREATED)
def add_appointment(case_id: str, payload: mm.AppointmentCreate, actor: Actor) -> dict:
    return _call(service.add_appointment, store, case_id, payload, actor.id)


@router.patch("/appointments/{appointment_id}")
def update_appointment(case_id: str, appointment_id: str, payload: mm.AppointmentPatch, actor: Actor) -> dict:
    return _call(service.update_appointment, store, case_id, appointment_id, payload, actor.id)


@router.delete("/appointments/{appointment_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_appointment(case_id: str, appointment_id: str, actor: Actor) -> None:
    _call(service.delete_appointment, store, case_id, appointment_id, actor.id)


# ─── quotes, orders, change orders ───────────────────────────────────────────

@router.post("/quotes", status_code=status.HTTP_201_CREATED)
def add_quote(case_id: str, payload: mm.QuoteCreate, actor: Actor) -> dict:
    return _dump(_call(service.add_quote, store, case_id, payload, actor.id))


@router.patch("/quotes/{quote_id}")
def update_quote(case_id: str, quote_id: str, payload: mm.QuotePatch, actor: Actor) -> dict:
    return _dump(_call(service.update_quote, store, case_id, quote_id, payload, actor.id))


@router.delete("/quotes/{quote_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_quote(case_id: str, quote_id: str, actor: Actor) -> None:
    _call(service.delete_quote, store, case_id, quote_id, actor.id)


@router.post("/quotes/{quote_id}/accept", status_code=status.HTTP_201_CREATED)
def accept_quote(case_id: str, quote_id: str, payload: mm.QuoteDecision, actor: Actor) -> dict:
    """Award the order: the accepted quote becomes the order, its amounts frozen."""
    return _dump(_call(service.accept_quote, store, case_id, quote_id, payload, actor.id))


@router.post("/quotes/{quote_id}/reject")
def reject_quote(case_id: str, quote_id: str, payload: mm.Decision, actor: Actor) -> dict:
    return _dump(_call(service.reject_quote, store, case_id, quote_id, payload, actor.id))


@router.post("/orders/{order_id}/cancel")
def cancel_order(case_id: str, order_id: str, payload: mm.Decision, actor: Actor) -> dict:
    return _dump(_call(service.cancel_order, store, case_id, order_id, payload, actor.id))


@router.post("/orders/{order_id}/complete")
def complete_order(case_id: str, order_id: str, actor: Actor) -> dict:
    return _dump(_call(service.complete_order, store, case_id, order_id, actor.id))


@router.post("/orders/{order_id}/change-orders", status_code=status.HTTP_201_CREATED)
def add_change_order(case_id: str, order_id: str, payload: mm.ChangeOrderCreate, actor: Actor) -> dict:
    return _dump(_call(service.add_change_order, store, case_id, order_id, payload, actor.id))


@router.patch("/change-orders/{change_id}")
def update_change_order(case_id: str, change_id: str, payload: mm.ChangeOrderPatch, actor: Actor) -> dict:
    return _dump(_call(service.update_change_order, store, case_id, change_id, payload, actor.id))


@router.delete("/change-orders/{change_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_change_order(case_id: str, change_id: str, actor: Actor) -> None:
    _call(service.delete_change_order, store, case_id, change_id, actor.id)


@router.post("/change-orders/{change_id}/approve")
def approve_change_order(case_id: str, change_id: str, payload: mm.Decision, actor: Actor) -> dict:
    return _dump(_call(service.decide_change_order, store, case_id, change_id, payload, actor.id, approve=True))


@router.post("/change-orders/{change_id}/reject")
def reject_change_order(case_id: str, change_id: str, payload: mm.Decision, actor: Actor) -> dict:
    return _dump(_call(service.decide_change_order, store, case_id, change_id, payload, actor.id, approve=False))


# ─── invoices of an order ────────────────────────────────────────────────────

@router.post("/orders/{order_id}/invoices", status_code=status.HTTP_201_CREATED)
def link_invoice(case_id: str, order_id: str, payload: mm.InvoiceLinkCreate, actor: Actor) -> dict:
    """An existing invoice of the case's property, or a new one, billed against the order."""
    return _call(service.link_invoice, store, case_id, order_id, payload, actor.id)


@router.get("/invoice-candidates")
def invoice_candidates(case_id: str, actor: Actor, q: str | None = Query(None, max_length=200),
                       skip: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=200)) -> dict:
    """Invoices of the case's property not yet billed against an order (one page)."""
    return _call(service.invoice_candidates, store, case_id, q=q, skip=skip, limit=limit)


@router.delete("/invoice-links/{link_id}", status_code=status.HTTP_204_NO_CONTENT)
def unlink_invoice(case_id: str, link_id: str, actor: Actor) -> None:
    _call(service.unlink_invoice, store, case_id, link_id, actor.id)


# ─── protocols ───────────────────────────────────────────────────────────────

@router.post("/protocols", status_code=status.HTTP_201_CREATED)
def add_protocol(case_id: str, payload: mm.ProtocolCreate, actor: Actor) -> dict:
    return _dump(_call(service.add_protocol, store, case_id, payload, actor.id))


@router.patch("/protocols/{protocol_id}")
def update_protocol(case_id: str, protocol_id: str, payload: mm.ProtocolPatch, actor: Actor) -> dict:
    return _dump(_call(service.update_protocol, store, case_id, protocol_id, payload, actor.id))


@router.delete("/protocols/{protocol_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_protocol(case_id: str, protocol_id: str, actor: Actor) -> None:
    _call(service.delete_protocol, store, case_id, protocol_id, actor.id)


@router.post("/protocols/{protocol_id}/finalize")
def finalize_protocol(case_id: str, protocol_id: str, payload: mm.ProtocolFinalize, actor: Actor) -> dict:
    """Render, archive as immutable original and close the protocol, in one transaction."""
    return _call(service.finalize_protocol, store, case_id, protocol_id, payload, actor.id)


@router.get("/protocols/{protocol_id}/pdf")
def protocol_pdf(case_id: str, protocol_id: str, actor: Actor) -> Response:
    """A draft as preview (nothing stored); a final protocol as its verified archived original."""
    content = _call(service.protocol_preview_pdf, store, case_id, protocol_id, _reader(actor))
    return Response(content, media_type="application/pdf", headers={
        **_PRIVATE, "Content-Disposition": "inline; filename*=UTF-8''" + quote(f"protokoll-{protocol_id}.pdf")})


# ─── documents ───────────────────────────────────────────────────────────────

@router.post("/documents", status_code=status.HTTP_201_CREATED)
def link_document(case_id: str, payload: mm.CaseDocumentCreate, actor: Actor) -> dict:
    return _call(service.link_document, store, case_id, payload, actor.id)


@router.delete("/documents/{link_id}", status_code=status.HTTP_204_NO_CONTENT)
def unlink_document(case_id: str, link_id: str, actor: Actor) -> None:
    _call(service.unlink_document, store, case_id, link_id, actor.id)


# ─── payments of an invoice (the bookings that pay it) ───────────────────────

payments_router = APIRouter(prefix="/invoices/{invoice_id}/payments", tags=["Rechnungen"])


@payments_router.get("")
def list_invoice_payments(invoice_id: str, actor: Actor) -> dict:
    return _call(service.invoice_payments, store, invoice_id)


@payments_router.get("/candidates")
def payment_candidates(invoice_id: str, actor: Actor, q: str | None = Query(None, max_length=200),
                       skip: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=200),
                       all_properties: bool = Query(False)) -> dict:
    """Outgoing bookings that could pay the invoice, newest first, with their free amount (one page)."""
    return _call(service.payment_candidates, store, invoice_id, q=q, skip=skip, limit=limit,
                 all_properties=all_properties)


@payments_router.post("", status_code=status.HTTP_201_CREATED)
def add_invoice_payment(invoice_id: str, payload: mm.InvoicePaymentCreate, actor: Actor) -> dict:
    return _dump(_call(service.add_invoice_payment, store, invoice_id, payload, actor.id))


@payments_router.delete("/{payment_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_invoice_payment(invoice_id: str, payment_id: str, actor: Actor) -> None:
    _call(service.delete_invoice_payment, store, invoice_id, payment_id, actor.id)
