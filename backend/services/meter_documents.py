"""Documents of metering services (ista, Techem, Brunata-Metrona, Minol, KALO, …): read, propose, take over.

A heating cost statement, a reading report or an invoice of a metering service becomes a proposal:

- costs with their kind and the allocation key of the property they suggest (heating and hot water by
  the consumption key with the share the document names, water by the water meters or persons);
- meter readings, matched to the property's meters by their device number;
- the results per unit the service computed, for comparison with the app's own statement.

Two readers give the same shape (`Extraction`): local rules, always there and without any account, and
the AI of the person's connected Claude or ChatGPT account (`meter_documents_ai`). Nothing is stored by
reading. A person checks the proposal and takes over the rows they chose (`apply`): cost items of the
billing period whose source is the document, and meter readings, in one transaction.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from types import SimpleNamespace
from typing import Any, Optional

from fastapi import HTTPException

from ..domain.clock import local_today

KINDS = {"heating_statement": "Heizkostenabrechnung", "water_statement": "Wasserkostenabrechnung",
         "reading_report": "Ableseprotokoll", "invoice": "Rechnung des Messdienstes", "other": "Dokument"}
CATEGORIES = {"heating": "Heizkosten", "hot_water": "Warmwasser", "water": "Wasser und Abwasser",
              "electricity": "Allgemeinstrom", "other": "Sonstige Kosten"}

_COMPANIES = (("ista", r"\bista\b"), ("Techem", r"\btechem\b"), ("Brunata-Metrona", r"brunata|metrona"),
              ("Minol", r"\bminol\b"), ("KALO", r"\bkalo\b"), ("Qundis", r"\bqundis\b"),
              ("Kalorimeta", r"kalorimeta"), ("Noventic", r"\bnoventic\b"), ("WDV Wärmedienst", r"wärmedienst|wdv"))
_KINDS = (("heating_statement", r"heiz(?:ungs)?kosten[- ]*(?:und[- ]*warmwasserkosten[- ]*)?abrechnung|"
                                r"heiz-\s*und\s*warmwasserkosten|heizkostenaufteilung|wärmekostenabrechnung|"
                                r"gesamtabrechnung|abrechnung (?:der|über) (?:die )?heiz"),
          ("water_statement", r"wasserkostenabrechnung|kaltwasserabrechnung|abrechnung (?:der )?wasserkosten"),
          ("reading_report", r"ableseprotokoll|ablesebeleg|ableseergebnis|ableseliste|verbrauchswerte|zählerstände"),
          ("invoice", r"\brechnung\b|rechnungsnummer|rechnungs-nr"))
_DATE = r"(\d{1,2})\.(\d{1,2})\.(\d{2,4})"
_PERIOD = re.compile(rf"(?:abrechnungszeitraum|abrechnungsperiode|nutzungszeitraum|zeitraum|vom)\s*:?\s*{_DATE}"
                     rf"\s*(?:-|–|bis)\s*{_DATE}", re.I)
_PAIR = re.compile(rf"{_DATE}\s*(?:-|–|bis)\s*{_DATE}")
_READING_DAY = re.compile(rf"(?:ablesedatum|ablesetag|abgelesen am|stichtag|ablesung am|ablesung vom)\s*:?\s*{_DATE}", re.I)
_SPLIT = re.compile(r"(\d{2})\s*%\s*(?:der\s+kosten\s+)?(?:nach\s+)?(?:grundkosten|grundkostenanteil|festkosten|fläche)", re.I)
_SPLIT_USE = re.compile(r"(\d{2})\s*%\s*(?:der\s+kosten\s+)?(?:nach\s+)?(?:verbrauch|verbrauchskosten|verbrauchsanteil)", re.I)
_AMOUNT = re.compile(r"(-?\d{1,3}(?:\.\d{3})+,\d{2}|-?\d+,\d{2})\s*(?:€|EUR|Euro)?\s*$")
_NUMBER = re.compile(r"(?<![\d,.])-?\d{1,3}(?:\.\d{3})+(?:,\d+)?(?![\d,.])|(?<![\d,.])-?\d+(?:,\d+)?(?![\d,.])")
_TOTAL = re.compile(r"\b(summe|gesamtkosten|gesamtbetrag|kosten gesamt|gesamt)\b", re.I)
_NOT_A_COST = re.compile(r"\b(vorauszahlung|guthaben|nachzahlung|zu zahlen|ihr anteil|ihre kosten|anteil|mwst|ust|"
                         r"umsatzsteuer|netto|saldo|differenz|einheiten|übertrag|seite|datum|kundennummer|"
                         r"rechnungsnummer|liegenschaft)\b", re.I)
_UNIT_LINE = re.compile(r"\b(nutzeinheit|nutzer(?:-?nr)?|whg\.?|wohnung|ne)\b\s*(?:nr\.?)?\s*[:.-]?\s*(.+?)\s+"
                        r"(-?\d{1,3}(?:\.\d{3})+,\d{2}|-?\d+,\d{2})\s*(?:€|EUR)?\s*$", re.I)
_DEVICES = (("heating", "HKV", r"\bhkv\b|heizkostenverteiler|verdunster"),
            ("heating", "kWh", r"\bwmz\b|wärmemengenzähler|wärmezähler"),
            ("hot_water", "m³", r"\bwwz\b|warmwasserzähler|warmwasser"),
            ("cold_water", "m³", r"\bkwz\b|kaltwasserzähler|kaltwasser|wasserzähler"))
_SERIAL = re.compile(r"\b(?=[A-Z0-9]*\d{5})[A-Z0-9]{5,16}\b")
# in this order: hot water before water, water (also its meters and their service) before heating
_COSTS = (("hot_water", r"warmwasser|wassererwärmung"),
          ("water", r"wasser|kanal|niederschlag|entwässerung"),
          ("heating", r"brennstoff|heizöl|erdgas|\bgas\b|fernwärme|nahwärme|wärmeliefer|pellet|flüssiggas|holzhack|"
                      r"betriebsstrom|heizungsstrom|wartung|reinigung der (?:anlage|heizung)|immissionsmessung|"
                      r"emissionsmessung|schornsteinfeger|kaminkehrer|abgasmessung|verbrauchserfassung|messdienst|"
                      r"abrechnungs(?:service|gebühr|kosten|dienst)|erstellung der abrechnung|gerätemiete|\bmiete\b|eichung|"
                      r"eichkosten|heiz"),
          ("electricity", r"allgemeinstrom|hausstrom"))


def _day(day: str, month: str, year: str) -> Optional[date]:
    try:
        number = int(year)
        return date(number + 2000 if number < 100 else number, int(month), int(day))
    except ValueError:
        return None


def german_number(text: str) -> Optional[Decimal]:
    """'1.234,56' -> 1234.56, '12,345' -> 12.345 (comma is the decimal sign), '1.234' -> 1234."""
    value = text.strip().replace(" ", "").replace(" ", "")
    if "," in value:
        value = value.replace(".", "").replace(",", ".")
    elif re.fullmatch(r"-?\d{1,3}(?:\.\d{3})+", value):
        value = value.replace(".", "")
    try:
        return Decimal(value)
    except InvalidOperation:
        return None


def plain_number(value: Any) -> Optional[Decimal]:
    """A number as the AI gives it ("1234.56", 1234.56) or as a German text."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return Decimal(str(value))
    text = str(value).strip()
    if re.fullmatch(r"-?\d+(?:\.\d+)?", text):
        return Decimal(text)
    return german_number(text)


