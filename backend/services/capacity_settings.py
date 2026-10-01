"""Explicit host capacity for streaming backup/recovery commands.

These are adjustable resource budgets, never maximum business record counts.
No application settings or ambient environment are read by this module.
"""
import json
import os
import stat
from dataclasses import fields
from pathlib import Path
from typing import Any, TypeVar

Capacity = TypeVar("Capacity")
SECTIONS = {"sqlite_recovery", "private_server_backup"}


class CapacityProfileError(ValueError):
    pass


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise CapacityProfileError("Doppelte Felder im Kapazitätsprofil. Profil korrigieren und erneut starten.")
        result[key] = value
    return result


def _constant(_value):
    raise CapacityProfileError("Kapazitätswerte müssen positiv und endlich sein.")


def load_capacity(path: Path | None, section: str, model: type[Capacity],
                  *, overrides: dict[str, Any] | None = None) -> Capacity:
    """Read an optional versioned profile, then apply explicit CLI overrides."""
    values = {}
    if section not in SECTIONS:
        raise CapacityProfileError("Unbekannter Kapazitätsbereich.")
    if path is not None:
        try:
            initial = path.lstat()
            if (not stat.S_ISREG(initial.st_mode) or initial.st_nlink != 1
                    or getattr(initial, "st_file_attributes", 0) & 0x400):
                raise CapacityProfileError("Kapazitätsprofil muss eine reguläre lokale Datei sein.")
            with path.open("rb") as source:
                opened = os.fstat(source.fileno())
                if (initial.st_dev, initial.st_ino) != (opened.st_dev, opened.st_ino):
                    raise CapacityProfileError("Kapazitätsprofil wurde verändert. Erneut starten.")
                raw = source.read(65537)
            if len(raw) > 65536:
                raise CapacityProfileError("Kapazitätsprofil ist zu groß. Nur die dokumentierten Einstellungsfelder verwenden.")
            profile = json.loads(raw, object_pairs_hook=_object, parse_constant=_constant)
            if (not isinstance(profile, dict) or type(profile.get("version")) is not int
                    or profile["version"] != 1 or set(profile) - (SECTIONS | {"version"})):
                raise CapacityProfileError("Unbekanntes Kapazitätsprofil. Version 1 und dokumentierte Bereiche verwenden.")
            if any(not isinstance(profile.get(name, {}), dict) for name in SECTIONS):
                raise CapacityProfileError("Kapazitätsbereiche müssen Einstellungsobjekte sein.")
            values.update(profile.get(section, {}))
        except (OSError, UnicodeError, json.JSONDecodeError, RecursionError) as exc:
            raise CapacityProfileError("Kapazitätsprofil konnte nicht gelesen werden. Dateirechte und JSON-Format prüfen.") from exc
    values.update(overrides or {})
    allowed = {field.name for field in fields(model)}  # type: ignore[arg-type]
    if set(values) - allowed:
        raise CapacityProfileError("Unbekannte Kapazitätseinstellung. Feldnamen im Profil korrigieren.")
    if any(type(value) not in {int, float} or isinstance(value, bool) for value in values.values()):
        raise CapacityProfileError("Kapazitätseinstellungen müssen numerische Werte sein.")
    try:
        return model(**values)
    except (TypeError, ValueError, OverflowError) as exc:
        raise CapacityProfileError("Ungültige Kapazitätseinstellungen. Positive Dateigrößen, Anzahlen und endliche Zeitwerte verwenden.") from exc
