"""Keep a rent adjustment and its effective rent period in one transaction."""

from decimal import Decimal, InvalidOperation
from math import isfinite
from typing import Any
from uuid import uuid4

from pydantic import ValidationError as ModelError

from ..models import ChangeHistoryEntry, ContractRentPeriod, RentAdjustment, RentAdjustmentCreate
from ..storage import NotFoundError, ValidationError
from .maintenance_rows import Rows
from .notifier import day, eur
from .portfolio_scope import current_scope
from .record_work import record_work

AREA = "/rent-adjustments"
MISSING = "Mietanpassung nicht gefunden"


def _adjustment(rows: Rows, adjustment_id: str) -> Any:
    if not rows.lock("rent_adjustments", adjustment_id):
        raise NotFoundError(MISSING)
    return rows.require("rent_adjustments", adjustment_id, MISSING)


def _contracts(rows: Rows, *identifiers: str) -> None:
    # A contract serializes different adjustments affecting the same rent history.
    for identifier in sorted(set(identifiers)):
        if not rows.lock("contracts", identifier):
            raise ValidationError("Vertrag nicht gefunden")


def _period(rows: Rows, adjustment_id: str) -> Any:
    periods = rows.find("contract_rent_periods", rent_adjustment_id=adjustment_id)
    if len(periods) > 1:
        raise ValidationError("Die Mietanpassung ist mehrfach im Mietverlauf enthalten. Bitte den Mietverlauf prüfen.")
    return periods[0] if periods else None


def _history(rows: Rows, before: Any, after: Any) -> None:
    """The contract timeline retains the rent before and after an explicit correction."""
    scope = current_scope()
    identifiers = {period.contract_id for period in (before, after) if period is not None}

    def description(period: Any, contract_id: str) -> str:
        if period is None or period.contract_id != contract_id:
            return "Nicht angewendet"
        return (f"Ab {day(period.valid_from)}: {eur(period.cold_rent)} Kaltmiete, "
                f"{eur(period.service_charge_advance)} Betriebskosten, {eur(period.heating_advance)} Heizung")

    for contract_id in sorted(identifiers):
        old, new = description(before, contract_id), description(after, contract_id)
        if old != new:
            rows.add("change_history", ChangeHistoryEntry(id=str(uuid4()), entity_type="contract",
                entity_id=contract_id, field_name="rent_adjustment", old_value=old, new_value=new,
                changed_by=scope.user_id if scope else None, reason="Mietanpassung und Mietverlauf gemeinsam geändert"))


def _reconcile(rows: Rows, adjustment: Any) -> list[str]:
    period = _period(rows, adjustment.id)
    if adjustment.status != "applied":
        if period is not None:
            rows.delete("contract_rent_periods", period.id)
            _history(rows, period, None)
        return []
    contract = rows.require("contracts", adjustment.contract_id, "Vertrag nicht gefunden")
    if not isfinite(adjustment.new_rent) or adjustment.new_rent <= 0:
        raise ValidationError("Die neue Miete muss größer als 0 sein")
    if adjustment.effective_date.day != 1:
        raise ValidationError("Eine Mietanpassung gilt ab einem Monatsersten")
    if adjustment.effective_date < contract.start_date:
        raise ValidationError("Eine Mietanpassung kann nicht vor Vertragsbeginn gelten")
    if contract.end_date and adjustment.effective_date > contract.end_date:
        raise ValidationError("Eine Mietanpassung kann nicht nach Vertragsende gelten")

    periods = rows.find("contract_rent_periods", contract_id=contract.id)
    others = [item for item in periods if period is None or item.id != period.id]
    if any(item.valid_from == adjustment.effective_date for item in others):
        raise ValidationError("Für dieses Datum gibt es schon einen Mietstand")
    if not others:
        place = rows.require("units", contract.unit_id, "Einheit nicht gefunden")
        initial = ContractRentPeriod(id=str(uuid4()), contract_id=contract.id,
            valid_from=contract.start_date, source="contract_start", cold_rent=place.cold_rent or 0,
            service_charge_advance=place.service_charge_advance or 0,
            heating_advance=place.heating_advance or 0)
        # Contract start and adjustment may not create two periods on the same day.
        if initial.valid_from == adjustment.effective_date:
            raise ValidationError("Für dieses Datum gibt es schon einen Mietstand")
        rows.add("contract_rent_periods", initial)
        others = [initial]
    applicable = [item for item in others if item.valid_from <= adjustment.effective_date]
    if not applicable:
        raise ValidationError("Für das Wirksamkeitsdatum fehlt der bisherige Mietstand. Bitte den Mietverlauf ergänzen.")
    previous = max(applicable, key=lambda item: (item.valid_from, item.id))
    warnings = []
    if adjustment.previous_rent and Decimal(str(adjustment.previous_rent)) != Decimal(str(previous.cold_rent)):
        warnings.append(f"Bisherige Miete der Anpassung ({adjustment.previous_rent:.2f} €) weicht vom Mietverlauf "
                        f"ab ({previous.cold_rent:.2f} €)")
    values = {"contract_id": contract.id, "valid_from": adjustment.effective_date,
              "cold_rent": adjustment.new_rent, "service_charge_advance": previous.service_charge_advance,
              "heating_advance": previous.heating_advance, "source": "adjustment",
              "rent_adjustment_id": adjustment.id}
    if period is None:
        saved = rows.add("contract_rent_periods", ContractRentPeriod(id=str(uuid4()), **values))
        _history(rows, None, saved)
    elif any(getattr(period, key) != value for key, value in values.items()):
        saved = rows.update("contract_rent_periods", period.id, **values)
        _history(rows, period, saved)
    return warnings


