"""A meter only counts up: every way a reading enters keeps it between the one before and the one after."""

from datetime import date
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from backend.app import app
from backend.auth import clear_users, create_access_token, register_user
from backend.dependencies import store
from backend.services.data_snapshot import clear_business_data
from backend.services.meter_history import order_problem


def _reading(day, value, identifier=None, meter="m"):
    return SimpleNamespace(id=identifier or f"{meter}-{day}", meter_id=meter, reading_date=day, value=value)


HISTORY = [_reading(date(2025, 12, 31), 120, "a"), _reading(date(2026, 6, 30), 200, "b"), _reading(date(2026, 6, 30), 5, "x", "other")]


@pytest.mark.parametrize(("day", "value", "expected"), [
    (date(2026, 3, 31), 150, None),
    (date(2026, 3, 31), 120, None),
    (date(2026, 3, 31), 200, None),
    (date(2026, 3, 31), 110, "kleiner als der Stand 120 vom 31.12.2025"),
    (date(2026, 3, 31), 250, "größer als der spätere Stand 200 vom 30.06.2026"),
    (date(2026, 9, 30), 199, "kleiner als der Stand 200 vom 30.06.2026"),
    (date(2025, 6, 30), 130, "größer als der spätere Stand 120 vom 31.12.2025"),
    (date(2026, 6, 30), 210, None),
])
def test_order_against_the_neighbours(day, value, expected):
    problem = order_problem(HISTORY, "m", day, value)
    assert (problem is None) if expected is None else (expected in (problem or ""))


def test_a_corrected_reading_is_not_compared_with_itself():
    assert order_problem(HISTORY, "m", date(2026, 6, 30), 180, ignore=("b",)) is None
    assert "kleiner" in (order_problem(HISTORY, "m", date(2026, 6, 30), 100, ignore=("b",)) or "")


@pytest.fixture
def owner():
    clear_business_data(store)
    clear_users()
    user = register_user("owner", "owner@example.com", "Owner", "Secret123", "eigentuemer")
    yield {"Authorization": f"Bearer {create_access_token(user.id)}"}
    clear_users()
    clear_business_data(store)


def test_a_backdated_reading_above_a_later_one_is_refused(owner):
    client = TestClient(app)
    pf = client.post("/api/v1/portfolios", headers=owner, json={"name": "P"}).json()
    prop = client.post("/api/v1/properties", headers=owner,
                       json={"portfolio_id": pf["id"], "name": "Haus", "property_type": "residential"}).json()
    unit = client.post("/api/v1/units", headers=owner, json={"property_id": prop["id"], "label": "WE 1",
                                                             "unit_type": "Wohnung"}).json()
    meter = client.post("/api/v1/meters", headers=owner, json={"unit_id": unit["id"], "meter_type": "water_cold"}).json()
    url = f"/api/v1/meters/{meter['id']}/readings"
    for day, value in (("2025-12-31", 120), ("2026-06-30", 200)):
        assert client.post(url, headers=owner, json={"meter_id": meter["id"], "reading_date": day, "value": value}).status_code == 201
    late = client.post(url, headers=owner, json={"meter_id": meter["id"], "reading_date": "2026-03-31", "value": 250})
    assert late.status_code == 400
    assert "größer als der spätere Stand 200 vom 30.06.2026" in late.json()["error"]["message"]
    fits = client.post(url, headers=owner, json={"meter_id": meter["id"], "reading_date": "2026-03-31", "value": 160})
    assert fits.status_code == 201
    assert sorted(r.value for r in store.list_standalone_meter_readings() if r.meter_id == meter["id"]) == [120, 160, 200]
