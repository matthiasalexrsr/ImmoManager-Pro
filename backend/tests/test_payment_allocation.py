"""Payments are credited to the contract they pay, also when one transfer pays flat and garage."""

from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from backend.app import app
from backend.auth import clear_users, create_access_token, register_user
from backend.dependencies import store
from backend.domain.payment_allocation import ContractCandidate, suggest_allocation
from backend.services.data_snapshot import clear_business_data

D = Decimal


def _c(contract_id, due, unit="u", start=date(2024, 1, 1), end=None):
    return ContractCandidate(contract_id, unit, start, end, D(due))


@pytest.mark.parametrize("amount, unit, candidates, expected", [
    (1570, None, [_c("flat", 1480, "u1"), _c("garage", 90, "u2")], [("flat", 1480), ("garage", 90)]),
    (785, None, [_c("flat", 1480, "u1"), _c("garage", 90, "u2")], [("flat", 740), ("garage", 45)]),
    (2000, None, [_c("flat", 1480, "u1"), _c("garage", 90, "u2")], [("flat", 1480), ("garage", 90)]),  # 430 € stay open
    (1570, "u1", [_c("flat", 1480, "u1"), _c("garage", 90, "u2")], [("flat", 1480), ("garage", 90)]),
    (1480, "u1", [_c("flat", 1480, "u1"), _c("garage", 90, "u2")], [("flat", 1480)]),
    (-1570, None, [_c("flat", 1480, "u1"), _c("garage", 90, "u2")], [("flat", -1480), ("garage", -90)]),
    (500, None, [_c("old", 700, end=date(2024, 12, 31)), _c("new", 800, start=date(2025, 1, 1))], [("new", 500)]),
    (500, None, [], []),
])
def test_suggestion_rules(amount, unit, candidates, expected):
    pairs = suggest_allocation(D(amount), date(2025, 3, 3), unit, candidates)

    assert pairs == [(cid, D(value)) for cid, value in expected]
    assert abs(sum((value for _, value in pairs), D(0))) <= abs(D(amount))


@pytest.fixture
def client():
    clear_business_data(store)
    clear_users()
    owner = register_user("owner", "owner@example.com", "Owner", "Secret123", "eigentuemer")
    yield TestClient(app, headers={"Authorization": f"Bearer {create_access_token(owner.id)}"})
    clear_users()
    clear_business_data(store)


@pytest.fixture
def yilmaz(client):
    """Köln: Familie Yilmaz rents flat (1,480 €) and garage (90 €) since March 2024."""
    pf = client.post("/api/v1/portfolios", json={"name": "Erbengemeinschaft"}).json()
    prop = client.post("/api/v1/properties", json={"portfolio_id": pf["id"], "name": "WGH Köln",
                                                   "property_type": "mixed"}).json()
    account = client.post("/api/v1/accounts", json={"portfolio_id": pf["id"], "name": "Mietkonto",
                                                    "account_type": "bank"}).json()
    tenant = client.post("/api/v1/tenants", json={"full_name": "Familie Yilmaz"}).json()
    contracts = {}
    for label, rent in [("Whg 1.OG", (1200, 180, 100)), ("Garage", (90, 0, 0))]:
        unit = client.post("/api/v1/units", json={
            "property_id": prop["id"], "label": label, "unit_type": "Wohnung" if label.startswith("Whg") else "Stellplatz",
            "cold_rent": rent[0], "service_charge_advance": rent[1], "heating_advance": rent[2]}).json()
        contracts[label] = client.post("/api/v1/contracts", json={
            "contract_number": f"K-{label}", "property_id": prop["id"], "unit_id": unit["id"],
            "tenant_id": tenant["id"], "start_date": "2024-03-01"}).json()
    for month in range(1, 10):
        client.post("/api/v1/bookings", json={"account_id": account["id"], "tenant_id": tenant["id"],
                                               "booking_date": f"2025-{month:02d}-03", "amount": 1570,
                                               "payment_text": "Miete Whg+Garage"})
    return {"tenant": tenant, "account": account, **contracts}


