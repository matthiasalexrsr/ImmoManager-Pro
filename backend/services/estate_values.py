"""Validate new input without making an old, repairable unit disappear from reads."""

from math import isfinite

from ..storage import NotFoundError, ValidationError

RENT_FIELDS = {"cold_rent": "Plan-Kaltmiete", "service_charge_advance": "Nebenkostenvorauszahlung",
               "heating_advance": "Heizkostenvorauszahlung"}


def _nonnegative(data, fields):
    for name, label in fields.items():
        value = getattr(data, name)
        if value is not None and (not isfinite(value) or value < 0):
            raise ValidationError(f"{label} muss eine gültige Zahl ab 0 sein.")


def validate_unit(data):
    if not data.label.strip():
        raise ValidationError("Bitte eine Bezeichnung für die Einheit angeben.")
    if not data.unit_type.strip():
        raise ValidationError("Bitte einen Einheitstyp angeben.")
    _nonnegative(data, {**RENT_FIELDS, "rooms": "Zimmerzahl", "person_count": "Personenzahl"})


def validate_initial_rent(store, unit_id):
    try:
        unit = store.get_unit(unit_id)
    except NotFoundError as error:
        raise ValidationError("Einheit existiert nicht") from error
    # A failed initial rent period must never leave a committed contract behind.
    _nonnegative(unit, RENT_FIELDS)
