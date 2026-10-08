"""Rent history per contract: applied adjustments count, unit changes do not rewrite running contracts."""

from datetime import date

import pytest
from fastapi.testclient import TestClient

from backend.app import app
from backend.auth import clear_users, create_access_token, register_user
from backend.dependencies import store
from backend.services.data_snapshot import clear_business_data
from backend.services.utility_billing import prepayment_for_month


@pytest.fixture
def client():
    clear_business_data(store)
    clear_users()
    owner = register_user("owner", "owner@example.com", "Owner", "Secret123", "eigentuemer")
    yield TestClient(app, headers={"Authorization": f"Bearer {create_access_token(owner.id)}"})
    clear_users()
    clear_business_data(store)


def _we05(client, start="2018-10-01"):
    """Leipzig, Wohnung 05: 780 € cold rent, 190 € service charges, 100 € heating."""
    pf = client.post("/api/v1/portfolios", json={"name": "P"}).json()
    prop = client.post("/api/v1/properties", json={"portfolio_id": pf["id"], "name": "MFH Leipzig",
                                                   "property_type": "residential"}).json()
    unit = client.post("/api/v1/units", json={"property_id": prop["id"], "label": "WE 05", "unit_type": "Wohnung",
                                              "cold_rent": 780, "service_charge_advance": 190,
                                              "heating_advance": 100}).json()
    tenant = client.post("/api/v1/tenants", json={"full_name": "Dr. Maria Hoffmann"}).json()
    contract = client.post("/api/v1/contracts", json={"contract_number": "MV-005", "property_id": prop["id"],
                                                      "unit_id": unit["id"], "tenant_id": tenant["id"],
                                                      "start_date": start}).json()
    return unit, contract


def _expected(client, contract, as_of="2025-06-30"):
    body = client.get(f"/api/v1/contracts/{contract['id']}/settlement", params={"as_of": as_of}).json()
    return body["balance"]["expected_total"]


def _adjustment(client, contract, **extra):
    return client.post("/api/v1/rent-adjustments", json={
        "contract_id": contract["id"], "adjustment_type": "index", "effective_date": "2025-01-01",
        "previous_rent": 780, "new_rent": 820, **extra}).json()


def test_applied_increase_counts_from_its_date_and_unit_changes_do_not_reach_back(client):
    """Regression: an applied increase changed nothing (86,670 €); editing the unit made it 89,910 €."""
    unit, contract = _we05(client)
    adjustment = _adjustment(client, contract)

    assert _expected(client, contract) == 86670.0  # 81 months × 1,070 €
    applied = client.post(f"/api/v1/rent-adjustments/{adjustment['id']}/apply").json()
    assert applied["adjustment"]["status"] == "applied" and applied["warnings"] == []
    assert _expected(client, contract) == 86910.0  # + 6 months × 40 €

    client.patch(f"/api/v1/units/{unit['id']}", json={"cold_rent": 900})
    assert _expected(client, contract) == 86910.0

    client.post(f"/api/v1/rent-adjustments/{adjustment['id']}/apply")  # twice counts once
    assert len(client.get(f"/api/v1/contracts/{contract['id']}/rent-periods").json()) == 2
    client.post(f"/api/v1/rent-adjustments/{adjustment['id']}/revert")
    assert _expected(client, contract) == 86670.0


def test_status_applied_through_the_old_form_goes_through_the_history(client):
    _, contract = _we05(client)
    adjustment = _adjustment(client, contract)
    fields = {k: v for k, v in adjustment.items() if k not in ("id", "created_at", "updated_at")}

    client.put(f"/api/v1/rent-adjustments/{adjustment['id']}", json={**fields, "status": "applied"})
    assert _expected(client, contract) == 86910.0
    client.patch(f"/api/v1/rent-adjustments/{adjustment['id']}", json={"status": "rejected"})
    assert _expected(client, contract) == 86670.0
    client.patch(f"/api/v1/rent-adjustments/{adjustment['id']}", json={"status": "applied"})
    client.delete(f"/api/v1/rent-adjustments/{adjustment['id']}")
    assert _expected(client, contract) == 86670.0


def test_invalid_adjustments_are_refused_and_differences_reported(client):
    _, contract = _we05(client)
    mid_month = _adjustment(client, contract, effective_date="2025-01-15")
    wrong_base = _adjustment(client, contract, previous_rent=700, effective_date="2025-03-01")

    assert client.post(f"/api/v1/rent-adjustments/{mid_month['id']}/apply").status_code == 400
    warnings = client.post(f"/api/v1/rent-adjustments/{wrong_base['id']}/apply").json()["warnings"]
    assert warnings == ["Bisherige Miete der Anpassung (700.00 €) weicht vom Mietverlauf ab (780.00 €)"]


def test_moving_in_mid_month_pays_by_days(client):
    _, contract = _we05(client, start="2025-09-16")
    body = client.get(f"/api/v1/contracts/{contract['id']}/settlement", params={"as_of": "2025-10-31"}).json()

    assert [line["total_amount"] for line in body["receivables"]] == [535.0, 1070.0]  # 15/30 of 1,070 €


def test_utility_advances_follow_the_rent_history(client):
    _, contract = _we05(client)
    client.post(f"/api/v1/contracts/{contract['id']}/rent-periods", json={
        "contract_id": contract["id"], "valid_from": "2025-07-01", "cold_rent": 780,
        "service_charge_advance": 210, "heating_advance": 120})
    stored = store.get_contract(contract["id"])

    assert prepayment_for_month(store, stored, date(2025, 6, 1)) == 290
    assert prepayment_for_month(store, stored, date(2025, 7, 1)) == 330


def test_deleting_a_contract_removes_its_rent_history(client):
    _, contract = _we05(client)

    assert client.delete(f"/api/v1/contracts/{contract['id']}").status_code == 204
    assert store.list_contract_rent_periods(contract["id"]) == []
