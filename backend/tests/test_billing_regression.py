"""Regression matrix for utility statements (docs/BILLING_REGRESSION_20261008.md).

A medium and unit of measure, B meter replacement, C dated occupants, D real
sections, E vacancy, F objection and correction, G unchanged final version.
Every expected value is computed by hand in the comment next to it.
"""

import copy
from datetime import date

import pytest
from fastapi import HTTPException

from backend.dependencies import store
from backend.models import (
    AllocationKeyCreate,
    BillingObjectionRequest,
    BillingPeriodCreate,
    BillingPeriodPatch,
    ContractOccupancyCreate,
    ContractPatch,
    ContractRentPeriodCreate,
    CostItemCreate,
    CostItemPatch,
    MeterCreate,
    PortfolioCreate,
    PropertyCreate,
    StandaloneMeterReadingCreate,
    TenantCreate,
    UnitCreate,
    UtilityStatementPatch,
)
from backend.routers import billing, contracts
from backend.services.data_snapshot import SnapshotError, clear_business_data, export_snapshot, import_snapshot
from backend.services.rent_history import start_rent_history
from backend.storage import ValidationError

Y2025 = (date(2025, 1, 1), date(2025, 12, 31))


@pytest.fixture(autouse=True)
def _clean():
    clear_business_data(store)
    yield
    clear_business_data(store)


# --- helpers -------------------------------------------------------------------------------


def _property(name="Haus"):
    pf = store.create_portfolio(PortfolioCreate(name=name))
    return store.create_property(PropertyCreate(portfolio_id=pf.id, name=name, property_type="residential",
                                                address_line="Ringstr. 1", city="Leipzig"))


def _unit(prop, label, area=50.0, advance=(0, 0), persons=None):
    return store.create_unit(UnitCreate(
        property_id=prop.id, label=label, unit_type="residential", area_sqm=area,
        service_charge_advance=advance[0], heating_advance=advance[1], person_count=persons))


def _lease(prop, unit, number, start=date(2020, 1, 1), end=None, persons=None, history=False):
    tenant = store.create_tenant(TenantCreate(full_name=f"Mieter {number}"))
    contract = store.create_contract(contracts.ContractCreate(
        contract_number=number, property_id=prop.id, unit_id=unit.id, tenant_id=tenant.id,
        start_date=start, end_date=end, status="terminated" if end else "active", persons=persons))
    if history:
        start_rent_history(store, contract)
    return contract


def _key(prop, key_type, name=None, meter_type=None, measure_unit=None):
    return store.create_allocation_key(AllocationKeyCreate(
        property_id=prop.id, name=name or key_type, key_type=key_type, meter_type=meter_type,
        measure_unit=measure_unit))


def _period(prop, costs, start=Y2025[0], end=Y2025[1], label="BK 2025"):
    """costs: (description, amount, key)"""
    period = store.create_billing_period(BillingPeriodCreate(
        property_id=prop.id, label=label, start_date=start, end_date=end))
    for description, amount, key in costs:
        store.create_cost_item(CostItemCreate(billing_period_id=period.id, description=description,
                                              amount=amount, allocation_key_id=key.id))
    return period


def _meter(unit, meter_type, readings, **fields):
    meter = store.create_meter(MeterCreate(unit_id=unit.id, meter_type=meter_type, **fields))
    for day, value in readings:
        store.create_standalone_meter_reading(StandaloneMeterReadingCreate(
            meter_id=meter.id, reading_date=day, value=value))
    return meter


def _issues(period):
    result = billing.get_billing_period_preflight(period.id)
    return {i.code: i for i in result.blockers}, {i.code: i for i in result.warnings}


def _by(stmts, *fields):
    return {tuple(getattr(s, f) for f in fields): s for s in stmts}


def _finalized(prop_name="Haus"):
    """Two flats 60/40 m², 1,000 € property tax by area, advances 40 €/month each."""
    prop = _property(prop_name)
    big, small = _unit(prop, "WE 01", 60, (40, 0)), _unit(prop, "WE 02", 40, (40, 0))
    prefix = "V" if prop_name == "Haus" else prop_name[:1]
    first, second = _lease(prop, big, f"{prefix}-1", history=True), _lease(prop, small, f"{prefix}-2", history=True)
    area = _key(prop, "area_sqm", "Fläche")
    period = _period(prop, [("Grundsteuer", 1000, area)])
    stmts = billing.generate_utility_statements(period.id)
    billing.finalize_billing_period(period.id)
    return {"prop": prop, "units": (big, small), "contracts": (first, second), "key": area,
            "period": store.get_billing_period(period.id), "stmts": stmts}


def _stored(period_id):
    return sorted((s for s in store.list_utility_statements() if s.billing_period_id == period_id),
                  key=lambda s: s.id)


def _content(statements):
    return [s.model_dump(exclude={"status", "delivery_status", "delivered_at", "delivery_channel", "updated_at"})
            for s in statements]


# --- A: medium and unit of measure ---------------------------------------------------------


