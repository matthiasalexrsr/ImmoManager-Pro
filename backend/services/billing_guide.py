"""What the utility statement assistant shows for one property and period: the situation and the next steps.

Read only. Everything comes from the existing records: units and their tenancies and vacancies in the period,
the keys the property has and the ones its situation calls for, the costs against the previous period, the
meter readings the consumption keys need (also on the days tenants changed), the deadline, and the check of
the statement itself. The hints name the property's own units, tenants, meters and days.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Optional

from ..domain.clock import local_today
from ..domain.occupancy import OverlappingTenanciesError, billable_contracts, unit_segments
from .meter_history import unusual_intervals
from .utility_billing import (
    DEFAULT_UNITS,
    METER_TYPE_LABELS,
    READING_TOLERANCE_DAYS,
    _advance_sections,
    normalize_unit,
    statement_deadline,
)

KEY_LABELS = {"area_sqm": "Wohn-/Nutzfläche", "person_count": "Personen", "unit_count": "Einheiten", "consumption": "Verbrauch"}
_NO_RESIDENTS = ("stellplatz", "garage", "parking", "carport", "keller", "basement", "storage", "lager", "abstell")
_COMMERCIAL = ("gewerbe", "commercial", "laden", "büro", "office", "praxis", "shop")

# Operating costs of § 2 BetrKV with the key they usually go by; the person picks.
BETRKV = [
    ("property_tax", "Grundsteuer", "area_sqm"), ("water", "Wasserversorgung und Entwässerung", "consumption:cold_water"),
    ("heating", "Heizkosten", "consumption:heating"), ("hot_water", "Warmwasser", "consumption:hot_water"),
    ("elevator", "Aufzug", "area_sqm"), ("street_cleaning", "Straßenreinigung", "area_sqm"),
    ("garbage", "Müllbeseitigung", "person_count"), ("cleaning", "Gebäudereinigung und Ungezieferbekämpfung", "area_sqm"),
    ("garden", "Gartenpflege", "area_sqm"), ("electricity", "Allgemeinstrom (Beleuchtung)", "area_sqm"),
    ("chimney", "Schornsteinreinigung", "area_sqm"), ("insurance", "Sach- und Haftpflichtversicherung", "area_sqm"),
    ("caretaker", "Hauswart", "area_sqm"), ("cable", "Gemeinschaftsantenne / Kabel", "unit_count"),
    ("laundry", "Wäschepflege", "unit_count"), ("other", "Sonstige Betriebskosten", "area_sqm"),
]


def _fmt(day: Optional[date]) -> str:
    return day.strftime("%d.%m.%Y") if day else "—"


def _money(value: Any) -> str:
    text = f"{Decimal(str(value or 0)):,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")
    return f"{text} €"


def _normal(text: Optional[str]) -> str:
    return "".join(character for character in (text or "").lower() if character.isalnum())


def _residential(unit: Any) -> bool:
    kind = (unit.unit_type or "").lower()
    return not any(marker in kind for marker in _NO_RESIDENTS + _COMMERCIAL)


def _commercial(unit: Any) -> bool:
    return any(marker in (unit.unit_type or "").lower() for marker in _COMMERCIAL)


def _parking(unit: Any) -> bool:
    return any(marker in (unit.unit_type or "").lower() for marker in _NO_RESIDENTS)


@dataclass
class Hints:
    items: list[dict] = field(default_factory=list)

    def add(self, step: str, text: str, level: str = "info", link: Optional[str] = None) -> None:
        self.items.append({"step": step, "level": level, "text": text, "link": link})


def suggested_period(periods: list[Any], today: date) -> dict:
    """After the last period the next twelve months, else the last calendar year."""
    if periods:
        last = max(periods, key=lambda period: period.end_date)
        start = last.end_date + timedelta(days=1)
        try:
            end = start.replace(year=start.year + 1) - timedelta(days=1)
        except ValueError:                     # 29 February
            end = start.replace(year=start.year + 1, day=28) - timedelta(days=1)
    else:
        start, end = date(today.year - 1, 1, 1), date(today.year - 1, 12, 31)
    label = f"Nebenkosten {start.year}" if (start.month, start.day, end.month, end.day) == (1, 1, 12, 31) \
        else f"Nebenkosten {start:%m/%Y} – {end:%m/%Y}"
    return {"label": label, "start_date": start.isoformat(), "end_date": end.isoformat()}


def guide(store: Any, property_id: str, period_id: Optional[str] = None, *, checks: Any = None) -> dict:
    """The assistant's view of one property; `checks` is the preflight of the period (from the billing router)."""
    today = local_today()
    prop = store.get_property(property_id)
    units = sorted((unit for unit in store.list_units() if unit.property_id == property_id), key=lambda unit: unit.label or "")
    unit_label = {unit.id: unit.label for unit in units}
    periods = sorted((period for period in store.list_billing_periods() if period.property_id == property_id),
                     key=lambda period: period.start_date, reverse=True)
    period = next((item for item in periods if item.id == period_id), None) if period_id else None
    proposal = suggested_period(periods, today)
    start = period.start_date if period else date.fromisoformat(proposal["start_date"])
    end = period.end_date if period else date.fromisoformat(proposal["end_date"])
    hints = Hints()

    # ── units, tenancies, vacancies ────────────────────────────────────────────
    tenants = {tenant.id: tenant.full_name for tenant in store.list_tenants()}
    contracts = billable_contracts(store.list_contracts(), property_id, start, end)
    contract_by_id = {contract.id: contract for contract in contracts}
    occupancy, changes, vacancy_days, overlaps = [], [], 0, []
    for unit in units:
        try:
            segments = unit_segments(unit.id, contracts, start, end)
        except OverlappingTenanciesError:
            overlaps.append(unit.label)
            segments = []
        rows = []
        for segment in segments:
            contract = contract_by_id.get(segment.contract_id) if segment.contract_id else None
            advance = None
            if contract is not None:
                try:
                    advance = float(sum((Decimal(str(part["amount"])) for part in _advance_sections(store, contract, segment.start, segment.end)), Decimal("0")))
                except Exception:          # a missing rent history shows as "unknown", the check names it
                    advance = None
            rows.append({"kind": "vacancy" if segment.is_vacancy else "tenancy", "start": segment.start.isoformat(),
                         "end": segment.end.isoformat(), "days": segment.days,
                         "contract_id": contract.id if contract else None,
                         "contract_number": contract.contract_number if contract else None,
                         "tenant": tenants.get(contract.tenant_id) if contract else None,
                         "persons": contract.persons if contract and contract.persons is not None else unit.person_count,
                         "advances": advance})
            if segment.is_vacancy:
                vacancy_days += segment.days
        tenancies = [row for row in rows if row["kind"] == "tenancy"]
        for before, after in zip(rows, rows[1:]):
            changes.append({"unit_id": unit.id, "unit_label": unit.label, "out": before.get("tenant") or "Leerstand",
                            "in": after.get("tenant") or "Leerstand", "day": after["start"]})
        occupancy.append({"unit_id": unit.id, "label": unit.label, "unit_type": unit.unit_type, "area_sqm": unit.area_sqm,
                          "person_count": unit.person_count, "residential": _residential(unit), "segments": rows,
                          "rented_days": sum(row["days"] for row in tenancies)})

    # ── meters and keys ───────────────────────────────────────────────────────
    unit_ids = {unit.id for unit in units}
    meters = [meter for meter in store.list_meters() if meter.unit_id in unit_ids
              and (meter.is_active is not False or meter.removal_date)]
    rented = {row["unit_id"] for row in occupancy if row["rented_days"]}
    keys = [key for key in store.list_allocation_keys() if key.property_id == property_id]
    items = [item for item in store.list_cost_items() if period is not None and item.billing_period_id == period.id]
    used_keys = {item.allocation_key_id for item in items} | {item.fixed_key_id for item in items if item.fixed_key_id}
    present = [{"id": key.id, "name": key.name, "key_type": key.key_type, "key_label": KEY_LABELS.get(key.key_type, key.key_type),
                "meter_type": key.meter_type, "measure_unit": key.measure_unit, "used": key.id in used_keys} for key in keys]
    have = {(key.key_type, key.meter_type if key.key_type == "consumption" else None) for key in keys}
    suggested: list[dict[str, Any]] = []
    if ("area_sqm", None) not in have:
        suggested.append({"key_type": "area_sqm", "name": "Wohn-/Nutzfläche", "reason": "Der übliche Schlüssel für Grundsteuer, "
                          "Versicherung, Reinigung, Gartenpflege und Allgemeinstrom (§ 556a BGB: ohne Vereinbarung nach Fläche)."})
    residential = [unit for unit in units if _residential(unit)]
    if residential and ("person_count", None) not in have:
        suggested.append({"key_type": "person_count", "name": "Personen", "reason": "Für Müll und Wasser, wenn nicht nach "
                          "Verbrauch verteilt wird – nur wenn der Mietvertrag es so vorsieht."})
    by_type: dict[str, list[Any]] = {}
    for meter in meters:
        by_type.setdefault(meter.meter_type, []).append(meter)
    for meter_type, group in sorted(by_type.items()):
        with_meter = {meter.unit_id for meter in group}
        label = METER_TYPE_LABELS.get(meter_type, meter_type)
        lacking = sorted(unit_label[unit_id] for unit_id in rented - with_meter)
        if ("consumption", meter_type) in have:
            if lacking:
                hints.add("keys", f"Der Verbrauchsschlüssel {label} braucht in jeder vermieteten Einheit einen Zähler; es fehlt einer in "
                          f"{', '.join(lacking[:6])}{' …' if len(lacking) > 6 else ''}.", "warning", "/meters")
            continue
        units_of = Counter(normalize_unit(meter.measure_unit) or DEFAULT_UNITS.get(meter_type) for meter in group)
        if len(units_of) > 1 or None in units_of:
            hints.add("keys", f"Die {label}zähler zählen in verschiedenen oder unbekannten Einheiten "
                      f"({', '.join(str(unit) for unit in units_of)}). Für einen Verbrauchsschlüssel bitte an den Zählern die Einheit angeben.",
                      "warning", "/meters")
            continue
        measure = next(iter(units_of))
        if lacking:
            hints.add("keys", f"{len(with_meter & rented)} von {len(rented)} vermieteten Einheiten haben einen {label}zähler "
                      f"(es fehlt einer in {', '.join(lacking[:6])}). Nach Verbrauch verteilen geht erst, wenn alle erfasst sind.", "info")
            continue
        suggested.append({"key_type": "consumption", "meter_type": meter_type, "measure_unit": measure,
                          "name": f"{label} (Verbrauch)",
                          "reason": f"Alle {len(rented)} vermieteten Einheiten haben einen {label}zähler ({measure}). "
                                    + ("Heiz- und Warmwasserkosten müssen nach der HeizkostenV zu 50 bis 70 % nach Verbrauch verteilt werden."
                                       if meter_type in ("heating", "hot_water") else "So zahlt jede Partei, was sie verbraucht.")})

    # ── costs: this period and the one before ─────────────────────────────────
    key_name = {key.id: key.name for key in keys}
    cost_rows = [{"id": item.id, "description": item.description, "amount": item.amount, "category": item.cost_category,
                  "key_name": key_name.get(item.allocation_key_id), "is_recoverable": item.is_recoverable,
                  "consumption_share": item.consumption_share, "source_document_id": item.source_document_id,
                  "service_contract_invoice_id": item.service_contract_invoice_id} for item in items]
    previous = next((item for item in sorted(periods, key=lambda p: p.end_date, reverse=True)
                     if item.end_date < start and (period is None or item.id != period.id)), None)
    previous_rows = []
    if previous is not None:
        names = {_normal(item.description) for item in items}
        for item in store.list_cost_items():
            if item.billing_period_id != previous.id:
                continue
            previous_rows.append({"description": item.description, "amount": item.amount, "category": item.cost_category,
                                  "allocation_key_id": item.allocation_key_id, "key_name": key_name.get(item.allocation_key_id),
                                  "is_recoverable": item.is_recoverable, "consumption_share": item.consumption_share,
                                  "fixed_key_id": item.fixed_key_id, "missing": _normal(item.description) not in names})
        missing = [row for row in previous_rows if row["missing"] and row["is_recoverable"] is not False]
        if missing and period is not None:
            hints.add("costs", f"Im Vorjahr ({previous.label}) abgerechnet, hier noch nicht erfasst: "
                      + ", ".join(f"{row['description']} ({_money(row['amount'])})" for row in missing[:8])
                      + (" …" if len(missing) > 8 else "") + ".", "warning")
        totals = {item.description: item.amount for item in store.list_cost_items() if item.billing_period_id == previous.id}
        for row in cost_rows:
            last_year = totals.get(row["description"])
            if last_year and row["amount"] and abs(row["amount"] - last_year) / last_year > 0.25:
                hints.add("costs", f"„{row['description']}“ ist {'gestiegen' if row['amount'] > last_year else 'gesunken'}: "
                          f"{_money(last_year)} im Vorjahr, jetzt {_money(row['amount'])}. Rechnung prüfen.", "info")
    service = []
    for contract in store.list_service_contracts():
        locations = store.list_service_contract_locations(contract.id)
        if not any(location.property_id == property_id for location in locations):
            continue
        bills = [bill for bill in store.list_service_contract_invoices(contract.id)
                 if bill.period_start <= end and bill.period_end >= start]
        taken = {row["service_contract_invoice_id"] for row in cost_rows if row["service_contract_invoice_id"]}
        open_bills = [bill for bill in bills if bill.id not in taken]
        service.append({"id": contract.id, "title": contract.title, "bills": len(bills), "open": len(open_bills)})
        if open_bills and period is not None:
            hints.add("costs", f"Objektvertrag „{contract.title}“: {len(open_bills)} Rechnung(en) für den Zeitraum sind noch "
                      "nicht in der Abrechnung. In der Vertragsakte unter „Nebenkosten übernehmen“.", "warning",
                      f"/service-contracts/{contract.id}")

    # ── readings the consumption keys need ────────────────────────────────────
    keys_by_id = {key.id: key for key in keys}
    needed_types = {keys_by_id[key_id].meter_type for key_id in used_keys if key_id in keys_by_id
                    and keys_by_id[key_id].key_type == "consumption" and keys_by_id[key_id].meter_type}
    if not needed_types:
        needed_types = {key.meter_type for key in keys if key.key_type == "consumption" and key.meter_type}
    readings_by_meter: dict[str, list[Any]] = {}
    for reading in store.list_standalone_meter_readings():
        readings_by_meter.setdefault(reading.meter_id, []).append(reading)
    segments_of = {row["unit_id"]: row["segments"] for row in occupancy}
    needed = []
    for meter in meters:
        if meter.meter_type not in needed_types:
            continue
        first = max(start, meter.installation_date) if meter.installation_date else start
        last = min(end, meter.removal_date) if meter.removal_date else end
        if first > last:
            continue
        days = {first: "Beginn des Zeitraums" if first == start else "Einbau", last: "Ende des Zeitraums" if last == end else "Ausbau"}
        rows = segments_of.get(meter.unit_id, [])
        for before, after in zip(rows, rows[1:]):
            out = date.fromisoformat(before["end"])
            if first <= out <= last:
                days.setdefault(out, f"Auszug {before['tenant']}" if before["kind"] == "tenancy" and before.get("tenant")
                                else f"Einzug {after.get('tenant') or 'neuer Mieter'}")
        for day, reason in sorted(days.items()):
            near = [reading for reading in readings_by_meter.get(meter.id, [])
                    if abs((reading.reading_date - day).days) <= READING_TOLERANCE_DAYS]
            best = min(near, key=lambda reading: abs((reading.reading_date - day).days)) if near else None
            needed.append({"meter_id": meter.id, "serial_number": meter.serial_number, "meter_type": meter.meter_type,
                           "meter_label": METER_TYPE_LABELS.get(meter.meter_type, meter.meter_type),
                           "unit_id": meter.unit_id, "unit_label": unit_label.get(meter.unit_id), "day": day.isoformat(),
                           "reason": reason, "present": best is not None,
                           "value": best.value if best else None, "reading_date": best.reading_date.isoformat() if best else None})
    missing_readings = [row for row in needed if not row["present"]]
    if missing_readings:
        moves = [row for row in missing_readings if row["reason"].startswith(("Auszug", "Einzug"))]
        hints.add("readings", f"{len(missing_readings)} Zählerstände fehlen"
                  + (f", davon {len(moves)} Zwischenablesungen beim Mieterwechsel" if moves else "")
                  + ". Ohne sie teilt die Abrechnung den Verbrauch nach Tagen auf.", "warning")
    # a typo, a unit mix-up or a leak shows as a jump: worth a look before it is billed
    unusual = []
    for meter in meters:
        if meter.meter_type in needed_types:
            for row in unusual_intervals(readings_by_meter.get(meter.id, [])):
                if start <= date.fromisoformat(row["reading_date"]) <= end + timedelta(days=READING_TOLERANCE_DAYS):
                    unusual.append((meter, row))
    if unusual:
        meter, row = unusual[0]
        hints.add("readings", f"{len(unusual)} auffällige{'r' if len(unusual) == 1 else ''} Zählerstand"
                  f"{'' if len(unusual) == 1 else 'e'} im Zeitraum, z. B. Zähler {meter.serial_number or meter.id[:8]} "
                  f"({unit_label.get(meter.unit_id, '')}) am {_fmt(date.fromisoformat(row['reading_date']))}: "
                  f"{row['warning']}. Bitte im Zählerverlauf prüfen, bevor abgerechnet wird.", "warning", "/meters")

    # ── situation hints ───────────────────────────────────────────────────────
    deadline = statement_deadline(end)
    days_left = (deadline - today).days
    if days_left < 0:
        hints.add("period", f"Die Abrechnungsfrist endete am {_fmt(deadline)} (§ 556 Abs. 3 BGB): Nachforderungen an "
                  "Wohnungsmieter sind ausgeschlossen, Guthaben bleiben zu erstatten.", "warning")
    else:
        hints.add("period", f"Die Abrechnung muss den Mietern bis {_fmt(deadline)} zugehen (§ 556 Abs. 3 BGB), "
                  f"noch {days_left} Tage.", "warning" if days_left <= 60 else "info")
    heat_meters = by_type.get("heating", [])
    heating_known = any((row.get("category") or "") in ("heating", "hot_water") or "heiz" in (row.get("description") or "").lower()
                        for row in cost_rows + previous_rows)
    if heat_meters:
        hints.add("keys", f"{len(heat_meters)} Heizkostenverteiler/Wärmezähler: Heizkosten nach der HeizkostenV zu 50 bis 70 % "
                  "nach Verbrauch verteilen, den Rest nach Fläche. Die Werte des Messdienstes lassen sich als Dokument einlesen.")
    elif heating_known:
        flats = len(residential)
        hints.add("keys", "Für die Heizkosten gibt es keine Verbrauchserfassung: Wird nicht nach Verbrauch verteilt, darf jeder "
                  "Mieter seinen Anteil um 15 % kürzen (§ 12 HeizkostenV)"
                  + (". Ausgenommen sind Häuser mit höchstens zwei Wohnungen, von denen der Vermieter eine bewohnt (§ 2 HeizkostenV)."
                     if flats <= 2 else "."), "warning")
    if changes:
        hints.add("occupancy", "Mieterwechsel im Zeitraum: " + "; ".join(
            f"{row['unit_label']} am {_fmt(date.fromisoformat(row['day']))} ({row['out']} → {row['in']})" for row in changes[:6])
            + ". Die Kosten werden tagesgenau geteilt.")
    if vacancy_days:
        vacant = [row["label"] for row in occupancy if any(segment["kind"] == "vacancy" for segment in row["segments"])]
        hints.add("occupancy", f"Leerstand in {', '.join(vacant[:6])} ({vacancy_days} Tage zusammen): Diesen Anteil trägt der "
                  "Vermieter; er wird nicht auf andere Mieter verteilt.")
    if overlaps:
        hints.add("occupancy", f"Verträge überschneiden sich in {', '.join(overlaps)}. Bitte Beginn und Ende prüfen.", "warning", "/contracts")
    no_area = [unit.label for unit in units if not unit.area_sqm and not _parking(unit)]
    if no_area:
        hints.add("occupancy", f"Ohne Fläche: {', '.join(no_area[:6])}. Für die Verteilung nach Fläche bitte eintragen.", "warning", "/units")
    parking = [unit.label for unit in units if _parking(unit)]
    if parking:
        hints.add("occupancy", f"{len(parking)} Stellplätze/Nebenräume ({', '.join(parking[:4])}): ohne Fläche nehmen sie an der "
                  "Flächenumlage nicht teil, an Personen nie.")
    commercial = [unit.label for unit in units if _commercial(unit)]
    if commercial:
        hints.add("occupancy", f"Gewerbe ({', '.join(commercial[:4])}): Die Ausschlussfrist für Nachforderungen gilt hier nicht; "
                  "bei Option zur Umsatzsteuer die Umsatzsteuer auf die Nebenkosten ausweisen.")
    no_persons = [row["label"] for row in occupancy if row["residential"] and row["rented_days"]
                  and all(segment["persons"] is None for segment in row["segments"] if segment["kind"] == "tenancy")]
    if no_persons and any(key.key_type == "person_count" for key in keys):
        hints.add("occupancy", f"Personenzahl fehlt bei {', '.join(no_persons[:6])}. Für die Verteilung nach Personen im "
                  "Vertrag (Personen im Haushalt) eintragen.", "warning", "/contracts")
    no_advance = [segment["contract_number"] for row in occupancy for segment in row["segments"]
                  if segment["kind"] == "tenancy" and segment["advances"] == 0]
    if no_advance:
        hints.add("occupancy", f"Ohne Vorauszahlung: {', '.join(no_advance[:6])}. Diese Mieter zahlen ihren ganzen Anteil nach.", "info")

    # ── the statement itself ──────────────────────────────────────────────────
    statements = []
    if period is not None:
        for row in store.list_utility_statements():
            if row.billing_period_id != period.id:
                continue
            contract = contract_by_id.get(row.contract_id) if row.contract_id else None
            statements.append({"id": row.id, "unit_id": row.unit_id, "unit_label": unit_label.get(row.unit_id), "party": row.party,
                               "tenant": tenants.get(contract.tenant_id) if contract else None,
                               "usage_start": row.usage_start.isoformat() if row.usage_start else None,
                               "usage_end": row.usage_end.isoformat() if row.usage_end else None, "usage_days": row.usage_days,
                               "total_cost": row.total_cost, "advance_paid": row.advance_paid, "balance": row.balance,
                               "status": row.status})
        statements.sort(key=lambda row: (row["unit_label"] or "", row["usage_start"] or ""))
    blockers = [issue.model_dump() for issue in checks.blockers] if checks is not None else []
    warnings = [issue.model_dump() for issue in checks.warnings] if checks is not None else []
    outdated = any(issue["code"] == "STATEMENTS_OUTDATED" for issue in warnings)
    recoverable = [row for row in cost_rows if row["is_recoverable"] is not False]
    steps = [
        {"key": "period", "label": "Objekt & Zeitraum", "done": period is not None},
        {"key": "occupancy", "label": "Nutzer & Zeiträume", "done": period is not None and not overlaps and not no_area},
        {"key": "keys", "label": "Verteilerschlüssel", "done": bool(keys) and not [row for row in suggested if row["key_type"] != "person_count"]},
        {"key": "costs", "label": "Kosten", "done": bool(recoverable)},
        {"key": "readings", "label": "Zählerstände", "done": not missing_readings},
        {"key": "check", "label": "Prüfen", "done": checks is not None and not blockers},
        {"key": "result", "label": "Abrechnen", "done": bool(statements) and not outdated},
    ]
    return {
        "property": {"id": prop.id, "name": prop.name, "address": ", ".join(filter(None, [prop.address_line,
                     " ".join(filter(None, [prop.postal_code, prop.city]))])) or None,
                     "units": len(units), "residential": len(residential), "commercial": len(commercial), "parking": len(parking),
                     "area_sqm": round(sum(unit.area_sqm or 0 for unit in units), 2),
                     "meters": {meter_type: len(group) for meter_type, group in by_type.items()}},
        "periods": [{"id": item.id, "label": item.label, "start_date": item.start_date.isoformat(), "end_date": item.end_date.isoformat(),
                     "status": item.status} for item in periods],
        "period": None if period is None else {"id": period.id, "label": period.label, "start_date": period.start_date.isoformat(),
                                               "end_date": period.end_date.isoformat(), "status": period.status},
        "suggested_period": proposal,
        "deadline": {"date": deadline.isoformat(), "days_left": days_left},
        "occupancy": {"units": occupancy, "changes": changes, "vacancy_days": vacancy_days},
        "keys": {"present": present, "suggested": suggested},
        "costs": {"items": cost_rows, "total": round(sum(row["amount"] or 0 for row in recoverable), 2),
                  "previous_period": None if previous is None else {"id": previous.id, "label": previous.label},
                  "previous": previous_rows, "service_contracts": service, "catalogue": [
                      {"category": category, "label": label, "key": key} for category, label, key in BETRKV]},
        "readings": {"needed": needed, "missing": len(missing_readings)},
        "checks": None if checks is None else {"blockers": blockers, "warnings": warnings, "metrics": checks.metrics},
        "statements": {"items": statements, "outdated": outdated,
                       "total_cost": round(sum(row["total_cost"] for row in statements), 2),
                       "advances": round(sum(row["advance_paid"] for row in statements), 2),
                       "balance": round(sum(row["balance"] for row in statements if row["party"] == "tenant"), 2)},
        "hints": hints.items,
        "steps": steps,
    }
