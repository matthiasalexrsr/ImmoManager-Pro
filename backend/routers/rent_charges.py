"""Rent charges (Sollstellung) router: monthly rent ledger entries."""

from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status

from ..dependencies import store
from ..models import RentCharge, RentChargeCreate, RentChargePatch
from ..services.payments import (
    FinancialConsistencyError,
    Payment,
    PaymentCreate,
    PaymentReversal,
    PaymentReversalCreate,
)
from ..services.rent_batch import BatchCreate, BatchError, create_batch
from ..services.rent_ledger import (
    RentGenerationRequest,
    generate_rent_charges,
    generation_requires_batch,
    list_open_items,
    preview_generation,
)
from ..storage import NotFoundError, ValidationError
from ._helpers import apply_sort
from .rent_batches import writer

router = APIRouter(prefix="/rent-charges", tags=["Sollstellung"])


@router.get("/open-items", response_model=None)
def open_rental_items() -> dict:
    return list_open_items(store)


@router.post("/preview", response_model=None)
def preview_rent_generation(payload: RentGenerationRequest, identity=Depends(writer)) -> dict:
    try:
        if generation_requires_batch(store, payload):
            return _delegate(payload, identity)
        return preview_generation(store, payload)
    except (ValidationError, NotFoundError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/generate", response_model=None)
def generate_monthly_rent(payload: RentGenerationRequest, identity=Depends(writer)) -> dict:
    try:
        if generation_requires_batch(store, payload):
            return _delegate(payload, identity)
        return generate_rent_charges(store, payload)
    except (ValidationError, NotFoundError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


def _delegate(payload, identity):
    try:
        request = BatchCreate(start_month=payload.start_month, end_month=payload.end_month,
            contract_ids=payload.contract_ids, idempotency_key=payload.idempotency_key or str(uuid4()))
        return {"policy": "durable_batch", "batch": create_batch(store, request, **identity),
            "created_count": 0, "requires_confirmation": True}
    except BatchError as exc:
        raise HTTPException(exc.status, exc.detail) from exc


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
    except FinancialConsistencyError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.patch("/{charge_id}", response_model=RentCharge)
def patch_rent_charge(charge_id: str, payload: RentChargePatch) -> RentCharge:
    try:
        return store._patch_entity("rent_charge", charge_id, payload)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except FinancialConsistencyError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.delete("/{charge_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_rent_charge(charge_id: str) -> None:
    try:
        store.delete_rent_charge(charge_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.get("/{charge_id}/payments", response_model=list[Payment])
def list_charge_payments(charge_id: str) -> list[Payment]:
    store.get_rent_charge(charge_id)
    return store.list_payments("rent_charge", charge_id)


@router.post("/{charge_id}/payments", response_model=Payment, status_code=201)
def record_charge_payment(charge_id: str, payload: PaymentCreate) -> Payment:
    try:
        return store.record_payment("rent_charge", charge_id, payload)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/{charge_id}/payments/{payment_id}/reversal", response_model=PaymentReversal, status_code=201)
def reverse_charge_payment(charge_id: str, payment_id: str, payload: PaymentReversalCreate) -> PaymentReversal:
    try:
        return store.reverse_payment("rent_charge", charge_id, payment_id, payload)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