def test_a1_a_key_counts_only_its_own_medium():
    prop = _property()
    first, second = _unit(prop, "WE 01"), _unit(prop, "WE 02")
    _lease(prop, first, "C-1")
    _lease(prop, second, "C-2")
    _meter(first, "cold_water", [(date(2025, 1, 1), 0), (date(2025, 12, 31), 30)])
    _meter(first, "hot_water", [(date(2025, 1, 1), 0), (date(2025, 12, 31), 100)])
    _meter(second, "cold_water", [(date(2025, 1, 1), 0), (date(2025, 12, 31), 10)])
    _meter(second, "hot_water", [(date(2025, 1, 1), 0), (date(2025, 12, 31), 0)])
    period = _period(prop, [("Kaltwasser", 400, _key(prop, "consumption", meter_type="cold_water"))])

    rows = _by(billing.generate_utility_statements(period.id), "unit_id")

    # cold water only: 30 m³ and 10 m³ of 40 m³ -> 300 € / 100 €; hot water is not counted
    assert (rows[(first.id,)].total_cost, rows[(second.id,)].total_cost) == (300.0, 100.0)
    line = rows[(first.id,)].line_items[0]
    assert (line["basis"], line["total_basis"], line["basis_unit"]) == (30.0, 40.0, "m³")


def test_a2_kwh_and_mwh_are_converted_only_when_the_key_names_its_unit():
    prop = _property()
    first, second = _unit(prop, "WE 01"), _unit(prop, "WE 02")
    _lease(prop, first, "C-1")
    _lease(prop, second, "C-2")
    _meter(first, "heating", [(date(2025, 1, 1), 0), (date(2025, 12, 31), 1000)], measure_unit="kWh")
    _meter(second, "heating", [(date(2025, 1, 1), 0), (date(2025, 12, 31), 3)], measure_unit="MWh",
           serial_number="WMZ-2")
    key = _key(prop, "consumption", "Heizung", meter_type="heating")
    period = _period(prop, [("Heizung", 800, key)])

    # Regression: 1,000 kWh and 3 MWh were added as 1,000 : 3 (797.61 € / 2.39 €).
    blockers, _ = _issues(period)
    assert blockers["CONSUMPTION_UNIT_MISMATCH"].context == "Heizung: MWh, kWh"

    store.update_allocation_key(key.id, AllocationKeyCreate(**{
        **key.model_dump(include=set(AllocationKeyCreate.model_fields)), "measure_unit": "kWh"}))
    rows = _by(billing.generate_utility_statements(period.id), "unit_id")
    _, warnings = _issues(period)

    # 1,000 kWh and 3 MWh = 3,000 kWh of 4,000 kWh -> 200 € / 600 €
    assert (rows[(first.id,)].total_cost, rows[(second.id,)].total_cost) == (200.0, 600.0)
    line = rows[(second.id,)].line_items[0]
    assert (line["basis"], line["total_basis"], line["basis_unit"]) == (3000.0, 4000.0, "kWh")
    assert warnings["CONSUMPTION_UNIT_CONVERTED"].context == "Heizung: WE 02 (WMZ-2): MWh → kWh (× 1000)"


@pytest.mark.parametrize("medium,first_unit,second_unit,target", [
    ("heating", "kWh", "HKV", "kWh"),  # heat cost allocator units are no energy
    ("gas", "kWh", "m³", "kWh"),       # gas m³ -> kWh needs calorific value and z-number
])
def test_a3_units_without_an_exact_factor_are_refused(medium, first_unit, second_unit, target):
    prop = _property()
    first, second = _unit(prop, "WE 01"), _unit(prop, "WE 02")
    _lease(prop, first, "C-1")
    _lease(prop, second, "C-2")
    _meter(first, medium, [(date(2025, 1, 1), 0), (date(2025, 12, 31), 10)], measure_unit=first_unit,
           serial_number="Z-1")
    _meter(second, medium, [(date(2025, 1, 1), 0), (date(2025, 12, 31), 10)], measure_unit=second_unit,
           serial_number="Z-2")
    period = _period(prop, [("Kosten", 100, _key(prop, "consumption", "K", medium, target))])

    blockers, _ = _issues(period)

    # only the meter whose unit has no exact factor is named
    assert blockers["CONSUMPTION_UNIT_MISMATCH"].context == f"K: WE 02 (Z-2): {second_unit}"
    with pytest.raises(HTTPException) as exc:
        billing.generate_utility_statements(period.id)
    assert exc.value.status_code == 400 and "nicht exakt" in exc.value.detail


def test_a4_unit_must_fit_the_medium_and_be_known():
    prop = _property()
    flat = _unit(prop, "WE 01")
    _lease(prop, flat, "C-1")
    _meter(flat, "cold_water", [(date(2025, 1, 1), 0), (date(2025, 12, 31), 10)])
    wrong_key = _period(prop, [("Wasser", 100, _key(prop, "consumption", "W", "cold_water", "kWh"))])
    assert "CONSUMPTION_UNIT_INVALID" in _issues(wrong_key)[0]

    other = _property("Zweites Haus")
    second = _unit(other, "WE 01")
    _lease(other, second, "C-2")
    _meter(second, "heating", [(date(2025, 1, 1), 0), (date(2025, 12, 31), 10)], measure_unit="kWh")
    _meter(second, "heating", [(date(2025, 1, 1), 0), (date(2025, 12, 31), 5)], serial_number="HKV-1")
    without_unit = _period(other, [("Heizung", 100, _key(other, "consumption", "H", "heating"))])
    # heating has no usual unit: an unspecified meter is not silently taken as kWh
    assert _issues(without_unit)[0]["CONSUMPTION_UNIT_MISMATCH"].context == "H: kWh, ohne Angabe"


