"""Utility cost billing for one billing period (Nebenkostenabrechnung).

One calculation serves the pre-check, the generation and the check before
finalizing, so they cannot disagree:

- every unit of the property takes part, also vacant ones;
- each unit's period splits into tenancies and vacant gaps (domain.occupancy);
- area, unit and person keys share by value × days, consumption keys by the
  consumption of each segment (meter readings at move-in and move-out);
- within a tenancy, the person key follows the dated occupants (person-days)
  and the advances follow the rent history, each in sections of equal value;
- a consumption key counts one medium in one unit of measure; other units are
  converted only by an exact factor (MWh -> kWh, l -> m³), otherwise refused;
- a replaced meter counts until its removal date, its successor from its
  installation date (final reading + initial reading);
- vacant segments are the landlord's share and get rows of their own;
- non-recoverable cost items are not distributed;
- advances count per month as agreed, partial months by days.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from functools import partial
from typing import Any, Optional

from ..domain.billing_engine import AdvancePayment, BillingEngine, CostEntry, UnitShare
from ..domain.lease_engine import charge_on
from ..domain.occupancy import (
    OverlappingTenanciesError,
    Segment,
    billable_contracts,
    days_between,
    prorate_monthly,
    unit_segments,
)
from ..models import UtilityStatementCreate
from .read_cache import CachedReads
from .rent_history import charge_for, rent_steps

READING_TOLERANCE_DAYS = 7
DEADLINE_WARNING_DAYS = 60

KEY_UNITS = {"area_sqm": "m²", "person_count": "Personen", "unit_count": "Einheiten"}

METER_TYPE_LABELS = {"cold_water": "Kaltwasser", "hot_water": "Warmwasser", "heating": "Heizung",
                     "electricity": "Strom", "gas": "Gas"}

# Spellings people enter -> the unit used in statements.
_UNIT_ALIASES = {
    "m3": "m³", "m^3": "m³", "m³": "m³", "cbm": "m³", "qm3": "m³",
    "l": "l", "liter": "l", "litre": "l",
    "wh": "Wh", "kwh": "kWh", "mwh": "MWh",
    "hkv": "HKV", "einheiten": "HKV", "einheit": "HKV", "striche": "HKV", "units": "HKV", "skt": "HKV",
}
# Exact factors into the base unit of a dimension. Nothing else is converted:
# gas m³ -> kWh needs calorific value and z-number, HKV units are no energy.
_EXACT = {"m³": ("volume", Decimal("1")), "l": ("volume", Decimal("0.001")),
          "kWh": ("energy", Decimal("1")), "MWh": ("energy", Decimal("1000")), "Wh": ("energy", Decimal("0.001"))}
# Units a medium is measured in.
MEDIUM_UNITS = {
    "cold_water": frozenset({"m³", "l"}),
    "hot_water": frozenset({"m³", "l"}),
    "heating": frozenset({"kWh", "MWh", "Wh", "HKV"}),
    "electricity": frozenset({"kWh", "MWh", "Wh"}),
    "gas": frozenset({"m³", "kWh", "MWh"}),
}
# The usual unit when a meter does not say. Heating (kWh or HKV) and gas (m³ or kWh) have none.
DEFAULT_UNITS = {"cold_water": "m³", "hot_water": "m³", "electricity": "kWh"}


def normalize_unit(value: Optional[str]) -> Optional[str]:
    text = (value or "").strip()
    if not text:
        return None
    return _UNIT_ALIASES.get(text.lower().replace(" ", ""), text)


def conversion_factor(from_unit: str, to_unit: str) -> Optional[Decimal]:
    """Exact factor from one unit into another, None if there is none."""
    if from_unit == to_unit:
        return Decimal("1")
    source, target = _EXACT.get(from_unit), _EXACT.get(to_unit)
    if source is None or target is None or source[0] != target[0]:
        return None
    return source[1] / target[1]


@dataclass(frozen=True)
class Issue:
    severity: str  # blocker | warning
    code: str
    message: str
    context: Optional[str] = None


@dataclass
class PeriodBilling:
    issues: list[Issue] = field(default_factory=list)
    statements: list[UtilityStatementCreate] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)

    @property
    def blockers(self) -> list[Issue]:
        return [i for i in self.issues if i.severity == "blocker"]

    @property
    def warnings(self) -> list[Issue]:
        return [i for i in self.issues if i.severity != "blocker"]

    def blocker(self, code: str, message: str, context: Optional[str] = None) -> None:
        self.issues.append(Issue("blocker", code, message, context))

    def warn(self, code: str, message: str, context: Optional[str] = None) -> None:
        self.issues.append(Issue("warning", code, message, context))


@dataclass(frozen=True)
class Section:
    """A stretch of a party's usage period with one basis value (e.g. 3 persons)."""
    start: date
    end: date
    basis: Decimal

    @property
    def days(self) -> int:
        return days_between(self.start, self.end)


