"""The application's deliberately small recurrence-rule dialect.

COUNT limits generated children (the template is not counted); UNTIL includes
its date. Monthly/yearly dates above day 28 retain the established day-28 clamp.
"""
from datetime import date, timedelta


def parse_rrule(rule: str) -> dict[str, str]:
    parts = {}
    for token in rule.split(";"):
        if "=" not in token:
            raise ValueError("Serienregel: erwartet wird SCHLÜSSEL=WERT")
        key, value = (part.strip().upper() for part in token.split("=", 1))
        if key not in {"FREQ", "INTERVAL", "COUNT", "UNTIL"}:
            raise ValueError(f"Serienregel: {key or 'leerer Schlüssel'} wird nicht unterstützt")
        if key in parts:
            raise ValueError(f"Serienregel: {key} darf nur einmal vorkommen")
        parts[key] = value
    if parts.get("FREQ") not in {"DAILY", "WEEKLY", "MONTHLY", "YEARLY"}:
        raise ValueError("Serienregel: FREQ muss DAILY, WEEKLY, MONTHLY oder YEARLY sein")
    for key in ("INTERVAL", "COUNT"):
        if key in parts and (not parts[key].isascii() or not parts[key].isdigit() or int(parts[key]) < 1):
            raise ValueError(f"Serienregel: {key} muss eine positive ganze Zahl sein")
    if "UNTIL" in parts:
        try:
            parts["UNTIL"] = date.fromisoformat(parts["UNTIL"]).isoformat()
        except ValueError as exc:
            raise ValueError("Serienregel: UNTIL muss ein gültiges Datum sein (JJJJ-MM-TT)") from exc
    return parts


def next_due_date(current: date, rrule: dict[str, str]) -> date:
    freq = rrule["FREQ"]
    interval = int(rrule.get("INTERVAL", "1"))
    if freq == "DAILY":
        return current + timedelta(days=interval)
    if freq == "WEEKLY":
        return current + timedelta(weeks=interval)
    if freq == "MONTHLY":
        month = current.month + interval
        year = current.year + (month - 1) // 12
        month = (month - 1) % 12 + 1
        return date(year, month, min(current.day, 28))
    return date(current.year + interval, current.month, min(current.day, 28))
