from decimal import Decimal

import pytest

from backend.domain.property_engine import PropertyEngine, PropertySnapshot, UnitSnapshot


def test_property_performance_computation() -> None:
    prop = PropertySnapshot(property_id="p-1", property_name="Objekt A", market_value=Decimal("550000"))
    units = [
        UnitSnapshot(property_id="p-1", unit_id="u-1", status="occupied", cold_rent=Decimal("1000")),
        UnitSnapshot(property_id="p-1", unit_id="u-2", status="vacant", cold_rent=Decimal("900")),
        UnitSnapshot(property_id="p-1", unit_id="u-3", status="occupied", cold_rent=Decimal("1100")),
        UnitSnapshot(property_id="p-2", unit_id="u-x", status="occupied", cold_rent=Decimal("999")),
    ]

    perf = PropertyEngine.property_performance(prop, units)

    assert perf.total_units == 3
    assert perf.rented_units == 2
    assert perf.vacant_units == 1
    assert perf.occupancy_rate == Decimal("0.67")
    assert perf.potential_monthly_rent == Decimal("3000.00")
    assert perf.occupied_monthly_rent == Decimal("2100.00")
    assert perf.vacant_monthly_rent == Decimal("900.00")


def test_portfolio_summary_aggregation() -> None:
    properties = [
        PropertySnapshot(property_id="p-1", property_name="Objekt A", market_value=Decimal("400000")),
        PropertySnapshot(property_id="p-2", property_name="Objekt B", market_value=Decimal("600000")),
    ]
    units = [
        UnitSnapshot(property_id="p-1", unit_id="u-1", status="occupied", cold_rent=Decimal("800")),
        UnitSnapshot(property_id="p-1", unit_id="u-2", status="vacant", cold_rent=Decimal("700")),
        UnitSnapshot(property_id="p-2", unit_id="u-3", status="occupied", cold_rent=Decimal("1200")),
    ]

    summary = PropertyEngine.portfolio_summary(properties, units)

    assert summary.total_properties == 2
    assert summary.total_units == 3
    assert summary.rented_units == 2
    assert summary.vacant_units == 1
    assert summary.occupancy_rate == Decimal("0.67")
    assert summary.total_market_value == Decimal("1000000.00")
    assert summary.potential_monthly_rent == Decimal("2700.00")
    assert summary.occupied_monthly_rent == Decimal("2000.00")
    assert summary.vacant_monthly_rent == Decimal("700.00")
    assert summary.average_market_value_per_property == Decimal("500000.00")


def test_snapshot_validation() -> None:
    with pytest.raises(ValueError):
        PropertySnapshot(property_id="", property_name="Objekt")

    with pytest.raises(ValueError):
        UnitSnapshot(property_id="p-1", unit_id="", status="occupied")

    with pytest.raises(ValueError):
        UnitSnapshot(property_id="p-1", unit_id="u-1", status="occupied", cold_rent=Decimal("-1"))
