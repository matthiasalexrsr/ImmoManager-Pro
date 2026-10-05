"""Utility statements by usage period: reference cases from the review and edge cases."""

from datetime import date, timedelta

import pytest
from fastapi import HTTPException

from backend.dependencies import store
from backend.models import (
    AllocationKeyCreate,
    BillingPeriodCreate,
    ContractCreate,
    ContractPatch,
    CostItemCreate,
    MeterCreate,
    PortfolioCreate,
    PropertyCreate,
    StandaloneMeterReadingCreate,
    TenantCreate,
    UnitCreate,
)
from backend.routers import billing
from backend.services.data_snapshot import clear_business_data
from backend.services.utility_billing import compute_period_billing, statement_deadline

Y2025 = (date(2025, 1, 1), date(2025, 12, 31))


@pytest.fixture(autouse=True)
def _clean():
    clear_business_data(store)
    yield
    clear_business_data(store)


def _property(name: str):
    pf = store.create_portfolio(PortfolioCreate(name=name))
    return store.create_property(PropertyCreate(portfolio_id=pf.id, name=name, property_type="residential"))


def _unit(prop, label, area, advance=(0, 0), persons=None, rooms=None, unit_type="residential"):
    return store.create_unit(UnitCreate(
        property_id=prop.id, label=label, unit_type=unit_type, area_sqm=area, rooms=rooms,
        service_charge_advance=advance[0], heating_advance=advance[1], person_count=persons))


def _lease(prop, unit, number, start, end=None, status="active", persons=None):
    tenant = store.create_tenant(TenantCreate(full_name=f"Mieter {number}"))
    return store.create_contract(ContractCreate(
        contract_number=number, property_id=prop.id, unit_id=unit.id, tenant_id=tenant.id,
        start_date=start, end_date=end, status=status, persons=persons))


def _period(prop, costs, start=Y2025[0], end=Y2025[1]):
    period = store.create_billing_period(BillingPeriodCreate(
        property_id=prop.id, label="BK", start_date=start, end_date=end))
    keys = {}
    for description, amount, key_type, *rest in costs:
        recoverable = rest[0] if rest else True
        if key_type not in keys:
            keys[key_type] = store.create_allocation_key(AllocationKeyCreate(
                property_id=prop.id, name=key_type, key_type=key_type))
        store.create_cost_item(CostItemCreate(
            billing_period_id=period.id, description=description, amount=amount,
            allocation_key_id=keys[key_type].id, is_recoverable=recoverable))
    return period


def _rows(statements, units):
    label = {u.id: u.label for u in units}
    return {(label[s.unit_id], s.party, s.usage_start): s for s in statements}


@pytest.fixture
def leipzig():
    """MFH Gohliser Str. 12 from the review: WE 06 changes tenant with two months vacancy."""
    prop = _property("Leipzig")
    spec = [("WE 01", 62, 2, (140, 70)), ("WE 02", 58, 1, (130, 65)), ("WE 03", 75, 3, (165, 85)),
            ("WE 04", 75, 4, (165, 85)), ("WE 05", 90, 2, (190, 100))]
    units = [_unit(prop, label, area, advance, persons=p) for label, area, p, advance in spec]
    we06 = _unit(prop, "WE 06", 60, (135, 65), rooms=1.5)  # no person count: rooms stand in
    units.append(we06)
    for i, unit in enumerate(units[:5]):
        _lease(prop, unit, f"A-00{i + 1}", date(2020, 1, 1))
    lukas = _lease(prop, we06, "A-006", date(2021, 3, 1), date(2025, 6, 30), status="terminated")
    sophie = _lease(prop, we06, "A-007", date(2025, 9, 1))
    period = _period(prop, [("Grundsteuer", 1800, "area_sqm"), ("Müllabfuhr", 1200, "person_count"),
                            ("Allgemeinstrom", 600, "unit_count"), ("Heizung/Warmwasser", 9000, "area_sqm")])
    return {"prop": prop, "units": units, "period": period, "lukas": lukas, "sophie": sophie}


@pytest.fixture
def koeln():
    """WGH Aachener Str. 5 from the review: shop, empty flat, new tenant from November, garage."""
    prop = _property("Köln")
    units = [_unit(prop, "Laden EG", 180, (450, 200)), _unit(prop, "Whg 1.OG", 100, (220, 110), persons=3),
             _unit(prop, "Whg 2.OG", 100, (220, 110)), _unit(prop, "Whg 3.OG", 100, (220, 110), persons=2),
             _unit(prop, "Garage 1", 15)]
    _lease(prop, units[0], "B-001", date(2019, 1, 1))
    _lease(prop, units[1], "B-002", date(2024, 3, 1))
    ben = _lease(prop, units[3], "B-003", date(2025, 11, 1))
    _lease(prop, units[4], "B-004", date(2024, 3, 1))
    period = _period(prop, [("Grundsteuer", 4000, "area_sqm"), ("Versicherung", 2400, "area_sqm"),
                            ("Hausmeister", 3000, "unit_count")])
    return {"prop": prop, "units": units, "period": period, "ben": ben}