# --- B: meter replacement ------------------------------------------------------------------


def _two_flats():
    prop = _property()
    first, second = _unit(prop, "WE 01"), _unit(prop, "WE 02")
    return prop, first, second


def test_b1_replacement_adds_final_and_initial_reading():
    prop, first, second = _two_flats()
    _lease(prop, first, "C-1")
    _lease(prop, second, "C-2")
    _meter(first, "cold_water", [(date(2025, 1, 1), 100), (date(2025, 6, 15), 160)],
           removal_date=date(2025, 6, 15), is_active=False)
    _meter(first, "cold_water", [(date(2025, 6, 15), 0), (date(2025, 12, 31), 40)],
           installation_date=date(2025, 6, 15))
    _meter(second, "cold_water", [(date(2025, 1, 1), 0), (date(2025, 12, 31), 100)])
    period = _period(prop, [("Wasser", 1000, _key(prop, "consumption", meter_type="cold_water"))])

    # Regression: the deactivated meter was ignored and the new one had no reading on 01.01. (blocker).
    rows = _by(billing.generate_utility_statements(period.id), "unit_id")

    # WE 01: (160 - 100) + (40 - 0) = 100 m³, WE 02: 100 m³ -> 500 € each
    assert (rows[(first.id,)].total_cost, rows[(second.id,)].total_cost) == (500.0, 500.0)
    assert rows[(first.id,)].line_items[0]["basis"] == 100.0


def test_b2_replacement_and_tenant_change_in_one_year():
    prop, first, second = _two_flats()
    _lease(prop, first, "A", end=date(2025, 6, 30))
    _lease(prop, first, "B", start=date(2025, 7, 1))
    _lease(prop, second, "C")
    _meter(first, "cold_water", [(date(2025, 1, 1), 1000), (date(2025, 4, 10), 1020)],
           removal_date=date(2025, 4, 10), is_active=False)
    _meter(first, "cold_water", [(date(2025, 4, 10), 0), (date(2025, 6, 30), 15), (date(2025, 12, 31), 45)],
           installation_date=date(2025, 4, 10))
    _meter(second, "cold_water", [(date(2025, 1, 1), 0), (date(2025, 12, 31), 35)])
    period = _period(prop, [("Wasser", 1000, _key(prop, "consumption", meter_type="cold_water"))])

    rows = _by(billing.generate_utility_statements(period.id), "unit_id", "usage_start")
    _, warnings = _issues(period)

    # A: old meter 1020 - 1000 = 20 + new meter 15 - 0 = 15 -> 35 m³; B: 45 - 15 = 30 m³; C: 35 m³ of 100
    assert rows[(first.id, date(2025, 1, 1))].total_cost == 350.0
    assert rows[(first.id, date(2025, 7, 1))].total_cost == 300.0
    assert rows[(second.id, date(2025, 1, 1))].total_cost == 350.0
    assert "MISSING_INTERMEDIATE_READING" not in warnings


def test_b3_reset_on_the_same_meter_is_never_a_negative_share():
    prop, first, second = _two_flats()
    _lease(prop, first, "C-1")
    _lease(prop, second, "C-2")
    _meter(first, "cold_water", [(date(2025, 1, 1), 100), (date(2025, 6, 15), 160), (date(2025, 12, 31), 40)],
           serial_number="KW-1")
    _meter(second, "cold_water", [(date(2025, 1, 1), 0), (date(2025, 12, 31), 100)])
    period = _period(prop, [("Wasser", 1000, _key(prop, "consumption", meter_type="cold_water"))])

    blockers, _ = _issues(period)

    assert blockers["INVALID_CONSUMPTION"].context == "WE 01 (KW-1)"
    assert "Ausbaudatum" in blockers["INVALID_CONSUMPTION"].message


def test_b4_a_deactivated_meter_needs_its_removal_date():
    prop, first, second = _two_flats()
    _lease(prop, first, "C-1")
    _lease(prop, second, "C-2")
    _meter(first, "cold_water", [(date(2025, 1, 1), 100), (date(2025, 6, 15), 160)],
           is_active=False, serial_number="ALT")
    _meter(first, "cold_water", [(date(2025, 6, 15), 0), (date(2025, 12, 31), 40)],
           installation_date=date(2025, 6, 15))
    _meter(second, "cold_water", [(date(2025, 1, 1), 0), (date(2025, 12, 31), 100)])
    period = _period(prop, [("Wasser", 1000, _key(prop, "consumption", meter_type="cold_water"))])

    blockers, _ = _issues(period)

    # without it 60 m³ of the old meter would silently disappear
    assert blockers["METER_REMOVAL_DATE_MISSING"].context == "WE 01 (ALT)"
    with pytest.raises(ValueError, match="Ausbaudatum"):
        MeterCreate(unit_id=first.id, meter_type="cold_water", installation_date=date(2025, 6, 15),
                    removal_date=date(2025, 6, 1))


