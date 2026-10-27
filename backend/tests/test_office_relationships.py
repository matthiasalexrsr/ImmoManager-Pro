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


def test_calendar_context_and_date_filters_precede_pagination_and_have_stable_order(office):
    from datetime import date

    from backend.models import CalendarEventCreate

    client, ((north, north_unit), (south, south_unit)) = office
    for day, place, home in ((10, north, north_unit), (4, south, south_unit), (3, north, north_unit), (5, north, north_unit)):
        store.create_calendar_event(CalendarEventCreate(title=f"Termin {day}", event_type="meeting",
            event_date=date(2026, 11, day), property_id=place["id"], unit_id=home["id"]))
    query = f"/api/v1/calendar?unit_id={north_unit['id']}&date_from=2026-11-01&date_to=2026-11-08&limit=1"
    first = client.get(query).json()
    second = client.get(query + "&skip=1").json()
    assert [row["event_date"] for row in first + second] == ["2026-11-03", "2026-11-05"]
    assert client.get(query + "&skip=2").json() == []
    assert client.get("/api/v1/calendar?date_from=2026-11-08&date_to=2026-11-01").status_code == 422


def test_calendar_filters_find_records_after_more_than_a_thousand_other_events(office):
    from datetime import date

    from backend.models import CalendarEvent
    from backend.services.maintenance_projects import work
    from backend.services.maintenance_rows import Rows

    client, ((north, north_unit), (south, south_unit)) = office
    with work(store, None, ("/calendar",)) as unit:
        rows = Rows.of(unit)
        for index in range(1001):
            rows.add("calendar_events", CalendarEvent(id=f"calendar-bulk-{index:04}", title="Anderes Objekt",
                event_type="meeting", event_date=date(2026, 11, 1), property_id=south["id"], unit_id=south_unit["id"]))
        rows.add("calendar_events", CalendarEvent(id="calendar-last-match", title="Später Treffer", event_type="meeting",
            event_date=date(2026, 11, 3), property_id=north["id"], unit_id=north_unit["id"]))
    result = client.get(f"/api/v1/calendar?unit_id={north_unit['id']}&limit=1").json()
    assert [row["id"] for row in result] == ["calendar-last-match"]
