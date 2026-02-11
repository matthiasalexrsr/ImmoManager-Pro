"""Tax rate management router (T14: VAT/MwSt.)."""

from fastapi import APIRouter, HTTPException, Query, status

from ..dependencies import store
from ..models import TaxRate, TaxRateCreate, TaxRatePatch
from ..storage import NotFoundError

router = APIRouter(prefix="/tax-rates", tags=["Steuersätze"])


@router.get("", response_model=list[TaxRate])
def list_tax_rates(skip: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=1000)):
    results = store.list_tax_rates()
    return results[skip: skip + limit]


@router.post("", response_model=TaxRate, status_code=status.HTTP_201_CREATED)
def create_tax_rate(payload: TaxRateCreate):
    return store.create_tax_rate(payload)


@router.get("/{tax_rate_id}", response_model=TaxRate)
def get_tax_rate(tax_rate_id: str):
    try:
        return store.get_tax_rate(tax_rate_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.put("/{tax_rate_id}", response_model=TaxRate)
def update_tax_rate(tax_rate_id: str, payload: TaxRateCreate):
    try:
        return store.update_tax_rate(tax_rate_id, payload)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.patch("/{tax_rate_id}", response_model=TaxRate)
def patch_tax_rate(tax_rate_id: str, payload: TaxRatePatch):
    try:
        return store._patch_entity(store.tax_rates, tax_rate_id, payload, "Steuersatz nicht gefunden")
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/{tax_rate_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_tax_rate(tax_rate_id: str):
    try:
        store.delete_tax_rate(tax_rate_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
