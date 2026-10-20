from dataclasses import asdict
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, HTTPException, Query, status

from ..dependencies import store
from ..domain.invoice_matching import BookingCandidate, InvoiceMatcher, InvoiceToMatch
from ..domain.money import money
from ..models import Invoice, InvoiceCreate, InvoicePatch
from ..services.deletion_guard import ensure_deletable
from ..services.invoice_review import ensure_invoice_change_allowed, ensure_invoice_deletable
from ..services.maintenance_projects import ensure_invoice_unbound
from ..services.portfolio_scope import scope_context
from ..storage import NotFoundError, ValidationError

router = APIRouter(prefix="/invoices", tags=["Rechnungen"])


@router.get("/overview")
def invoice_overview(skip: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=1000)) -> list[dict]:
    """Complete invoice facts with evidence-based payment balances, one page.

    The legacy collection keeps its existing response contract.
    """
    from ..services.invoice_overview import overview

    return overview(store, store._list_paginated(entity_type="invoice", skip=skip, limit=limit,
                                                order_by="id"))


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
    return store._list_paginated(
        entity_type="invoice",
        skip=skip,
        limit=limit,
        filters=filters,
        order_by=sort_by,
        order_desc=(sort_order == "desc"),
        range_filters={"invoice_date": (
            date_from if isinstance(date_from, date) else None,
            date_to if isinstance(date_to, date) else None,
        )},
    )


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
        ensure_invoice_change_allowed(store, invoice_id, payload.model_dump())   # a decided review fixes the facts
        return store.update_invoice(invoice_id, payload)
    except (NotFoundError, ValidationError) as exc:
        status_code = status.HTTP_404_NOT_FOUND if isinstance(exc, NotFoundError) else status.HTTP_400_BAD_REQUEST
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc


@router.patch("/{invoice_id}", response_model=Invoice)
def patch_invoice(invoice_id: str, payload: InvoicePatch) -> Invoice:
    try:
        changes = payload.model_dump(exclude_unset=True)
        if {"performance_start", "performance_end"} & changes.keys():
            current = store.get_invoice(invoice_id)
            start = changes.get("performance_start", current.performance_start)
            end = changes.get("performance_end", current.performance_end)
            if bool(start) != bool(end) or (start and end < start):
                raise HTTPException(422, "Leistungsbeginn und Leistungsende gemeinsam und in richtiger Reihenfolge angeben.")
        ensure_invoice_change_allowed(store, invoice_id, payload.model_dump(exclude_unset=True))
        return store._patch_entity("invoice", invoice_id, payload)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.delete("/{invoice_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_invoice(invoice_id: str) -> None:
    try:
        store.get_invoice(invoice_id)
        ensure_invoice_unbound(store, invoice_id)        # billed against an order or paid by bookings
        with scope_context(None):   # a credit note of another portfolio counts too
            ensure_invoice_deletable(store, invoice_id)  # the review history stays as evidence
        with scope_context(None):   # references from other portfolios count too (the database refuses them)
            ensure_deletable(store, "invoice", invoice_id)
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

    from ..services.booking_payment_capacity import booking_payment_capacity
    from ..services.invoice_review import settlements
    from ..services.maintenance_rows import Rows
    from ..services.service_contracts import _is_tenant_money

    rows = Rows.reading(store)
    balance = settlements(rows, [invoice], date.today())[invoice.id]
    remaining = (max(money(invoice.gross_amount) - balance.paid, Decimal("0"))
                 if balance.payable is None else balance.open)
    if invoice.status == "cancelled" or balance.payment_status in ("rejected", "credit_note"):
        raise HTTPException(409, "Für eine stornierte/abgelehnte Rechnung oder Gutschrift gibt es keinen Zahlungsvorschlag.")
    invoice_to_match = InvoiceToMatch(
        invoice_id=invoice.id,
        gross_amount=remaining,
        invoice_date=invoice.invoice_date,
    )

    bookings = store.list_bookings()
    capacity = booking_payment_capacity(rows, [b.id for b in bookings])
    used = {p.booking_id for p in rows.find("invoice_payments", invoice_id=invoice_id)}
    candidates = []
    for booking in bookings:
        if booking.amount >= 0 or booking.status != "open" or booking.reverses_booking_id or booking.id in used:
            continue
        if _is_tenant_money(store, booking):
            continue
        if invoice.property_id and booking.property_id not in (None, invoice.property_id):
            continue
        open_amount = max(capacity.available.get(booking.id, Decimal("0")), Decimal("0"))
        if open_amount > 0:
            candidates.append(BookingCandidate(booking_id=booking.id, open_amount=open_amount,
                                               booking_date=booking.booking_date))

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
