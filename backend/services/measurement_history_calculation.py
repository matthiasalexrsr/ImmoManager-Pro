"""Historical shares from actual boundary readings and confirmed occupancy."""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import timedelta
from decimal import Decimal

from ..models import BillingPreflightIssue
from .measurement_history import historical_key_ids, period_sources
from .measurement_history_validation import DATA, MeasurementIntegrityError, validate_effective


@dataclass
class HistoricalBasis:
    managed_keys: set[str] = field(default_factory=set)
    weights: dict[str, dict[tuple[str, str], Decimal]] = field(default_factory=dict)
    blockers: list[BillingPreflightIssue] = field(default_factory=list)
    sources: list[dict] = field(default_factory=list)

    def block(self, code, message, *refs):
        self.blockers.append(BillingPreflightIssue(code=code, message=message, severity="blocker", context=", ".join(refs)))


class BasisGap(ValueError):
    pass


def _cover(rows, first, last):
    spans = sorted(((max(first, data.valid_from), min(last, data.valid_until), row, data)
                   for row, data in rows if data.valid_from < last and data.valid_until > first), key=lambda item: (item[0], item[1]))
    cursor = first
    for start, end, row, data in spans:
        if start != cursor:
            raise BasisGap("Zeitabschnitte sind lückenhaft oder überlappen; originale Beginn-/Endgrenzen ergänzen.")
        yield start, end, row, data
        cursor = end
    if cursor != last:
        raise BasisGap("Die bestätigte historische Grundlage deckt den Zeitraum nicht vollständig ab.")


def _reading(assignment_key, boundary, readings, approvals):
    exact = [(row, data) for row, data in readings if data.assignment_key == assignment_key and data.boundary_date == boundary]
    if len(exact) == 1:
        return exact[0][1].value
    if exact:
        raise BasisGap("Mehrdeutige Originalablesung an einer Teilperiodengrenze.")
    accepted = [(row, data) for row, data in approvals if data.assignment_key == assignment_key
                and data.valid_from <= boundary <= data.valid_until]
    if len(accepted) != 1:
        raise BasisGap("Originalablesung an Einzug, Auszug, Zählerwechsel oder Periodengrenze fehlt. Nur eine belegte ausdrückliche Freigabe erlaubt Tagesprorata.")
    _approval_row, approval = accepted[0]
    by_id = {row["id"]: data for row, data in readings}
    left, right = by_id.get(approval.start_reading_id), by_id.get(approval.end_reading_id)
    if (left is None or right is None or left.assignment_key != assignment_key or right.assignment_key != assignment_key
            or left.boundary_date != approval.valid_from or right.boundary_date != approval.valid_until
            or right.value < left.value):
        raise BasisGap("Zeitfreigabe bezieht sich auf fehlende oder inzwischen korrigierte Originalgrenzablesungen. Erneut anhand der Originale bestätigen.")
    return left.value + (right.value - left.value) * Decimal((boundary - left.boundary_date).days) / Decimal((right.boundary_date - left.boundary_date).days)