# --- C: dated occupants --------------------------------------------------------------------


def test_c1_person_key_counts_person_days():
    prop, first, second = _two_flats()
    family = _lease(prop, first, "C-1", persons=2)
    _lease(prop, second, "C-2", persons=2)
    contracts.add_occupancy(family.id, ContractOccupancyCreate(
        contract_id=family.id, valid_from=date(2025, 7, 1), persons=3, notes="Geburt"))
    period = _period(prop, [("Müll", 1000, _key(prop, "person_count", "Personen"))])

    # Regression: the household size was a constant (500 € / 500 €).
    rows = _by(billing.generate_utility_statements(period.id), "unit_id")

    # WE 01: 2 × 181 + 3 × 184 = 914 person-days, WE 02: 2 × 365 = 730, of 1,644
    # 1000 × 914 / 1644 = 555.961 -> 555.96; 444.038 -> 444.04 (largest remainder)
    assert (rows[(first.id,)].total_cost, rows[(second.id,)].total_cost) == (555.96, 444.04)
    line = rows[(first.id,)].line_items[0]
    assert line["basis"] == pytest.approx(914 / 365) and line["total_basis"] == pytest.approx(1644 / 365)
    assert line["sections"] == [
        {"start": "2025-01-01", "end": "2025-06-30", "days": 181, "basis": 2.0},
        {"start": "2025-07-01", "end": "2025-12-31", "days": 184, "basis": 3.0},
    ]
    share = next(row[2] for row in billing._statement_document(rows[(first.id,)])["rows"])
    assert "01.01.2025–30.06.2025: 2 Personen × 181 Tage; 01.07.2025–31.12.2025: 3 Personen × 184 Tage" in share


def test_c2_occupancy_from_before_the_period_and_down_to_zero():
    prop, first, second = _two_flats()
    family = _lease(prop, first, "C-1", persons=3)
    _lease(prop, second, "C-2", persons=1)
    for valid_from, persons in [(date(2024, 5, 1), 1), (date(2025, 10, 1), 0)]:
        contracts.add_occupancy(family.id, ContractOccupancyCreate(
            contract_id=family.id, valid_from=valid_from, persons=persons))
    period = _period(prop, [("Müll", 638, _key(prop, "person_count"))])

    rows = _by(billing.generate_utility_statements(period.id), "unit_id")

    # WE 01: 1 × 273 (to 30.09.) + 0 × 92 = 273, WE 02: 1 × 365 -> 273 € / 365 € of 638 €
    assert (rows[(first.id,)].total_cost, rows[(second.id,)].total_cost) == (273.0, 365.0)


def test_c3_occupancies_stay_within_the_contract():
    prop, first, _ = _two_flats()
    lease = _lease(prop, first, "C-1", start=date(2024, 3, 1), end=date(2025, 8, 31), persons=2)
    entry = contracts.add_occupancy(lease.id, ContractOccupancyCreate(
        contract_id=lease.id, valid_from=date(2025, 1, 1), persons=3))

    for valid_from in (date(2024, 2, 29), date(2025, 9, 1), date(2025, 1, 1)):
        with pytest.raises(HTTPException) as exc:
            contracts.add_occupancy(lease.id, ContractOccupancyCreate(
                contract_id=lease.id, valid_from=valid_from, persons=1))
        assert exc.value.status_code == 400
    with pytest.raises(HTTPException):
        contracts.add_occupancy("other", ContractOccupancyCreate(contract_id=lease.id,
                                                                 valid_from=date(2025, 2, 1), persons=1))
    assert [o.id for o in contracts.list_occupancies(lease.id)] == [entry.id]
    contracts.delete_occupancy(lease.id, entry.id)
    assert contracts.list_occupancies(lease.id) == []


# --- D: real sections ----------------------------------------------------------------------


def test_d1_leap_year_days_are_inclusive():
    prop = _property()
    flat, other = _unit(prop, "WE 01", 60, (100, 0)), _unit(prop, "WE 02", 40, (100, 0))
    _lease(prop, flat, "A", start=date(2023, 1, 1), end=date(2024, 2, 29))
    _lease(prop, flat, "B", start=date(2024, 4, 1))
    _lease(prop, other, "O")
    period = _period(prop, [("Grundsteuer", 3660, _key(prop, "area_sqm"))], date(2024, 1, 1), date(2024, 12, 31))

    rows = _by(billing.generate_utility_statements(period.id), "unit_id", "usage_start")

    # 366 days; m²-days: A 60 × 60, vacancy 60 × 31, B 60 × 275, O 40 × 366 of 36,600
    a, vacancy = rows[(flat.id, date(2024, 1, 1))], rows[(flat.id, date(2024, 3, 1))]
    b, o = rows[(flat.id, date(2024, 4, 1))], rows[(other.id, date(2024, 1, 1))]
    assert [(s.usage_days, s.total_cost) for s in (a, vacancy, b, o)] == [
        (60, 360.0), (31, 186.0), (275, 1650.0), (366, 1464.0)]
    # advances 100 €/month: A January + February (29 days, a full month) = 200 €, B April-December = 900 €
    assert (a.advance_paid, vacancy.advance_paid, b.advance_paid) == (200.0, 0.0, 900.0)
    assert a.line_items[0]["period_days"] == 366