def serial_key(value: Optional[str]) -> str:
    return re.sub(r"[^A-Z0-9]", "", (value or "").upper()).lstrip("0")


def serial_keys(value: Optional[str]) -> set[str]:
    """The forms a device number is matched by: as written, and its digits alone ("WZ 0268" ~ "268")."""
    keys = {serial_key(value)}
    digits = re.sub(r"\D", "", value or "").lstrip("0")
    if len(digits) >= 6:
        keys.add(digits)
    return keys - {""}


@dataclass
class Extraction:
    company: Optional[str] = None
    kind: str = "other"
    period_start: Optional[date] = None
    period_end: Optional[date] = None
    reading_date: Optional[date] = None
    consumption_share: Optional[int] = None
    total: Optional[Decimal] = None
    costs: list[dict] = field(default_factory=list)            # label, amount, category, recoverable, line
    readings: list[dict] = field(default_factory=list)         # serial, device, medium, measure_unit, value, previous, consumption, date, line
    unit_results: list[dict] = field(default_factory=list)     # label, amount, line
    notes: list[str] = field(default_factory=list)


def _category(label: str) -> str:
    lowered = label.lower()
    for category, pattern in _COSTS:
        if re.search(pattern, lowered):
            return category
    return "other"


def _device(text: str) -> Optional[tuple[str, str]]:
    lowered = text.lower()
    for medium, unit, pattern in _DEVICES:
        if re.search(pattern, lowered):
            return medium, unit
    return None


