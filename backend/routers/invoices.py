from dataclasses import asdict
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, HTTPException, Query, status

from ..dependencies import store
from ..domain.invoice_matching import BookingCandidate, InvoiceMatcher, InvoiceToMatch
from ..models import Invoice, InvoiceCreate, InvoicePatch
from ..storage import NotFoundError, ValidationError
from ._helpers import apply_sort

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
    results = store.list_invoices()
    if supplier:
        results = [i for i in results if i.supplier == supplier]
    if status_filter:
        results = [i for i in results if i.status == status_filter]
    if isinstance(date_from, date):
        results = [
            r for r in results
            if getattr(r, 'invoice_date', None)
            and r.invoice_date >= date_from
        ]
    if isinstance(date_to, date):
        results = [
            r for r in results
            if getattr(r, 'invoice_date', None)
            and r.invoice_date <= date_to
        ]
    results = apply_sort(results, sort_by, sort_order)
    return results[skip : skip + limit]


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
    except (NotFoundError, ValidationError) as exc:
        status_code = status.HTTP_404_NOT_FOUND if isinstance(exc, NotFoundError) else status.HTTP_400_BAD_REQUEST
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc


@router.patch("/{invoice_id}", response_model=Invoice)
def patch_invoice(invoice_id: str, payload: InvoicePatch) -> Invoice:
    try:
        return store._patch_entity(None, invoice_id, payload, "Rechnung nicht gefunden")
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.delete("/{invoice_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_invoice(invoice_id: str) -> None:
    try:
        store.delete_invoice(invoice_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/{invoice_id}/match")
def match_invoice_to_bookings(invoice_id: str) -> dict:
    """Match an invoice to open bookings using FIFO allocation."""
    try:
        invoice = store.get_invoice(invoice_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    invoice_to_match = InvoiceToMatch(
        invoice_id=invoice.id,
        gross_amount=Decimal(str(invoice.gross_amount)),
        invoice_date=invoice.invoice_date,
    )

    candidates = [
        BookingCandidate(
            booking_id=booking.id,
            open_amount=Decimal(str(abs(booking.amount))),
            booking_date=booking.booking_date,
        )
        for booking in store.list_bookings()
        if booking.amount < 0 and booking.status == "open"
    ]

    result = InvoiceMatcher.allocate_fifo(invoice_to_match, candidates)

    raw = asdict(result)
    return {
        key: (
            float(value) if isinstance(value, Decimal)
            else [
                {k: (float(v) if isinstance(v, Decimal) else v) for k, v in item.items()}
                for item in value
            ] if isinstance(value, list) else value
        )
        for key, value in raw.items()
    }