def test_d2_an_advance_change_mid_month_splits_the_month_by_days():
    prop = _property()
    flat = _unit(prop, "WE 01", 50, (100, 50))
    lease = _lease(prop, flat, "C-1", history=True)
    store.create_contract_rent_period(ContractRentPeriodCreate(
        contract_id=lease.id, valid_from=date(2025, 4, 16), cold_rent=500, service_charge_advance=200,
        heating_advance=100))
    period = _period(prop, [("Grundsteuer", 100, _key(prop, "area_sqm"))])

    [stmt] = billing.generate_utility_statements(period.id)

    # Regression: April counted the advance of 01.04. only (3,000 €).
    # 3 × 150 + 150 × 15/30 = 525 €; 300 × 15/30 + 8 × 300 = 2,550 € -> 3,075 €
    assert stmt.advance_paid == 3075.0
    assert stmt.advance_sections == [
        {"start": "2025-01-01", "end": "2025-04-15", "days": 105, "monthly": 150.0, "amount": 525.0},
        {"start": "2025-04-16", "end": "2025-12-31", "days": 260, "monthly": 300.0, "amount": 2550.0},
    ]
    advances = billing._statement_document(stmt)["advances"]
    assert advances[1] == ("16.04.2025 – 31.12.2025", "300,00 € / Monat", "2.550,00 €")


def test_d3_tenant_and_person_changes_are_sections_of_their_own():
    prop, first, second = _two_flats()
    _lease(prop, first, "A", end=date(2025, 5, 31), persons=1)
    family = _lease(prop, first, "B", start=date(2025, 6, 1), persons=2)
    _lease(prop, second, "C", persons=2)
    contracts.add_occupancy(family.id, ContractOccupancyCreate(
        contract_id=family.id, valid_from=date(2025, 9, 1), persons=4))
    period = _period(prop, [("Müll", 1553, _key(prop, "person_count"))])

    rows = _by(billing.generate_utility_statements(period.id), "unit_id", "usage_start")

    # A: 1 × 151 = 151; B: 2 × 92 + 4 × 122 = 672; C: 2 × 365 = 730 person-days of 1,553
    a, b = rows[(first.id, date(2025, 1, 1))], rows[(first.id, date(2025, 6, 1))]
    assert [(s.usage_days, s.total_cost) for s in (a, b)] == [(151, 151.0), (214, 672.0)]
    assert rows[(second.id, date(2025, 1, 1))].total_cost == 730.0
    assert [s["days"] for s in b.line_items[0]["sections"]] == [92, 122]
    assert "sections" not in a.line_items[0]


def test_d4_partial_months_at_move_in_and_move_out():
    prop = _property()
    flat = _unit(prop, "WE 01", 50, (100, 40))
    _lease(prop, flat, "C-1", start=date(2025, 2, 15), end=date(2025, 11, 10), history=True)
    period = _period(prop, [("Grundsteuer", 100, _key(prop, "area_sqm"))])

    tenant = next(s for s in billing.generate_utility_statements(period.id) if s.party == "tenant")

    # 140 × 14/28 = 70 + 8 × 140 = 1,120 + 140 × 10/30 = 46.67 -> 1,236.67 €; 269 days
    assert (tenant.usage_days, tenant.advance_paid) == (269, 1236.67)


# --- E: vacancy ----------------------------------------------------------------------------


def test_e1_vacancy_carries_its_consumption_and_is_never_billed():
    prop = _property()
    empty, let = _unit(prop, "WE 01"), _unit(prop, "WE 02", advance=(10, 0))
    _lease(prop, let, "C-1", history=True)
    _meter(empty, "cold_water", [(date(2025, 1, 1), 0), (date(2025, 12, 31), 5)])
    _meter(let, "cold_water", [(date(2025, 1, 1), 0), (date(2025, 12, 31), 15)])
    period = _period(prop, [("Wasser", 200, _key(prop, "consumption", meter_type="cold_water"))])

    rows = _by(billing.generate_utility_statements(period.id), "party")
    billing.finalize_billing_period(period.id)
    billing.create_receivables_from_period(period.id)

    # 5 m³ vacant, 15 m³ let of 20 m³ -> 50 € landlord, 150 € tenant (advance 120 €)
    vacancy, tenant = rows[("vacancy",)], rows[("tenant",)]
    assert (vacancy.contract_id, vacancy.total_cost, vacancy.advance_paid, vacancy.balance) == (None, 50.0, 0.0, 50.0)
    assert (tenant.total_cost, tenant.advance_paid, tenant.balance) == (150.0, 120.0, 30.0)
    assert [r.amount_due for r in store.list_receivables()] == [30.0]