@dataclass(frozen=True)
class _Share:
    segment: Segment
    value: Decimal  # what the engine divides by: basis × days, or consumption
    basis: Decimal  # m², persons, units or consumption of the segment (persons: average)
    sections: tuple[Section, ...] = ()  # only where the basis changes within the segment


def prepayment_for_month(store: Any, contract: Any, month: date) -> Decimal:
    """Agreed monthly advance (service charges and heating) of a contract in a month,
    from the contract's rent history."""
    charge = charge_for(store, contract, month)
    return charge.service_charge_advance + charge.heating_advance if charge else Decimal("0")


def statement_deadline(period_end: date) -> date:
    """§ 556 Abs. 3 BGB: the statement must reach the tenant by the end of the twelfth month."""
    year, month = period_end.year + 1, period_end.month
    return date(year, month, calendar.monthrange(year, month)[1])


def _fmt(day: date) -> str:
    return day.strftime("%d.%m.%Y")


def _decimal(value: Any) -> Decimal:
    return Decimal(str(value or 0))


def _split(start: date, end: date, changes: list[tuple[date, Any]], initial: Any) -> list[tuple[date, date, Any]]:
    """[start, end] in stretches of one value; changes are (valid from, value), sorted."""
    stretches: list[tuple[date, date, Any]] = []
    cursor, value = start, initial
    for valid_from, new_value in changes:
        if valid_from <= start or valid_from > end:
            continue
        stretches.append((cursor, valid_from - timedelta(days=1), value))
        cursor, value = valid_from, new_value
    stretches.append((cursor, end, value))
    return stretches


