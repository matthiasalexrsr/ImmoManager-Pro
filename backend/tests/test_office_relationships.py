"""Object-level office records must not silently point into another property's unit."""

import pytest
from fastapi.testclient import TestClient

from backend.app import app
from backend.auth import clear_users, create_access_token, register_user
from backend.dependencies import store
from backend.services.data_snapshot import clear_business_data


@pytest.fixture
def office():
    clear_business_data(store)
    clear_users()
    owner = register_user("office-review", "office@example.invalid", "Office", "Secret123", "eigentuemer")
    client = TestClient(app, headers={"Authorization": f"Bearer {create_access_token(owner.id)}"})
    portfolio = client.post("/api/v1/portfolios", json={"name": "Verwaltung"}).json()
    places = []
    for name in ("Haus Nord", "Haus Süd"):
        building = client.post("/api/v1/properties", json={
            "portfolio_id": portfolio["id"], "name": name, "property_type": "residential"}).json()
        unit = client.post("/api/v1/units", json={
            "property_id": building["id"], "label": "Wohnung 1", "unit_type": "flat"}).json()
        places.append((building, unit))
    yield client, places
    client.close()
    clear_users()
    clear_business_data(store)


def payload(kind, building, unit):
    values = {"property_id": building["id"], "unit_id": unit["id"]}
    return values | ({"provider": "Muster Versicherung", "insurance_type": "building"}
                     if kind == "insurances" else
                     {"title": "Ablesetermin", "event_type": "reading", "event_date": "2026-11-01"})


@pytest.mark.parametrize("kind", ["insurances", "calendar"])
def test_create_refuses_unit_of_another_property(office, kind):
    client, ((north, _), (_, south_unit)) = office
    response = client.post(f"/api/v1/{kind}", json=payload(kind, north, south_unit))
    assert response.status_code == 400, response.text
    assert "Einheit" in response.json()["error"]["message"]
    assert client.get(f"/api/v1/{kind}").json() == []


@pytest.mark.parametrize("kind", ["insurances", "calendar"])
@pytest.mark.parametrize("method", ["put", "patch"])
def test_edit_refuses_inconsistent_assignment_without_changing_the_record(office, kind, method):
    client, ((north, north_unit), (_, south_unit)) = office
    values = payload(kind, north, north_unit)
    created = client.post(f"/api/v1/{kind}", json=values).json()
    changed = {"unit_id": south_unit["id"]}
    if method == "put":
        changed = values | changed

    response = getattr(client, method)(f"/api/v1/{kind}/{created['id']}", json=changed)

    assert response.status_code == 400, response.text
    assert client.get(f"/api/v1/{kind}/{created['id']}").json() == created
    # An explicit move of both references is valid.
    south = office[1][1][0]
    moved = client.patch(f"/api/v1/{kind}/{created['id']}", json={
        "property_id": south["id"], "unit_id": south_unit["id"]})
    assert moved.status_code == 200, moved.text
    assert moved.json()["property_id"] == south["id"]


def test_calendar_unit_only_is_assigned_to_its_property_and_can_be_unassigned(office):
    client, ((north, unit), _) = office
    values = payload("calendar", north, unit)
    values.pop("property_id")
    created = client.post("/api/v1/calendar", json=values)
    assert created.status_code == 201, created.text
    assert created.json()["property_id"] == north["id"]
    detached = client.patch(f"/api/v1/calendar/{created.json()['id']}",
                            json={"property_id": None, "unit_id": None})
    assert detached.status_code == 200
    assert detached.json()["property_id"] is None and detached.json()["unit_id"] is None


def test_insurance_invalid_date_edit_preserves_original(office):
    client, ((north, unit), _) = office
    values = payload("insurances", north, unit) | {"start_date": "2026-01-01", "end_date": "2026-12-31"}
    created = client.post("/api/v1/insurances", json=values).json()
    response = client.patch(f"/api/v1/insurances/{created['id']}", json={"end_date": "2025-12-31"})
    assert response.status_code == 400, response.text
    assert client.get(f"/api/v1/insurances/{created['id']}").json() == created
