from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Iterable

CENT = Decimal("0.01")


def _money(value: Decimal | float | int | str) -> Decimal:
    return Decimal(str(value)).quantize(CENT, rounding=ROUND_HALF_UP)


def _safe_decimal(value: Decimal | float | int | str | None) -> Decimal:
    if value is None:
        return Decimal("0.00")
    return _money(value)


@dataclass(frozen=True)
class PropertySnapshot:
    property_id: str
    property_name: str
    market_value: Decimal = Decimal("0.00")

    def __post_init__(self) -> None:
        if not self.property_id:
            raise ValueError("property_id ist erforderlich")
        if not self.property_name:
            raise ValueError("property_name ist erforderlich")
        object.__setattr__(self, "market_value", _safe_decimal(self.market_value))


@dataclass(frozen=True)
class UnitSnapshot:
    property_id: str
    unit_id: str
    status: str
    cold_rent: Decimal = Decimal("0.00")
    area_sqm: Decimal = Decimal("0.00")

    def __post_init__(self) -> None:
        if not self.property_id:
            raise ValueError("property_id ist erforderlich")
        if not self.unit_id:
            raise ValueError("unit_id ist erforderlich")
        normalized_rent = _safe_decimal(self.cold_rent)
        normalized_area = _safe_decimal(self.area_sqm)
        if normalized_rent < Decimal("0.00"):
            raise ValueError("cold_rent darf nicht negativ sein")
        if normalized_area < Decimal("0.00"):
            raise ValueError("area_sqm darf nicht negativ sein")
        object.__setattr__(self, "cold_rent", normalized_rent)
        object.__setattr__(self, "area_sqm", normalized_area)


@dataclass(frozen=True)
class PropertyPerformance:
    property_id: str
    property_name: str
    total_units: int
    rented_units: int
    vacant_units: int
    occupancy_rate: Decimal
    potential_monthly_rent: Decimal
    occupied_monthly_rent: Decimal
    vacant_monthly_rent: Decimal


@dataclass(frozen=True)
class PortfolioPropertySummary:
    total_properties: int
    total_units: int
    rented_units: int
    vacant_units: int
    occupancy_rate: Decimal
    total_market_value: Decimal
    potential_monthly_rent: Decimal
    occupied_monthly_rent: Decimal
    vacant_monthly_rent: Decimal
    average_market_value_per_property: Decimal


class PropertyEngine:
    """Domain logic for property-level KPIs and portfolio aggregation."""

    @staticmethod
    def property_performance(
        property_item: PropertySnapshot,
        units: Iterable[UnitSnapshot],
    ) -> PropertyPerformance:
        relevant_units = [unit for unit in units if unit.property_id == property_item.property_id]
        total_units = len(relevant_units)
        rented_units = sum(1 for unit in relevant_units if unit.status == "occupied")
        vacant_units = sum(1 for unit in relevant_units if unit.status in {"vacant", "reserved", "renovation"})

        potential_rent = _money(sum((unit.cold_rent for unit in relevant_units), Decimal("0.00")))
        occupied_rent = _money(sum((unit.cold_rent for unit in relevant_units if unit.status == "occupied"), Decimal("0.00")))
        vacant_rent = _money(potential_rent - occupied_rent)

        occupancy_rate = Decimal("0.00")
        if total_units > 0:
            occupancy_rate = (Decimal(rented_units) / Decimal(total_units)).quantize(CENT, rounding=ROUND_HALF_UP)

        return PropertyPerformance(
            property_id=property_item.property_id,
            property_name=property_item.property_name,
            total_units=total_units,
            rented_units=rented_units,
            vacant_units=vacant_units,
            occupancy_rate=occupancy_rate,
            potential_monthly_rent=potential_rent,
            occupied_monthly_rent=occupied_rent,
            vacant_monthly_rent=vacant_rent,
        )

    @staticmethod
    def portfolio_summary(
        properties: Iterable[PropertySnapshot],
        units: Iterable[UnitSnapshot],
    ) -> PortfolioPropertySummary:
        property_list = list(properties)
        unit_list = list(units)

        performances = [PropertyEngine.property_performance(prop, unit_list) for prop in property_list]

        total_properties = len(property_list)
        total_units = sum(item.total_units for item in performances)
        rented_units = sum(item.rented_units for item in performances)
        vacant_units = sum(item.vacant_units for item in performances)

        occupancy_rate = Decimal("0.00")
        if total_units > 0:
            occupancy_rate = (Decimal(rented_units) / Decimal(total_units)).quantize(CENT, rounding=ROUND_HALF_UP)

        total_market_value = _money(sum((prop.market_value for prop in property_list), Decimal("0.00")))
        potential_monthly_rent = _money(sum((item.potential_monthly_rent for item in performances), Decimal("0.00")))
        occupied_monthly_rent = _money(sum((item.occupied_monthly_rent for item in performances), Decimal("0.00")))
        vacant_monthly_rent = _money(sum((item.vacant_monthly_rent for item in performances), Decimal("0.00")))

        average_market_value = Decimal("0.00")
        if total_properties > 0:
            average_market_value = (total_market_value / Decimal(total_properties)).quantize(CENT, rounding=ROUND_HALF_UP)

        return PortfolioPropertySummary(
            total_properties=total_properties,
            total_units=total_units,
            rented_units=rented_units,
            vacant_units=vacant_units,
            occupancy_rate=occupancy_rate,
            total_market_value=total_market_value,
            potential_monthly_rent=potential_monthly_rent,
            occupied_monthly_rent=occupied_monthly_rent,
            vacant_monthly_rent=vacant_monthly_rent,
            average_market_value_per_property=average_market_value,
        )