# --- Reference cases from the review ------------------------------------------------


def test_leipzig_tenant_change_is_billed_by_days(leipzig):
    """Regression: Lukas got no statement and Sophie paid the full year (976.19 € back payment)."""
    stmts = billing.generate_utility_statements(leipzig["period"].id)
    rows = _rows(stmts, leipzig["units"])

    lukas = rows[("WE 06", "tenant", date(2025, 1, 1))]
    vacancy = rows[("WE 06", "vacancy", date(2025, 7, 1))]
    sophie = rows[("WE 06", "tenant", date(2025, 9, 1))]
    assert (lukas.contract_id, lukas.usage_days, lukas.total_cost, lukas.advance_paid, lukas.balance) == (
        leipzig["lukas"].id, 181, 880.80, 1200.00, -319.20)
    # Exact shares are 880.797 / 301.709 / 593.686 €; every cost item is rounded on its own
    # (largest remainder), so a row may be a cent off its exact total while the sum stays exact.
    assert (vacancy.contract_id, vacancy.usage_days, vacancy.total_cost, vacancy.advance_paid) == (
        None, 62, 301.72, 0)
    assert (sophie.contract_id, sophie.usage_days, sophie.total_cost, sophie.advance_paid, sophie.balance) == (
        leipzig["sophie"].id, 122, 593.68, 800.00, -206.32)
    assert sum(s.total_cost for s in stmts) == pytest.approx(12600.00)


def test_koeln_vacancy_stays_with_the_landlord(koeln):
    """Regression: 100 % of the costs went to the let units; the empty flat was not in the denominator."""
    stmts = billing.generate_utility_statements(koeln["period"].id)
    rows = _rows(stmts, koeln["units"])

    assert rows[("Laden EG", "tenant", date(2025, 1, 1))].total_cost == 2927.27
    assert rows[("Whg 1.OG", "tenant", date(2025, 1, 1))].total_cost == 1892.93
    assert rows[("Garage 1", "tenant", date(2025, 1, 1))].total_cost == 793.94
    assert rows[("Whg 2.OG", "vacancy", date(2025, 1, 1))].total_cost == 1892.93
    ben = rows[("Whg 3.OG", "tenant", date(2025, 11, 1))]
    assert (ben.usage_days, ben.total_cost, ben.advance_paid, ben.balance) == (61, 316.35, 660.00, -343.65)
    assert rows[("Whg 3.OG", "vacancy", date(2025, 1, 1))].total_cost == 1576.58
    assert sum(s.total_cost for s in stmts) == pytest.approx(9400.00)


def test_line_items_explain_the_share(koeln):
    stmts = billing.generate_utility_statements(koeln["period"].id)
    ben = next(s for s in stmts if s.contract_id == koeln["ben"].id)
    tax = next(li for li in ben.line_items or [] if li["description"] == "Grundsteuer")

    assert (tax["key_type"], tax["basis"], tax["total_basis"], tax["days"], tax["period_days"]) == (
        "area_sqm", 100.0, 495.0, 61, 365)
    assert tax["total_amount"] == 4000.0 and tax["cost_item_id"]


def test_preflight_names_tenant_change_and_vacancy(leipzig):
    result = billing.get_billing_period_preflight(leipzig["period"].id)
    warnings = {w.code: w for w in result.warnings}

    assert not result.has_blockers
    assert "A-006 01.01.2025–30.06.2025" in (warnings["TENANT_CHANGE"].context or "")
    assert warnings["VACANCY"].context == "WE 06: 62 Tage"
    assert result.metrics["vacancy_days"] == 62 and result.metrics["contracts_in_period"] == 7


# --- Rules -----------------------------------------------------------------------------


def test_non_recoverable_costs_are_not_billed():
    """Regression: a roof repair marked as not recoverable was billed to the tenant."""
    prop = _property("H")
    unit = _unit(prop, "1", 50, (100, 0))
    _lease(prop, unit, "C-1", date(2020, 1, 1))
    period = _period(prop, [("Grundsteuer", 500, "area_sqm"), ("Dachreparatur", 8000, "area_sqm", False)])

    stmts = billing.generate_utility_statements(period.id)
    warning = next(w for w in billing.get_billing_period_preflight(period.id).warnings
                   if w.code == "NON_RECOVERABLE_COSTS")

    assert [s.total_cost for s in stmts] == [500.0]
    assert "Dachreparatur" in (warning.context or "")


