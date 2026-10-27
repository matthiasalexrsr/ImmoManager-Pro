"""The utility statement assistant's view: tenancies, keys, costs against the year before, readings, hints."""
from datetime import date

import pytest
from fastapi.testclient import TestClient

from backend import auth
from backend.app import app
from backend.dependencies import store
from backend.models import (
    AllocationKeyCreate,
    BillingPeriodCreate,
    ContractCreate,
    CostItemCreate,
    MeterCreate,
    PortfolioCreate,
    PropertyCreate,
    StandaloneMeterReadingCreate,
    TenantCreate,
    UnitCreate,
)
from backend.services.data_snapshot import clear_business_data


@pytest.fixture
def case():
    clear_business_data(store)
    auth.clear_users()
    owner = auth.register_user("guide-owner", "guide@example.test", "Linda Reiser", "Secret123", "eigentuemer")
    portfolio = store.create_portfolio(PortfolioCreate(name="Bestand", owner_name="Linda Reiser"))
    prop = store.create_property(PropertyCreate(portfolio_id=portfolio.id, name="Gohliser Straße 17", property_type="residential"))
    ground = store.create_unit(UnitCreate(property_id=prop.id, label="EG", unit_type="apartment", area_sqm=60))
    upper = store.create_unit(UnitCreate(property_id=prop.id, label="OG", unit_type="apartment", area_sqm=40))
    store.create_unit(UnitCreate(property_id=prop.id, label="Stellplatz 1", unit_type="Stellplatz"))
    names = {}
    for key, name in (("a", "Anna Alt"), ("b", "Bernd Neu"), ("c", "Clara Oben")):
        names[key] = store.create_tenant(TenantCreate(full_name=name))
    store.create_contract(ContractCreate(contract_number="MV-1", property_id=prop.id, unit_id=ground.id, tenant_id=names["a"].id,
                                         status="terminated", start_date=date(2024, 1, 1), end_date=date(2025, 6, 30), persons=1))
    store.create_contract(ContractCreate(contract_number="MV-2", property_id=prop.id, unit_id=ground.id, tenant_id=names["b"].id,
                                         start_date=date(2025, 8, 1), persons=1))
    store.create_contract(ContractCreate(contract_number="MV-3", property_id=prop.id, unit_id=upper.id, tenant_id=names["c"].id,
                                         start_date=date(2020, 1, 1), persons=2))
    meters = {unit.label: store.create_meter(MeterCreate(unit_id=unit.id, meter_type="cold_water", measure_unit="m³",
                                                         serial_number=f"WZ {index}0000")) for index, unit in enumerate((ground, upper), 1)}
    for meter, days in ((meters["EG"], (date(2025, 1, 1), date(2025, 12, 31))), (meters["OG"], (date(2025, 1, 2), date(2025, 12, 30)))):
        for value, day in enumerate(days):
            store.create_standalone_meter_reading(StandaloneMeterReadingCreate(meter_id=meter.id, reading_date=day, value=10 + value * 40))
    area = store.create_allocation_key(AllocationKeyCreate(property_id=prop.id, name="Fläche", key_type="area_sqm"))
    before = store.create_billing_period(BillingPeriodCreate(property_id=prop.id, label="Nebenkosten 2024", status="finalized",
                                                             start_date=date(2024, 1, 1), end_date=date(2024, 12, 31)))
    for description, amount in (("Grundsteuer", 1000.0), ("Wasser", 800.0), ("Verwaltung", 300.0)):
        store.create_cost_item(CostItemCreate(billing_period_id=before.id, description=description, amount=amount,
                                              allocation_key_id=area.id, is_recoverable=description != "Verwaltung"))
    period = store.create_billing_period(BillingPeriodCreate(property_id=prop.id, label="Nebenkosten 2025",
                                                             start_date=date(2025, 1, 1), end_date=date(2025, 12, 31)))
    store.create_cost_item(CostItemCreate(billing_period_id=period.id, description="Grundsteuer", amount=1300.0, allocation_key_id=area.id))
    client = TestClient(app, headers={"Authorization": "Bearer " + auth.create_access_token(owner.id)})
    yield {"client": client, "property": prop, "period": period, "before": before, "meters": meters}
    client.close()
    auth.clear_users()
    clear_business_data(store)


def _guide(case, **params):
    response = case["client"].get("/api/v1/billing/guide", params={"property_id": case["property"].id, **params})
    assert response.status_code == 200, response.text
    return response.json()


def _hint(view, step, words):
    return next((hint for hint in view["hints"] if hint["step"] == step and words in hint["text"]), None)


def test_without_a_period_the_assistant_proposes_the_next_one(case):
    view = _guide(case)
    assert view["period"] is None and view["checks"] is None
    assert view["suggested_period"] == {"label": "Nebenkosten 2026", "start_date": "2026-01-01", "end_date": "2026-12-31"}
    assert [item["label"] for item in view["periods"]] == ["Nebenkosten 2025", "Nebenkosten 2024"]
    assert view["steps"][0] == {"key": "period", "label": "Objekt & Zeitraum", "done": False}


