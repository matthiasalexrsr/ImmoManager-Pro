"""Explicit, dimensional consumption weights; no medium inference or interpolation."""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Iterable

from ..models import (
    AllocationKey,
    BillingPeriod,
    BillingPreflightIssue,
    Contract,
    Meter,
    StandaloneMeterReading,
)


@dataclass
class ConsumptionBasis:
    weights: dict[str, dict[str, Decimal]] = field(default_factory=dict)
    blockers: list[BillingPreflightIssue] = field(default_factory=list)

    def block(self, code: str, message: str, *references: str) -> None:
        self.blockers.append(BillingPreflightIssue(
            code=code, message=message, severity="blocker", context=", ".join(references),
        ))


def _meter_delta(
    result: ConsumptionBasis, period: BillingPeriod, key: AllocationKey,
    meter: Meter, readings: list[StandaloneMeterReading],
) -> Decimal | None:
    references = (key.id, meter.unit_id, meter.id)
    if not meter.measurement_unit:
        result.block("MISSING_METER_UNIT", "Am Zähler die tatsächliche Maßeinheit ergänzen.", *references)
        return None
    if meter.measurement_unit != key.consumption_unit:
        result.block("CONSUMPTION_UNIT_MISMATCH",
            "Zähler und Verbrauchsschlüssel verwenden unterschiedliche Maßeinheiten. "
            "Originalangaben prüfen; ohne bestätigte Umrechnung werden Werte nicht addiert.", *references)
        return None
    if meter.installation_date and meter.installation_date > period.start_date:
        result.block("CONSUMPTION_METER_CHANGE_BASIS_MISSING",
            "Unterjähriger Zählereinbau benötigt eine datierte Wechsel- und Teilperiodengrundlage. "
            "Abrechnung anhand der Originalbelege aufteilen oder einen fachlich bestätigten Schlüssel verwenden.", *references)
        return None

    values: dict[date, Decimal] = {}
    for reading in readings:
        try:
            value = Decimal(str(reading.value))
            if not value.is_finite() or value < 0:
                raise InvalidOperation
        except (InvalidOperation, ValueError):
            result.block("INVALID_CONSUMPTION_READING", "Ungültigen Ablesewert anhand des Originals korrigieren.",
                *references, reading.id)
            return None
        if reading.reading_date in values and values[reading.reading_date] != value:
            result.block("AMBIGUOUS_CONSUMPTION_READING",
                "Widersprüchliche Ablesewerte am selben Tag anhand der Originalbelege klären.", *references)
            return None
        values[reading.reading_date] = value
    if len(values) < 2 or period.start_date not in values or period.end_date not in values:
        result.block("MISSING_CONSUMPTION_BOUNDARY",
            "Für diesen Zähler fehlen eindeutige Grenzablesungen am Beginn und Ende der Abrechnungsperiode. "
            "Originalablesungen ergänzen oder eine ausdrücklich geprüfte andere Verteilungsgrundlage wählen.", *references)
        return None
    ordered = sorted(values.items())
    if any(after[1] < before[1] for before, after in zip(ordered, ordered[1:])):
        result.block("CONSUMPTION_READING_DECREASE",
            "Fallende Zählerstände benötigen eine nachvollziehbare Korrektur, Überlauf- oder Wechselgrundlage.", *references)
        return None
    return values[period.end_date] - values[period.start_date]


def consumption_basis(
    period: BillingPeriod, keys: Iterable[AllocationKey], contracts: Iterable[Contract],
    meters: Iterable[Meter], readings: Iterable[StandaloneMeterReading],
    nonzero_cost_key_ids: set[str],
) -> ConsumptionBasis:
    """Return complete per-key weights or explicit blockers, never a partial total."""
    result = ConsumptionBasis()
    selected = sorted((key for key in keys if key.key_type == "consumption"), key=lambda key: key.id)
    if not selected:
        return result
    contracts_by_unit: dict[str, list[Contract]] = defaultdict(list)
    for contract in contracts:
        contracts_by_unit[contract.unit_id].append(contract)
    meters_by_medium_unit: dict[tuple[str, str], list[Meter]] = defaultdict(list)
    readings_by_meter: dict[str, list[StandaloneMeterReading]] = defaultdict(list)
    for reading in readings:
        if period.start_date <= reading.reading_date <= period.end_date:
            readings_by_meter[reading.meter_id].append(reading)
    for meter in meters:
        if meter.unit_id not in contracts_by_unit:
            continue
        if meter.installation_date and meter.installation_date > period.end_date:
            continue
        # Today's active flag must not erase a past period's meter evidence.
        if meter.is_active is not False or readings_by_meter.get(meter.id):
            meters_by_medium_unit[(meter.meter_type, meter.unit_id)].append(meter)

    for key in selected:
        before = len(result.blockers)
        if not key.consumption_medium or not key.consumption_unit:
            result.block("MISSING_CONSUMPTION_BINDING",
                "Am verwendeten Verbrauchsschlüssel Medium und Maßeinheit ausdrücklich zuordnen. "
                "Das Medium muss genau dem Zählertyp entsprechen; Namen und Notizen werden nicht ausgewertet. "
                "Bereits finalisiert verwendete Schlüssel erhalten: neue zugeordnete Fassung anlegen und nur Entwurfskosten umstellen.", key.id)
            continue
        weights: dict[str, Decimal] = {}
        for unit_id, tenancies in sorted(contracts_by_unit.items()):
            if (len(tenancies) != 1 or tenancies[0].start_date > period.start_date
                    or (tenancies[0].end_date and tenancies[0].end_date < period.end_date)):
                result.block("CONSUMPTION_TENANCY_BASIS_MISSING",
                    "Mieterwechsel oder Teilbelegung benötigt datierte Verbrauchsanteile. "
                    "Belegte Teilperioden aufbereiten; Jahresverbrauch wird nicht nach Tagen geschätzt.", key.id, unit_id)
                continue
            matching = meters_by_medium_unit.get((key.consumption_medium, unit_id), [])
            if not matching:
                result.block("MISSING_CONSUMPTION_METER",
                    "Für das zugeordnete Medium fehlt ein Zähler mit Periodenbezug. Zählerzuordnung und Originalablesungen prüfen.",
                    key.id, unit_id)
                continue
            meter_values = [_meter_delta(result, period, key, meter, readings_by_meter[meter.id])
                for meter in sorted(matching, key=lambda meter: meter.id)]
            if all(value is not None for value in meter_values):
                weights[unit_id] = sum((value for value in meter_values if value is not None), Decimal(0))
        if len(result.blockers) != before:
            continue
        if sum(weights.values(), Decimal(0)) == 0 and key.id in nonzero_cost_key_ids:
            result.block("ZERO_CONSUMPTION_TOTAL",
                "Belegter Gesamtverbrauch ist null. Für die Kosten eine fachlich bestätigte andere Verteilungsgrundlage wählen.", key.id)
            continue
        result.weights[key.id] = weights
    return result
