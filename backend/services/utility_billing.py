"""Utility cost billing for one billing period (Nebenkostenabrechnung).

One calculation serves the pre-check, the generation and the check before
finalizing, so they cannot disagree:

- every unit of the property takes part, also vacant ones;
- each unit's period splits into tenancies and vacant gaps (domain.occupancy);
- area, unit and person keys share by value × days, consumption keys by the
  consumption of each segment (meter readings at move-in and move-out);
- vacant segments are the landlord's share and get rows of their own;
- non-recoverable cost items are not distributed;
- advances count per month as agreed, partial months by days.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from functools import partial
from typing import Any, Optional

from ..domain.billing_engine import AdvancePayment, BillingEngine, CostEntry, UnitShare
from ..domain.occupancy import (
    OverlappingTenanciesError,
    Segment,
    billable_contracts,
    days_between,
    prorate_monthly,
    unit_segments,
)
from ..models import UtilityStatementCreate
from .rent_history import charge_for

READING_TOLERANCE_DAYS = 7
DEADLINE_WARNING_DAYS = 60

KEY_UNITS = {"area_sqm": "m²", "person_count": "Personen", "unit_count": "Einheiten"}


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
class _Share:
    segment: Segment
    value: Decimal  # what the engine divides by: basis × days, or consumption
    basis: Decimal  # m², persons, units or consumption of the segment


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


def compute_period_billing(store: Any, period: Any, today: Optional[date] = None) -> PeriodBilling:
    today = today or date.today()
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
    person_problems = _PersonProblems()
    area_missing: set[str] = set()
    if segments is not None:
        for key in keys.values():
            if key.key_type == "consumption":
                shares[key.id] = _consumption_shares(result, store, key, units, segments, start, end, period_days, label)
            else:
                shares[key.id] = _time_shares(key, units, segments, contract_by_id, area_missing, person_problems)
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
        "contracts_without_advance": len([a for _, a in advances.values() if a == 0]),
        "non_positive_cost_items": len(non_positive),
        "non_recoverable_cost_items": len(excluded),
        "vacancy_days": sum(s.days for s in all_segments if s.is_vacancy),
        "tenant_changes": len([u for u, segs in (segments or {}).items()
                               if len([s for s in segs if not s.is_vacancy]) > 1]),
        "deadline": deadline.isoformat(),
    }

    if result.blockers or segments is None:
        return result

    result.statements = _statements(period, keys, recoverable, shares, advances, period_days, label)
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


def _time_shares(key, units, segments, contract_by_id, area_missing: set[str], persons: _PersonProblems) -> list[_Share]:
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
                if contract is not None and contract.persons is not None:
                    basis = Decimal(contract.persons)
                else:
                    unit_value = _unit_persons(unit, persons)
                    if segment.is_vacancy and _has_residents(unit):
                        # The landlord pays for an empty flat as if one person lived there.
                        basis = max(Decimal("1"), unit_value or Decimal("0"))
                    else:
                        basis = unit_value
                        if basis is None:
                            persons.missing.add(unit.id)
            else:  # unit_count and any other key: one share per unit
                basis = Decimal("1")
            if basis is not None:
                shares.append(_Share(segment, basis * segment.days, basis))
    return shares


def _consumption_shares(result, store, key, units, segments, start, end, period_days, label) -> list[_Share]:
    unit_ids = {u.id for u in units}
    meters = [m for m in store.list_meters() if m.unit_id in unit_ids and m.is_active is not False]
    meter_type = key.meter_type
    if not meter_type:
        types = sorted({m.meter_type for m in meters})
        if len(types) > 1:
            result.blocker("CONSUMPTION_METER_TYPE_REQUIRED",
                           "Verbrauchsschlüssel: bitte die Zählerart festlegen",
                           f"{key.name} (vorhanden: {', '.join(types)})")
            return []
        meter_type = types[0] if types else None
    meters = [m for m in meters if m.meter_type == meter_type]
    meter_ids = {m.id for m in meters}
    readings: dict[str, list] = {}
    for reading in store.list_standalone_meter_readings():
        if reading.meter_id in meter_ids:
            readings.setdefault(reading.meter_id, []).append(reading)

    def value_near(meter_id: str, day: date) -> Optional[Decimal]:
        candidates = [
            r for r in readings.get(meter_id, [])
            if abs((r.reading_date - day).days) <= READING_TOLERANCE_DAYS
        ]
        if not candidates:
            return None
        best = min(candidates, key=lambda r: (abs((r.reading_date - day).days), r.reading_date))
        return _decimal(best.value)

    def consumption(unit_meters: list, from_day: date, to_day: date) -> Optional[Decimal]:
        total = Decimal("0")
        for meter in unit_meters:
            first, last = value_near(meter.id, from_day), value_near(meter.id, to_day)
            if first is None or last is None:
                return None
            total += last - first
        return total

    shares: list[_Share] = []
    missing, negative, intermediate = [], [], []
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
        whole = consumption(unit_meters, start, end)
        if whole is not None:
            with_data += 1
        for segment in unit_segs:
            used = whole if len(unit_segs) == 1 else consumption(unit_meters, segment.start, segment.end)
            if used is None and whole is not None:
                # No reading at move-in/move-out: share the year's consumption by days.
                used = whole * segment.days / period_days
                boundary = segment.end if segment.end != end else segment.start
                intermediate.append(f"{label(unit.id)} zum {_fmt(boundary)}")
            if used is None:
                missing.append(f"{label(unit.id)}: keine Ablesung zum {_fmt(segment.start)} und {_fmt(segment.end)}")
                continue
            if used < 0:
                negative.append(label(unit.id))
                continue
            shares.append(_Share(segment, used, used))

    result.metrics["consumption_units_with_data"] = result.metrics.get("consumption_units_with_data", 0) + with_data
    if missing:
        result.blocker("MISSING_CONSUMPTION", "Keine verwertbaren Verbrauchsdaten für consumption-Verteilung im Zeitraum",
                       "; ".join(missing))
    if negative:
        result.blocker("INVALID_CONSUMPTION", "Zählerstände ergeben einen negativen Verbrauch (Zählertausch?)",
                       ", ".join(sorted(set(negative))))
    if intermediate:
        result.warn("MISSING_INTERMEDIATE_READING",
                    "Keine Zwischenablesung beim Mieterwechsel: Verbrauch wird nach Tagen geteilt",
                    ", ".join(sorted(set(intermediate))))
    return shares


def _advances(store, result, segments, contract_by_id) -> dict[str, tuple[str, Decimal]]:
    """Agreed advances per contract over its usage period: contract id -> (unit id, amount)."""
    advances: dict[str, tuple[str, Decimal]] = {}
    without = []
    for unit_id, unit_segs in segments.items():
        for segment in unit_segs:
            if segment.contract_id is None:
                continue
            contract = contract_by_id[segment.contract_id]
            total = prorate_monthly(partial(prepayment_for_month, store, contract), segment.start, segment.end)
            advances[segment.contract_id] = (unit_id, total)
            if total == 0:
                without.append(contract.contract_number)
    if without:
        result.warn("MISSING_ADVANCE", "Verträge ohne Nebenkosten-/Heizkostenvorauszahlung", ", ".join(without))
    return advances


def _statements(period, keys, cost_items, shares, advances, period_days, label) -> list[UtilityStatementCreate]:
    engine = BillingEngine()
    for key_id, key_shares in shares.items():
        for share in key_shares:
            s = share.segment
            engine.add_unit_share(key_id, UnitShare(s.unit_id, s.contract_id, share.value, s.start, s.end))
    for item in cost_items:
        engine.add_cost(CostEntry(item.description, _decimal(item.amount), item.allocation_key_id, cost_id=item.id))
    for contract_id, (unit_id, total) in advances.items():
        engine.add_advance(AdvancePayment(unit_id, contract_id, total))

    basis_by_party = {
        (key_id, s.segment.unit_id, s.segment.contract_id, s.segment.start): s.basis
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
            lines.append({
                "cost_item_id": line.cost_id,
                "description": line.description,
                "allocation_key_id": key.id,
                "key_name": key.name,
                "key_type": key.key_type,
                "basis_unit": KEY_UNITS.get(key.key_type, ""),
                "total_amount": float(line.total_amount or 0),
                "basis": float(basis_by_party[(key.id, generated.unit_id, generated.contract_id, usage_start)]),
                "total_basis": float(total_share / period_days if time_based else total_share),
                "days": days if time_based else None,
                "period_days": period_days,
                "allocated_amount": float(line.allocated_amount),
            })
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
            line_items=lines,
        ))
    statements.sort(key=lambda st: (label(st.unit_id), st.usage_start or period.start_date))
    return statements
