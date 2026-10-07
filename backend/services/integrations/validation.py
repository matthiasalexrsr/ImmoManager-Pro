"""Strict, UI-readable field contracts without coercing submitted values."""

import math
import re


def is_email(value):
    return isinstance(value, str) and bool(re.fullmatch(r"[^\s@,;<>]+@[^\s@,;<>]+\.[^\s@,;<>]+", value))


def config_fields(manifest):
    if manifest.config_fields:
        return manifest.config_fields
    return [{"key": key, "label": key, "type": "string", "required": key in manifest.required_config_keys,
             "secret": key in manifest.secret_config_keys}
            for key in dict.fromkeys(manifest.required_config_keys + manifest.secret_config_keys)]


def field_errors(values, fields, *, required=False):
    errors = {}
    for field in fields:
        key = field["key"]
        value = values.get(key)
        if value is None or value == "":
            if required and field.get("required"):
                errors[key] = "Pflichtfeld fehlt"
            continue
        kind = field.get("type", "string")
        valid = {"string": isinstance(value, str), "boolean": type(value) is bool,
                 "integer": type(value) is int, "number": type(value) in (int, float),
                 "object": isinstance(value, dict), "array": isinstance(value, list)}.get(kind, False)
        if not valid:
            errors[key] = f"Ungültiger Typ: {kind} erwartet"
        elif kind in ("integer", "number") and (not math.isfinite(value) or
                value < field.get("min", -math.inf) or value > field.get("max", math.inf)):
            errors[key] = "Wert außerhalb des erlaubten Bereichs"
        elif field.get("format") == "email" and not is_email(value):
            errors[key] = "Eine einzelne gültige E-Mail-Adresse ist erforderlich"
        elif field.get("options") and value not in field["options"]:
            errors[key] = "Wert ist nicht unterstützt"
        elif isinstance(value, str) and ("\r" in value or "\n" in value) and field.get("single_line"):
            errors[key] = "Zeilenumbrüche sind nicht erlaubt"
        elif kind == "array" and field.get("items"):
            for index, item in enumerate(value):
                specification = field["items"]
                if specification.get("type") == "object" and not isinstance(item, dict):
                    errors[f"{key}[{index}]"] = "Objekt erwartet"
                elif isinstance(item, dict):
                    for nested_key, message in field_errors(item, specification.get("fields", []), required=True).items():
                        errors[f"{key}[{index}].{nested_key}"] = message
    return errors
