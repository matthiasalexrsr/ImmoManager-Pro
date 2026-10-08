from dataclasses import asdict
from datetime import date
from decimal import Decimal
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel

from ..concurrency import one_at_a_time
from ..dependencies import store
from ..domain.lease_engine import LeaseEngine, PaymentLine, RentStep
from ..models import (
    Contract,
    ContractCreate,
    ContractOccupancy,
    ContractOccupancyCreate,
    ContractPatch,
    ContractRentPeriod,
    ContractRentPeriodCreate,
)
from ..services.deletion_guard import ensure_deletable
from ..services.document_versions import ensure_binding_kept
from ..services.payment_allocations import contract_payments
from ..services.read_cache import CachedReads
from ..services.rent_history import charge_for, follow_contract_start, rent_steps, start_rent_history
from ..storage import NotFoundError, ValidationError

router = APIRouter(prefix="/contracts", tags=["Verträge"])


class DunningPolicyRequest(BaseModel):
    level_1_after_days: int = 1
    level_2_after_days: int = 14
    level_3_after_days: int = 30
    fee_level_1: float = 2.50
    fee_level_2: float = 5.00
    fee_level_3: float = 7.50


@router.get("", response_model=list[Contract])
def list_contracts(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    property_id: str | None = Query(None),
    tenant_id: str | None = Query(None),
    status_filter: str | None = Query(None, alias="status"),
    sort_by: str | None = Query(None),
    sort_order: str = Query("asc"),
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
) -> list[Contract]:
    filters = {"property_id": property_id, "tenant_id": tenant_id, "status": status_filter}
    return store._list_paginated(
        entity_type="contract",
        skip=skip,
        limit=limit,
        filters=filters,
        order_by=sort_by,
        order_desc=(sort_order == "desc"),
        range_filters={
            "start_date": (date_from if isinstance(date_from, date) else None, None),
            "end_date": (None, date_to if isinstance(date_to, date) else None),
        },
    )


@router.post("", response_model=Contract, status_code=status.HTTP_201_CREATED)
def create_contract(payload: ContractCreate) -> Contract:
    try:
        contract = store.create_contract(payload)
        start_rent_history(store, contract)
        return contract
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/current-rents")
@one_at_a_time
def current_rents(as_of: Optional[date] = Query(None)) -> dict[str, dict]:
    """The rent each contract owes on a day (today by default), from its rent history."""
    day = as_of or date.today()
    reads = CachedReads(store)      # all rent histories in one query instead of one per contract
    rents = {}
    for contract in reads.list_contracts():
        charge = charge_for(reads, contract, day)
        if charge is not None:
            rents[contract.id] = {"cold_rent": float(charge.cold_rent),
                                  "service_charge_advance": float(charge.service_charge_advance),
                                  "heating_advance": float(charge.heating_advance)}
    return rents


