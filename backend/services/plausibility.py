"""Plausibility checks for what users enter (create, replace, change).

They run before the endpoint, on the JSON body, so records already stored are never
rejected when they are read. For a change (PATCH/PUT) the rules see the stored record
merged with the new values, so cross-field rules (gross = net + VAT, a unit inside its
property) also hold after partial edits.

A failed check raises storage.ValidationError: 400 with a German message.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timezone
from typing import Any, Callable, Optional

from ..storage import NotFoundError, ValidationError

PROPERTY_TYPES = {"residential", "commercial", "mixed", "condominium", "single_family", "multi_family", "office",
                  "land", "parking", "other"}
KEY_TYPES = {"area_sqm", "unit_count", "person_count", "consumption"}
PRIORITIES = {"low", "medium", "high", "urgent"}
PAYMENT_METHODS = {"bank_transfer", "sepa_direct_debit", "cash"}
MARKUP = re.compile(r"<\s*/?\s*[a-zA-Z][^>]*>")
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


def _at_most(data: dict, keys: dict[str, tuple[str, float]]) -> None:
    """Upper bounds against typos with too many digits (1 Billion € rent, 10 Mio. m²)."""
    for key, (label, limit) in keys.items():
        value = data.get(key)
        if _touched(data, key) and isinstance(value, (int, float)) and not isinstance(value, bool) \
                and abs(value) > limit:
            raise ValidationError(f"{label} {value:,.0f} ist nicht plausibel (höchstens {limit:,.0f})".replace(",", "."))


def _no_markup(data: dict, key: str, label: str) -> None:
    """Names are printed in letters, PDFs and e-mails: no HTML tags (a pasted script, a broken copy)."""
    value = data.get(key)
    if _touched(data, key) and isinstance(value, str) and MARKUP.search(value):
        raise ValidationError(f"{label} enthält HTML-Code (< >); bitte nur den Text eintragen")


def _max_length(data: dict, key: str, label: str, limit: int = 200) -> None:
    value = data.get(key)
    if _touched(data, key) and isinstance(value, str) and len(value) > limit:
        raise ValidationError(f"{label} ist zu lang (höchstens {limit} Zeichen)")


def iban_valid(iban: str) -> bool:
    compact = re.sub(r"\s+", "", iban).upper()
    if not re.fullmatch(r"[A-Z]{2}\d{2}[A-Z0-9]{11,30}", compact):
        return False
    digits = "".join(str(int(ch, 36)) for ch in compact[4:] + compact[:4])
    return int(digits) % 97 == 1


def _positive(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0


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
    _max_length(data, "label", "Die Bezeichnung")
    _at_most(data, {"area_sqm": ("Die Fläche", 100_000), "cold_rent": ("Die Kaltmiete", 10_000_000),
                    "service_charge_advance": ("Die NK-Vorauszahlung", 1_000_000),
                    "heating_advance": ("Die Heizkosten-Vorauszahlung", 1_000_000), "rooms": ("Die Zimmerzahl", 500),
                    "person_count": ("Die Personenzahl", 1_000)})
    _not_negative(data, {"cold_rent": "Die Kaltmiete", "service_charge_advance": "Die NK-Vorauszahlung",
                         "heating_advance": "Die Heizkosten-Vorauszahlung", "person_count": "Die Personenzahl",
                         "rooms": "Die Zimmerzahl"})
    _no_markup(data, "label", "Die Bezeichnung")
    rooms: Any = data.get("rooms")
    area: Any = data.get("area_sqm")
    if (_touched(data, "rooms") or _touched(data, "area_sqm")) and _positive(rooms) and _positive(area) \
            and float(rooms) > 1 and float(area) / float(rooms) < 5:     # one room may be a tiny storeroom
        raise ValidationError(f"{rooms:g} Zimmer auf {area:g} m² sind nicht plausibel (weniger als 5 m² je Zimmer)")


def tenant(data: dict, store: Any) -> None:
    _text(data, "full_name", "Der Name", required=True)
    _max_length(data, "full_name", "Der Name")
    _no_markup(data, "full_name", "Der Name")
    _one_of(data, "payment_method", PAYMENT_METHODS, "Die Zahlungsart")
    phone = data.get("phone")
    if _touched(data, "phone") and isinstance(phone, str) and phone.strip() and not re.search(r"\d", phone):
        raise ValidationError("Die Telefonnummer enthält keine Ziffern")
    for key, label in [("address_line", "Die Straße"), ("city", "Der Ort"), ("notes", "Die Notiz")]:
        _text(data, key, label)


def property_(data: dict, store: Any) -> None:
    _text(data, "name", "Der Name", required=True)
    _no_markup(data, "name", "Der Name")
    _one_of(data, "property_type", PROPERTY_TYPES, "Der Objekttyp")
    year = data.get("year_built") if _touched(data, "year_built") else None
    if isinstance(year, int) and not 1000 <= year <= date.today().year + 5:
        raise ValidationError(f"Baujahr {year} ist nicht plausibel")
    _max_length(data, "name", "Der Name")
    code, country = data.get("postal_code"), (data.get("country") or "DE").strip().upper()
    if _touched(data, "postal_code") and isinstance(code, str) and code.strip() and country in ("DE", "DEU", "DEUTSCHLAND") \
            and not re.fullmatch(r"\d{5}", code.strip()):
        raise ValidationError(f"Postleitzahl „{code}“: in Deutschland fünf Ziffern")
    _not_negative(data, {"living_area_sqm": "Die Wohnfläche", "usable_area_sqm": "Die Nutzfläche",
                         "plot_area_sqm": "Die Grundstücksfläche", "purchase_price": "Der Kaufpreis",
                         "market_value": "Der Marktwert"})


def booking(data: dict, store: Any) -> None:
    _number(data, {"amount": "Der Betrag"})
    _at_most(data, {"amount": ("Der Betrag", 1_000_000_000)})
    day = _day(data.get("booking_date")) if _touched(data, "booking_date") else None
    if day and not 1950 <= day.year <= date.today().year + 10:
        raise ValidationError(f"Buchungsdatum {day:%d.%m.%Y} ist nicht plausibel")
    unit_obj = _get(store.get_unit, data.get("unit_id"))
    if unit_obj and data.get("property_id") and unit_obj.property_id != data["property_id"]:
        raise ValidationError("Die Einheit gehört nicht zur gewählten Immobilie")


def contract(data: dict, store: Any) -> None:
    start = _day(data.get("start_date")) if _touched(data, "start_date") else None
    if start and not 1900 <= start.year <= date.today().year + 5:
        raise ValidationError(f"Vertragsbeginn {start:%d.%m.%Y} ist nicht plausibel")
    end = _day(data.get("end_date")) if _touched(data, "end_date") else None
    if end and end.year > date.today().year + 100:
        raise ValidationError(f"Vertragsende {end:%d.%m.%Y} ist nicht plausibel; ohne Ende bitte leer lassen")


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


def account(data: dict, store: Any) -> None:
    _text(data, "name", "Der Name", required=True)
    iban = data.get("iban")
    if _touched(data, "iban") and isinstance(iban, str) and iban.strip() and not iban_valid(iban):
        raise ValidationError("Die IBAN ist ungültig (Prüfziffer oder Länge stimmt nicht)")


def rent_period(data: dict, store: Any) -> None:
    _not_negative(data, {"cold_rent": "Die Kaltmiete", "service_charge_advance": "Die NK-Vorauszahlung",
                         "heating_advance": "Die Heizkosten-Vorauszahlung"})
    _at_most(data, {"cold_rent": ("Die Kaltmiete", 10_000_000)})
    day = _day(data.get("valid_from"))
    if day and day.day != 1:
        # rent is charged per calendar month; a change in the middle would only count from the next month
        raise ValidationError("Ein Mietstand gilt ab dem 1. eines Monats")


# path pattern (relative to /api/v1) -> (rule, getter of the stored record for changes)
RULES: list[tuple[re.Pattern, Callable, Optional[str]]] = [
    (re.compile(r"^/units(?:/(?P<id>[^/]+))?$"), unit, "get_unit"),
    (re.compile(r"^/tenants(?:/(?P<id>[^/]+))?$"), tenant, "get_tenant"),
    (re.compile(r"^/contracts(?:/(?P<id>[^/]+))?$"), contract, "get_contract"),
    (re.compile(r"^/properties(?:/(?P<id>[^/]+))?$"), property_, "get_property"),
    (re.compile(r"^/bookings(?:/(?P<id>[^/]+))?$"), booking, "get_booking"),
    (re.compile(r"^/rent-adjustments(?:/(?P<id>[^/]+))?$"), rent_adjustment, "get_rent_adjustment"),
    (re.compile(r"^/invoices(?:/(?P<id>[^/]+))?$"), invoice, "get_invoice"),
    (re.compile(r"^/maintenance(?:/(?P<id>[^/]+))?$"), maintenance, "get_maintenance_case"),
    (re.compile(r"^/tasks(?:/(?P<id>[^/]+))?$"), task, "get_task"),
    (re.compile(r"^/billing/allocation-keys(?:/(?P<id>[^/]+))?$"), allocation_key, "get_allocation_key"),
    (re.compile(r"^/meters/(?P<meter>[^/]+)/readings$"), meter_reading, None),
    (re.compile(r"^/accounts(?:/(?P<id>[^/]+))?$"), account, "get_account"),
    (re.compile(r"^/contracts/[^/]+/rent-periods$"), rent_period, None),
]


# --- someone else saved in between ----------------------------------------------------------------

class StaleRecordError(Exception):
    """The record changed after the user opened it (answered with 409)."""


# collection path -> getter; a form sends back the `updated_at` it was opened with
STORED = {"/portfolios": "get_portfolio", "/accounts": "get_account", "/categories": "get_category",
          "/properties": "get_property", "/units": "get_unit", "/tenants": "get_tenant", "/contracts": "get_contract",
          "/bookings": "get_booking", "/receivables": "get_receivable", "/invoices": "get_invoice",
          "/maintenance": "get_maintenance_case", "/documents": "get_document", "/tasks": "get_task",
          "/calendar": "get_calendar_event", "/listings": "get_listing", "/leads": "get_lead",
          "/viewings": "get_viewing_appointment", "/billing/periods": "get_billing_period",
          "/billing/allocation-keys": "get_allocation_key", "/billing/cost-items": "get_cost_item",
          "/deposits": "get_deposit", "/notifications/templates": "get_notification_template",
          "/tax-rates": "get_tax_rate", "/rent-adjustments": "get_rent_adjustment",
          "/handover-protocols": "get_handover_protocol", "/budgets": "get_budget",
          "/escalation/rules": "get_escalation_rule", "/insurances": "get_insurance", "/contacts": "get_contact",
          "/meters": "get_meter", "/rent-charges": "get_rent_charge"}
_RECORD_PATH = re.compile(r"^(?P<collection>/.+)/(?P<id>[^/]+)$")


def _moment(value: Any) -> Optional[datetime]:
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            return None
    if not isinstance(value, datetime):
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def check_not_stale(method: str, path: str, body: Any, store: Any) -> None:
    """Refuse to save over a change someone else made after this user opened the record.

    Only when the client says which state it edited (`updated_at` in the body); clients
    that do not send it keep "the last one wins".
    """
    if method not in ("PUT", "PATCH") or not isinstance(body, dict) or not body.get("updated_at"):
        return
    match = _RECORD_PATH.match(path)
    getter = STORED.get(match["collection"]) if match else None
    if not match or not getter or not hasattr(store, getter):
        return
    current = _get(getattr(store, getter), match["id"])
    seen, stored = _moment(body["updated_at"]), _moment(getattr(current, "updated_at", None))
    if seen and stored and abs((stored - seen).total_seconds()) > 0.001:
        raise StaleRecordError(f"Der Datensatz wurde inzwischen geändert (zuletzt am "
                               f"{stored.astimezone():%d.%m.%Y um %H:%M:%S}). Bitte neu laden und die Änderung "
                               "noch einmal eintragen, damit nichts überschrieben wird.")


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