def compute_period_billing(store: Any, period: Any, today: Optional[date] = None) -> PeriodBilling:
    today = today or date.today()
    store = CachedReads(store)  # rent histories are read once, not once per contract and month
    result = PeriodBilling()
    start, end = period.start_date, period.end_date
    period_days = days_between(start, end)

    units = sorted(
        (u for u in store.list_units() if u.property_id == period.property_id),
        key=lambda u: (u.label or "", u.id),
    )
    unit_by_id = {u.id: u for u in units}
    contracts = billable_contracts(store.list_contracts(), period.property_id, start, end)
    contract_by_id = {c.id: c for c in contracts}

    def label(unit_id: str) -> str:
        unit = unit_by_id.get(unit_id)
        return (unit.label or unit_id) if unit else unit_id

    _check_contracts(result, contracts, unit_by_id, today)
    segments = _segments(result, units, contracts, contract_by_id, start, end, label)

    cost_items = [ci for ci in store.list_cost_items() if ci.billing_period_id == period.id]
    recoverable = [ci for ci in cost_items if ci.is_recoverable]
    excluded = [ci for ci in cost_items if not ci.is_recoverable]
    if excluded:
        amount = sum((_decimal(ci.amount) for ci in excluded), Decimal("0"))
        result.warn(
            "NON_RECOVERABLE_COSTS",
            "Nicht umlagefähige Kosten werden nicht auf die Mieter verteilt",
            f"{', '.join(ci.description for ci in excluded)} ({amount:.2f} €)",
        )
    if not contracts:
        result.blocker("NO_ACTIVE_CONTRACTS", "Keine abrechenbaren Verträge im Abrechnungszeitraum gefunden")
    if not recoverable:
        result.blocker("NO_COST_ITEMS", "Keine umlagefähigen Kostenpositionen für diese Periode vorhanden")
    non_positive = [ci for ci in recoverable if ci.amount <= 0]
    if non_positive:
        result.warn("NON_POSITIVE_COST", "Kostenpositionen mit <= 0 Betrag gefunden",
                    ", ".join(ci.description for ci in non_positive))

    all_keys = {k.id: k for k in store.list_allocation_keys()}
    used_key_ids = sorted({ci.allocation_key_id for ci in recoverable})
    missing_keys = [key_id for key_id in used_key_ids if key_id not in all_keys]
    if missing_keys:
        result.blocker("MISSING_ALLOCATION_KEYS", "Verteilerschlüssel für Kostenpositionen fehlen", ", ".join(missing_keys))
    keys = {key_id: all_keys[key_id] for key_id in used_key_ids if key_id in all_keys}
    foreign = [k.name for k in keys.values() if k.property_id != period.property_id]
    if foreign:
        result.blocker("FOREIGN_ALLOCATION_KEY", "Verteilerschlüssel gehört zu einem anderen Objekt", ", ".join(foreign))

    shares: dict[str, list[_Share]] = {}
    basis_units: dict[str, str] = {}
    person_problems = _PersonProblems()
    area_missing: set[str] = set()
    if segments is not None:
        occupancies = _occupancies_by_contract(store, contract_by_id)
        for key in keys.values():
            if key.key_type == "consumption":
                shares[key.id], basis_units[key.id] = _consumption_shares(
                    result, store, key, units, segments, start, end, period_days, label)
            else:
                shares[key.id] = _time_shares(key, units, segments, contract_by_id, occupancies,
                                              area_missing, person_problems)
                basis_units[key.id] = KEY_UNITS.get(key.key_type, "")
            if shares[key.id] and sum((s.value for s in shares[key.id]), Decimal("0")) == 0:
                # e.g. persons in a building of shops only: nothing to divide by
                items = ", ".join(ci.description for ci in recoverable if ci.allocation_key_id == key.id)
                result.blocker("ZERO_TOTAL_SHARE",
                               "Die Anteile des Verteilerschlüssels ergeben zusammen 0; bitte diese Kosten nach "
                               "einem anderen Schlüssel verteilen (z. B. Fläche oder Einheiten)",
                               f"{key.name}: {items}" if items else key.name)
        if area_missing:
            result.blocker("MISSING_AREA", "Fläche fehlt oder ist 0 für area_sqm-Verteilung",
                           ", ".join(sorted(label(u) for u in area_missing)))
        person_problems.report(result, label)

    advances = _advances(store, result, segments or {}, contract_by_id)

    deadline = statement_deadline(end)
    if today > deadline:
        result.warn("DEADLINE_PASSED",
                    f"Abrechnungsfrist am {_fmt(deadline)} abgelaufen: Nachforderungen sind ausgeschlossen "
                    "(§ 556 Abs. 3 BGB), Guthaben bleiben zu erstatten")
    elif (deadline - today).days <= DEADLINE_WARNING_DAYS:
        result.warn("DEADLINE_SOON", f"Abrechnungsfrist endet am {_fmt(deadline)} (§ 556 Abs. 3 BGB)")

    all_segments = [s for segs in (segments or {}).values() for s in segs]
    result.metrics = {
        "contracts_in_period": len(contracts),
        "cost_items": len(cost_items),
        "allocation_keys_used": len(used_key_ids),
        "allocation_keys_missing": len(missing_keys),
        "units": len(units),
        "units_missing": len([c for c in contracts if c.unit_id not in unit_by_id]),
        "area_missing_units": len(area_missing),
        "person_count_missing_units": len(person_problems.missing),
        "person_count_from_rooms_units": len(person_problems.from_rooms),
        "consumption_units_with_data": result.metrics.get("consumption_units_with_data", 0),
        "contracts_without_advance": len([a for _, a, _ in advances.values() if a == 0]),
        "non_positive_cost_items": len(non_positive),
        "non_recoverable_cost_items": len(excluded),
        "vacancy_days": sum(s.days for s in all_segments if s.is_vacancy),
        "tenant_changes": len([u for u, segs in (segments or {}).items()
                               if len([s for s in segs if not s.is_vacancy]) > 1]),
        "deadline": deadline.isoformat(),
    }

    if result.blockers or segments is None:
        return result

    result.statements = _statements(period, keys, recoverable, shares, basis_units, advances, period_days, label)
    return result


