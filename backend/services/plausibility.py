"""Plausibility checks for what users enter (create, replace, change).

They run before the endpoint, on the JSON body, so records already stored are never
rejected when they are read. For a change (PATCH/PUT) the rules see the stored record
merged with the new values, so cross-field rules (gross = net + VAT, a unit inside its
property) also hold after partial edits.

A failed check raises storage.ValidationError: 400 with a German message.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any, Callable, Optional

from ..storage import NotFoundError, ValidationError

PROPERTY_TYPES = {"residential", "commercial", "mixed", "condominium", "single_family", "multi_family", "office",
                  "land", "parking", "other"}
KEY_TYPES = {"area_sqm", "unit_count", "person_count", "consumption"}
PRIORITIES = {"low", "medium", "high", "urgent"}
CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


class Record(dict):
    """The data a rule sees; `touched` are the fields this request sets.

    Field rules only look at touched fields, so an old record that would fail a newer rule
    can still be changed elsewhere. Cross-field rules see the whole merged record.
    """

    def __init__(self, data: dict, touched: set):
        super().__init__(data)
        self.touched = touched


def _touched(data: dict, key: str) -> bool:
    return key in data and key in getattr(data, "touched", data)


def _text(data: dict, key: str, label: str, required: bool = False) -> None:
    if not _touched(data, key):
        return
    value = data[key]
    if value is None:
        if required:
            raise ValidationError(f"{label} fehlt")
        return
    if not isinstance(value, str):
        return
    if required and not value.strip():
        raise ValidationError(f"{label} darf nicht leer sein")
    if CONTROL.search(value):
        raise ValidationError(f"{label} enthält unzulässige Steuerzeichen")


def _not_negative(data: dict, keys: dict[str, str]) -> None:
    for key, label in keys.items():
        if not _touched(data, key):
            continue
        value = data.get(key)
        if isinstance(value, bool):
            raise ValidationError(f"{label}: bitte eine Zahl angeben")
        if isinstance(value, (int, float)) and value < 0:
            raise ValidationError(f"{label} darf nicht negativ sein")


def _number(data: dict, keys: dict[str, str]) -> None:
    for key, label in keys.items():
        if _touched(data, key) and isinstance(data.get(key), bool):
            raise ValidationError(f"{label}: bitte eine Zahl angeben, nicht ja/nein")


def _day(value: Any) -> Optional[date]:
    if isinstance(value, date):
        return value
    if isinstance(value, str) and len(value) >= 10:
        try:
            return date.fromisoformat(value[:10])
        except ValueError:
            return None
    return None


def _one_of(data: dict, key: str, allowed: set, label: str) -> None:
    if not _touched(data, key):
        return
    value = data.get(key)
    if value is not None and value not in allowed:
        raise ValidationError(f"{label} „{value}“ ist unbekannt. Erlaubt: {', '.join(sorted(allowed))}")


def _get(getter: Callable[[str], Any], entity_id: Any) -> Any:
    if not entity_id:
        return None
    try:
        return getter(entity_id)
    except NotFoundError:
        return None


# --- rules: (merged data, store) ---------------------------------------------------------------

def unit(data: dict, store: Any) -> None:
    _text(data, "label", "Die Bezeichnung", required=True)
    _not_negative(data, {"cold_rent": "Die Kaltmiete", "service_charge_advance": "Die NK-Vorauszahlung",
                         "heating_advance": "Die Heizkosten-Vorauszahlung", "person_count": "Die Personenzahl",
                         "rooms": "Die Zimmerzahl"})


def tenant(data: dict, store: Any) -> None:
    _text(data, "full_name", "Der Name", required=True)
    for key, label in [("address_line", "Die Straße"), ("city", "Der Ort"), ("notes", "Die Notiz")]:
        _text(data, key, label)


def property_(data: dict, store: Any) -> None:
    _text(data, "name", "Der Name", required=True)
    _one_of(data, "property_type", PROPERTY_TYPES, "Der Objekttyp")
    year = data.get("year_built") if _touched(data, "year_built") else None
    if isinstance(year, int) and not 1000 <= year <= date.today().year + 5:
        raise ValidationError(f"Baujahr {year} ist nicht plausibel")
    _not_negative(data, {"living_area_sqm": "Die Wohnfläche", "usable_area_sqm": "Die Nutzfläche",
                         "plot_area_sqm": "Die Grundstücksfläche", "purchase_price": "Der Kaufpreis",
                         "market_value": "Der Marktwert"})


def booking(data: dict, store: Any) -> None:
    _number(data, {"amount": "Der Betrag"})
    day = _day(data.get("booking_date")) if _touched(data, "booking_date") else None
    if day and not 1950 <= day.year <= date.today().year + 10:
        raise ValidationError(f"Buchungsdatum {day:%d.%m.%Y} ist nicht plausibel")
    unit_obj = _get(store.get_unit, data.get("unit_id"))
    if unit_obj and data.get("property_id") and unit_obj.property_id != data["property_id"]:
        raise ValidationError("Die Einheit gehört nicht zur gewählten Immobilie")


def rent_adjustment(data: dict, store: Any) -> None:
    _not_negative(data, {"new_rent": "Die neue Miete", "previous_rent": "Die bisherige Miete"})
    contract = _get(store.get_contract, data.get("contract_id"))
    day = _day(data.get("effective_date"))
    if contract and day and day < contract.start_date:
        raise ValidationError(f"Die Anpassung kann nicht vor Vertragsbeginn ({contract.start_date:%d.%m.%Y}) wirksam "
                              "werden")


def invoice(data: Record, store: Any) -> None:
    _number(data, {"net_amount": "Der Nettobetrag", "gross_amount": "Der Bruttobetrag"})
    rate = data.get("vat_rate")
    if _touched(data, "vat_rate") and isinstance(rate, (int, float)) and not 0 <= rate <= 100:
        raise ValidationError(f"MwSt-Satz {rate} % ist nicht plausibel")
    if not {"net_amount", "gross_amount", "vat_amount", "vat_rate"} & data.touched:
        return
    net, gross, vat = data.get("net_amount"), data.get("gross_amount"), data.get("vat_amount")
    if isinstance(net, (int, float)) and isinstance(gross, (int, float)):
        if isinstance(vat, (int, float)) and vat:
            expected = float(net + vat)
        elif isinstance(rate, (int, float)):
            expected = net * (1 + rate / 100)
        else:
            return
        if abs(expected - gross) > 0.05:
            raise ValidationError(f"Brutto {gross:.2f} € passt nicht zu Netto {net:.2f} € und MwSt "
                                  f"(erwartet {expected:.2f} €)")


def maintenance(data: dict, store: Any) -> None:
    _text(data, "title", "Der Titel", required=True)
    _not_negative(data, {"estimated_cost": "Die Kosten"})
    _one_of(data, "priority", PRIORITIES, "Die Priorität")


def task(data: dict, store: Any) -> None:
    _text(data, "title", "Der Titel", required=True)
    _one_of(data, "priority", PRIORITIES, "Die Priorität")


def allocation_key(data: dict, store: Any) -> None:
    _text(data, "name", "Der Name", required=True)
    _one_of(data, "key_type", KEY_TYPES, "Die Schlüsselart")


def meter_reading(data: dict, store: Any) -> None:
    value = data.get("value")
    _not_negative(data, {"value": "Der Zählerstand"})
    day = _day(data.get("reading_date"))
    if day and day > date.today():
        raise ValidationError("Eine Ablesung kann nicht in der Zukunft liegen")
    if not isinstance(value, (int, float)) or not day or not data.get("meter_id"):
        return
    earlier = [r for r in store.list_standalone_meter_readings()
               if r.meter_id == data["meter_id"] and r.reading_date <= day and r.id != data.get("id")]
    if earlier:
        last = max(earlier, key=lambda r: r.reading_date)
        if value < last.value:
            raise ValidationError(f"Zählerstand {value:g} ist kleiner als der Stand {last.value:g} vom "
                                  f"{last.reading_date:%d.%m.%Y}. Bei einem Zählerwechsel bitte einen neuen Zähler "
                                  "anlegen.")


# path pattern (relative to /api/v1) -> (rule, getter of the stored record for changes)
RULES: list[tuple[re.Pattern, Callable, Optional[str]]] = [
    (re.compile(r"^/units(?:/(?P<id>[^/]+))?$"), unit, "get_unit"),
    (re.compile(r"^/tenants(?:/(?P<id>[^/]+))?$"), tenant, "get_tenant"),
    (re.compile(r"^/properties(?:/(?P<id>[^/]+))?$"), property_, "get_property"),
    (re.compile(r"^/bookings(?:/(?P<id>[^/]+))?$"), booking, "get_booking"),
    (re.compile(r"^/rent-adjustments(?:/(?P<id>[^/]+))?$"), rent_adjustment, "get_rent_adjustment"),
    (re.compile(r"^/invoices(?:/(?P<id>[^/]+))?$"), invoice, "get_invoice"),
    (re.compile(r"^/maintenance(?:/(?P<id>[^/]+))?$"), maintenance, "get_maintenance_case"),
    (re.compile(r"^/tasks(?:/(?P<id>[^/]+))?$"), task, "get_task"),
    (re.compile(r"^/billing/allocation-keys(?:/(?P<id>[^/]+))?$"), allocation_key, "get_allocation_key"),
    (re.compile(r"^/meters/(?P<meter>[^/]+)/readings$"), meter_reading, None),
]


def check(method: str, path: str, body: Any, store: Any) -> None:
    if not isinstance(body, dict):
        return
    for pattern, rule, getter in RULES:
        match = pattern.match(path)
        if not match:
            continue
        data = Record(body, set(body))
        groups = match.groupdict()
        if groups.get("meter"):
            data["meter_id"] = groups["meter"]
        if method in ("PATCH", "PUT") and groups.get("id") and getter and hasattr(store, getter):
            existing = _get(getattr(store, getter), groups["id"])
            if existing is not None:
                data = Record({**existing.model_dump(), **body}, set(body))
        rule(data, store)
        return