def _numbers(text: str) -> list[Decimal]:
    without_dates = re.sub(_DATE, " ", text)
    return [number for number in (german_number(item) for item in _NUMBER.findall(without_dates)) if number is not None]


def _reading_values(numbers: list[Decimal]) -> tuple[Optional[Decimal], Optional[Decimal], Optional[Decimal], bool]:
    """(value, previous, consumption, sure) from the numbers after a device number on its line.

    Start, end and consumption side by side are recognised by their sum; a single number is the reading.
    """
    if not numbers:
        return None, None, None, False
    if len(numbers) >= 3:
        for index in range(len(numbers) - 2):
            previous, value, used = numbers[index:index + 3]
            if abs(value - previous - used) <= Decimal("0.01") and value >= previous:
                return value, previous, used, True
    if len(numbers) == 1:
        return numbers[0], None, None, True
    return numbers[-1], None, None, False


def extract_local(text: str, known_serials: Optional[set[str]] = None) -> Extraction:
    """Local rules for the usual layouts of metering services; the person checks every value."""
    result = Extraction()
    lowered = text.lower()
    for name, pattern in _COMPANIES:
        if re.search(pattern, lowered):
            result.company = name
            break
    for kind, pattern in _KINDS:
        if re.search(pattern, lowered):
            result.kind = kind
            break
    found = _PERIOD.search(text) or _PAIR.search(text)
    if found:
        start, end = _day(*found.groups()[:3]), _day(*found.groups()[3:])
        if start and end and start < end:
            result.period_start, result.period_end = start, end
    day = _READING_DAY.search(text)
    if day:
        result.reading_date = _day(*day.groups())
    use = _SPLIT_USE.search(text)
    base = _SPLIT.search(text)
    if use:
        result.consumption_share = int(use.group(1))
    elif base:
        result.consumption_share = 100 - int(base.group(1))
    known = known_serials or set()
    seen_serials: set[str] = set()
    for raw in text.splitlines():
        line = " ".join(raw.split())
        if not line:
            continue
        unit_line = _UNIT_LINE.search(line)
        if unit_line:
            amount = german_number(unit_line.group(3))
            if amount is not None:
                result.unit_results.append({"label": unit_line.group(2).strip(" :-"), "amount": amount, "line": line})
            continue
        # device rows: a known device number, or a device word with a number that looks like one
        serials = [token for token in _SERIAL.findall(line.upper()) if serial_key(token) in known] if known else []
        device = _device(line)
        if not serials and device:
            serials = [token for token in _SERIAL.findall(line.upper()) if not re.fullmatch(r"\d{1,2}", token)]
        if serials and (device or serial_key(serials[0]) in known):
            serial = serials[0]
            after = line[line.upper().index(serial) + len(serial):]
            value, previous, used, sure = _reading_values(_numbers(after))
            key = serial_key(serial)
            if value is not None and key not in seen_serials:
                seen_serials.add(key)
                medium, unit = device or (None, None)
                dated = re.search(_DATE, after)
                result.readings.append({"serial": serial, "medium": medium, "measure_unit": unit, "value": value,
                                        "previous": previous, "consumption": used, "sure": sure,
                                        "date": _day(*dated.groups()) if dated else None, "line": line})
            continue
        amount_match = _AMOUNT.search(line)
        if not amount_match:
            continue
        label = line[:amount_match.start()].strip(" .:-€")
        amount = german_number(amount_match.group(1))
        if amount is None or not re.search(r"[A-Za-zÄÖÜäöüß]{3}", label):
            continue
        if _TOTAL.search(label):
            if result.total is None and amount > 0:
                result.total = amount
            continue
        if _NOT_A_COST.search(label) or amount <= 0:
            continue
        label = re.sub(r"\s+\d+(?:,\d+)?\s*%.*$", "", label)[:120].strip(" .:-")
        result.costs.append({"label": label, "amount": amount, "category": _category(label), "recoverable": True,
                             "line": line})
    if result.total is not None and result.costs:
        listed = sum((cost["amount"] for cost in result.costs), Decimal("0"))
        if abs(listed - result.total) > Decimal("0.05"):
            result.notes.append(f"Die erkannten Kostenpositionen ergeben {_money(listed)}, das Dokument nennt als "
                                f"Summe {_money(result.total)}. Bitte die Positionen mit dem Original vergleichen.")
    return result