def test_household_size_of_the_contract_beats_the_unit():
    prop = _property("H")
    big, small = _unit(prop, "1", 50, persons=2), _unit(prop, "2", 50, persons=2)
    _lease(prop, big, "C-1", date(2020, 1, 1), persons=4)
    _lease(prop, small, "C-2", date(2020, 1, 1))
    period = _period(prop, [("Müll", 600, "person_count")])

    totals = {s.unit_id: s.total_cost for s in billing.generate_utility_statements(period.id)}

    assert (totals[big.id], totals[small.id]) == (400.0, 200.0)


def test_empty_flat_counts_as_one_person_for_the_landlord():
    prop = _property("H")
    let = _unit(prop, "1", 50, persons=3)
    _unit(prop, "2", 50, persons=0)  # empty flat
    _lease(prop, let, "C-1", date(2020, 1, 1))
    period = _period(prop, [("Müll", 400, "person_count")])

    rows = {s.party: s.total_cost for s in billing.generate_utility_statements(period.id)}

    assert rows == {"tenant": 300.0, "vacancy": 100.0}


def test_garages_take_no_part_in_the_person_key():
    """Regression: a garage without a person count blocked the whole statement (stress test)."""
    prop = _property("H")
    flat = _unit(prop, "WE 01", 60, persons=2)
    garage = _unit(prop, "Garage 1", 15, unit_type="Stellplatz")
    _unit(prop, "Garage 2", 15, unit_type="parking")  # empty
    _lease(prop, flat, "C-1", date(2020, 1, 1))
    _lease(prop, garage, "C-2", date(2020, 1, 1))
    period = _period(prop, [("Müll", 600, "person_count"), ("Allgemeinstrom", 300, "unit_count")])

    assert not billing.get_billing_period_preflight(period.id).has_blockers
    totals = {(s.unit_id, s.party): s.total_cost for s in billing.generate_utility_statements(period.id)}

    assert totals[(flat.id, "tenant")] == 700.0  # all of the waste, a third of the electricity
    assert totals[(garage.id, "tenant")] == 100.0


def test_shop_needs_an_entered_person_count_and_zero_counts():
    prop = _property("H")
    flat = _unit(prop, "WE 01", 60, persons=2)
    shop = _unit(prop, "Laden", 120, unit_type="Gewerbe")
    _lease(prop, flat, "C-1", date(2020, 1, 1))
    _lease(prop, shop, "C-2", date(2020, 1, 1))
    period = _period(prop, [("Müll", 600, "person_count")])

    blocker = next(b for b in billing.get_billing_period_preflight(period.id).blockers
                   if b.code == "MISSING_PERSON_COUNT")
    assert blocker.context == "Laden" and "Gewerbe" in blocker.message

    store.update_unit(shop.id, UnitCreate(**{**shop.model_dump(include=set(UnitCreate.model_fields)), "person_count": 0}))
    totals = {s.unit_id: s.total_cost for s in billing.generate_utility_statements(period.id)}

    assert (totals[flat.id], totals[shop.id]) == (600.0, 0.0)


def test_a_key_with_no_shares_names_its_costs_and_a_way_out():
    """Shops only: persons add up to 0, so the waste cannot be divided by persons."""
    prop = _property("Gewerbehof")
    shop = _unit(prop, "Laden", 120, unit_type="Gewerbe", persons=0)
    _lease(prop, shop, "C-1", date(2020, 1, 1))
    period = _period(prop, [("Müll", 600, "person_count")])

    blocker = next(b for b in billing.get_billing_period_preflight(period.id).blockers if b.code == "ZERO_TOTAL_SHARE")

    assert "Müll" in (blocker.context or "") and "anderen Schlüssel" in blocker.message


def _consumption_case(intermediate: bool):
    prop = _property("H")
    we06, other = _unit(prop, "WE 06", 60, (100, 0)), _unit(prop, "WE 01", 60, (100, 0))
    _lease(prop, we06, "L", date(2020, 1, 1), date(2025, 6, 30), status="terminated")
    _lease(prop, we06, "S", date(2025, 9, 1))
    _lease(prop, other, "O", date(2020, 1, 1))
    readings = {other.id: [(date(2024, 12, 31), 0), (date(2025, 12, 31), 50)],
                we06.id: [(date(2024, 12, 31), 100), (date(2025, 12, 31), 150)]}
    if intermediate:
        readings[we06.id] += [(date(2025, 6, 30), 130), (date(2025, 9, 1), 131)]
    for unit_id, values in readings.items():
        meter = store.create_meter(MeterCreate(unit_id=unit_id, meter_type="cold_water"))
        for day, value in values:
            store.create_standalone_meter_reading(StandaloneMeterReadingCreate(
                meter_id=meter.id, reading_date=day, value=value))
    period = _period(prop, [("Wasser", 1000, "consumption")])
    return period, we06


