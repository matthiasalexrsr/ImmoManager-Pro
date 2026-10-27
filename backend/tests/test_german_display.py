"""What the server writes for people to read is German: dates, money and states."""

from datetime import date

import pytest
from fastapi.testclient import TestClient

from backend import auth
from backend.app import app
from backend.dependencies import store
from backend.models import AccountCreate, BookingCreate, PortfolioCreate, PropertyCreate
from backend.services.data_snapshot import clear_business_data


@pytest.fixture
def client():
    clear_business_data(store)
    auth.clear_users()
    user = auth.register_user("linda.reiser", "linda@example.com", "Linda Reiser", "Secret123", "eigentuemer")
    yield TestClient(app, headers={"Authorization": f"Bearer {auth.create_access_token(user.id)}"})
    clear_business_data(store)
    auth.clear_users()


def test_a_payment_in_a_property_timeline_reads_in_german(client):
    portfolio = store.create_portfolio(PortfolioCreate(name="Nord", owner_name="Linda Reiser"))
    prop = store.create_property(PropertyCreate(portfolio_id=portfolio.id, name="Bautzner Straße 61",
                                                property_type="residential"))
    account = store.create_account(AccountCreate(portfolio_id=portfolio.id, name="Giro", account_type="bank"))
    store.create_booking(BookingCreate(account_id=account.id, property_id=prop.id, booking_date=date(2026, 10, 12),
                                       amount=-1153.66, status="booked", payment_text="Dachrinne"))
    feed = client.get("/api/v1/work-center/timeline", params={"entity_type": "property", "entity_id": prop.id})
    assert feed.status_code == 200, feed.text
    bodies = [item["body"] for item in feed.json()["items"] if item["kind"] == "payment"]
    assert bodies == ["12.10.2026 · -1.153,66 € · Gebucht"]