def test_e2_vacancy_between_tenants_with_a_meter_replaced_while_empty():
    prop, first, second = _two_flats()
    _lease(prop, first, "A", end=date(2025, 3, 31))
    _lease(prop, first, "B", start=date(2025, 6, 1))
    _lease(prop, second, "C")
    _meter(first, "cold_water", [(date(2025, 1, 1), 0), (date(2025, 3, 31), 30), (date(2025, 5, 1), 32)],
           removal_date=date(2025, 5, 1), is_active=False)
    _meter(first, "cold_water", [(date(2025, 5, 1), 0), (date(2025, 5, 31), 1), (date(2025, 12, 31), 41)],
           installation_date=date(2025, 5, 1))
    _meter(second, "cold_water", [(date(2025, 1, 1), 0), (date(2025, 12, 31), 27)])
    period = _period(prop, [("Wasser", 1000, _key(prop, "consumption", meter_type="cold_water"))])

    rows = _by(billing.generate_utility_statements(period.id), "unit_id", "party", "usage_start")

    # A 30 m³; vacancy (32 - 30) + (1 - 0) = 3 m³; B 41 - 1 = 40 m³; C 27 m³ of 100 m³
    assert rows[(first.id, "tenant", date(2025, 1, 1))].total_cost == 300.0
    assert rows[(first.id, "vacancy", date(2025, 4, 1))].total_cost == 30.0
    assert rows[(first.id, "tenant", date(2025, 6, 1))].total_cost == 400.0
    assert rows[(second.id, "tenant", date(2025, 1, 1))].total_cost == 270.0


# --- F: objection and correction -----------------------------------------------------------


def test_f1_an_objection_is_recorded_and_the_issued_version_stays():
    case = _finalized()
    period, big_stmt = case["period"], next(s for s in case["stmts"] if s.unit_id == case["units"][0].id)
    before = _content(_stored(period.id))

    objection = billing.create_billing_objection(period.id, BillingObjectionRequest(
        statement_id=big_stmt.id, received_on=date(2026, 2, 1), reason="Fläche falsch"))

    assert store.get_billing_period(period.id).status == "disputed"
    assert (objection.status, objection.statement_id, objection.received_on) == ("open", big_stmt.id, date(2026, 2, 1))
    assert [o.reason for o in billing.list_billing_objections(period.id)] == ["Fläche falsch"]
    # Regression: a disputed period could be regenerated, edited and deleted.
    for change in (lambda: billing.generate_utility_statements(period.id),
                   lambda: billing.create_cost_item(CostItemCreate(billing_period_id=period.id, description="X",
                                                                   amount=1, allocation_key_id=case["key"].id)),
                   lambda: billing.delete_billing_period(period.id),
                   lambda: billing.patch_utility_statement(big_stmt.id, UtilityStatementPatch(total_cost=1)),
                   lambda: billing.delete_utility_statement(big_stmt.id)):
        with pytest.raises(HTTPException) as exc:
            change()
        assert exc.value.status_code == 409
    assert _content(_stored(period.id)) == before
    assert billing.get_billing_period_preflight(period.id).metrics["final_version_intact"] is True


def test_f2_a_correction_is_a_new_version_and_bills_only_the_difference():
    case = _finalized()
    period = case["period"]
    big, small = case["contracts"]
    billing.create_receivables_from_period(period.id)
    # WE 01: 600 € - 480 € = +120 €, WE 02: 400 € - 480 € = -80 €
    assert sorted(r.amount_due for r in store.list_receivables()) == [-80.0, 120.0]
    issued = _content(_stored(period.id))
    billing.dispute_billing_period(period.id, reason="Grundsteuerbescheid nur 800 €")

    revision = billing.create_period_revision(period.id, revision_notes="Bescheid vom 03.02.2026")
    correction = store.get_billing_period(revision["new_period_id"])
    assert (correction.corrects_period_id, correction.revision, correction.status) == (period.id, 2, "draft")
    assert correction.label == "BK 2025 (Korrektur Rev. 2)"
    [objection] = billing.list_billing_objections(period.id)
    assert (objection.status, objection.correction_period_id) == ("correction", correction.id)
    with pytest.raises(HTTPException) as exc:  # one open correction per version
        billing.create_period_revision(period.id)
    assert exc.value.status_code == 409

    [tax] = [ci for ci in store.list_cost_items() if ci.billing_period_id == correction.id]
    billing.patch_cost_item(tax.id, CostItemPatch(amount=800))
    stmts = _by(billing.generate_utility_statements(correction.id), "contract_id")
    billing.finalize_billing_period(correction.id)
    billing.create_receivables_from_period(correction.id)

    # 800 € by area: 480 € / 320 €; balances 0 € / -160 €
    assert [(stmts[(c.id,)].total_cost, stmts[(c.id,)].balance) for c in (big, small)] == [(480.0, 0.0), (320.0, -160.0)]
    assert {(s.revision, s.revision_notes) for s in stmts.values()} == {(2, "Bescheid vom 03.02.2026")}
    assert store.get_billing_period(period.id).status == "corrected"
    assert billing.list_billing_objections(period.id)[0].status == "resolved"
    assert _content(_stored(period.id)) == issued  # the corrected version stays as issued
    # receivables of the correction: only the difference, 0 - 120 = -120 €, -160 - (-80) = -80 €
    by_contract: dict = {}
    for receivable in store.list_receivables():
        by_contract.setdefault(receivable.contract_id, []).append(receivable.amount_due)
    assert (sorted(by_contract[big.id]), sorted(by_contract[small.id])) == ([-120.0, 120.0], [-80.0, -80.0])
    facts = dict(billing._statement_document(stmts[(big.id,)])["facts"])
    assert facts["Fassung"] == "Korrektur Rev. 2, ersetzt die vorherige Fassung"
    with pytest.raises(HTTPException):  # the corrected version is closed
        billing.create_period_revision(period.id)