def test_the_assistant_names_the_situation_of_this_property(case):
    view = _guide(case, period_id=case["period"].id)
    assert view["property"]["units"] == 3 and view["property"]["parking"] == 1 and view["property"]["meters"] == {"cold_water": 2}
    ground = next(row for row in view["occupancy"]["units"] if row["label"] == "EG")
    assert [(segment["kind"], segment["start"], segment["end"], segment["tenant"]) for segment in ground["segments"]] == [
        ("tenancy", "2025-01-01", "2025-06-30", "Anna Alt"), ("vacancy", "2025-07-01", "2025-07-31", None),
        ("tenancy", "2025-08-01", "2025-12-31", "Bernd Neu")]
    assert view["occupancy"]["vacancy_days"] == 31 + 365          # the parking space stood empty all year
    assert _hint(view, "occupancy", "EG am 01.07.2025 (Anna Alt → Leerstand)")
    assert _hint(view, "occupancy", "Leerstand in EG, Stellplatz 1 (396 Tage")
    assert _hint(view, "occupancy", "Stellplätze")
    assert _hint(view, "period", "bis 31.12.2026")
    # keys: persons for the flats, water by consumption since every rented flat has a meter
    suggested = {(row["key_type"], row.get("meter_type")) for row in view["keys"]["suggested"]}
    assert suggested == {("person_count", None), ("consumption", "cold_water")}
    water = next(row for row in view["keys"]["suggested"] if row["key_type"] == "consumption")
    assert water["measure_unit"] == "m³" and "Alle 2 vermieteten Einheiten" in water["reason"]
    # costs against the year before: water is missing, the property tax rose by 30 %, administration is no operating cost
    missing = _hint(view, "costs", "hier noch nicht erfasst")
    assert missing and "Wasser (800,00 €)" in missing["text"] and "Verwaltung" not in missing["text"]
    assert _hint(view, "costs", "„Grundsteuer“ ist gestiegen: 1.000,00 € im Vorjahr, jetzt 1.300,00 €")
    assert view["costs"]["total"] == 1300 and view["costs"]["previous_period"]["label"] == "Nebenkosten 2024"
    assert any(row["label"] == "Grundsteuer" for row in view["costs"]["catalogue"])
    assert view["readings"] == {"needed": [], "missing": 0}         # no consumption key yet
    assert view["checks"] is not None and view["statements"]["items"] == []


def test_readings_are_asked_for_on_the_days_tenants_changed(case):
    store.create_allocation_key(AllocationKeyCreate(property_id=case["property"].id, name="Kaltwasser", key_type="consumption",
                                                    meter_type="cold_water", measure_unit="m³"))
    view = _guide(case, period_id=case["period"].id)
    rows = [(row["unit_label"], row["day"], row["reason"], row["present"]) for row in view["readings"]["needed"]]
    assert rows == [("EG", "2025-01-01", "Beginn des Zeitraums", True), ("EG", "2025-06-30", "Auszug Anna Alt", False),
                    ("EG", "2025-07-31", "Einzug Bernd Neu", False), ("EG", "2025-12-31", "Ende des Zeitraums", True),
                    ("OG", "2025-01-01", "Beginn des Zeitraums", True), ("OG", "2025-12-31", "Ende des Zeitraums", True)]
    assert view["readings"]["missing"] == 2
    assert _hint(view, "readings", "2 Zählerstände fehlen, davon 2 Zwischenablesungen beim Mieterwechsel")
    assert all(row["key_type"] != "consumption" for row in view["keys"]["suggested"])


def test_an_unusual_reading_in_the_period_is_named_before_billing(case):
    store.create_allocation_key(AllocationKeyCreate(property_id=case["property"].id, name="Kaltwasser", key_type="consumption",
                                                    meter_type="cold_water", measure_unit="m³"))
    assert not _hint(_guide(case, period_id=case["period"].id), "readings", "auffällig")
    # about 0.02 m³ a day for three quarters, then 0.38: a typo, a unit mix-up or a leak
    for day, value in ((date(2025, 4, 1), 12), (date(2025, 7, 1), 14), (date(2025, 10, 1), 16)):
        store.create_standalone_meter_reading(StandaloneMeterReadingCreate(meter_id=case["meters"]["OG"].id,
                                                                          reading_date=day, value=value))
    hint = _hint(_guide(case, period_id=case["period"].id), "readings", "1 auffälliger Zählerstand im Zeitraum")
    assert hint and hint["level"] == "warning" and hint["link"] == "/meters"
    assert "Zähler WZ 20000 (OG) am 30.12.2025: Auffällig hoher Verbrauch je Tag" in hint["text"]


def test_a_period_of_another_property_is_refused(case):
    other = store.create_property(PropertyCreate(portfolio_id=case["property"].portfolio_id, name="Anderes Haus", property_type="residential"))
    response = case["client"].get("/api/v1/billing/guide", params={"property_id": other.id, "period_id": case["period"].id})
    assert response.status_code == 422