def _check_contracts(result: PeriodBilling, contracts: list, unit_by_id: dict, today: date) -> None:
    missing_unit = [c.contract_number for c in contracts if c.unit_id not in unit_by_id]
    if missing_unit:
        result.blocker("MISSING_UNITS", "Vertragszuordnungen ohne Einheit dieses Objekts", ", ".join(missing_unit))
    without_end = [c.contract_number for c in contracts if c.status == "terminated" and c.end_date is None]
    if without_end:
        result.blocker("TERMINATED_WITHOUT_END",
                       "Beendeter Vertrag ohne Enddatum: bitte das Auszugsdatum eintragen", ", ".join(without_end))
    ended = [f"{c.contract_number} (Ende {_fmt(c.end_date)})"
             for c in contracts if c.status == "active" and c.end_date and c.end_date < today]
    if ended:
        result.warn("ACTIVE_CONTRACT_ENDED", "Aktiver Vertrag mit Enddatum in der Vergangenheit", ", ".join(ended))


def _segments(result, units, contracts, contract_by_id, start, end, label) -> Optional[dict[str, list[Segment]]]:
    segments: dict[str, list[Segment]] = {}
    overlapping = []
    for unit in units:
        try:
            segments[unit.id] = unit_segments(unit.id, contracts, start, end)
        except OverlappingTenanciesError as exc:
            numbers = " / ".join(contract_by_id[i].contract_number for i in exc.contract_ids)
            overlapping.append(f"{label(unit.id)}: {numbers}")
    if overlapping:
        result.blocker("OVERLAPPING_CONTRACTS", "Verträge derselben Einheit überschneiden sich", "; ".join(overlapping))
        return None

    for unit_id, unit_segs in segments.items():
        tenancies = [s for s in unit_segs if not s.is_vacancy]
        if len(tenancies) > 1:
            stretches = ", ".join(
                f"{contract_by_id[s.contract_id].contract_number} {_fmt(s.start)}–{_fmt(s.end)}" for s in tenancies
            )
            result.warn("TENANT_CHANGE", "Mieterwechsel: Kosten werden tagesgenau aufgeteilt", f"{label(unit_id)}: {stretches}")
        vacant_days = sum(s.days for s in unit_segs if s.is_vacancy)
        if vacant_days:
            result.warn("VACANCY", "Leerstand: den Anteil trägt der Vermieter", f"{label(unit_id)}: {vacant_days} Tage")
    return segments


class _PersonProblems:
    def __init__(self) -> None:
        self.missing: set[str] = set()
        self.from_rooms: set[str] = set()

    def report(self, result: PeriodBilling, label) -> None:
        if self.missing:
            result.blocker("MISSING_PERSON_COUNT",
                           "Personenzahl fehlt für die Personen-Verteilung (bei Gewerbe ggf. 0 eintragen)",
                           ", ".join(sorted(label(u) for u in self.missing)))
        if self.from_rooms:
            result.warn("PERSON_COUNT_FROM_ROOMS",
                        "Personenzahl fehlt; für die Personen-Verteilung wird die Zimmerzahl verwendet",
                        ", ".join(sorted(label(u) for u in self.from_rooms)))


# Unit types nobody lives in. They take no part in the person key, and without an area
# they take no part in the area key either (a parking space has no living area).
_NO_RESIDENTS = ("stellplatz", "garage", "parking", "carport", "keller", "basement", "storage", "lager", "abstell")


def _has_residents(unit: Any) -> bool:
    unit_type = (unit.unit_type or "").lower()
    return not any(marker in unit_type for marker in _NO_RESIDENTS)


def _unit_persons(unit: Any, problems: _PersonProblems) -> Optional[Decimal]:
    if unit.person_count is not None:  # an entered 0 is a real answer
        return Decimal(unit.person_count)
    if not _has_residents(unit):
        return Decimal("0")
    if unit.rooms:
        problems.from_rooms.add(unit.id)
        return _decimal(unit.rooms)
    return None


