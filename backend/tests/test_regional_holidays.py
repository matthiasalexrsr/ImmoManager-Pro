"""A property's federal state adds its own public holidays to due dates, notice periods and deadlines."""

from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from backend.app import app
from backend.auth import clear_users, create_access_token, register_user
from backend.dependencies import store
from backend.domain import deposit_rules
from backend.domain.calendar_days import (
    STATES,
    deadline_end,
    holiday_name,
    holiday_names,
    is_working_day,
    rent_due_date,
)
from backend.domain.lease_engine import ChargeConfig, LeaseEngine
from backend.services.data_snapshot import clear_business_data
from backend.services.letter_templates import tenant_notice_end
from backend.services.workflow_guidance import calendar_deadline


@pytest.mark.parametrize(("day", "state", "name"), [
    (date(2027, 1, 6), "BY", "Heilige Drei Könige"),
    (date(2027, 1, 6), "ST", "Heilige Drei Könige"),
    (date(2026, 3, 8), "BE", "Internationaler Frauentag"),
    (date(2026, 6, 4), "NW", "Fronleichnam"),
    (date(2026, 8, 15), "SL", "Mariä Himmelfahrt"),
    (date(2026, 9, 20), "TH", "Weltkindertag"),
    (date(2026, 10, 31), "SN", "Reformationstag"),
    (date(2026, 10, 31), "NI", "Reformationstag"),
    (date(2027, 11, 1), "RP", "Allerheiligen"),
    (date(2026, 11, 18), "SN", "Buß- und Bettag"),
    (date(2027, 11, 17), "SN", "Buß- und Bettag"),
])
def test_statewide_holidays(day, state, name):
    assert holiday_name(day, state) == name
    assert holiday_name(day) is None and holiday_name(day, None) is None


@pytest.mark.parametrize(("day", "state"), [
    (date(2027, 1, 6), "NW"),           # no Epiphany there
    (date(2026, 6, 4), "SN"),           # Corpus Christi only in some Saxon municipalities
    (date(2026, 8, 15), "BY"),          # Assumption only in Catholic Bavarian municipalities
    (date(2017, 10, 31), "NI"),         # Reformation Day in Lower Saxony since 2018 (2017 was a one-off)
    (date(2022, 3, 8), "MV"),           # Women's Day there since 2023
])
def test_holidays_not_kept_statewide_or_not_yet(day, state):
    assert holiday_name(day, state) is None


def test_every_state_keeps_the_nine_nationwide_holidays_and_unknown_states_add_none():
    national = holiday_names(2027)
    assert len(national) == 9
    for state in STATES:
        assert set(national) <= set(holiday_names(2027, state))
    assert holiday_names(2027, "XX") == national
    holiday_names(2027, "BY").clear()                   # a copy: the cache stays intact
    assert holiday_name(date(2027, 1, 6), "BY") == "Heilige Drei Könige"


def test_rent_falls_due_a_day_later_where_the_state_keeps_a_holiday():
    assert rent_due_date(date(2027, 1, 1)) == date(2027, 1, 6)            # 1.1. holiday, Mon 4., Tue 5., Wed 6.
    assert rent_due_date(date(2027, 1, 1), "BY") == date(2027, 1, 7)      # Epiphany on Wed 6.
    assert rent_due_date(date(2027, 11, 1)) == date(2027, 11, 3)
    assert rent_due_date(date(2027, 11, 1), "NW") == date(2027, 11, 4)    # All Saints' on Mon 1.
    assert rent_due_date(date(2021, 6, 1), "HE") == date(2021, 6, 4)      # Corpus Christi on Thu 3.
    assert rent_due_date(date(2021, 6, 1), "BE") == date(2021, 6, 3)
    assert not is_working_day(date(2027, 1, 6), "BY") and is_working_day(date(2027, 1, 6), "BE")


def test_a_deadline_on_a_free_day_ends_on_the_next_working_day():
    assert deadline_end(date(2027, 10, 30)) == date(2027, 11, 1)          # Saturday → Monday
    assert deadline_end(date(2027, 10, 30), "BW") == date(2027, 11, 2)    # Monday is All Saints' there
    assert deadline_end(date(2027, 11, 2), "BW") == date(2027, 11, 2)


def test_the_lease_engine_dates_the_rent_by_the_property_state():
    charge = ChargeConfig(cold_rent=Decimal("500"), service_charge_advance=Decimal("100"), heating_advance=Decimal("50"))
    lines = {state: LeaseEngine.build_monthly_receivables(contract_start=date(2027, 1, 1), contract_end=None, charge=charge,
                                                         until_including=date(2027, 1, 31), federal_state=state)
             for state in (None, "BY")}
    assert [line.due_date for line in lines[None]] == [date(2027, 1, 6)]
    assert [line.due_date for line in lines["BY"]] == [date(2027, 1, 7)]
    fixed = LeaseEngine.build_monthly_receivables(contract_start=date(2027, 1, 1), contract_end=None, charge=charge,
                                                  until_including=date(2027, 1, 31), due_day=5, federal_state="BY")
    assert [line.due_date for line in fixed] == [date(2027, 1, 5)]       # a fixed calendar day stays