def test_f3_objections_need_an_issued_statement_of_the_period():
    case = _finalized()
    other = _finalized("Anderes Haus")
    with pytest.raises(HTTPException) as exc:
        billing.create_billing_objection(case["period"].id, BillingObjectionRequest(
            statement_id=other["stmts"][0].id, reason="falsch"))
    assert exc.value.status_code == 400

    prop = _property("Entwurf")
    flat = _unit(prop, "WE 01")
    _lease(prop, flat, "D-1")
    draft = _period(prop, [("Grundsteuer", 100, _key(prop, "area_sqm"))])
    for attempt in (lambda: billing.dispute_billing_period(draft.id),
                    lambda: billing.create_period_revision(draft.id)):
        with pytest.raises(HTTPException) as exc:
            attempt()
        assert exc.value.status_code == 400

    billing.dispute_billing_period(case["period"].id)  # without a reason
    billing.dispute_billing_period(case["period"].id, reason="zweiter Mieter")  # a second objection
    assert [o.reason for o in billing.list_billing_objections(case["period"].id)] == [
        "ohne Begründung", "zweiter Mieter"]


# --- G: unchanged final version ------------------------------------------------------------


@pytest.mark.parametrize("state", ["finalized", "delivered", "disputed"])
def test_g1_an_issued_period_refuses_every_change(state):
    case = _finalized()
    period, stmt = case["period"], case["stmts"][0]
    if state == "delivered":
        billing.mark_statement_delivered(stmt.id)
        billing._set_period_status(period.id, "delivered")
    if state == "disputed":
        billing.dispute_billing_period(period.id, reason="x")
    before = _content(_stored(period.id))
    cost = next(ci for ci in store.list_cost_items() if ci.billing_period_id == period.id)

    changes = [
        lambda: billing.generate_utility_statements(period.id),
        lambda: billing.update_billing_period(period.id, BillingPeriodCreate(
            property_id=period.property_id, label="neu", start_date=period.start_date, end_date=period.end_date)),
        lambda: billing.patch_billing_period(period.id, BillingPeriodPatch(status="draft")),
        lambda: billing.delete_billing_period(period.id),
        lambda: billing.patch_cost_item(cost.id, CostItemPatch(amount=1)),
        lambda: billing.delete_cost_item(cost.id),
        lambda: billing.patch_utility_statement(stmt.id, UtilityStatementPatch(total_cost=1)),
        lambda: billing.delete_utility_statement(stmt.id),
    ]
    for change in changes:
        with pytest.raises(HTTPException) as exc:
            change()
        assert exc.value.status_code == 409
    assert _content(_stored(period.id)) == before


def test_g2_status_changes_only_through_the_workflow():
    prop = _property()
    flat = _unit(prop, "WE 01")
    _lease(prop, flat, "C-1")
    draft = _period(prop, [("Grundsteuer", 100, _key(prop, "area_sqm"))])

    # Regression: PATCH status=finalized finalized a period without statements or hash.
    for attempt in (lambda: billing.patch_billing_period(draft.id, BillingPeriodPatch(status="finalized")),
                    lambda: billing.create_billing_period(BillingPeriodCreate(
                        property_id=prop.id, label="X", start_date=Y2025[0], end_date=Y2025[1], status="finalized")),
                    lambda: billing.create_billing_period(BillingPeriodCreate(
                        property_id=prop.id, label="X", start_date=Y2025[0], end_date=Y2025[1],
                        corrects_period_id=draft.id, revision=2))):
        with pytest.raises(HTTPException) as exc:
            attempt()
        assert exc.value.status_code == 400
    assert store.get_billing_period(draft.id).status == "draft"


