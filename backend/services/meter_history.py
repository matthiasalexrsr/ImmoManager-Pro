"""A meter's readings over time: consumption between readings, per day and per calendar year.

Values are compared as exact decimals (a reading of 1234.56 minus 1200.1 is 34.46, not
34.460000000000036). A calendar year gets the share of each interval that falls into it,
by days; a year is "complete" only when readings cover all of its days.
"""

from __future__ import annotations

from calendar import isleap
from datetime import date, timedelta
from decimal import Decimal
from typing import Any
from urllib.parse import quote

from sqlalchemy import select

from ..db.service_contract_models import ServiceContractLocationORM, ServiceContractORM

_PLACES = Decimal("0.001")


def _number(value: Any) -> Decimal:
    return Decimal(repr(value)) if isinstance(value, float) else Decimal(str(value))


def _shown(value: Decimal) -> float:
    return float(value.quantize(_PLACES))


def _readings(store: Any, meter_id: str) -> list:
    if hasattr(store, "db"):
        # Reuse the repository's filtered, portfolio-scoped read instead of
        # materializing every meter's readings for one history.
        rows = store._resolve_repo("standalone_reading").filter_by(meter_id=meter_id)
    else:
        rows = [r for r in store.standalone_meter_readings.values() if r.meter_id == meter_id]
    return sorted(rows, key=lambda r: (r.reading_date, str(r.created_at), r.id))


def _intervals(readings: list) -> list[dict]:
    rows = []
    previous = None
    for reading in readings:
        row: dict[str, Any] = {"id": reading.id, "reading_date": reading.reading_date.isoformat(),
                               "value": _shown(_number(reading.value)), "recorded_by": reading.recorded_by,
                               "notes": reading.notes, "photo_url": reading.photo_url,
                               "consumption": None, "days": None, "per_day": None, "warning": None}
        if previous is not None:
            consumption = _number(reading.value) - _number(previous.value)
            days = (reading.reading_date - previous.reading_date).days
            row.update(consumption=_shown(consumption), days=days,
                       per_day=_shown(consumption / days) if days > 0 else None)
            if consumption < 0:
                row["warning"] = "Stand kleiner als zuvor: Zählertausch, Überlauf oder Ablesefehler?"
            elif days == 0:
                row["warning"] = "Zweite Ablesung am selben Tag"
        rows.append(row)
        previous = reading
    # a period far above the meter's usual daily use is worth a second look (a typo, a leak)
    usual = sorted(row["per_day"] for row in rows if row["per_day"] is not None and row["per_day"] > 0)
    if len(usual) >= 3:
        median = usual[len(usual) // 2]
        for row in rows:
            if row["warning"] is None and row["per_day"] is not None and median > 0 and row["per_day"] > 5 * median:
                row["warning"] = "Auffällig hoher Verbrauch je Tag gegenüber den übrigen Zeiträumen"
    return rows


def _years(readings: list) -> list[dict]:
    """Each interval's consumption spread over its days.

    A reading is taken at the end of its day (the annual reading on 31.12 closes the year), so an
    interval covers the days after the earlier reading up to and including the later one.
    """
    totals: dict[int, Decimal] = {}
    covered: dict[int, int] = {}
    for earlier, later in zip(readings, readings[1:]):
        days = (later.reading_date - earlier.reading_date).days
        consumption = _number(later.value) - _number(earlier.value)
        if days <= 0 or consumption < 0:
            continue                          # a replacement or an error is not consumption
        day = earlier.reading_date + timedelta(days=1)
        end = later.reading_date + timedelta(days=1)
        while day < end:
            year_end = date(day.year, 12, 31)
            stop = min(end, year_end + timedelta(days=1))
            span = (stop - day).days
            totals[day.year] = totals.get(day.year, Decimal(0)) + consumption * span / days
            covered[day.year] = covered.get(day.year, 0) + span
            day = stop
    return [{"year": year, "consumption": _shown(totals[year]), "covered_days": covered[year],
             "complete": covered[year] >= (366 if isleap(year) else 365)} for year in sorted(totals)]


def _contracts(store: Any, meter_id: str) -> list[dict]:
    """The service contracts that supply this meter (a location naming it), with their provider and portal."""
    if hasattr(store, "db"):
        ids = list(store.db.scalars(select(ServiceContractLocationORM.service_contract_id)
                                    .where(ServiceContractLocationORM.meter_id == meter_id).distinct()))
        contracts = list(store.db.scalars(select(ServiceContractORM).where(ServiceContractORM.id.in_(ids))))
    else:
        wanted = {row.service_contract_id for row in store.service_contract_locations.values() if row.meter_id == meter_id}
        contracts = [row for row in store.service_contracts.values() if row.id in wanted]
    result = []
    for contract in sorted(contracts, key=lambda row: row.title):
        try:
            provider = store.get_contact(contract.provider_contact_id)
            name = (provider.company_name or " ".join(filter(None, [provider.first_name, provider.last_name]))
                    or None)
        except Exception:  # noqa: BLE001 - a provider outside the account's portfolios stays unnamed
            name = None
        result.append({"id": contract.id, "title": contract.title, "provider": name,
                       "contract_number": contract.contract_number, "customer_number": contract.customer_number,
                       "portal_url": getattr(contract, "portal_url", None),
                       "href": f"/service-contracts/{quote(contract.id, safe='')}"})
    return result


def history(store: Any, meter_id: str) -> dict:
    meter = store.get_meter(meter_id)
    readings = _readings(store, meter_id)
    return {"meter": meter.model_dump(mode="json"), "readings": _intervals(readings), "years": _years(readings),
            "contracts": _contracts(store, meter_id)}
