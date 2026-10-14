"""Rent charges (Sollstellung) router: monthly rent ledger entries."""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError

from ..auth import require_auth
from ..dependencies import store
from ..models import RentCharge, RentChargeCreate, RentChargePatch, UserRead
from ..services import rent_payments
from ..services.jobs.schedule import local_today
from ..storage import NotFoundError, ValidationError
from ._helpers import apply_sort

router = APIRouter(prefix="/rent-charges", tags=["Sollstellung"])


@router.get("/ledger")
def rent_ledger(month: str = Query(pattern=r"^\d{4}-\d{2}$"), as_of: date | None = None,
                property_id: str | None = None) -> dict:
    return rent_payments.monthly_ledger(store, month, as_of or local_today(), property_id)


@router.post("/contract-payment", status_code=status.HTTP_201_CREATED, response_model=None)
def record_contract_payment(payload: rent_payments.ContractPaymentRequest,
                            actor: Annotated[UserRead, Depends(require_auth)]) -> dict | JSONResponse:
    try:
        return rent_payments.record_payment(store, payload, actor.id)
    except rent_payments.PaymentConflict as exc:
        return JSONResponse(status_code=exc.status_code, content={"error": {"code": exc.code, "message": exc.detail,
                                                               "details": exc.details}})
    except NotFoundError as exc:
        raise HTTPException(404, "Vertrag oder Zahlungskonto nicht vorhanden.") from exc
    except IntegrityError as exc:
        raise HTTPException(409, "Der Bestand wurde gleichzeitig geändert. Bitte den Vorgang erneut prüfen.") from exc


@router.get("", response_model=list[RentCharge])
def list_rent_charges(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    sort_by: str | None = Query(None),
    sort_order: str = Query("asc"),
    contract_id: str | None = Query(None),
    month: str | None = Query(None),
    charge_status: str | None = Query(None, alias="status"),
) -> list[RentCharge]:
    results = store.list_rent_charges()
    if isinstance(contract_id, str) and contract_id:
        results = [r for r in results if r.contract_id == contract_id]
    if isinstance(month, str) and month:
        results = [r for r in results if r.month == month]
    if isinstance(charge_status, str) and charge_status:
        results = [r for r in results if r.status == charge_status]
    results = apply_sort(results, sort_by, sort_order)
    return results[skip : skip + limit]


@router.post("", response_model=RentCharge, status_code=status.HTTP_201_CREATED)
def create_rent_charge(payload: RentChargeCreate) -> RentCharge:
    try:
        return store.create_rent_charge(payload)
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/{charge_id}", response_model=RentCharge)
def get_rent_charge(charge_id: str) -> RentCharge:
    try:
        return store.get_rent_charge(charge_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.put("/{charge_id}", response_model=RentCharge)
def update_rent_charge(charge_id: str, payload: RentChargeCreate) -> RentCharge:
    try:
        return store.update_rent_charge(charge_id, payload)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.patch("/{charge_id}", response_model=RentCharge)
def patch_rent_charge(charge_id: str, payload: RentChargePatch) -> RentCharge:
    try:
        return store._patch_entity("rent_charge", charge_id, payload)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.delete("/{charge_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_rent_charge(charge_id: str) -> None:
    try:
        store.delete_rent_charge(charge_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