@router.get("/{contract_id}", response_model=Contract)
def get_contract(contract_id: str) -> Contract:
    try:
        return store.get_contract(contract_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.put("/{contract_id}", response_model=Contract)
def update_contract(contract_id: str, payload: ContractCreate) -> Contract:
    try:
        ensure_binding_kept(store, "contract", contract_id, store.get_contract(contract_id), payload.model_dump())
        contract = store.update_contract(contract_id, payload)
        follow_contract_start(store, contract)
        return contract
    except (NotFoundError, ValidationError) as exc:
        status_code = status.HTTP_404_NOT_FOUND if isinstance(exc, NotFoundError) else status.HTTP_400_BAD_REQUEST
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc


@router.patch("/{contract_id}", response_model=Contract)
def patch_contract(contract_id: str, payload: ContractPatch) -> Contract:
    # A patch gets the same checks as a full update (status, dates, unit and
    # property, unique number, no second tenancy of the unit).
    try:
        current = store.get_contract(contract_id)
        merged = ContractCreate.model_validate({
            **current.model_dump(include=set(ContractCreate.model_fields)),
            **payload.model_dump(exclude_unset=True),
        })
        ensure_binding_kept(store, "contract", contract_id, current, merged.model_dump())
        contract = store.update_contract(contract_id, merged)
        follow_contract_start(store, contract)
        return contract
    except (NotFoundError, ValidationError) as exc:
        status_code = status.HTTP_404_NOT_FOUND if isinstance(exc, NotFoundError) else status.HTTP_400_BAD_REQUEST
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc


@router.delete("/{contract_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_contract(contract_id: str) -> None:
    try:
        ensure_deletable(store, "contract", contract_id)
        store.delete_contract(contract_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


def _build_charge_and_payments(contract: Contract) -> tuple[list[RentStep], list[PaymentLine]]:
    """The contract's rent history and the payments credited to it."""
    steps = rent_steps(store, contract)
    payments = contract_payments(store, contract)
    return steps, payments


@router.get("/{contract_id}/settlement")
def get_contract_settlement(
    contract_id: str,
    as_of: Optional[date] = Query(None, description="Reference date (defaults to today)"),
) -> dict:
    """Return a full settlement dashboard for a contract using the LeaseEngine."""
    try:
        contract = store.get_contract(contract_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    today = as_of or date.today()
    steps, payments = _build_charge_and_payments(contract)

    dashboard = LeaseEngine.build_dashboard(
        contract_start=contract.start_date,
        contract_end=contract.end_date,
        rent_steps=steps,
        payments=payments,
        today=today,
    )

    result = asdict(dashboard)
    # Convert Decimal/date values for JSON serialisation
    return _serialise(result)


@router.post("/{contract_id}/dunning-campaign")
def create_dunning_campaign(
    contract_id: str,
    policy: Optional[DunningPolicyRequest] = None,
    as_of: Optional[date] = Query(None, description="Reference date (defaults to today)"),
) -> dict:
    """Generate a dunning campaign for overdue receivables on a contract."""
    from ..domain.dunning_engine import DunningPolicy

    try:
        contract = store.get_contract(contract_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    today = as_of or date.today()
    steps, payments = _build_charge_and_payments(contract)

    dunning_policy = None
    if policy:
        dunning_policy = DunningPolicy(
            level_1_after_days=policy.level_1_after_days,
            level_2_after_days=policy.level_2_after_days,
            level_3_after_days=policy.level_3_after_days,
            fee_level_1=Decimal(str(policy.fee_level_1)),
            fee_level_2=Decimal(str(policy.fee_level_2)),
            fee_level_3=Decimal(str(policy.fee_level_3)),
        )

    campaign = LeaseEngine.build_dunning_campaign(
        contract_start=contract.start_date,
        contract_end=contract.end_date,
        rent_steps=steps,
        payments=payments,
        today=today,
        policy=dunning_policy,
    )

    return _serialise(asdict(campaign))


@router.get("/{contract_id}/rent-periods", response_model=list[ContractRentPeriod])
def list_rent_periods(contract_id: str) -> list[ContractRentPeriod]:
    """The contract's rent history, oldest first."""
    try:
        store.get_contract(contract_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return store.list_contract_rent_periods(contract_id)


@router.post("/{contract_id}/rent-periods", response_model=ContractRentPeriod, status_code=status.HTTP_201_CREATED)
def add_rent_period(contract_id: str, payload: ContractRentPeriodCreate) -> ContractRentPeriod:
    """Record a rent change by hand (adjustments go through /rent-adjustments/{id}/apply)."""
    if payload.contract_id != contract_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Vertrag passt nicht zum Pfad")
    try:
        return store.create_contract_rent_period(payload.model_copy(update={"source": "manual"}))
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/{contract_id}/occupancies", response_model=list[ContractOccupancy])
def list_occupancies(contract_id: str) -> list[ContractOccupancy]:
    """Dated occupants: persons from a date on (before the first entry the contract's persons apply)."""
    try:
        store.get_contract(contract_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return store.list_contract_occupancies(contract_id)


@router.post("/{contract_id}/occupancies", response_model=ContractOccupancy, status_code=status.HTTP_201_CREATED)
def add_occupancy(contract_id: str, payload: ContractOccupancyCreate) -> ContractOccupancy:
    """Record that the household size changes from a date on (birth, move-in, move-out of a person)."""
    if payload.contract_id != contract_id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Vertrag passt nicht zum Pfad")
    try:
        store.get_contract(contract_id)
        return store.create_contract_occupancy(payload)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.delete("/{contract_id}/occupancies/{occupancy_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_occupancy(contract_id: str, occupancy_id: str) -> None:
    try:
        occupancy = store.get_contract_occupancy(occupancy_id)
        if occupancy.contract_id != contract_id:
            raise NotFoundError("Bewohnerstand nicht gefunden")
        store.delete_contract_occupancy(occupancy_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


def _serialise(obj: Any) -> Any:
    """Recursively convert Decimal and date objects for JSON output."""
    if isinstance(obj, dict):
        return {key: _serialise(value) for key, value in obj.items()}
    if isinstance(obj, list):
        return [_serialise(item) for item in obj]
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, date):
        return obj.isoformat()
    return obj