def _occupancies_by_contract(store: Any, contract_by_id: dict) -> dict[str, list[tuple[date, int]]]:
    """Dated occupants of the billed contracts: contract id -> [(valid from, persons)], sorted."""
    list_occupancies = getattr(store, "list_contract_occupancies", None)
    if list_occupancies is None:
        return {}
    grouped: dict[str, list[tuple[date, int]]] = {}
    for occupancy in list_occupancies():
        if occupancy.contract_id in contract_by_id:
            grouped.setdefault(occupancy.contract_id, []).append((occupancy.valid_from, occupancy.persons))
    return {contract_id: sorted(entries) for contract_id, entries in grouped.items()}


def _person_sections(segment: Segment, contract: Any, occupancies: list[tuple[date, int]]
                     ) -> list[tuple[date, date, Optional[int]]]:
    """Stretches of the segment with one household size; None: unknown (the unit decides)."""
    started = [persons for valid_from, persons in occupancies if valid_from <= segment.start]
    initial: Optional[int] = started[-1] if started else contract.persons
    return _split(segment.start, segment.end, occupancies, initial)


def _time_shares(key, units, segments, contract_by_id, occupancies, area_missing: set[str],
                 persons: _PersonProblems) -> list[_Share]:
    shares = []
    for unit in units:
        for segment in segments[unit.id]:
            basis: Optional[Decimal]
            if key.key_type == "area_sqm":
                basis = _decimal(unit.area_sqm) if unit.area_sqm and unit.area_sqm > 0 else None
                if basis is None and _has_residents(unit):
                    area_missing.add(unit.id)
            elif key.key_type == "person_count":
                contract = contract_by_id.get(segment.contract_id) if segment.contract_id else None
                if contract is not None:
                    share = _person_days_share(segment, contract, occupancies.get(contract.id, []), unit, persons)
                    if share is not None:
                        shares.append(share)
                    continue
                unit_value = _unit_persons(unit, persons)
                if _has_residents(unit):
                    # The landlord pays for an empty flat as if one person lived there.
                    basis = max(Decimal("1"), unit_value or Decimal("0"))
                else:
                    basis = unit_value
            else:  # unit_count and any other key: one share per unit
                basis = Decimal("1")
            if basis is not None:
                shares.append(_Share(segment, basis * segment.days, basis))
    return shares


def _person_days_share(segment: Segment, contract: Any, occupancies: list[tuple[date, int]], unit: Any,
                       persons: _PersonProblems) -> Optional[_Share]:
    """Person-days of a tenancy: persons × days of each section with one household size."""
    sections = []
    for start, end, value in _person_sections(segment, contract, occupancies):
        basis = Decimal(value) if value is not None else _unit_persons(unit, persons)
        if basis is None:
            persons.missing.add(unit.id)
            return None
        sections.append(Section(start, end, basis))
    person_days = sum((s.basis * s.days for s in sections), Decimal("0"))
    average = person_days / segment.days
    return _Share(segment, person_days, average, tuple(sections) if len(sections) > 1 else ())


