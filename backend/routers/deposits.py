"""Deposits (Kautionen): the deposit file from agreement to settlement (services/deposits.py),
plus the older plain record endpoints, which refuse to touch a settled file.

All endpoints are synchronous (thread pool): no database work on the event loop.
"""

from datetime import date
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import delete as sql_delete
from sqlalchemy.exc import IntegrityError

from ..auth import require_auth
from ..db.deposit_models import DepositInstalmentORM, DepositInterestRateORM
from ..dependencies import store
from ..models import Deposit, DepositCreate, DepositPatch, UserRead
from ..models_deposits import (
    AgreementRequest,
    FinalizeRequest,
    LegacyTakeoverRequest,
    RatesRequest,
    ReceiptRequest,
    SecurityRequest,
    SettlementContent,
    SettlementCreate,
    TakeoverRequest,
)
from ..services import deposits as service
from ..storage import NotFoundError, ValidationError
from ._helpers import apply_sort

router = APIRouter(prefix="/deposits", tags=["Kautionen"])
Actor = Annotated[UserRead, Depends(require_auth)]
_PRIVATE = {"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"}


def _call(operation, *args, **kwargs):
    try:
        return operation(*args, **kwargs)
    except NotFoundError:
        raise HTTPException(404, "Kaution oder Zuordnung nicht vorhanden.") from None
    except ValidationError as error:
        raise HTTPException(409, str(error)) from None
    except IntegrityError:
        raise HTTPException(409, "Der Bestand wurde gleichzeitig geändert. Bitte den aktuellen Stand neu "
                                 "laden.") from None


# ─── Deposit file ────────────────────────────────────────────────────────────

@router.get("/files")
def deposit_files(actor: Actor, contract_id: str | None = Query(None), stage: str | None = Query(None),
                  q: str | None = Query(None, max_length=200), skip: int = Query(0, ge=0),
                  limit: int = Query(50, ge=1, le=500)):
    """Deposit files with received amount and stage; all counted, one page returned."""
    return _call(service.files, store, actor.id, contract_id=contract_id, stage=stage, query=q, skip=skip,
                 limit=limit)


@router.get("/source")
def deposit_source(actor: Actor, contract_id: str = Query(..., min_length=1)):
    """What a new agreement of the contract starts from (cold rent, cap, instalments, accounts)."""
    return _call(service.source, store, contract_id, actor.id)


@router.get("/legacy-takeover")
def legacy_takeover_candidates(actor: Actor):
    """Plain records of earlier versions (held since a receipt date) that can be taken over as received."""
    return _call(service.legacy_candidates, store, actor.id)


@router.post("/legacy-takeover")
def legacy_takeover(payload: LegacyTakeoverRequest, actor: Actor):
    """Take over the named plain records as received on their receipt date (all or none)."""
    return _call(service.take_over_legacy, store, payload, actor.id)


@router.post("/agreements", status_code=status.HTTP_201_CREATED)
def create_agreement(payload: AgreementRequest, actor: Actor):
    return _call(service.create, store, payload, actor.id)


@router.get("/{deposit_id}/file")
def deposit_file(deposit_id: str, actor: Actor):
    return _call(service.detail, store, deposit_id, actor.id)


@router.put("/{deposit_id}/agreement")
def update_agreement(deposit_id: str, payload: AgreementRequest, actor: Actor):
    return _call(service.update_agreement, store, deposit_id, payload, actor.id)


@router.put("/{deposit_id}/takeover")
def set_takeover(deposit_id: str, payload: TakeoverRequest, actor: Actor):
    """A deposit paid before the app's bookings: received and credited until the takeover day."""
    return _call(service.set_takeover, store, deposit_id, payload, actor.id)


@router.get("/{deposit_id}/payment-candidates")
def payment_candidates(deposit_id: str, actor: Actor):
    return _call(service.payment_candidates, store, deposit_id, actor.id)


@router.post("/{deposit_id}/payments")
def add_receipt(deposit_id: str, payload: ReceiptRequest, actor: Actor):
    return _call(service.add_receipt, store, deposit_id, payload, actor.id)


@router.delete("/{deposit_id}/payments/{payment_id}")
def remove_receipt(deposit_id: str, payment_id: str, actor: Actor):
    return _call(service.remove_receipt, store, deposit_id, payment_id, actor.id)


@router.put("/{deposit_id}/interest-rates")
def set_rates(deposit_id: str, payload: RatesRequest, actor: Actor):
    return _call(service.set_rates, store, deposit_id, payload, actor.id)


@router.put("/{deposit_id}/security")
def set_security(deposit_id: str, payload: SecurityRequest, actor: Actor):
    return _call(service.set_security, store, deposit_id, payload, actor.id)


@router.post("/{deposit_id}/settlements")
def create_settlement(deposit_id: str, payload: SettlementCreate, actor: Actor):
    return _call(service.create_settlement, store, deposit_id, payload, actor.id)


@router.put("/{deposit_id}/settlements/{settlement_id}")
def save_settlement(deposit_id: str, settlement_id: str, payload: SettlementContent, actor: Actor):
    return _call(service.save_settlement, store, deposit_id, settlement_id, payload, actor.id)


@router.delete("/{deposit_id}/settlements/{settlement_id}")
def delete_settlement(deposit_id: str, settlement_id: str, actor: Actor):
    return _call(service.delete_settlement, store, deposit_id, settlement_id, actor.id)


@router.post("/{deposit_id}/settlements/{settlement_id}/preview")
def preview_settlement(deposit_id: str, settlement_id: str, actor: Actor):
    return _call(service.preview, store, deposit_id, settlement_id, actor.id)


