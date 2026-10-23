"""The consumer price index (VPI) for index rents, kept by hand in the installation.

Index rents follow the consumer price index for Germany that the Federal Statistical
Office publishes monthly (§ 557b BGB; Destatis table 61111-0002). The program fetches
nothing: an owner or manager enters the monthly values (base year 2020 = 100 at the
time of writing) on the letter templates page. They live as one installation-wide rule
in `daily_setting_rules` (scope "global", key KEY) with revision and audit journal,
like the letterhead; letters read them as suggestions and freeze them in their source.
"""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select

from ..db.daily_models import SettingRuleORM
from . import daily_state as state
from . import document_versions as archive
from .portfolio_scope import scope_context, scope_from_user
from .settings_catalogue import record_audit, rule

KEY = "price_index:vpi"
SCOPE = "global"
WRITE_AREA = "/letter-templates"
MONTH = re.compile(r"^(19|20)\d\d-(0[1-9]|1[0-2])$")
MAX_MONTHS = 600
MONTH_NAMES = ("Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August", "September", "Oktober",
               "November", "Dezember")


def month_label(value: str) -> str:
    year, month = value.split("-")
    return f"{MONTH_NAMES[int(month) - 1]} {year}"


def _payload(saved: dict) -> dict:
    value = saved.get("payload", {}).get("value") or {}
    return {"revision": saved["revision"], "base_year": value.get("base_year"), "values": dict(value.get("values") or {})}


def read(unit) -> dict:
    """The stored series: revision, base year and {"YYYY-MM": "121.4"}."""
    return _payload(rule(unit, SCOPE, KEY))


def view(store, actor_id: str) -> dict:
    with archive.work(store, actor_id) as unit, scope_context(scope_from_user(unit.user)):
        series = read(unit)
        can_edit = unit.user["role"] in ("eigentuemer", "verwalter") and scope_from_user(unit.user).unrestricted
        return {**series, "months": sorted(series["values"]), "can_edit": can_edit}


def parse_value(raw: Any, label: str) -> Decimal:
    try:
        value = Decimal(str(raw).strip().replace(",", "."))
    except (InvalidOperation, ValueError):
        raise HTTPException(422, f"{label}: kein gültiger Indexwert.") from None
    if not value.is_finite() or not Decimal("1") <= value <= Decimal("1000") or value != value.quantize(Decimal("0.001")):
        raise HTTPException(422, f"{label}: Indexwert zwischen 1 und 1000 mit höchstens drei Nachkommastellen angeben.")
    return value.normalize() if value == value.to_integral() else value


def validate(base_year: Any, values: Any) -> tuple[int, dict[str, str]]:
    if type(base_year) is not int or not 1990 <= base_year <= 2100:
        raise HTTPException(422, "Basisjahr zwischen 1990 und 2100 angeben (z. B. 2020 für 2020 = 100).")
    if not isinstance(values, dict) or len(values) > MAX_MONTHS:
        raise HTTPException(422, f"Höchstens {MAX_MONTHS} Monatswerte angeben.")
    cleaned: dict[str, str] = {}
    for month, raw in values.items():
        if not isinstance(month, str) or not MONTH.match(month):
            raise HTTPException(422, f"„{month}“ ist kein Monat im Format JJJJ-MM.")
        cleaned[month] = str(parse_value(raw, month_label(month)))
    return base_year, dict(sorted(cleaned.items()))


def save(store, actor_id: str, payload: dict) -> dict:
    """Replace the series against its revision (owner or manager with access to all holdings)."""
    base_year, values = validate(payload.get("base_year"), payload.get("values"))
    base_revision, key = payload.get("base_revision"), payload.get("idempotency_key")
    if type(base_revision) is not int or base_revision < 0:
        raise HTTPException(422, "Erwartete Revision fehlt.")
    if not isinstance(key, str) or not 8 <= len(key) <= 120:
        raise HTTPException(422, "Ungültige Vorgangskennung.")
    with archive.work(store, actor_id, write_areas=(WRITE_AREA,)) as unit, scope_context(scope_from_user(unit.user)):
        if unit.user["role"] not in ("eigentuemer", "verwalter") or not scope_from_user(unit.user).unrestricted:
            raise HTTPException(403, "Den Verbraucherpreisindex pflegen Eigentümer oder Verwaltung mit Zugriff auf "
                                     "alle Bestände.")
        fingerprint = state.digest("price_index_put", {"base_revision": base_revision, "base_year": base_year,
                                                        "values": values})
        saved = state.replay(unit, key, fingerprint)
        if saved is not None:
            return saved
        before = read(unit)
        if before["revision"] != base_revision:
            raise HTTPException(409, "Der Verbraucherpreisindex wurde zwischenzeitlich geändert. Bitte neu laden.")
        stored = {"value": {"base_year": base_year, "values": values}}
        if unit.db is None:
            unit.insert(state.memory(unit, "rules"), (SCOPE, KEY), {"revision": base_revision + 1, "payload": stored})
        else:
            row = unit.db.scalar(select(SettingRuleORM).where(SettingRuleORM.scope == SCOPE,
                                                              SettingRuleORM.key == KEY).with_for_update())
            if row is None:
                row = SettingRuleORM(scope=SCOPE, key=KEY)
                unit.db.add(row)
            row.revision, row.payload, row.updated_at = base_revision + 1, stored, state.now()
            unit.db.flush()
        record_audit(unit, key, "settings_change", SCOPE,
                     {KEY: {"base_year": before["base_year"], "months": len(before["values"])}},
                     {KEY: {"base_year": base_year, "months": len(values)}})
        response = {"revision": base_revision + 1, "base_year": base_year, "values": values,
                    "months": list(values), "can_edit": True}
        state.remember(unit, key, fingerprint, response)
        return response
