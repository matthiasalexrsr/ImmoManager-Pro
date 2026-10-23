"""Rent history of contracts: which rent applies when, and applying rent adjustments.

A contract's rent is a list of periods, each valid from a date until the next
one starts. The rent fields of a unit are only the default for new contracts.
"""

from datetime import date
from decimal import Decimal
from typing import Any, Optional

from ..domain.clock import local_today
from ..domain.lease_engine import ChargeConfig, RentStep, charge_on
from ..models import ContractRentPeriod, ContractRentPeriodCreate


def _charge(cold_rent: Any, service_charge_advance: Any, heating_advance: Any) -> ChargeConfig:
    return ChargeConfig(
        cold_rent=Decimal(str(cold_rent or 0)),
        service_charge_advance=Decimal(str(service_charge_advance or 0)),
        heating_advance=Decimal(str(heating_advance or 0)),
    )


def _unit_defaults(store: Any, contract: Any) -> dict:
    try:
        unit = store.get_unit(contract.unit_id)
    except Exception:
        return {"cold_rent": 0.0, "service_charge_advance": 0.0, "heating_advance": 0.0}
    return {
        "cold_rent": unit.cold_rent or 0.0,
        "service_charge_advance": unit.service_charge_advance or 0.0,
        "heating_advance": unit.heating_advance or 0.0,
    }


def rent_steps(store: Any, contract: Any) -> list[RentStep]:
    """The contract's rent history; without stored periods the unit's rent from the start."""
    periods = store.list_contract_rent_periods(contract.id)
    if periods:
        return [RentStep(p.valid_from, _charge(p.cold_rent, p.service_charge_advance, p.heating_advance))
                for p in periods]
    return [RentStep(contract.start_date, _charge(**_unit_defaults(store, contract)))]


# adjustment types whose rent change is no comparative increase (§ 558 Abs. 1 Satz 3 BGB)
CHANGE_KINDS = {"modernization": "559", "operating_costs": "560"}


def rent_change_kinds(store: Any, contract: Any) -> list[Optional[str]]:
    """Per step of rent_steps: "559"/"560" when an applied modernization or operating-cost adjustment
    set it, else None (a § 558 increase, an index or stepped rent, an agreement or the start)."""
    periods = store.list_contract_rent_periods(contract.id)
    if not periods:
        return [None]
    types = {a.id: a.adjustment_type for a in store.list_rent_adjustments() if a.contract_id == contract.id}
    return [CHANGE_KINDS.get(types.get(p.rent_adjustment_id or "", "")) if p.source == "adjustment" else None
            for p in periods]


def charge_for(store: Any, contract: Any, day: date) -> Optional[ChargeConfig]:
    return charge_on(rent_steps(store, contract), max(day, contract.start_date))


def overview_rent(contract: Any, periods: list[ContractRentPeriod], day: date | None = None) -> dict | None:
    """Display the stored rent at today, or at the end of a historical contract.

    Missing history stays unknown: a unit's current defaults cannot establish
    what a previous tenant paid. Callers can load every contract's periods once.
    """
    effective_day = max(day or local_today(), contract.start_date)
    if contract.end_date:
        effective_day = min(effective_day, contract.end_date)
    applicable = [period for period in periods if period.valid_from <= effective_day]
    if not applicable:
        return None
    period = max(applicable, key=lambda value: (value.valid_from, value.id))
    return {
        "cold_rent": period.cold_rent,
        "service_charge": period.service_charge_advance,
        "heating_charge": period.heating_advance,
        "valid_from": period.valid_from,
    }


def start_rent_history(store: Any, contract: Any) -> None:
    """Give a new contract its first rent period, taken from its unit."""
    if store.list_contract_rent_periods(contract.id):
        return
    store.create_contract_rent_period(ContractRentPeriodCreate(
        contract_id=contract.id, valid_from=contract.start_date, source="contract_start",
        **_unit_defaults(store, contract)))


def follow_contract_start(store: Any, contract: Any) -> None:
    """Keep the first period at the contract start when the start date changes."""
    periods = store.list_contract_rent_periods(contract.id)
    if not periods:
        return start_rent_history(store, contract)
    first = periods[0]
    if first.valid_from != contract.start_date and all(p.valid_from > contract.start_date for p in periods[1:]):
        store.update_contract_rent_period(first.id, ContractRentPeriodCreate(**{
            **first.model_dump(include=set(ContractRentPeriodCreate.model_fields)),
            "valid_from": contract.start_date}))


def apply_rent_adjustment(store: Any, adjustment_id: str) -> tuple[Any, list[str]]:
    """Apply once, including the status and rent period in the same transaction."""
    from .rent_adjustments import apply_adjustment
    return apply_adjustment(store, adjustment_id)


def revert_rent_adjustment(store: Any, adjustment_id: str, status: str = "pending") -> Any:
    """Take the adjustment out of the rent history in the same transaction."""
    from .rent_adjustments import revert_adjustment
    return revert_adjustment(store, adjustment_id, status)