def _consumption_shares(result, store, key, units, segments, start, end, period_days, label
                        ) -> tuple[list[_Share], str]:
    unit_ids = {u.id for u in units}
    meters_of_property = [m for m in store.list_meters() if m.unit_id in unit_ids]
    readings: dict[str, list] = {}
    meter_ids = {m.id for m in meters_of_property}
    for reading in store.list_standalone_meter_readings():
        if reading.meter_id in meter_ids:
            readings.setdefault(reading.meter_id, []).append(reading)

    def in_service(meter: Any, from_day: date, to_day: date) -> Optional[tuple[date, date]]:
        first = max(from_day, meter.installation_date) if meter.installation_date else from_day
        last = min(to_day, meter.removal_date) if getattr(meter, "removal_date", None) else to_day
        return (first, last) if first <= last else None

    def meter_name(meter: Any) -> str:
        return f"{label(meter.unit_id)} ({meter.serial_number or meter.id[:8]})"

    # Active meters, and replaced ones up to their removal date. A deactivated meter
    # without one would silently drop its consumption, so its readings must be dated.
    counted, undated = [], []
    for meter in meters_of_property:
        removed = getattr(meter, "removal_date", None)
        if meter.is_active is False and removed is None:
            if any(start <= r.reading_date <= end for r in readings.get(meter.id, [])):
                undated.append(meter)
            continue
        if in_service(meter, start, end) is not None:
            counted.append(meter)

    meter_type = key.meter_type
    if not meter_type:
        types = sorted({m.meter_type for m in counted})
        if len(types) > 1:
            result.blocker("CONSUMPTION_METER_TYPE_REQUIRED",
                           "Verbrauchsschlüssel: bitte die Zählerart festlegen",
                           f"{key.name} (vorhanden: {', '.join(types)})")
            return [], ""
        meter_type = types[0] if types else None
    meters = [m for m in counted if m.meter_type == meter_type]
    undated = [m for m in undated if m.meter_type == meter_type]
    if undated:
        result.blocker("METER_REMOVAL_DATE_MISSING",
                       "Deaktivierter Zähler mit Ablesungen im Zeitraum: bitte beim Zählerwechsel das Ausbaudatum "
                       "des alten und das Einbaudatum des neuen Zählers eintragen",
                       ", ".join(sorted(meter_name(m) for m in undated)))

    factors, billing_unit = _unit_factors(result, key, meter_type, meters, meter_name)
    if factors is None:
        return [], billing_unit

    def value_near(meter_id: str, day: date) -> Optional[Decimal]:
        candidates = [
            r for r in readings.get(meter_id, [])
            if abs((r.reading_date - day).days) <= READING_TOLERANCE_DAYS
        ]
        if not candidates:
            return None
        best = min(candidates, key=lambda r: (abs((r.reading_date - day).days), r.reading_date))
        return _decimal(best.value)

    negative: set[str] = set()

    def consumption(unit_meters: list, from_day: date, to_day: date) -> Optional[Decimal]:
        """Sum over the meters in service: old meter to its final, new one from its initial reading."""
        total = Decimal("0")
        for meter in unit_meters:
            service = in_service(meter, from_day, to_day)
            if service is None:
                continue
            first, last = value_near(meter.id, service[0]), value_near(meter.id, service[1])
            if first is None or last is None:
                return None
            if last < first:
                negative.add(meter_name(meter))
                return None
            total += (last - first) * factors[meter.id]
        return total

    shares: list[_Share] = []
    missing, intermediate = [], []
    with_data = 0
    for unit in units:
        unit_segs = segments[unit.id]
        unit_meters = [m for m in meters if m.unit_id == unit.id]
        rented = any(not s.is_vacancy for s in unit_segs)
        if not unit_meters:
            if rented:
                missing.append(f"{label(unit.id)}: kein Zähler der Art {meter_type or '—'}")
            shares.extend(_Share(s, Decimal("0"), Decimal("0")) for s in unit_segs)
            continue
        negative_before = len(negative)
        whole = consumption(unit_meters, start, end)
        if whole is not None:
            with_data += 1
        for segment in unit_segs:
            used = whole if len(unit_segs) == 1 else consumption(unit_meters, segment.start, segment.end)
            if len(negative) > negative_before:
                break
            if used is None and whole is not None:
                # No reading at move-in/move-out: share the year's consumption by days.
                used = whole * segment.days / period_days
                boundary = segment.end if segment.end != end else segment.start
                intermediate.append(f"{label(unit.id)} zum {_fmt(boundary)}")
            if used is None:
                missing.append(f"{label(unit.id)}: keine Ablesung zum {_fmt(segment.start)} und {_fmt(segment.end)}")
                continue
            shares.append(_Share(segment, used, used))

    result.metrics["consumption_units_with_data"] = result.metrics.get("consumption_units_with_data", 0) + with_data
    if missing:
        result.blocker("MISSING_CONSUMPTION", "Keine verwertbaren Verbrauchsdaten für consumption-Verteilung im Zeitraum",
                       "; ".join(missing))
    if negative:
        result.blocker("INVALID_CONSUMPTION",
                       "Zählerstände ergeben einen negativen Verbrauch: bei einem Zählerwechsel den alten Zähler "
                       "mit Ausbaudatum und Endstand, den neuen mit Einbaudatum und Anfangsstand erfassen",
                       ", ".join(sorted(negative)))
    if intermediate:
        result.warn("MISSING_INTERMEDIATE_READING",
                    "Keine Zwischenablesung beim Mieterwechsel: Verbrauch wird nach Tagen geteilt",
                    ", ".join(sorted(set(intermediate))))
    return shares, billing_unit