@router.post("/{deposit_id}/settlements/{settlement_id}/preview-pdf")
def preview_settlement_pdf(deposit_id: str, settlement_id: str, actor: Actor):
    content, sha256, review_hash = _call(service.preview_pdf, store, deposit_id, settlement_id, actor.id)
    return Response(content, media_type="application/pdf", headers={
        **_PRIVATE, "Content-Disposition": "inline; filename=\"kautionsabrechnung-vorschau.pdf\"",
        "X-Content-SHA256": sha256, "X-Review-Hash": review_hash})


@router.post("/{deposit_id}/settlements/{settlement_id}/finalize")
def finalize_settlement(deposit_id: str, settlement_id: str, payload: FinalizeRequest, actor: Actor):
    return _call(service.finalize, store, deposit_id, settlement_id, payload, actor.id)


@router.get("/{deposit_id}/settlements/{settlement_id}/document")
def settlement_document(deposit_id: str, settlement_id: str, actor: Actor,
                        download: bool = Query(False)):
    content, row = _call(service.read_original, store, deposit_id, settlement_id, actor.id)
    name = f"kautionsabrechnung-{date.today():%Y%m%d}.pdf" if not row.filename else row.filename
    disposition = "attachment" if download else "inline"
    return Response(content, media_type="application/pdf", headers={
        **_PRIVATE, "Content-Disposition": f"{disposition}; filename*=UTF-8''{quote(name)}",
        "X-Content-SHA256": row.sha256})


# ─── Plain records (older endpoints) ─────────────────────────────────────────

@router.get("", response_model=list[Deposit])
def list_deposits(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    contract_id: str | None = Query(None),
    status_filter: str | None = Query(None, alias="status"),
    sort_by: str | None = Query(None),
    sort_order: str = Query("asc"),
) -> list[Deposit]:
    results = store.list_deposits()
    if contract_id:
        results = [r for r in results if r.contract_id == contract_id]
    if status_filter:
        results = [r for r in results if r.status == status_filter]
    results = apply_sort(results, sort_by, sort_order)
    return results[skip : skip + limit]


def _check_amounts(deposit: DepositCreate) -> None:
    """Reject amounts that cannot be right; kept out of the model so existing records stay readable."""
    problem = None
    if deposit.amount <= 0:
        problem = "Der Kautionsbetrag muss größer als 0 sein"
    elif deposit.deductions is not None and deposit.deductions < 0:
        problem = "Abzüge dürfen nicht negativ sein"
    elif deposit.deductions is not None and deposit.deductions > deposit.amount:
        problem = "Abzüge dürfen die Kaution nicht übersteigen; weitergehende Ansprüche sind eine eigene Forderung"
    elif deposit.held_date and deposit.return_date and deposit.return_date < deposit.held_date:
        problem = "Das Rückgabedatum liegt vor dem Eingangsdatum"
    if problem:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=problem)


def _plain_editable(deposit_id: str, changes: dict | None = None) -> None:
    """A settled file stays as it is; a file with payments keeps its contract."""
    service.ensure_plain_record_editable(store, deposit_id)
    if changes and "contract_id" in changes:
        current = store.get_deposit(deposit_id)
        if changes["contract_id"] != current.contract_id and store.list_deposit_payments(deposit_id):
            raise HTTPException(409, "Eine Kaution mit Zahlungen bleibt bei ihrem Vertrag.")


@router.post("", response_model=Deposit, status_code=status.HTTP_201_CREATED)
def create_deposit(payload: DepositCreate) -> Deposit:
    _check_amounts(payload)
    try:
        return store.create_deposit(payload)
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/{deposit_id}", response_model=Deposit)
def get_deposit(deposit_id: str) -> Deposit:
    try:
        return store.get_deposit(deposit_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.put("/{deposit_id}", response_model=Deposit)
def update_deposit(deposit_id: str, payload: DepositCreate) -> Deposit:
    try:
        _plain_editable(deposit_id, {"contract_id": payload.contract_id})
        _check_amounts(payload)
        return store.update_deposit(deposit_id, payload)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.patch("/{deposit_id}", response_model=Deposit)
def patch_deposit(deposit_id: str, payload: DepositPatch) -> Deposit:
    try:
        current = store.get_deposit(deposit_id)
        merged = DepositCreate.model_validate({
            **current.model_dump(include=set(DepositCreate.model_fields)),
            **payload.model_dump(exclude_unset=True),
        })
        _plain_editable(deposit_id, payload.model_dump(exclude_unset=True))
        _check_amounts(merged)
        return store._patch_entity("deposit", deposit_id, payload)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.delete("/{deposit_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_deposit(deposit_id: str) -> None:
    """Delete a deposit without payments or settlements; its instalments and rates go with it."""
    try:
        store.get_deposit(deposit_id)
        if store.list_deposit_payments(deposit_id) or store.list_deposit_settlements(deposit_id):
            raise HTTPException(409, "Die Kaution hat Zahlungen oder eine Abrechnung und bleibt deshalb erhalten.")
        if hasattr(store, "db"):
            for model in (DepositInstalmentORM, DepositInterestRateORM):
                store.db.execute(sql_delete(model).where(model.deposit_id == deposit_id))
        else:
            for name in ("deposit_instalments", "deposit_interest_rates"):
                collection = getattr(store, name)
                for key in [key for key, row in collection.items() if row.deposit_id == deposit_id]:
                    del collection[key]
        store.delete_deposit(deposit_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