def save_adjustment(store: Any, payload: Any, adjustment_id: str | None = None, *, partial: bool = False) -> Any:
    with record_work(store, AREA) as unit:
        rows = Rows.of(unit)
        before = _adjustment(rows, adjustment_id) if adjustment_id else None
        values = before.model_dump(include=set(RentAdjustmentCreate.model_fields)) if before is not None and partial else {}
        values.update(payload.model_dump(exclude_unset=partial))
        try:
            data = RentAdjustmentCreate.model_validate(values)
        except ModelError as error:
            raise ValidationError("Bitte Vertrag, Wirksamkeitsdatum und Mietbeträge vollständig angeben.") from error
        if data.status not in {"pending", "applied", "rejected"}:
            raise ValidationError("Bitte einen gültigen Status für die Mietanpassung wählen.")
        if not isfinite(data.previous_rent) or not isfinite(data.new_rent):
            raise ValidationError("Bitte gültige Mietbeträge angeben.")
        try:
            percent = ((Decimal(str(data.new_rent)) - Decimal(str(data.previous_rent)))
                       * 100 / Decimal(str(data.previous_rent))).quantize(Decimal("0.0001")) if data.previous_rent > 0 else None
            data = data.model_copy(update={"increase_percent": float(percent) if percent is not None else None})
        except (InvalidOperation, OverflowError) as error:
            raise ValidationError("Die Mietbeträge können nicht berechnet werden. Bitte die Angaben prüfen.") from error
        _contracts(rows, data.contract_id, *([before.contract_id] if before else []))
        if before is None:
            saved = rows.add("rent_adjustments", RentAdjustment(id=str(uuid4()), **data.model_dump()))
        else:
            saved = rows.update("rent_adjustments", before.id, **data.model_dump())
        _reconcile(rows, saved)
        return rows.require("rent_adjustments", saved.id, MISSING)


def apply_adjustment(store: Any, adjustment_id: str) -> tuple[Any, list[str]]:
    with record_work(store, AREA) as unit:
        rows = Rows.of(unit)
        before = _adjustment(rows, adjustment_id)
        _contracts(rows, before.contract_id)
        if before.status == "rejected":
            raise ValidationError("Eine abgelehnte Mietanpassung kann nicht angewendet werden")
        applied = before if before.status == "applied" else rows.update("rent_adjustments", before.id, status="applied")
        return applied, _reconcile(rows, applied)


def revert_adjustment(store: Any, adjustment_id: str, status: str = "pending") -> Any:
    if status not in {"pending", "rejected"}:
        raise ValidationError("Bitte eine Mietanpassung zurücknehmen oder ablehnen.")
    with record_work(store, AREA) as unit:
        rows = Rows.of(unit)
        before = _adjustment(rows, adjustment_id)
        _contracts(rows, before.contract_id)
        saved = before if before.status == status else rows.update("rent_adjustments", before.id, status=status)
        _reconcile(rows, saved)
        return saved


def delete_adjustment(store: Any, adjustment_id: str) -> None:
    with record_work(store, AREA) as unit:
        rows = Rows.of(unit)
        before = _adjustment(rows, adjustment_id)
        _contracts(rows, before.contract_id)
        period = _period(rows, adjustment_id)
        if period is not None:
            rows.delete("contract_rent_periods", period.id)
            _history(rows, period, None)
        rows.delete("rent_adjustments", adjustment_id)