def test_one_transfer_for_flat_and_garage_is_split(client, yilmaz):
    """Regression: both contracts got all 14,130 €; the garage showed 12,420 € overpaid."""
    account = client.get(f"/api/v1/tenants/{yilmaz['tenant']['id']}/account",
                         params={"as_of": "2025-09-30"}).json()
    rows = {row["contract_number"]: row for row in account["contracts"]}

    assert (rows["K-Whg 1.OG"]["paid"], rows["K-Garage"]["paid"]) == (13320.0, 810.0)
    assert rows["K-Whg 1.OG"]["outstanding"] + rows["K-Garage"]["outstanding"] == 15700.0  # 10 months open
    assert rows["K-Garage"]["overpaid"] == 0.0
    assert sum(row["paid"] for row in rows.values()) == account["paid_total"] == 14130.0
    assert account["unassigned"] == []

    garage = client.get(f"/api/v1/contracts/{yilmaz['Garage']['id']}/settlement",
                        params={"as_of": "2025-09-30"}).json()
    assert garage["balance"]["paid_total"] == 810.0


def test_manual_split_is_checked(client, yilmaz):
    booking = client.get("/api/v1/bookings").json()[0]
    other_tenant = client.post("/api/v1/tenants", json={"full_name": "Jemand"}).json()
    flat, garage = yilmaz["Whg 1.OG"]["id"], yilmaz["Garage"]["id"]

    def put(items):
        return client.put(f"/api/v1/bookings/{booking['id']}/allocations", json=items)

    assert put([{"contract_id": flat, "amount": 1500}, {"contract_id": garage, "amount": 100}]).status_code == 400
    assert put([{"contract_id": flat, "amount": -100}]).status_code == 400
    stranger = client.post("/api/v1/contracts", json={
        "contract_number": "X", "property_id": yilmaz["Whg 1.OG"]["property_id"],
        "unit_id": client.post("/api/v1/units", json={"property_id": yilmaz["Whg 1.OG"]["property_id"],
                                                       "label": "Keller", "unit_type": "Keller"}).json()["id"],
        "tenant_id": other_tenant["id"], "start_date": "2024-01-01"}).json()
    assert put([{"contract_id": stranger["id"], "amount": 10}]).status_code == 400

    saved = put([{"contract_id": flat, "amount": 1570}]).json()
    assert [(a["contract_id"], a["amount"], a["source"]) for a in saved] == [(flat, 1570.0, "manual")]
    # Saving the booking again keeps the manual split.
    client.patch(f"/api/v1/bookings/{booking['id']}", json={"payment_text": "Miete März"})
    assert len(client.get(f"/api/v1/bookings/{booking['id']}/allocations").json()) == 1


def test_a_returned_payment_reduces_the_accounts(client, yilmaz):
    client.post("/api/v1/bookings", json={"account_id": yilmaz["account"]["id"], "tenant_id": yilmaz["tenant"]["id"],
                                           "booking_date": "2025-09-10", "amount": -1570,
                                           "payment_text": "Rücklastschrift"})
    account = client.get(f"/api/v1/tenants/{yilmaz['tenant']['id']}/account",
                         params={"as_of": "2025-09-30"}).json()

    assert sum(row["paid"] for row in account["contracts"]) == 12560.0


def test_contract_with_credited_payments_cannot_be_deleted(client, yilmaz):
    response = client.delete(f"/api/v1/contracts/{yilmaz['Garage']['id']}")

    assert response.status_code == 409 and "Zahlungszuordnungen" in response.text


def test_existing_payments_are_allocated_once(client, yilmaz):
    for allocation in store.list_payment_allocations():
        store.delete_payment_allocation(allocation.id)

    first = client.post("/api/v1/bookings/allocate-unassigned").json()
    second = client.post("/api/v1/bookings/allocate-unassigned").json()

    assert (first["allocated"], first["unassigned"], second["allocated"]) == (9, [], 0)
    assert len(store.list_payment_allocations()) == 18