def test_consumption_follows_the_readings_at_move_in_and_move_out():
    period, we06 = _consumption_case(intermediate=True)

    rows = {(s.party, s.usage_start): s.total_cost
            for s in billing.generate_utility_statements(period.id) if s.unit_id == we06.id}

    # WE 06: 30 m³ Lukas, 1 m³ vacant, 19 m³ Sophie; WE 01: 50 m³ — of 100 m³ in total
    assert rows == {("tenant", date(2025, 1, 1)): 300.0, ("vacancy", date(2025, 7, 1)): 10.0,
                    ("tenant", date(2025, 9, 1)): 190.0}


def test_consumption_without_intermediate_reading_is_split_by_days():
    period, we06 = _consumption_case(intermediate=False)

    result = billing.get_billing_period_preflight(period.id)
    rows = [s.total_cost for s in billing.generate_utility_statements(period.id) if s.unit_id == we06.id]

    assert "MISSING_INTERMEDIATE_READING" in {w.code for w in result.warnings}
    assert rows == [247.95, 84.93, 167.12]  # 500 € by 181 / 62 / 122 days


def test_consumption_keys_do_not_mix_meter_types():
    """Regression: water m³ and heat units were added up per unit."""
    prop = _property("H")
    unit = _unit(prop, "1", 50)
    _lease(prop, unit, "C-1", date(2020, 1, 1))
    for meter_type in ("cold_water", "heating"):
        meter = store.create_meter(MeterCreate(unit_id=unit.id, meter_type=meter_type))
        for day, value in [(date(2025, 1, 1), 0), (date(2025, 12, 31), 10)]:
            store.create_standalone_meter_reading(StandaloneMeterReadingCreate(
                meter_id=meter.id, reading_date=day, value=value))
    period = _period(prop, [("Wasser", 100, "consumption")])

    blockers = {b.code for b in billing.get_billing_period_preflight(period.id).blockers}

    assert "CONSUMPTION_METER_TYPE_REQUIRED" in blockers


def test_overlapping_legacy_contracts_block_billing():
    prop = _property("H")
    unit = _unit(prop, "1", 50)
    _lease(prop, unit, "C-1", date(2020, 1, 1), date(2025, 6, 30), status="terminated")
    second = _lease(prop, unit, "C-2", date(2025, 7, 1))
    store._patch_entity("contract", second.id, ContractPatch(start_date=date(2025, 3, 1)))  # data from before the check
    period = _period(prop, [("Grundsteuer", 100, "area_sqm")])

    blocker = next(b for b in billing.get_billing_period_preflight(period.id).blockers
                   if b.code == "OVERLAPPING_CONTRACTS")

    assert blocker.context == "1: C-1 / C-2"


def test_deadline_warnings():
    assert statement_deadline(date(2025, 12, 31)) == date(2026, 12, 31)
    prop = _property("H")
    unit = _unit(prop, "1", 50)
    _lease(prop, unit, "C-1", date(2020, 1, 1))
    period = _period(prop, [("Grundsteuer", 100, "area_sqm")])

    late = {w.code for w in compute_period_billing(store, period, today=date(2027, 1, 15)).warnings}
    soon = {w.code for w in compute_period_billing(store, period, today=date(2026, 11, 15)).warnings}

    assert "DEADLINE_PASSED" in late and "DEADLINE_SOON" in soon


# --- Workflow ----------------------------------------------------------------------------


def test_outdated_statements_cannot_be_finalized(leipzig):
    period = leipzig["period"]
    billing.generate_utility_statements(period.id)
    key = store.list_allocation_keys()[0]
    store.create_cost_item(CostItemCreate(billing_period_id=period.id, description="Nachtrag", amount=50,
                                          allocation_key_id=key.id))

    assert "STATEMENTS_OUTDATED" in {w.code for w in billing.get_billing_period_preflight(period.id).warnings}
    with pytest.raises(HTTPException, match="veraltet"):
        billing.finalize_billing_period(period.id)

    billing.generate_utility_statements(period.id)
    assert billing.finalize_billing_period(period.id).status == "finalized"