def _money(value: Decimal) -> str:
    text = f"{value:,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")
    return f"{text} €"


# ─── The property's side: meters, units, keys ────────────────────────────────

def _normal(text: str) -> str:
    return re.sub(r"[^a-z0-9äöüß]", "", (text or "").lower())


@dataclass
class PropertyFacts:
    property_id: str
    units: list[Any]
    meters: list[Any]
    keys: list[Any]
    tenants: dict[str, str]          # unit id -> tenant names in the period
    preferred: set[str] = field(default_factory=set)   # keys the period's cost items use
    year: Optional[int] = None

    def pick(self, candidates: list[Any]) -> Any:
        """Of several keys of one kind ("Personen 2023", "Personen 2025"): the one the period uses, else the one
        named after its year, else the newest."""
        if not candidates:
            return None
        used = [key for key in candidates if key.id in self.preferred]
        if used:
            return used[0]
        named = [key for key in candidates if self.year and str(self.year) in (key.name or "")]
        if named:
            return named[0]
        return max(candidates, key=lambda key: (getattr(key, "created_at", None) or 0, key.name or ""))


def property_facts(store: Any, property_id: str, start: Optional[date] = None, end: Optional[date] = None) -> PropertyFacts:
    units = [unit for unit in store.list_units() if unit.property_id == property_id]
    unit_ids = {unit.id for unit in units}
    meters = [meter for meter in store.list_meters() if meter.unit_id in unit_ids]
    keys = [key for key in store.list_allocation_keys() if key.property_id == property_id]
    tenants: dict[str, str] = {}
    names = {tenant.id: tenant.full_name for tenant in store.list_tenants()}
    for contract in store.list_contracts():
        if contract.unit_id not in unit_ids:
            continue
        if start and end and (contract.start_date > end or (contract.end_date and contract.end_date < start)):
            continue
        name = names.get(contract.tenant_id)
        if name:
            tenants[contract.unit_id] = ", ".join(filter(None, [tenants.get(contract.unit_id), name]))
    return PropertyFacts(property_id, units, meters, keys, tenants)


def _match_unit(label: str, facts: PropertyFacts) -> Optional[str]:
    wanted = _normal(label)
    if not wanted:
        return None
    hits = [unit.id for unit in facts.units if _normal(unit.label) and (_normal(unit.label) in wanted or wanted in _normal(unit.label))]
    if len(hits) != 1:
        hits = [unit_id for unit_id, names in facts.tenants.items()
                if any(_normal(part.split()[-1]) and _normal(part.split()[-1]) in wanted for part in names.split(", ") if part.split())]
    return hits[0] if len(hits) == 1 else None


