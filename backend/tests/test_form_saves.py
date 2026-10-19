"""The app's own forms save as the browser sends them: empty optional fields arrive as null.

Found by filling every "Neu" form in Chromium with only its required fields and saving it.
"""

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from backend import auth
from backend.app import app
from backend.dependencies import store
from backend.models import ContractCreate, PortfolioCreate, PropertyCreate, TenantCreate, UnitCreate
from backend.services.data_snapshot import clear_business_data

API = "/api/v1"


@pytest.fixture(autouse=True)
def _clean():
    clear_business_data(store)
    auth.clear_users()
    yield
    clear_business_data(store)
    auth.clear_users()


@pytest.fixture
def client():
    user = auth.register_user("linda.reiser", "linda@example.com", "Linda Reiser", "Secret123", "eigentuemer")
    return TestClient(app, headers={"Authorization": f"Bearer {auth.create_access_token(user.id)}"})


@pytest.fixture
def estate():
    portfolio = store.create_portfolio(PortfolioCreate(name="Nord", owner_name="Linda Reiser"))
    prop = store.create_property(PropertyCreate(portfolio_id=portfolio.id, name="Bautzner Straße 61",
                                                property_type="residential"))
    unit = store.create_unit(UnitCreate(property_id=prop.id, label="WE 3", unit_type="residential", cold_rent=500))
    tenant = store.create_tenant(TenantCreate(full_name="Mia Muster"))
    contract = store.create_contract(ContractCreate(contract_number="V-1", property_id=prop.id, unit_id=unit.id,
                                                    tenant_id=tenant.id, start_date="2024-01-01", status="active"))
    return {"property": prop, "contract": contract}


def _message(response):
    body = response.json()
    return body.get("error", {}).get("message") or str(body.get("detail"))


def test_optional_fields_left_empty_save_with_their_defaults(client, estate):
    budget = client.post(f"{API}/budgets", json={"property_id": estate["property"].id, "year": 2026,
                                                  "category": "maintenance", "planned_amount": 5000,
                                                  "actual_amount": None, "notes": None})
    assert budget.status_code == 201, budget.text
    assert budget.json()["actual_amount"] == 0.0
    rate = client.post(f"{API}/tax-rates", json={"name": "Regelsteuersatz", "rate": 19, "description": None,
                                                  "is_default": None, "valid_from": None, "valid_until": None})
    assert rate.status_code == 201, rate.text
    assert rate.json()["is_default"] is False
    # the form asks for name, kind, days, severity and whether active; the run reads the due date and notifies
    rule = client.post(f"{API}/escalation/rules", json={"name": "Aufgaben überfällig", "entity_type": "task",
                                                         "days_overdue": 3, "notification_severity": "warning",
                                                         "is_active": True})
    assert rule.status_code == 201, rule.text
    assert (rule.json()["condition_field"], rule.json()["action"]) == ("due_date", "notify")


def test_a_rent_charge_month_is_a_month(client, estate):
    base = {"contract_id": estate["contract"].id, "cold_rent": 500, "service_charge": 0, "heating_charge": 0,
            "other_charges": 0, "amount_paid": 0, "status": "open"}
    for month in ("QA Monat", "2026-13", "2026-6", "06.2026"):
        refused = client.post(f"{API}/rent-charges", json={**base, "month": month})
        assert refused.status_code == 400 and "JJJJ-MM" in _message(refused), (month, refused.text)
    saved = client.post(f"{API}/rent-charges", json={**base, "month": "2026-06"})
    assert saved.status_code == 201, saved.text
    negative = client.post(f"{API}/rent-charges", json={**base, "month": "2026-07", "cold_rent": -1})
    assert negative.status_code == 400


def test_a_contact_needs_a_name_or_a_company(client):
    nameless = client.post(f"{API}/contacts", json={"contact_type": "supplier", "first_name": None, "last_name": "  ",
                                                    "company_name": None, "email": "info@example.com"})
    assert nameless.status_code == 400 and "Namen oder eine Firma" in _message(nameless)
    company = client.post(f"{API}/contacts", json={"contact_type": "supplier", "company_name": "Dachdeckerei Kunze"})
    assert company.status_code == 201, company.text
    # a change of another field keeps the stored name
    changed = client.patch(f"{API}/contacts/{company.json()['id']}", json={"email": "info@kunze.example"})
    assert changed.status_code == 200, changed.text
    cleared = client.patch(f"{API}/contacts/{company.json()['id']}", json={"company_name": ""})
    assert cleared.status_code == 400


def test_an_invoice_amount_mismatch_reads_in_german_money(client, estate):
    response = client.post(f"{API}/invoices", json={"supplier": "Kunze", "invoice_date": "2026-10-01",
                                                    "net_amount": 1234.5, "vat_rate": 19, "gross_amount": 1234.5,
                                                    "property_id": estate["property"].id})
    assert response.status_code == 400
    assert _message(response) == ("Brutto 1.234,50 € passt nicht zu Netto 1.234,50 € und MwSt (erwartet 1.469,06 €)")


def test_the_service_contract_forms_keep_their_drafts(client, estate):
    """The create form carries the first location and tariff; the contract's page adds more forms on one route."""
    values = {"contract_type": "electricity", "title": "Allgemeinstrom", "start_date": "2026-01-01",
              "renewal_mode": "none", "property_id": estate["property"].id, "unit_id": None, "meter_id": None,
              "supply_point": "DE000123", "tariff_valid_from": "2026-01-01", "tariff_price": "0.3120",
              "tariff_price_unit": "kWh", "tariff_advance_amount": "45", "share_weight": 1, "effective_date": None,
              "period_start": "2026-01-01", "consumption": 1200}
    saved = client.put(f"{API}/workspace/drafts/{uuid4()}", json={
        "base_revision": 0, "idempotency_key": str(uuid4()), "context": "service-contracts", "values": values})
    assert saved.status_code == 200, saved.text
    foreign = client.put(f"{API}/workspace/drafts/{uuid4()}", json={
        "base_revision": 0, "idempotency_key": str(uuid4()), "context": "service-contracts",
        "values": {"title": "x", "role": "eigentuemer"}})
    assert foreign.status_code == 422          # still only the fields of these forms
