from fastapi import APIRouter, HTTPException, status

from ..models import Invoice, InvoiceCreate
from ..routers.portfolios import store
from ..storage import NotFoundError, ValidationError

router = APIRouter(prefix="/invoices", tags=["Rechnungen"])


@router.get("", response_model=list[Invoice])
def list_invoices() -> list[Invoice]:
    return store.list_invoices()


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


@router.delete("/{invoice_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_invoice(invoice_id: str) -> None:
    try:
        store.delete_invoice(invoice_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
