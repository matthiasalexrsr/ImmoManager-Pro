"""Genuine day-by-day meter replacement gaps in utility allocation preflight.

All tests use synthetic units and values. No past finalized original is
recomputed or modified; the calculation must warn before a new finalization.
"""
from datetime import date

import pytest

from backend.dependencies import store
from backend.routers import billing
from backend.services.data_snapshot import clear_business_data
from backend.tests import test_billing_regression as case


@pytest.fixture(autouse=True)
def synthetic_only():
    clear_business_data(store)
    yield
    clear_business_data(store)


def _prepared(old_end: date, new_start: date):
    prop = case._property("Nur Prüfobjekt")
    unit = case._unit(prop, "WE 01", 50)
    case._lease(prop, unit, "synthetic-lease", persons=1)
    allocation = case._key(prop, "consumption", "Kaltwasser", "cold_water", "m³")
    period = case._period(prop, [("Verbrauchsabrechnung", 160, allocation)])
    case._meter(unit, "cold_water", [
        (date(2025, 1, 1), 120), (old_end, 150),
    ], installation_date=date(2025, 1, 1), removal_date=old_end,
       serial_number="OLD-SYNTHETIC", measure_unit="m³", is_active=False)
    case._meter(unit, "cold_water", [
        (new_start, 10), (date(2025, 12, 31), 40),
    ], installation_date=new_start, serial_number="NEW-SYNTHETIC",
       measure_unit="m³")
    return period


def test_two_missing_service_days_are_visible_and_block_finalizing():
    period = _prepared(date(2025, 6, 30), date(2025, 7, 3))
    result = billing.get_billing_period_preflight(period.id)
    matches = [i for i in result.blockers if i.code == "METER_SERVICE_GAP"]
    assert len(matches) == 1
    assert matches[0].context is not None
    assert "01.07.2025 bis 02.07.2025" in matches[0].context
    assert "OLD-SYNTHETIC" in matches[0].context
    assert "NEW-SYNTHETIC" in matches[0].context
    assert result.has_blockers
    # Existing source readings must not be repaired or fabricated.
    assert len(store.list_standalone_meter_readings()) == 4


def test_seamless_next_day_replacement_has_no_false_gap_or_overlap():
    period = _prepared(date(2025, 6, 30), date(2025, 7, 1))
    result = billing.get_billing_period_preflight(period.id)
    codes = {i.code for i in (*result.blockers, *result.warnings)}
    assert "METER_SERVICE_GAP" not in codes
    assert "METER_SERVICE_OVERLAP" not in codes
    assert "MISSING_CONSUMPTION" not in codes
    assert result.metrics["consumption_units_with_data"] == 1


def test_overlapping_meters_raise_explicit_parallel_or_replacement_review():
    period = _prepared(date(2025, 7, 3), date(2025, 6, 30))
    result = billing.get_billing_period_preflight(period.id)
    matches = [i for i in result.warnings if i.code == "METER_SERVICE_OVERLAP"]
    assert len(matches) == 1
    assert matches[0].context is not None
    assert "OLD-SYNTHETIC" in matches[0].context
    assert "NEW-SYNTHETIC" in matches[0].context
    assert "METER_SERVICE_GAP" not in {i.code for i in result.blockers}