def suggest_key(category: str, facts: PropertyFacts, share: Optional[int]) -> dict:
    """The key a cost of this kind goes by in this property, and why (shown beside the choice)."""
    def kind(key_type: str, meter_type: Optional[str] = None) -> Any:
        return facts.pick([key for key in facts.keys if key.key_type == key_type
                           and (meter_type is None or key.meter_type == meter_type)])

    consumption = {medium: kind("consumption", medium) for medium in ("heating", "hot_water", "cold_water")}
    consumption = {medium: key for medium, key in consumption.items() if key is not None}
    area, persons = kind("area_sqm"), kind("person_count")
    if category in ("heating", "hot_water"):
        key = consumption.get(category) or consumption.get("heating")
        if key is not None:
            percent = share if share and 50 <= share <= 70 else 70
            return {"allocation_key_id": key.id, "consumption_share": percent,
                    "fixed_key_id": area.id if area else None,
                    "reason": f"{percent} % nach Verbrauch ({key.name}), der Rest nach "
                              f"{area.name if area else 'Fläche'} (HeizkostenV §§ 7, 8)"}
        return {"allocation_key_id": area.id if area else None, "consumption_share": None, "fixed_key_id": None,
                "reason": "Kein Verbrauchsschlüssel für Heizung angelegt: verteilt nach Fläche. Nach der HeizkostenV "
                          "müssen 50 bis 70 % nach Verbrauch verteilt werden, sonst darf um 15 % gekürzt werden."}
    if category == "water":
        key = consumption.get("cold_water") or persons or area
        reason = ("nach dem Verbrauch der Wasserzähler" if key is consumption.get("cold_water") and key is not None
                  else "nach Personen" if key is persons and key is not None else "nach Fläche")
        return {"allocation_key_id": key.id if key else None, "consumption_share": None, "fixed_key_id": None,
                "reason": reason}
    return {"allocation_key_id": area.id if area else None, "consumption_share": None, "fixed_key_id": None,
            "reason": "nach Fläche"}