def _unit_factors(result, key, meter_type, meters, meter_name) -> tuple[Optional[dict[str, Decimal]], str]:
    """Factor per meter into the key's unit; None (with a blocker) if the units do not fit."""
    medium = METER_TYPE_LABELS.get(meter_type or "", meter_type or "—")
    allowed = MEDIUM_UNITS.get(meter_type or "")

    def unit_of(meter: Any) -> Optional[str]:
        return normalize_unit(getattr(meter, "measure_unit", None)) or DEFAULT_UNITS.get(meter_type or "")

    wrong_medium = sorted(f"{meter_name(m)}: {unit_of(m)}" for m in meters
                          if allowed and unit_of(m) and unit_of(m) not in allowed)
    if wrong_medium:
        result.blocker("CONSUMPTION_UNIT_INVALID",
                       f"Maßeinheit passt nicht zur Zählerart {medium}", f"{key.name}: {', '.join(wrong_medium)}")
        return None, ""

    target = normalize_unit(getattr(key, "measure_unit", None))
    if target is None:
        found = {unit_of(m) for m in meters}
        if len(found) > 1:
            shown = ", ".join(sorted(u or "ohne Angabe" for u in found))
            result.blocker("CONSUMPTION_UNIT_MISMATCH",
                           "Zähler eines Verbrauchsschlüssels zeigen verschiedene Maßeinheiten: bitte am "
                           "Verteilerschlüssel die Abrechnungseinheit festlegen (umgerechnet wird nur mit exaktem "
                           "Faktor, z. B. MWh → kWh)",
                           f"{key.name}: {shown}")
            return None, ""
        billing_unit = next(iter(found), None) or ""
        return {m.id: Decimal("1") for m in meters}, billing_unit

    if allowed and target not in allowed:
        result.blocker("CONSUMPTION_UNIT_INVALID",
                       f"Die Abrechnungseinheit des Verteilerschlüssels passt nicht zur Zählerart {medium}",
                       f"{key.name}: {target}")
        return None, target
    factors: dict[str, Decimal] = {}
    unknown, refused, converted = [], [], []
    for meter in meters:
        unit = unit_of(meter)
        if unit is None:
            unknown.append(meter_name(meter))
            continue
        factor = conversion_factor(unit, target)
        if factor is None:
            refused.append(f"{meter_name(meter)}: {unit}")
            continue
        factors[meter.id] = factor
        if factor != 1:
            converted.append(f"{meter_name(meter)}: {unit} → {target} (× {factor.normalize():f})")
    if unknown:
        result.blocker("CONSUMPTION_UNIT_MISSING",
                       f"Maßeinheit des Zählers fehlt; ohne sie wird nicht in {target} umgerechnet",
                       f"{key.name}: {', '.join(sorted(unknown))}")
    if refused:
        result.blocker("CONSUMPTION_UNIT_MISMATCH",
                       f"Zählerstände lassen sich nicht exakt in {target} umrechnen (Gas in m³ braucht Brennwert und "
                       "Zustandszahl, Heizkostenverteiler-Einheiten sind keine kWh); bitte die Zähler in einer Einheit "
                       "erfassen oder einen eigenen Schlüssel verwenden",
                       f"{key.name}: {', '.join(sorted(refused))}")
    if unknown or refused:
        return None, target
    if converted:
        result.warn("CONSUMPTION_UNIT_CONVERTED", f"Zählerstände in {target} umgerechnet",
                    f"{key.name}: {', '.join(sorted(converted))}")
    return factors, target


def _constant(value: Decimal, _month: date) -> Decimal:
    return value


def _advance_sections(store: Any, contract: Any, start: date, end: date) -> list[dict]:
    """Advances of a tenancy segment in stretches of one monthly advance (rent history).

    A change in the middle of a month splits that month by days, like a move-in.
    """
    steps = sorted(rent_steps(store, contract), key=lambda step: step.valid_from)
    changes = [(step.valid_from, None) for step in steps]
    sections = []
    for section_start, section_end, _ in _split(start, end, changes, None):
        charge = charge_on(steps, max(section_start, contract.start_date))
        monthly = charge.service_charge_advance + charge.heating_advance if charge else Decimal("0")
        amount = prorate_monthly(partial(_constant, monthly), section_start, section_end)
        sections.append({"start": section_start, "end": section_end, "days": days_between(section_start, section_end),
                         "monthly": monthly, "amount": amount})
    return sections


