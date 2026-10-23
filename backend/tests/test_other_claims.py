"""Claims of their own (damage, keys, …) count as income in the period result (R12-15)."""

from datetime import date

import pytest
from fastapi.testclient import TestClient

from backend.app import app
from backend.auth import clear_users, create_access_token, register_user
from backend.dependencies import store
from backend.finance_models import ReportDefinition
from backend.services import finance_reports
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
        assert response.status_code == 201, response.text
        return response.json()

    pf = post("/portfolios", {"name": "P"})["id"]
    house = post("/properties", {"portfolio_id": pf, "name": "Haus", "property_type": "residential"})["id"]
    unit = post("/units", {"property_id": house, "label": "WE 1", "unit_type": "Wohnung", "cold_rent": 600})["id"]
    tenant = post("/tenants", {"full_name": "Anna Muster"})["id"]
    contract = post("/contracts", {"contract_number": "V-1", "property_id": house, "unit_id": unit,
                                   "tenant_id": tenant, "start_date": "2026-01-01", "cold_rent": 600})["id"]
    damage = post("/receivables", {"contract_id": contract, "due_date": "2026-03-10", "amount_due": 150,
                                   "kind": "other", "description": "Schlüssel verloren"})
    # entered by hand for a missed rent: the rent due holds it already
    post("/receivables", {"contract_id": contract, "due_date": "2026-03-03", "amount_due": 600,
                          "description": "Miete März"})
    yield {"client": client, "headers": headers, "damage": damage}
    clear_users()
    clear_business_data(store)


def test_a_claim_of_its_own_is_income_of_its_month(estate):
    response = estate["client"].get(f"{API}/reports/period-result?date_from=2026-03-01&date_to=2026-03-31",
                                    headers=estate["headers"])
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["totals"]["rent_due"] == 600 and result["totals"]["other_income"] == 150
    assert result["totals"]["result"] == 750
    assert estate["damage"]["kind"] == "other"

    performance = finance_reports.compute(store, ReportDefinition(
        kind="performance-period-v2", as_of=date(2026, 12, 31), date_from=date(2026, 3, 1), date_to=date(2026, 3, 31)))
    assert performance["totals"]["other_income"] == "150.00"
    assert [s["identity"] for s in performance["sources"] if s["contribution"] == "other_income"] == [
        "receivable:" + estate["damage"]["id"]]


def test_only_known_kinds_are_accepted(estate):
    response = estate["client"].patch(f"{API}/receivables/{estate['damage']['id']}", headers=estate["headers"],
                                      json={"kind": "miete"})
    assert response.status_code in (400, 422)
