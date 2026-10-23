"""The actual amount of a budget, taken from the bookings when the user asks for it."""

import pytest
from fastapi.testclient import TestClient

from backend.app import app
from backend.auth import clear_users, create_access_token, register_user
from backend.dependencies import store
from backend.services.data_snapshot import clear_business_data

API = "/api/v1"


@pytest.fixture
def client():
    clear_business_data(store)
    clear_users()
    yield TestClient(app)
    clear_users()
    clear_business_data(store)


@pytest.fixture
def estate(client):
    user = register_user("owner", "owner@example.com", "Owner", "Secret123", "eigentuemer")
    headers = {"Authorization": f"Bearer {create_access_token(user.id)}"}

    def post(path, body):
        response = client.post(API + path, headers=headers, json=body)
        assert response.status_code == 201, response.text
        return response.json()

    pf = post("/portfolios", {"name": "P"})["id"]
    other_pf = post("/portfolios", {"name": "Q"})["id"]
    house = post("/properties", {"portfolio_id": pf, "name": "Haus", "property_type": "residential"})["id"]
    other = post("/properties", {"portfolio_id": pf, "name": "Nachbarhaus", "property_type": "residential"})["id"]
    unit = post("/units", {"property_id": house, "label": "WE 1", "unit_type": "Wohnung", "cold_rent": 600})["id"]
    tenant = post("/tenants", {"full_name": "Anna Muster"})["id"]
    account = post("/accounts", {"portfolio_id": pf, "name": "Konto", "account_type": "bank"})["id"]
    repairs = post("/categories", {"portfolio_id": pf, "name": "Reparaturen", "category_type": "expense"})["id"]
    upkeep = post("/categories", {"portfolio_id": pf, "name": "Wartung", "category_type": "maintenance"})["id"]
    insurance = post("/categories", {"portfolio_id": pf, "name": "Versicherung", "category_type": "expense"})["id"]
    rent = post("/categories", {"portfolio_id": pf, "name": "Miete", "category_type": "income"})["id"]
    foreign = post("/categories", {"portfolio_id": other_pf, "name": "Fremd", "category_type": "expense"})["id"]

    def book(day, amount, category, **extra):
        return post("/bookings", {"account_id": account, "booking_date": day, "amount": amount,
                                  "category_id": category, "status": "booked", "property_id": house, **extra})

    roof = book("2026-03-10", -1200.50, repairs, payment_text="Dachdecker")
    book("2026-03-20", 1200.50, repairs, reverses_booking_id=roof["id"])   # reversed: nets out
    book("2026-04-02", -800.00, repairs, payment_text="Dachdecker, richtige Rechnung")
    book("2026-06-01", 50.00, repairs, payment_text="Gutschrift")             # refund lowers it
    book("2026-07-15", -199.99, upkeep, unit_id=unit)
    book("2026-08-01", -400.00, insurance)                                    # not chosen
    book("2025-12-31", -999.00, repairs)                                      # other year
    book("2027-01-01", -999.00, repairs)
    book("2026-05-05", -333.00, repairs, property_id=other)                   # other property
    book("2026-05-06", -10.00, repairs, tenant_id=tenant)                     # tenant money is no spending
    return {"client": client, "headers": headers, "house": house, "repairs": repairs, "upkeep": upkeep,
            "rent": rent, "foreign": foreign}


def budget(estate, **fields):
    body = {"property_id": estate["house"], "year": 2026, "category": "maintenance", "planned_amount": 1500,
            "actual_amount": 100, **fields}
    return estate["client"].post(f"{API}/budgets", headers=estate["headers"], json=body)


def test_the_bookings_of_the_chosen_categories_give_the_actual_amount_on_request(estate):
    client, headers = estate["client"], estate["headers"]
    created = budget(estate, booking_category_ids=[estate["repairs"], estate["upkeep"]])
    assert created.status_code == 201, created.text
    url = f"{API}/budgets/{created.json()['id']}/actual-from-bookings"

    preview = client.get(url, headers=headers).json()

    # 1200.50 - 1200.50 + 800 - 50 + 199.99
    assert preview["from_bookings"] == 949.99 and preview["actual_amount"] == 100
    assert preview["difference"] == 849.99 and len(preview["bookings"]) == 5
    # asking changes nothing
    assert client.get(f"{API}/budgets/{created.json()['id']}", headers=headers).json()["actual_amount"] == 100

    stale = client.post(url, headers=headers, json={"expected_amount": 900})
    assert stale.status_code == 409
    taken = client.post(url, headers=headers, json={"expected_amount": 949.99})
    assert taken.status_code == 200, taken.text
    assert taken.json()["actual_amount"] == 949.99
    assert taken.json()["booking_category_ids"] == [estate["repairs"], estate["upkeep"]]


def test_without_categories_the_actual_amount_stays_manual(estate):
    created = budget(estate).json()
    assert created["booking_category_ids"] == []
    response = estate["client"].get(f"{API}/budgets/{created['id']}/actual-from-bookings", headers=estate["headers"])
    assert response.status_code == 409 and "Buchungskategorien" in response.text


@pytest.mark.parametrize("pick", ["rent", "foreign"])
def test_only_spending_categories_of_the_property_portfolio_count(estate, pick):
    response = budget(estate, booking_category_ids=[estate[pick]])
    assert response.status_code == 400, response.text
    created = budget(estate).json()
    patched = estate["client"].patch(f"{API}/budgets/{created['id']}", headers=estate["headers"],
                                     json={"booking_category_ids": [estate[pick]]})
    assert patched.status_code == 400
