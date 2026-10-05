"""Values the database refuses are refused up front, with a message that says why."""

import pytest
from fastapi.testclient import TestClient

from backend.app import app
from backend.auth import clear_users, create_access_token, register_user
from backend.dependencies import store
from backend.services.data_snapshot import clear_business_data


@pytest.fixture
def client():
    clear_business_data(store)
    clear_users()
    owner = register_user("owner", "owner@example.com", "Owner", "Secret123", "eigentuemer")
    yield TestClient(app, headers={"Authorization": f"Bearer {create_access_token(owner.id)}"})
    clear_users()
    clear_business_data(store)


def test_zero_area_and_zero_amount_are_validation_errors(client):
    """Regression: SQLite answered 409 "doppelter Eintrag oder ungültige Referenz"; the memory store saved them."""
    pf = client.post("/api/v1/portfolios", json={"name": "P"}).json()
    prop = client.post("/api/v1/properties", json={"portfolio_id": pf["id"], "name": "H",
                                                   "property_type": "residential"}).json()
    account = client.post("/api/v1/accounts", json={"portfolio_id": pf["id"], "name": "K",
                                                    "account_type": "bank"}).json()
    unit = client.post("/api/v1/units", json={"property_id": prop["id"], "label": "WE 1", "unit_type": "Wohnung",
                                              "area_sqm": 50}).json()
    booking = client.post("/api/v1/bookings", json={"account_id": account["id"], "booking_date": "2025-01-01",
                                                    "amount": 5}).json()

    attempts = [
        client.post("/api/v1/units", json={"property_id": prop["id"], "label": "WE 2", "unit_type": "Wohnung",
                                           "area_sqm": 0}),
        client.patch(f"/api/v1/units/{unit['id']}", json={"area_sqm": 0}),
        client.post("/api/v1/bookings", json={"account_id": account["id"], "booking_date": "2025-01-01", "amount": 0}),
        client.patch(f"/api/v1/bookings/{booking['id']}", json={"amount": 0}),
    ]

    assert [r.status_code for r in attempts] == [422] * 4
    messages = [r.json()["detail"][0]["msg"] for r in attempts]
    assert messages == ["Fläche muss größer als 0 m² sein"] * 2 + ["Betrag darf nicht 0 sein"] * 2
    assert client.get(f"/api/v1/units/{unit['id']}").json()["area_sqm"] == 50
