"""One tenant account with all claims, and a proposal to settle a back payment paid as rent (R12-20)."""

import pytest
from fastapi.testclient import TestClient

from backend.app import app
from backend.auth import clear_users, create_access_token, register_user
from backend.dependencies import store
from backend.services.data_snapshot import clear_business_data

API = "/api/v1"


@pytest.fixture
def estate():
    clear_business_data(store)
    clear_users()
    client = TestClient(app)
    user = register_user("owner", "owner@example.com", "Owner", "Secret123", "eigentuemer")
    headers = {"Authorization": f"Bearer {create_access_token(user.id)}"}

    def post(path, body):
        response = client.post(API + path, headers=headers, json=body)
        assert response.status_code in (200, 201), response.text
        return response.json()

    pf = post("/portfolios", {"name": "P"})["id"]
    house = post("/properties", {"portfolio_id": pf, "name": "Haus", "property_type": "residential"})["id"]
    unit = post("/units", {"property_id": house, "label": "WE 1", "unit_type": "Wohnung", "cold_rent": 600})["id"]
    tenant = post("/tenants", {"full_name": "Anna Muster"})["id"]
    contract = post("/contracts", {"contract_number": "V-1", "property_id": house, "unit_id": unit,
                                   "tenant_id": tenant, "start_date": "2026-01-01", "cold_rent": 600})["id"]
    account = post("/accounts", {"portfolio_id": pf, "name": "Konto", "account_type": "bank"})["id"]
    claim = post("/receivables", {"contract_id": contract, "due_date": "2026-03-01", "amount_due": 120,
                                  "description": "Nebenkostenabrechnung 2025: Nachzahlung"})
    for day in ("2026-01-02", "2026-02-02", "2026-03-02"):
        post("/bookings", {"account_id": account, "tenant_id": tenant, "booking_date": day, "amount": 600,
                           "status": "booked"})
    paid = post("/bookings", {"account_id": account, "tenant_id": tenant, "booking_date": "2026-03-10",
                              "amount": 120, "status": "booked", "payment_text": "Nachzahlung NK 2025"})
    yield {"client": client, "headers": headers, "tenant": tenant, "contract": contract, "claim": claim,
           "paid": paid, "post": post}
    clear_users()
    clear_business_data(store)


def account(estate):
    response = estate["client"].get(f"{API}/tenants/{estate['tenant']}/account?as_of=2026-03-31",
                                    headers=estate["headers"])
    assert response.status_code == 200, response.text
    return response.json()


def test_the_account_holds_the_claims_and_proposes_to_settle_a_payment_credited_as_rent(estate):
    before = account(estate)
    (row,) = before["contracts"]
    # the payment on the back payment was credited as rent: a rent credit, the claim still open
    assert (row["outstanding"], row["overpaid"], row["claims"]) == (0, 120, 120)
    assert row["total_balance"] == 0 and before["totals"]["total_balance"] == 0
    (proposal,) = before["settlement_suggestions"]
    assert (proposal["receivable_id"], proposal["booking_id"], proposal["amount"]) == (
        estate["claim"]["id"], estate["paid"]["id"], 120)

    estate["post"](f"/receivables/{proposal['receivable_id']}/settlements", {
        "expected_revision": proposal["expected_revision"], "idempotency_key": "settle-nk-2025",
        "booking_id": proposal["booking_id"], "amount": proposal["amount"], "effective_date": "2026-03-31",
        "reason": "Ausgleich aus Mietguthaben"})

    after = account(estate)
    (row,) = after["contracts"]
    assert (row["outstanding"], row["overpaid"], row["claims"], row["total_balance"]) == (0, 0, 0, 0)
    assert after["settlement_suggestions"] == []


def test_without_a_rent_credit_nothing_is_proposed_and_the_claim_raises_the_total(estate):
    store.delete_booking(estate["paid"]["id"])
    result = account(estate)
    (row,) = result["contracts"]
    assert (row["overpaid"], row["claims"], row["total_balance"]) == (0, 120, 120)
    assert result["settlement_suggestions"] == []