def _unit_weights(key, rows, first, last, contracts):
    effective = [row for row in rows if not row["withdrawn"]]
    validate_effective(effective)
    typed = [(row, DATA.validate_python(row["data"])) for row in effective]
    selections = [(row, data) for row, data in typed if data.kind == "selection" and data.allocation_key_id == key.id]
    occupancy = [(row, data) for row, data in typed if data.kind == "occupancy"]
    occupants = list(_cover(occupancy, first, last))
    for start, end, row, data in occupants:
        if data.contract_id is not None:
            contract = contracts.get(data.contract_id)
            if (contract is None or contract.start_date > start or row["tenant_id"] != contract.tenant_id
                    or contract.end_date is not None and contract.end_date + timedelta(days=1) < end):
                raise BasisGap("Historische Belegung und tatsächlicher Mietvertrag stimmen nicht mehr überein.")
        elif any(c.start_date < end and (c.end_date is None or c.end_date + timedelta(days=1) > start) for c in contracts.values()):
            raise BasisGap("Bestätigter Leerstand überschneidet einen tatsächlichen Mietvertrag; Vertrags-/Belegungsquelle klären.")
    result: dict[str | None, Decimal] = defaultdict(Decimal)
    for start, end, _selected_row, selection in _cover(selections, first, last):
        if selection.basis != key.key_type:
            raise BasisGap("Bestätigte Auswahl und heutiger Umlageschlüssel haben unterschiedliche Typen.")
        if key.key_type == "person_count":
            for occupied_start, occupied_end, _row, occupant in occupants:
                days = (min(end, occupied_end) - max(start, occupied_start)).days
                if days > 0:
                    result[occupant.contract_id] += Decimal(occupant.persons * days)
            continue
        if not key.consumption_medium or not key.consumption_unit:
            raise BasisGap("Medium und Maßeinheit am verwendeten Verbrauchsschlüssel fehlen.")
        assignments = [(row, data) for row, data in typed if data.kind == "assignment"]
        readings = [(row, data) for row, data in typed if data.kind == "reading"]
        approvals = [(row, data) for row, data in typed if data.kind == "proration"]
        for circuit in selection.circuits:
            for meter_start, meter_end, assignment_row, assignment in _cover(
                    [(row, data) for row, data in assignments if data.circuit_path == circuit], start, end):
                if assignment.medium != key.consumption_medium or assignment.measurement_unit != key.consumption_unit:
                    raise BasisGap("Historisch bestätigtes Medium oder Maßeinheit passt nicht zum Kostenschlüssel; keine automatische Umrechnung.")
                original = sorted((data for _row, data in readings if data.assignment_key == assignment_row["source_key"]), key=lambda data: data.boundary_date)
                if any(right.value < left.value for left, right in zip(original, original[1:])):
                    raise BasisGap("Zählerstände fallen innerhalb derselben Betriebszeit; korrigierte Originale oder getrennten Gerätewechsel erfassen.")
                for occupied_start, occupied_end, _row, occupant in occupants:
                    left, right = max(meter_start, occupied_start), min(meter_end, occupied_end)
                    if left >= right:
                        continue
                    delta = _reading(assignment_row["source_key"], right, readings, approvals) - _reading(assignment_row["source_key"], left, readings, approvals)
                    if delta < 0:
                        raise BasisGap("Negativer Abschnittsverbrauch; Originalgrenzen korrigieren.")
                    result[occupant.contract_id] += delta
    return result


def historical_basis(store, period, keys, contracts, units, nonzero_key_ids) -> HistoricalBasis:
    result = HistoricalBasis()
    result.sources = period_sources(store, period)
    result.managed_keys = historical_key_ids(store, period.property_id, set(keys))
    by_unit = defaultdict(list)
    for row in result.sources:
        by_unit[row["ledger_id"]].append(row)
    for key_id in sorted(result.managed_keys):
        before = len(result.blockers)
        weights = {}
        for unit in units:
            try:
                values = _unit_weights(keys[key_id], by_unit[unit.id], period.start_date,
                    period.end_date + timedelta(days=1), {c.id: c for c in contracts if c.unit_id == unit.id})
                for contract_id, value in values.items():
                    weights[(unit.id, contract_id or f"owner:{unit.id}")] = value
            except (BasisGap, MeasurementIntegrityError) as error:
                result.block("HISTORICAL_BASIS_INCOMPLETE", str(error), key_id, unit.id)
        if len(result.blockers) != before:
            continue
        if sum(weights.values(), Decimal(0)) == 0 and key_id in nonzero_key_ids:
            result.block("HISTORICAL_TOTAL_ZERO", "Belegter Gesamtverbrauch bzw. Personentage sind null. Andere ausdrücklich bestätigte Verteilung erforderlich.", key_id)
            continue
        result.weights[key_id] = weights
    return result