def proposal(store: Any, document: Any, extraction: Extraction, *, property_id: str, period: Any = None,
             reader: str = "local") -> dict:
    """The proposal a person checks: costs with keys, readings matched to meters, results per unit."""
    facts = property_facts(store, property_id, period.start_date if period else extraction.period_start,
                           period.end_date if period else extraction.period_end)
    existing = [item for item in store.list_cost_items() if period is not None and item.billing_period_id == period.id]
    facts.preferred = {item.allocation_key_id for item in existing}
    end = period.end_date if period is not None else extraction.period_end
    facts.year = end.year if end else None
    unit_label = {unit.id: unit.label for unit in facts.units}
    by_serial: dict[str, Any] = {}
    for meter in facts.meters:
        for key in serial_keys(meter.serial_number):
            by_serial.setdefault(key, meter)
    notes = list(extraction.notes)
    default_day = extraction.reading_date or extraction.period_end or (period.end_date if period else None)
    costs = []
    for cost in extraction.costs:
        suggestion = suggest_key(cost["category"], facts, extraction.consumption_share)
        costs.append({"description": cost["label"], "amount": float(cost["amount"]), "cost_category": cost["category"],
                      "category_label": CATEGORIES.get(cost["category"], cost["category"]),
                      "is_recoverable": bool(cost.get("recoverable", True)), **suggestion, "line": cost.get("line")})
    readings = []
    for reading in extraction.readings:
        meter = next((by_serial[key] for key in serial_keys(reading.get("serial")) if key in by_serial), None)
        day = reading.get("date") or default_day
        readings.append({
            "serial": reading.get("serial"), "meter_id": meter.id if meter else None,
            "meter_label": f"{unit_label.get(meter.unit_id, '')} · {meter.serial_number}" if meter else None,
            "unit_id": meter.unit_id if meter else None, "medium": reading.get("medium") or (meter.meter_type if meter else None),
            "measure_unit": reading.get("measure_unit") or (meter.measure_unit if meter else None),
            "value": float(reading["value"]), "previous": float(reading["previous"]) if reading.get("previous") is not None else None,
            "consumption": float(reading["consumption"]) if reading.get("consumption") is not None else None,
            "reading_date": day.isoformat() if day else None, "sure": bool(reading.get("sure", True)),
            "line": reading.get("line")})
    imported = {cost["category"] for cost in extraction.costs}
    for category in sorted(imported):
        same = [item for item in existing if (item.cost_category or _category(item.description or "")) == category]
        if same:
            listed = ", ".join(f"„{item.description}“ ({_money(Decimal(str(item.amount)))})" for item in same[:3])
            notes.append(f"In dieser Periode gibt es schon {CATEGORIES.get(category, category)}: {listed}. Bitte prüfen, "
                         "ob das Dokument dieselben Kosten enthält; sonst würden sie doppelt umgelegt.")
    unmatched = [str(item["serial"]) for item in readings if not item["meter_id"]]
    if unmatched:
        notes.append(f"{len(unmatched)} Gerätenummern gehören zu keinem Zähler dieser Immobilie "
                     f"({', '.join(unmatched[:5])}{' …' if len(unmatched) > 5 else ''}). Bitte zuordnen oder auslassen.")
    if any(not item["sure"] for item in readings):
        notes.append("Bei einigen Zeilen war der Ablesewert nicht eindeutig; diese sind markiert.")
    if extraction.kind == "heating_statement" and not any(key.key_type == "consumption" for key in facts.keys):
        notes.append("Für diese Immobilie gibt es noch keinen Verbrauchsschlüssel. Im Nebenkosten-Assistenten "
                     "lässt er sich mit einem Klick anlegen.")
    if period is not None and extraction.period_start and extraction.period_end and (
            extraction.period_start != period.start_date or extraction.period_end != period.end_date):
        notes.append(f"Das Dokument gilt für {extraction.period_start:%d.%m.%Y} bis {extraction.period_end:%d.%m.%Y}, die "
                     f"Abrechnungsperiode für {period.start_date:%d.%m.%Y} bis {period.end_date:%d.%m.%Y}.")
    units = [{"label": item["label"], "amount": float(item["amount"]), "unit_id": _match_unit(item["label"], facts),
              "unit_label": unit_label.get(_match_unit(item["label"], facts) or "")} for item in extraction.unit_results]
    return {
        "document": {"id": document.id, "title": document.title},
        "reader": reader, "company": extraction.company, "kind": extraction.kind,
        "kind_label": KINDS.get(extraction.kind, "Dokument"),
        "period_start": extraction.period_start.isoformat() if extraction.period_start else None,
        "period_end": extraction.period_end.isoformat() if extraction.period_end else None,
        "reading_date": extraction.reading_date.isoformat() if extraction.reading_date else None,
        "consumption_share": extraction.consumption_share,
        "total": float(extraction.total) if extraction.total is not None else None,
        "costs": costs, "readings": readings, "unit_results": units, "notes": notes,
        "keys": [{"id": key.id, "name": key.name, "key_type": key.key_type, "meter_type": key.meter_type} for key in facts.keys],
        "meters": [{"id": meter.id, "label": f"{unit_label.get(meter.unit_id, '')} · {meter.serial_number or meter.id[:8]}",
                    "meter_type": meter.meter_type, "unit_id": meter.unit_id} for meter in facts.meters],
    }


def extraction_dict(extraction: Extraction) -> dict:
    return asdict(extraction)


# ─── Taking over ─────────────────────────────────────────────────────────────

