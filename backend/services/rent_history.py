"""Rent history of contracts: which rent applies when, and applying rent adjustments.

A contract's rent is a list of periods, each valid from a date until the next
one starts. The rent fields of a unit are only the default for new contracts.
"""

from datetime import date
from decimal import Decimal
from typing import Any, Optional

from ..domain.lease_engine import ChargeConfig, RentStep, charge_on
from ..models import ContractRentPeriod, ContractRentPeriodCreate, RentAdjustmentCreate
from ..storage import ValidationError


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


def charge_for(store: Any, contract: Any, day: date) -> Optional[ChargeConfig]:
    return charge_on(rent_steps(store, contract), max(day, contract.start_date))


def overview_rent(contract: Any, periods: list[ContractRentPeriod], day: date | None = None) -> dict | None:
    """Display the stored rent at today, or at the end of a historical contract.

    Missing history stays unknown: a unit's current defaults cannot establish
    what a previous tenant paid. Callers can load every contract's periods once.
    """
    effective_day = max(day or date.today(), contract.start_date)
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


def _period_of(store: Any, adjustment: Any) -> Optional[ContractRentPeriod]:
    return next((p for p in store.list_contract_rent_periods(adjustment.contract_id)
                 if p.rent_adjustment_id == adjustment.id), None)


def apply_rent_adjustment(store: Any, adjustment_id: str) -> tuple[Any, list[str]]:
    """Write the adjustment into the rent history (once) and mark it applied.

    Returns the adjustment and warnings, e.g. when its previous rent differs
    from the rent the history shows for that date.
    """
    adjustment = store.get_rent_adjustment(adjustment_id)
    contract = store.get_contract(adjustment.contract_id)
    warnings: list[str] = []
    if _period_of(store, adjustment) is None:
        if adjustment.status == "rejected":
            raise ValidationError("Eine abgelehnte Mietanpassung kann nicht angewendet werden")
        if adjustment.new_rent is None or adjustment.new_rent <= 0:
            raise ValidationError("Die neue Miete muss größer als 0 sein")
        if adjustment.effective_date.day != 1:
            raise ValidationError("Eine Mietanpassung gilt ab einem Monatsersten")
        if adjustment.effective_date < contract.start_date:
            raise ValidationError("Eine Mietanpassung kann nicht vor Vertragsbeginn gelten")
        start_rent_history(store, contract)
        current = charge_for(store, contract, adjustment.effective_date)
        assert current is not None
        if adjustment.previous_rent and Decimal(str(adjustment.previous_rent)) != current.cold_rent:
            warnings.append(
                f"Bisherige Miete der Anpassung ({adjustment.previous_rent:.2f} €) weicht vom Mietverlauf "
                f"ab ({current.cold_rent:.2f} €)")
        store.create_contract_rent_period(ContractRentPeriodCreate(
            contract_id=contract.id, valid_from=adjustment.effective_date, cold_rent=adjustment.new_rent,
            service_charge_advance=float(current.service_charge_advance),
            heating_advance=float(current.heating_advance),
            source="adjustment", rent_adjustment_id=adjustment.id))
    if adjustment.status != "applied":
        adjustment = _with_status(store, adjustment, "applied")
    return adjustment, warnings


def revert_rent_adjustment(store: Any, adjustment_id: str, status: str = "pending") -> Any:
    """Take the adjustment out of the rent history again."""
    adjustment = store.get_rent_adjustment(adjustment_id)
    period = _period_of(store, adjustment)
    if period is not None:
        store.delete_contract_rent_period(period.id)
    return _with_status(store, adjustment, status) if adjustment.status != status else adjustment


def _with_status(store: Any, adjustment: Any, status: str) -> Any:
    data = RentAdjustmentCreate(**{**adjustment.model_dump(include=set(RentAdjustmentCreate.model_fields)),
                                   "status": status})
    return store.update_rent_adjustment(adjustment.id, data)
