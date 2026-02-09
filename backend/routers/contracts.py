from dataclasses import asdict
from datetime import date
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel

from ..domain.lease_engine import ChargeConfig, LeaseEngine, PaymentLine
from ..models import Contract, ContractCreate
from ..routers.portfolios import store
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
def list_contracts() -> list[Contract]:
    return store.list_contracts()


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


@router.delete("/{contract_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_contract(contract_id: str) -> None:
    try:
        store.delete_contract(contract_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


def _build_charge_and_payments(contract: Contract) -> tuple[ChargeConfig, list[PaymentLine]]:
    """Derive ChargeConfig from the unit and collect tenant payment bookings."""
    unit = store.units.get(contract.unit_id)
    if unit is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Einheit zum Vertrag nicht gefunden",
        )
    charge = ChargeConfig(
        cold_rent=Decimal(str(unit.cold_rent or 0)),
        service_charge_advance=Decimal(str(unit.service_charge_advance or 0)),
        heating_advance=Decimal(str(unit.heating_advance or 0)),
    )
    payments = [
        PaymentLine(
            booking_date=booking.booking_date,
            amount=Decimal(str(booking.amount)),
        )
        for booking in store.bookings.values()
        if booking.tenant_id == contract.tenant_id and booking.amount > 0
    ]
    return charge, payments


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
    charge, payments = _build_charge_and_payments(contract)

    dashboard = LeaseEngine.build_dashboard(
        contract_start=contract.start_date,
        contract_end=contract.end_date,
        charge=charge,
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
    charge, payments = _build_charge_and_payments(contract)

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
    )

    return _serialise(asdict(campaign))


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