def apply(store: Any, document: Any, *, period: Any, property_id: str, costs: list[dict], readings: list[dict],
          actor: Any = None) -> dict:
    """Cost items (source: the document) and meter readings, after every check, in one transaction."""
    from ..models import CostItemCreate, StandaloneMeterReadingCreate
    from .billing_writes import billing_write
    from .meter_history import order_problem

    facts = property_facts(store, property_id)
    keys = {key.id: key for key in facts.keys}
    meters = {meter.id: meter for meter in facts.meters}
    if costs:
        if period is None:
            raise HTTPException(422, "Für Kosten bitte eine Abrechnungsperiode wählen.")
        already = [item for item in store.list_cost_items()
                   if item.billing_period_id == period.id and item.source_document_id == document.id]
        if already:
            raise HTTPException(409, f"Aus diesem Dokument wurden in dieser Periode schon {len(already)} Kostenpositionen "
                                     "übernommen. Bitte dort prüfen, statt sie ein zweites Mal anzulegen.")
        for cost in costs:
            if cost["allocation_key_id"] not in keys:
                raise HTTPException(422, f"„{cost['description']}“: der Verteilerschlüssel gehört nicht zu dieser Immobilie.")
            if cost.get("fixed_key_id") and cost["fixed_key_id"] not in keys:
                raise HTTPException(422, f"„{cost['description']}“: der Schlüssel der Grundkosten gehört nicht zu dieser Immobilie.")
            if cost.get("consumption_share") and keys[cost["allocation_key_id"]].key_type != "consumption":
                raise HTTPException(422, f"„{cost['description']}“: ein Verbrauchsanteil braucht einen Verbrauchsschlüssel.")
    existing: dict[tuple[str, date], float] = {}
    stored = [reading for reading in store.list_standalone_meter_readings() if reading.meter_id in meters]
    for reading in stored:
        existing[(reading.meter_id, reading.reading_date)] = reading.value
    new_readings, skipped, conflicts, out_of_order = [], 0, [], []
    latest = local_today() + timedelta(days=1)
    # in date order, so a document's own readings are checked against each other too
    for reading in sorted(readings, key=lambda item: (item["reading_date"], item["value"])):
        meter = meters.get(reading["meter_id"])
        if meter is None:
            raise HTTPException(422, "Ein Zählerstand gehört zu keinem Zähler dieser Immobilie.")
        day = reading["reading_date"]
        if day > latest:
            raise HTTPException(422, f"Zähler {meter.serial_number or meter.id[:8]}: der Ablesetag {day:%d.%m.%Y} liegt in der Zukunft.")
        known = existing.get((meter.id, day))
        if known is not None:
            if abs(known - reading["value"]) < 1e-9:
                skipped += 1
                continue
            conflicts.append(f"{meter.serial_number or meter.id[:8]} am {day:%d.%m.%Y}: gespeichert {known:g}, im Dokument {reading['value']:g}")
            continue
        order = order_problem(stored, meter.id, day, reading["value"])
        if order:
            out_of_order.append(f"{meter.serial_number or meter.id[:8]} am {day:%d.%m.%Y}: {order}")
            continue
        new_readings.append((meter, day, reading["value"]))
        existing[(meter.id, day)] = reading["value"]
        stored.append(SimpleNamespace(id=f"document-{len(new_readings)}", meter_id=meter.id, reading_date=day,
                                      value=reading["value"]))
    if conflicts:
        raise HTTPException(409, "Für diese Tage sind schon andere Zählerstände gespeichert: " + "; ".join(conflicts[:10])
                            + ". Bitte die Zeilen prüfen oder abwählen.")
    if out_of_order:
        raise HTTPException(422, "Diese Zählerstände passen nicht zu den gespeicherten Ablesungen: "
                            + " ".join(out_of_order[:10]))
    note = f"aus „{document.title}“"[:200]
    recorded_by = getattr(actor, "full_name", None) or getattr(actor, "username", None)
    with billing_write(store, [period.id] if period is not None else []):
        created = [store.create_cost_item(CostItemCreate(
            billing_period_id=period.id, description=cost["description"], amount=round(cost["amount"], 2),
            allocation_key_id=cost["allocation_key_id"], is_recoverable=cost.get("is_recoverable", True),
            cost_category=cost.get("cost_category"), source_document_id=document.id,
            consumption_share=cost.get("consumption_share"), fixed_key_id=cost.get("fixed_key_id"))).id
            for cost in costs]
        for meter, day, value in new_readings:
            store.create_standalone_meter_reading(StandaloneMeterReadingCreate(
                meter_id=meter.id, reading_date=day, value=value, recorded_by=recorded_by, notes=note))
    return {"cost_items": created, "readings_created": len(new_readings), "readings_skipped": skipped}