def test_receivables_only_for_tenants_and_due_in_30_days(koeln):
    """Regression: back payments were due on the last day of the period, i.e. overdue at once."""
    period = koeln["period"]
    billing.generate_utility_statements(period.id)
    billing.finalize_billing_period(period.id)

    billing.create_receivables_from_period(period.id)
    receivables = store.list_receivables()

    assert len(receivables) == 4  # Laden, 1.OG, 3.OG (Ben), Garage — no vacancy rows
    assert {r.due_date for r in receivables} == {date.today() + timedelta(days=30)}
    assert all((r.description or "").startswith("Nebenkostenabrechnung BK: ") for r in receivables)


def test_correction_keeps_cost_items_not_recoverable():
    prop = _property("H")
    unit = _unit(prop, "1", 50)
    _lease(prop, unit, "C-1", date(2020, 1, 1))
    period = _period(prop, [("Grundsteuer", 100, "area_sqm"), ("Dachreparatur", 900, "area_sqm", False)])

    revision = billing.create_period_revision(period.id)

    copies = [ci for ci in store.list_cost_items() if ci.billing_period_id == revision["new_period_id"]]
    assert {(ci.description, ci.is_recoverable) for ci in copies} == {("Grundsteuer", True), ("Dachreparatur", False)}


def test_vacant_unit_with_statement_rows_cannot_be_deleted(koeln):
    from fastapi.testclient import TestClient

    from backend.app import app
    from backend.auth import clear_users, create_access_token, register_user

    billing.generate_utility_statements(koeln["period"].id)
    empty = koeln["units"][2]  # Whg 2.OG: never let, only a vacancy row
    clear_users()
    owner = register_user("owner", "owner@example.com", "Owner", "Secret123", "eigentuemer")
    try:
        client = TestClient(app, headers={"Authorization": f"Bearer {create_access_token(owner.id)}"})
        resp = client.delete(f"/api/v1/units/{empty.id}")
    finally:
        clear_users()

    assert resp.status_code == 409
    assert "1 Nebenkostenabrechnung" in resp.json()["error"]["message"]


def test_statement_pdf_names_tenant_periods_and_shares(koeln):
    stmts = billing.generate_utility_statements(koeln["period"].id)
    ben = next(s for s in stmts if s.contract_id == koeln["ben"].id)
    vacancy = next(s for s in stmts if s.party == "vacancy")

    document = billing._statement_document(ben)
    facts = dict(document["facts"])

    assert facts["Mieter"] == "Mieter B-003"
    assert facts["Abrechnungszeitraum"] == "01.01.2025 – 31.12.2025"
    assert facts["Nutzungszeitraum"] == "01.11.2025 – 31.12.2025 (61 Tage)"
    tax = next(row for row in document["rows"] if row[0] == "Grundsteuer")
    assert tax == ["Grundsteuer", "4.000,00 €", "area_sqm: 100 von 495 m² · 61/365 Tage", "135,05 €"]  # 4000 × 100/495 × 61/365
    assert document["totals"][-1] == ("Guthaben", "343,65 €")
    assert dict(billing._statement_document(vacancy)["facts"])["Mieter"] == "Leerstand (Eigentümer)"
    assert billing.download_utility_statement_pdf(ben.id).media_type in {"application/pdf", "text/plain"}


def test_parking_and_storage_without_area_take_no_part_in_the_area_key():
    """Regression (extreme stress test): a parking space without an area blocked the whole statement."""
    prop = _property("H")
    flat = _unit(prop, "WE 01", 60, persons=2)
    spot = _unit(prop, "Stellplatz 1", None, unit_type="parking")
    cellar = _unit(prop, "Keller 1", None, unit_type="storage")
    _lease(prop, flat, "C-1", date(2020, 1, 1))
    _lease(prop, spot, "C-2", date(2020, 1, 1))
    _lease(prop, cellar, "C-3", date(2020, 1, 1))
    period = _period(prop, [("Grundsteuer", 600, "area_sqm"), ("Müll", 300, "person_count")])

    assert not billing.get_billing_period_preflight(period.id).has_blockers
    totals = {s.unit_id: s.total_cost for s in billing.generate_utility_statements(period.id)}

    assert totals[flat.id] == 900.0
    assert totals.get(spot.id, 0.0) == 0.0 and totals.get(cellar.id, 0.0) == 0.0


def test_a_flat_without_area_still_blocks_the_area_key():
    prop = _property("H")
    flat = _unit(prop, "WE 01", None, persons=2)
    _lease(prop, flat, "C-1", date(2020, 1, 1))
    period = _period(prop, [("Grundsteuer", 600, "area_sqm")])

    assert billing.get_billing_period_preflight(period.id).has_blockers
