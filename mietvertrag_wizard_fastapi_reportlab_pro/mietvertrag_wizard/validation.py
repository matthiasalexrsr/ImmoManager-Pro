"""Validation for rental-contract wizard payloads.

The validator intentionally checks structural consistency only. It does not
attempt to replace legal review of the generated contract text.
"""
from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Mapping


class ContractValidationError(ValueError):
    """Raised when a wizard payload cannot produce a coherent contract."""

    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__("; ".join(errors))


def _text(value: Any) -> str:
    return str(value or "").strip()


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _date(value: Any, label: str, errors: list[str]) -> datetime | None:
    raw = _text(value)
    if not raw:
        errors.append(f"{label} fehlt.")
        return None
    for fmt in ("%d.%m.%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            pass
    errors.append(f"{label} ist kein gültiges Datum.")
    return None


_BROWSER_MONEY_RE = re.compile(r"^[+-]?\d+(?:\.\d+)?$")
_GERMAN_MONEY_RE = re.compile(
    r"^[+-]?(?:\d+|\d{1,3}(?:\.\d{3})+)(?:,\d+)?$"
)


def parse_money_decimal(value: Any) -> Decimal | None:
    """Parse only explicit browser-point or German-comma money notation."""
    raw = _text(value)
    if not raw:
        return None
    if raw.startswith("€"):
        raw = raw[1:].strip()
    if raw.endswith("€"):
        raw = raw[:-1].strip()
    if "€" in raw or any(ch.isspace() for ch in raw):
        raise ValueError("invalid_money_notation")
    if raw.lower() in {"nan", "+nan", "-nan", "inf", "+inf", "-inf", "infinity", "+infinity", "-infinity"}:
        return Decimal(raw)
    if "e" in raw.lower():
        raise ValueError("exponential_money_notation")
    if "," in raw:
        if not _GERMAN_MONEY_RE.fullmatch(raw):
            raise ValueError("invalid_money_notation")
        normalized = raw.replace(".", "").replace(",", ".")
    else:
        if not _BROWSER_MONEY_RE.fullmatch(raw):
            raise ValueError("invalid_money_notation")
        normalized = raw
    try:
        return Decimal(normalized)
    except InvalidOperation as exc:
        raise ValueError("invalid_money_notation") from exc


def _has_exact_cents(amount: Decimal) -> bool:
    exponent = amount.as_tuple().exponent
    if not isinstance(exponent, int) or exponent >= -2:
        return True
    extra_places = -exponent - 2
    digits = amount.as_tuple().digits
    if not any(digits):
        return True
    return extra_places <= len(digits) and all(digit == 0 for digit in digits[-extra_places:])


def _money(
    value: Any,
    label: str,
    errors: list[str],
    *,
    required: bool = False,
    positive: bool = False,
) -> Decimal | None:
    raw = _text(value)
    if not raw:
        if required:
            errors.append(f"{label} fehlt.")
        return None
    try:
        amount = parse_money_decimal(value)
    except ValueError as exc:
        if str(exc) == "exponential_money_notation":
            errors.append(f"{label}: Exponentialnotation wird nicht unterstützt.")
        else:
            errors.append(f"{label} ist kein gültiger Betrag.")
        return None
    assert amount is not None
    if not amount.is_finite():
        errors.append(f"{label} muss ein endlicher Betrag sein.")
        return None
    if not _has_exact_cents(amount):
        errors.append(f"{label} muss centgenau sein.")
        return None
    if positive and amount <= 0:
        errors.append(f"{label} muss größer als 0 sein.")
        return None
    if not positive and amount < 0:
        errors.append(f"{label} darf nicht negativ sein.")
        return None
    return amount


def _require_mapping(value: Any, label: str, errors: list[str]) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        errors.append(f"{label} muss ein Objekt sein.")
        return {}
    return value


def _optional_mapping(data: Mapping[str, Any], key: str, label: str, errors: list[str]) -> Mapping[str, Any]:
    value = data.get(key)
    if value in (None, ""):
        return {}
    return _require_mapping(value, label, errors)


def _party_list(value: Any, label: str, errors: list[str]) -> list[Mapping[str, Any]]:
    if not isinstance(value, list):
        errors.append(f"{label} muss eine Liste sein.")
        return []
    mappings = [item for item in value if isinstance(item, Mapping)]
    if len(mappings) != len(value):
        errors.append(f"{label} darf nur Objekte enthalten.")
    if not any(_text(item.get("name")) for item in mappings):
        errors.append(f"Mindestens ein {label} mit Name ist erforderlich.")
    return mappings


def validate_contract_payload(data: Any) -> dict[str, Any]:
    """Return *data* when it contains the minimum coherent contract fields."""

    if not isinstance(data, dict):
        raise ContractValidationError(["Der Vertragsentwurf muss ein JSON-Objekt sein."])

    errors: list[str] = []

    _party_list(data.get("vermieter"), "Vermieter", errors)
    _party_list(data.get("mieter"), "Mieter", errors)

    rental_object = _require_mapping(data.get("objekt"), "Mietobjekt", errors)
    for field, label in (
        ("strasse", "Straße des Mietobjekts"),
        ("plz", "PLZ des Mietobjekts"),
        ("ort", "Ort des Mietobjekts"),
    ):
        if not _text(rental_object.get(field)):
            errors.append(f"{label} fehlt.")
    _optional_mapping(rental_object, "schluessel", "Schlüsselangaben", errors)

    tenancy = _require_mapping(data.get("mietzeit"), "Mietzeit", errors)
    start = _date(tenancy.get("beginn"), "Mietbeginn", errors)
    tenancy_type = _text(tenancy.get("art")) or "unbefristet"
    if tenancy_type not in {"unbefristet", "befristet"}:
        errors.append("Mietvertragsart ist ungültig.")
    if tenancy_type == "befristet":
        end = _date(tenancy.get("ende"), "Mietende", errors)
        if start and end and end <= start:
            errors.append("Mietende muss nach dem Mietbeginn liegen.")
    rent = _require_mapping(data.get("miete"), "Mietangaben", errors)
    _money(rent.get("grund"), "Grundmiete", errors, required=True, positive=True)
    for field, label in (
        ("betrieb", "Betriebskostenvorauszahlung"),
        ("heizung", "Heizkostenvorauszahlung"),
        ("kaution", "Mietkaution"),
    ):
        _money(rent.get(field), label, errors)

    escalation = _text(rent.get("erhoehung")) or "keine"
    if escalation not in {"keine", "staffel", "index"}:
        errors.append("Mieterhöhungsart ist ungültig.")

    tiers = rent.get("staffeln")
    if tiers not in (None, "") and not isinstance(tiers, list):
        errors.append("Staffeln müssen eine Liste sein.")
        tiers = []
    if escalation == "staffel" and not tiers:
        errors.append("Für eine Staffelmiete ist mindestens eine Staffel erforderlich.")
    if isinstance(tiers, list):
        for index, tier in enumerate(tiers, start=1):
            if not isinstance(tier, Mapping):
                errors.append(f"Staffel {index} muss ein Objekt sein.")
                continue
            _money(
                tier.get("betrag"),
                f"Grundmiete der Staffel {index}",
                errors,
                positive=True,
            )

    if escalation == "index" and not _text(rent.get("indexAusgang")):
        errors.append("Für eine Indexmiete fehlt der Ausgangsindex.")

    _optional_mapping(data, "zahlung", "Zahlungsangaben", errors)
    _optional_mapping(data, "mandat", "SEPA-Mandat", errors)
    _optional_mapping(data, "clauses", "Weitere Vereinbarungen", errors)

    if errors:
        raise ContractValidationError(errors)
    return data