def test_deposit_instalments_follow_the_rent_of_the_state():
    assert deposit_rules.instalment_due_dates(date(2026, 12, 15), 2) == [date(2026, 12, 15), date(2027, 1, 6)]
    assert deposit_rules.instalment_due_dates(date(2026, 12, 15), 2, "ST") == [date(2026, 12, 15), date(2027, 1, 7)]


def test_a_notice_is_timely_by_the_third_working_day_of_the_state():
    # Saturdays count for notices; Mon 1.11.2027 is All Saints' in NW: Tue 2., Wed 3., Thu 4. are the first three days
    assert tenant_notice_end(date(2027, 11, 4)) == date(2028, 2, 29)
    assert tenant_notice_end(date(2027, 11, 4), "NW") == date(2028, 1, 31)
    assert tenant_notice_end(date(2027, 11, 5), "NW") == date(2028, 2, 29)


def _deadline(kind, due, state) -> dict:
    result = calendar_deadline(kind, due, state)
    assert result is not None
    return result


def test_work_center_deadlines_name_the_free_day():
    payment = _deadline("invoice", date(2027, 11, 1), "NW")
    assert payment["effective"] == "2027-11-02"
    assert "Allerheiligen, ein Feiertag in Nordrhein-Westfalen" in payment["note"] and "§ 193 BGB" in payment["note"]
    assert calendar_deadline("invoice", date(2027, 11, 1), None) == {"due": "2027-11-01", "effective": "2027-11-01", "note": None}
    weekend = _deadline("receivable", date(2027, 10, 30), None)
    assert weekend["effective"] == "2027-11-01" and "ein Samstag" in weekend["note"]
    notice = _deadline("service_contract", date(2027, 11, 1), "NW")
    assert notice["effective"] == "2027-11-01" and "spätestens am 29.10.2027 zustellen" in notice["note"]
    task = _deadline("task", date(2027, 12, 25), "BY")
    assert task["effective"] == "2027-12-25" and "1. Weihnachtstag, ein bundesweiter Feiertag" in task["note"]
    assert calendar_deadline("task", None, "BY") is None


@pytest.fixture
def owner():
    clear_business_data(store)
    clear_users()
    user = register_user("owner", "owner@example.com", "Owner", "Secret123", "eigentuemer")
    yield {"Authorization": f"Bearer {create_access_token(user.id)}"}
    clear_users()
    clear_business_data(store)


def test_the_property_keeps_its_state_and_the_account_dates_the_rent_by_it(owner):
    client = TestClient(app)
    pf = client.post("/api/v1/portfolios", headers=owner, json={"name": "P"}).json()
    refused = client.post("/api/v1/properties", headers=owner,
                          json={"portfolio_id": pf["id"], "name": "Haus", "property_type": "residential", "federal_state": "XY"})
    assert refused.status_code == 422
    prop = client.post("/api/v1/properties", headers=owner, json={"portfolio_id": pf["id"], "name": "Haus",
                                                                  "property_type": "residential", "federal_state": "by"}).json()
    assert prop["federal_state"] == "BY"
    unit = client.post("/api/v1/units", headers=owner, json={"property_id": prop["id"], "label": "WE 1", "unit_type": "Wohnung",
                                                             "cold_rent": 600}).json()
    tenant = client.post("/api/v1/tenants", headers=owner, json={"full_name": "Anna Muster"}).json()
    contract = client.post("/api/v1/contracts", headers=owner, json={
        "contract_number": "V-1", "property_id": prop["id"], "unit_id": unit["id"], "tenant_id": tenant["id"],
        "start_date": "2026-12-01", "cold_rent": 600}).json()
    settlement = client.get(f"/api/v1/contracts/{contract['id']}/settlement", headers=owner,
                            params={"as_of": "2027-01-31"}).json()
    due = {line["period_start"]: line["due_date"] for line in settlement["settlement_lines"]}
    assert due["2027-01-01"] == "2027-01-07"
    kinds = {item["kind"] for item in client.get("/api/v1/review", headers=owner).json()["items"]}
    assert "federal_state_missing" not in kinds
    cleared = client.patch(f"/api/v1/properties/{prop['id']}", headers=owner, json={"federal_state": ""})
    assert cleared.status_code == 200 and cleared.json()["federal_state"] is None
    settlement = client.get(f"/api/v1/contracts/{contract['id']}/settlement", headers=owner,
                            params={"as_of": "2027-01-31"}).json()
    assert {line["period_start"]: line["due_date"] for line in settlement["settlement_lines"]}["2027-01-01"] == "2027-01-06"
    missing = next(item for item in client.get("/api/v1/review", headers=owner).json()["items"]
                   if item["kind"] == "federal_state_missing")
    assert missing["title"] == "1 vermietete Immobilie ohne Bundesland: Haus" and missing["link"] == f"/properties/{prop['id']}"
