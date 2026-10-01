from datetime import date

from fastapi import APIRouter, HTTPException, Query, status

from ..dependencies import store
from ..models import Invoice, InvoiceCreate, InvoicePatch
from ..services.invoice_list import filtered_invoices
from ..services.payments import (
    FinancialConsistencyError,
    Payment,
    PaymentCreate,
    PaymentReversal,
    PaymentReversalCreate,
)
from ..storage import NotFoundError, ValidationError

router = APIRouter(prefix="/invoices", tags=["Rechnungen"])


@router.get("", response_model=list[Invoice])
def list_invoices(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    supplier: str | None = Query(None),
    status_filter: str | None = Query(None, alias="status"),
    sort_by: str | None = Query(None),
    sort_order: str = Query("asc"),
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
) -> list[Invoice]:
    filters = {"supplier": supplier, "status": status_filter}
    return filtered_invoices(store, skip=skip, limit=limit, filters=filters,
        sort_by=sort_by, descending=sort_order == "desc",
        date_from=date_from if isinstance(date_from, date) else None,
        date_to=date_to if isinstance(date_to, date) else None)


@router.post("", response_model=Invoice, status_code=status.HTTP_201_CREATED)
def create_invoice(payload: InvoiceCreate) -> Invoice:
    try:
        return store.create_invoice(payload)
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/{invoice_id}", response_model=Invoice)
def get_invoice(invoice_id: str) -> Invoice:
    try:
        return store.get_invoice(invoice_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.put("/{invoice_id}", response_model=Invoice)
def update_invoice(invoice_id: str, payload: InvoiceCreate) -> Invoice:
    try:
        return store.update_invoice(invoice_id, payload)
    except FinancialConsistencyError as exc:
        raise HTTPException(409, str(exc)) from exc
    except (NotFoundError, ValidationError) as exc:
        status_code = status.HTTP_404_NOT_FOUND if isinstance(exc, NotFoundError) else status.HTTP_400_BAD_REQUEST
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc


@router.patch("/{invoice_id}", response_model=Invoice)
def patch_invoice(invoice_id: str, payload: InvoicePatch) -> Invoice:
    try:
        return store._patch_entity("invoice", invoice_id, payload)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.delete("/{invoice_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_invoice(invoice_id: str) -> None:
    try:
        store.delete_invoice(invoice_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.get("/{invoice_id}/payments", response_model=list[Payment])
def list_invoice_payments(invoice_id: str):
    try:
        store.get_invoice(invoice_id)
        return store.list_payments("invoice", invoice_id)
    except NotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc


@router.post("/{invoice_id}/payments", response_model=Payment, status_code=201)
def record_invoice_payment(invoice_id: str, payload: PaymentCreate):
    try:
        return store.record_payment("invoice", invoice_id, payload)
    except NotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post("/{invoice_id}/payments/{payment_id}/reversal", response_model=PaymentReversal, status_code=201)
def reverse_invoice_payment(invoice_id: str, payment_id: str, payload: PaymentReversalCreate):
    try:
        return store.reverse_payment("invoice", invoice_id, payment_id, payload)
    except NotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post("/{invoice_id}/match")
def match_invoice_to_bookings(invoice_id: str) -> dict:
    """Direct legacy clients to the reviewed, account-bound payment workflow."""
    try:
        store.get_invoice(invoice_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    raise HTTPException(410, {
        "code": "INVOICE_MATCH_REVIEW_REQUIRED",
        "message": "Eine Bankbuchung unter Buchungen auswählen und Rechnungszuordnung ausdrücklich prüfen.",
        "review_endpoint": "/api/v1/bookings/{booking_id}/suggestions?kind=invoice",
        "confirmation_endpoint": "/api/v1/bookings/{booking_id}/matching",
        "navigation": "/bookings",
    })