def _advances(store, result, segments, contract_by_id) -> dict[str, tuple[str, Decimal, list[dict]]]:
    """Agreed advances per contract over its usage period: contract id -> (unit id, amount, sections)."""
    advances: dict[str, tuple[str, Decimal, list[dict]]] = {}
    without = []
    for unit_id, unit_segs in segments.items():
        for segment in unit_segs:
            if segment.contract_id is None:
                continue
            contract = contract_by_id[segment.contract_id]
            sections = _advance_sections(store, contract, segment.start, segment.end)
            total = sum((s["amount"] for s in sections), Decimal("0"))
            advances[segment.contract_id] = (unit_id, total, sections)
            if total == 0:
                without.append(contract.contract_number)
    if without:
        result.warn("MISSING_ADVANCE", "Verträge ohne Nebenkosten-/Heizkostenvorauszahlung", ", ".join(without))
    return advances


def _section_rows(sections: tuple[Section, ...]) -> Optional[list[dict]]:
    if not sections:
        return None
    return [{"start": s.start.isoformat(), "end": s.end.isoformat(), "days": s.days, "basis": float(s.basis)}
            for s in sections]


def _statements(period, keys, cost_items, shares, basis_units, advances, period_days, label
                ) -> list[UtilityStatementCreate]:
    engine = BillingEngine()
    for key_id, key_shares in shares.items():
        for share in key_shares:
            s = share.segment
            engine.add_unit_share(key_id, UnitShare(s.unit_id, s.contract_id, share.value, s.start, s.end))
    for item in cost_items:
        engine.add_cost(CostEntry(item.description, _decimal(item.amount), item.allocation_key_id, cost_id=item.id))
    for contract_id, (unit_id, total, _) in advances.items():
        engine.add_advance(AdvancePayment(unit_id, contract_id, total))

    share_by_party = {
        (key_id, s.segment.unit_id, s.segment.contract_id, s.segment.start): s
        for key_id, key_shares in shares.items() for s in key_shares
    }
    statements = []
    for generated in engine.generate():
        usage_start, usage_end = generated.usage_start, generated.usage_end
        assert usage_start is not None and usage_end is not None
        days = days_between(usage_start, usage_end)
        lines = []
        for line in generated.line_items:
            key = keys[line.allocation_key_id]
            time_based = key.key_type != "consumption"
            total_share = line.total_share or Decimal("0")
            share = share_by_party[(key.id, generated.unit_id, generated.contract_id, usage_start)]
            row = {
                "cost_item_id": line.cost_id,
                "description": line.description,
                "allocation_key_id": key.id,
                "key_name": key.name,
                "key_type": key.key_type,
                "basis_unit": basis_units.get(key.id, ""),
                "total_amount": float(line.total_amount or 0),
                "basis": float(share.basis),
                "total_basis": float(total_share / period_days if time_based else total_share),
                "days": days if time_based else None,
                "period_days": period_days,
                "allocated_amount": float(line.allocated_amount),
            }
            sections = _section_rows(share.sections)
            if sections:
                row["sections"] = sections
            lines.append(row)
        advance_sections = None
        if generated.contract_id is not None:
            sections_of_contract = advances.get(generated.contract_id, ("", Decimal("0"), []))[2]
            advance_sections = [
                {"start": s["start"].isoformat(), "end": s["end"].isoformat(), "days": s["days"],
                 "monthly": float(s["monthly"]), "amount": float(round(s["amount"], 2))}
                for s in sections_of_contract
            ]
        statements.append(UtilityStatementCreate(
            billing_period_id=period.id,
            contract_id=generated.contract_id,
            unit_id=generated.unit_id,
            party="vacancy" if generated.is_vacancy else "tenant",
            usage_start=usage_start,
            usage_end=usage_end,
            usage_days=days,
            total_cost=float(generated.total_cost),
            advance_paid=float(generated.advance_paid),
            balance=float(generated.balance),
            revision=getattr(period, "revision", 1) or 1,
            revision_notes=getattr(period, "revision_notes", None),
            line_items=lines,
            advance_sections=advance_sections,
        ))
    statements.sort(key=lambda st: (label(st.unit_id), st.usage_start or period.start_date))
    return statements