def test_g3_the_issued_document_and_pdf_survive_later_edits():
    case = _finalized()
    period, (big, _) = case["period"], case["contracts"]
    stmt = next(s for s in _stored(period.id) if s.contract_id == big.id)
    document, pdf = billing._statement_document(stmt), billing.download_utility_statement_pdf(stmt.id).body

    tenant = store.get_tenant(big.tenant_id)
    store.update_tenant(tenant.id, TenantCreate(full_name="Umbenannt"))
    store._patch_entity("contract", big.id, ContractPatch(contract_number="V-1-neu", persons=5))
    unit = case["units"][0]
    store.update_unit(unit.id, UnitCreate(**{**unit.model_dump(include=set(UnitCreate.model_fields)),
                                             "label": "WE 01 neu", "area_sqm": 90}))
    prop = case["prop"]
    store.update_property(prop.id, PropertyCreate(**{**prop.model_dump(include=set(PropertyCreate.model_fields)),
                                                     "name": "Anderer Name"}))

    # Regression: the PDF of an issued statement showed today's names (and new bytes each time).
    stored = store.get_utility_statement(stmt.id)
    assert billing._statement_document(stored) == document
    assert dict(document["facts"])["Mieter"] == "Mieter V-1"
    assert billing.download_utility_statement_pdf(stmt.id).body == pdf
    preflight = billing.get_billing_period_preflight(period.id)
    assert preflight.metrics["final_version_intact"] is True
    # today's data would give another result (90 m²): shown, but the issued version stays
    assert "FINAL_VERSION_DIFFERS" in {w.code for w in preflight.warnings}


def test_g4_the_store_refuses_to_change_an_issued_statement():
    case = _finalized()
    stmt = _stored(case["period"].id)[0]

    with pytest.raises(ValidationError):
        store._patch_entity("utility_statement", stmt.id, UtilityStatementPatch(total_cost=1.0))
    with pytest.raises(ValidationError):
        store.delete_utility_statement(stmt.id)
    with pytest.raises(ValidationError):
        store.delete_billing_period(case["period"].id)
    delivered = store._patch_entity("utility_statement", stmt.id, UtilityStatementPatch(
        status="delivered", delivery_status="delivered", delivery_channel="post"))
    assert (delivered.status, delivered.total_cost) == ("delivered", stmt.total_cost)


def test_g5_a_snapshot_cannot_change_an_issued_version():
    case = _finalized()
    period = case["period"]
    snapshot = export_snapshot(store)
    issued = _content(_stored(period.id))

    tampered = copy.deepcopy(snapshot)
    tampered["utility_statements"][0]["total_cost"] = 1.0
    with pytest.raises(SnapshotError, match="weicht von der finalisierten Fassung ab"):
        import_snapshot(store, tampered, replace=True)
    extra_row = {"utility_statements": [{**snapshot["utility_statements"][0], "id": "extra-row"}]}
    extra_cost = {"cost_items": [{**snapshot["cost_items"][0], "id": "extra-cost"}]}
    for addition in (extra_row, extra_cost):
        with pytest.raises(SnapshotError, match="finalisiert"):
            import_snapshot(store, addition, replace=False)
    assert _content(_stored(period.id)) == issued

    import_snapshot(store, snapshot, replace=True)  # the untouched file restores as issued
    assert _content(_stored(period.id)) == issued
    assert billing.get_billing_period_preflight(period.id).metrics["final_version_intact"] is True


def test_g6_a_key_with_costs_is_not_deleted_with_them():
    case = _finalized()
    with pytest.raises(HTTPException) as exc:
        billing.delete_allocation_key(case["key"].id)
    assert exc.value.status_code == 409
    assert any(ci.allocation_key_id == case["key"].id for ci in store.list_cost_items())


# --- HTTP ----------------------------------------------------------------------------------


def test_http_occupancies_objections_and_meter_units():
    from fastapi.testclient import TestClient

    from backend.app import app
    from backend.auth import clear_users, create_access_token, register_user

    case = _finalized()
    big, _ = case["contracts"]
    clear_users()
    owner = register_user("owner", "owner@example.com", "Owner", "Secret123", "eigentuemer")
    try:
        client = TestClient(app, headers={"Authorization": f"Bearer {create_access_token(owner.id)}"})
        added = client.post(f"/api/v1/contracts/{big.id}/occupancies",
                            json={"contract_id": big.id, "valid_from": "2025-03-01", "persons": 4})
        listed = client.get(f"/api/v1/contracts/{big.id}/occupancies")
        objection = client.post(f"/api/v1/billing/periods/{case['period'].id}/objections",
                                json={"statement_id": case["stmts"][0].id, "received_on": "2026-01-20",
                                      "reason": "Fläche"})
        objections = client.get("/api/v1/billing/objections", params={"billing_period_id": case["period"].id})
        meter = client.post("/api/v1/meters", json={"unit_id": case["units"][0].id, "meter_type": "heating",
                                                    "measure_unit": "MWh", "removal_date": "2025-06-30"})
        regenerate = client.post(f"/api/v1/billing/periods/{case['period'].id}/generate")
    finally:
        clear_users()

    assert added.status_code == 201, added.text
    assert [o["persons"] for o in listed.json()] == [4]
    assert objection.status_code == 201, objection.text
    assert [o["reason"] for o in objections.json()] == ["Fläche"]
    assert (meter.json()["measure_unit"], meter.json()["removal_date"]) == ("MWh", "2025-06-30")
    assert regenerate.status_code == 409
