from dataclasses import asdict
from datetime import date
from decimal import Decimal
from typing import Optional, cast

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel

from ..dependencies import store
from ..domain.lease_engine import ChargeConfig, LeaseEngine
from ..models import Contract, ContractCreate, ContractPatch
from ..services.rent_ledger import contract_ledger_inputs, ungenerated_contract_preview
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
    has_date_filter = isinstance(date_from, date) or isinstance(date_to, date)
    results = store._list_paginated(
        entity_type="contract",
        skip=0 if has_date_filter else skip,
        limit=10000 if has_date_filter else limit,
        filters=filters,
        order_by=sort_by,
        order_desc=(sort_order == "desc"),
    )
    if isinstance(date_from, date):
        results = [
            r for r in results
            if getattr(r, 'start_date', None)
            and r.start_date >= date_from
        ]
    if isinstance(date_to, date):
        results = [
            r for r in results
            if getattr(r, 'end_date', None)
            and r.end_date <= date_to
        ]
    if has_date_filter:
        results = results[skip : skip + limit]
    return results


@router.post("", response_model=Contract, status_code=status.HTTP_201_CREATED)
def create_contract(payload: ContractCreate) -> Contract:
    try:
        return store.create_contract(payload)
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/{contract_id}", response_model=Contract)
def get_contract(contract_id: str) -> Contract:
    try:
        return store.get_contract(contract_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.put("/{contract_id}", response_model=Contract)
def update_contract(contract_id: str, payload: ContractCreate) -> Contract:
    try:
        return store.update_contract(contract_id, payload)
    except (NotFoundError, ValidationError) as exc:
        status_code = status.HTTP_404_NOT_FOUND if isinstance(exc, NotFoundError) else status.HTTP_400_BAD_REQUEST
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc


@router.patch("/{contract_id}", response_model=Contract)
def patch_contract(contract_id: str, payload: ContractPatch) -> Contract:
    try:
        return store._patch_entity("contract", contract_id, payload)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.delete("/{contract_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_contract(contract_id: str) -> None:
    try:
        store.delete_contract(contract_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


def _contract_charge(contract: Contract) -> ChargeConfig:
    """Obligations/payments come from the persisted contract ledger below."""
    try:
        unit = store.get_unit(contract.unit_id)
    except (NotFoundError, KeyError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Einheit zum Vertrag nicht gefunden",
        )
    charge = ChargeConfig(
        cold_rent=Decimal(str(unit.cold_rent or 0)),
        service_charge_advance=Decimal(str(unit.service_charge_advance or 0)),
        heating_advance=Decimal(str(unit.heating_advance or 0)),
    )
    return charge


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
    charge = _contract_charge(contract)
    charge_lines, payments = contract_ledger_inputs(store, contract, today)

    dashboard = LeaseEngine.build_dashboard(
        contract_start=contract.start_date,
        contract_end=contract.end_date,
        charge=charge,
        payments=payments,
        today=today,
        charge_lines=charge_lines,
    )

    result = asdict(dashboard)
    result["source"] = "booked_rent_charges"
    result["ungenerated_preview"] = ungenerated_contract_preview(store, contract, today)
    # Current credit is separate from the historical as_of rental balance.
    from ..services.credit_ledger import summary
    from ..services.tenant_privacy import _read_snapshot
    with _read_snapshot(store) as snapshot:
        result["credit_snapshot"] = {"reference": "current_snapshot",
                                    **summary(snapshot, contract_id, locked=True)}
    # Convert Decimal/date values for JSON serialisation
    return cast(dict, _serialise(result))


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
    charge = _contract_charge(contract)
    charge_lines, payments = contract_ledger_inputs(store, contract, today)

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
        charge=charge,
        payments=payments,
        today=today,
        policy=dunning_policy,
        charge_lines=charge_lines,
    )

    return cast(dict, _serialise(asdict(campaign)))


def _serialise(obj: object) -> object:
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
