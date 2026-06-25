"""Regression tests for frontend/API contracts used by routed pages."""

import pytest
from fastapi.testclient import TestClient

from backend.app import app
from backend.auth import clear_users, create_access_token, register_user
from backend.dependencies import store


@pytest.fixture(autouse=True)
def _clean_store():
    store.clear_all()
    clear_users()
    yield
    clear_users()


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def auth_headers():
    user = register_user("uiuser", "ui@example.com", "UI User", "Secret123", "eigentuemer")
    return {"Authorization": f"Bearer {create_access_token(user.id)}"}


def _create_contract(client: TestClient, headers: dict[str, str]) -> str:
    portfolio = client.post("/api/v1/portfolios", json={"name": "UI Portfolio"}, headers=headers)
    assert portfolio.status_code == 201, portfolio.text

    prop = client.post(
        "/api/v1/properties",
        json={
            "portfolio_id": portfolio.json()["id"],
            "name": "UI Haus",
            "property_type": "residential",
        },
        headers=headers,
    )
    assert prop.status_code == 201, prop.text

    unit = client.post(
        "/api/v1/units",
        json={
            "property_id": prop.json()["id"],
            "label": "WE 1",
            "unit_type": "apartment",
            "cold_rent": 900,
        },
        headers=headers,
    )
    assert unit.status_code == 201, unit.text

    tenant = client.post(
        "/api/v1/tenants",
        json={"full_name": "UI Mieter", "email": "ui-mieter@example.com"},
        headers=headers,
    )
    assert tenant.status_code == 201, tenant.text

    contract = client.post(
        "/api/v1/contracts",
        json={
            "contract_number": "UI-2026-001",
            "property_id": prop.json()["id"],
            "unit_id": unit.json()["id"],
            "tenant_id": tenant.json()["id"],
            "start_date": "2026-01-01",
            "status": "active",
        },
        headers=headers,
    )
    assert contract.status_code == 201, contract.text
    return contract.json()["id"]


def _create_unit(client: TestClient, headers: dict[str, str]) -> str:
    portfolio = client.post("/api/v1/portfolios", json={"name": "Meter Portfolio"}, headers=headers)
    assert portfolio.status_code == 201, portfolio.text

    prop = client.post(
        "/api/v1/properties",
        json={
            "portfolio_id": portfolio.json()["id"],
            "name": "Meter Haus",
            "property_type": "residential",
        },
        headers=headers,
    )
    assert prop.status_code == 201, prop.text

    unit = client.post(
        "/api/v1/units",
        json={
            "property_id": prop.json()["id"],
            "label": "Zaehler WE",
            "unit_type": "apartment",
        },
        headers=headers,
    )
    assert unit.status_code == 201, unit.text
    return unit.json()["id"]


def test_invoice_ui_fields_are_persisted(client, auth_headers):
    payload = {
        "supplier": "Hausservice GmbH",
        "invoice_number": "RE-2026-001",
        "invoice_date": "2026-06-15",
        "due_date": "2026-07-15",
        "net_amount": 100,
        "vat_rate": 19,
        "vat_amount": 19,
        "gross_amount": 119,
        "payment_terms": "30 Tage netto",
        "payment_reference": "RE-2026-001 Kundennr. 42",
        "category": "instandhaltung",
        "notes": "Im UI erfasst",
        "status": "open",
    }

    created = client.post("/api/v1/invoices", json=payload, headers=auth_headers)
    assert created.status_code == 201, created.text
    invoice = created.json()
    assert invoice["invoice_number"] == payload["invoice_number"]
    assert invoice["payment_reference"] == payload["payment_reference"]
    assert invoice["category"] == payload["category"]
    assert invoice["notes"] == payload["notes"]

    patched = client.patch(
        f"/api/v1/invoices/{invoice['id']}",
        json={"notes": "Nachbearbeitet", "status": "paid"},
        headers=auth_headers,
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["notes"] == "Nachbearbeitet"
    assert patched.json()["status"] == "paid"


def test_receivable_description_from_ui_is_persisted(client, auth_headers):
    contract_id = _create_contract(client, auth_headers)

    created = client.post(
        "/api/v1/receivables",
        json={
            "contract_id": contract_id,
            "due_date": "2026-07-03",
            "amount_due": 950,
            "status": "open",
            "description": "Miete Juli 2026",
        },
        headers=auth_headers,
    )
    assert created.status_code == 201, created.text
    assert created.json()["description"] == "Miete Juli 2026"


def test_rent_charge_page_payload_matches_backend_model(client, auth_headers):
    contract_id = _create_contract(client, auth_headers)

    created = client.post(
        "/api/v1/rent-charges",
        json={
            "contract_id": contract_id,
            "month": "2026-07",
            "cold_rent": 900,
            "service_charge": 120,
            "heating_charge": 80,
            "other_charges": 15,
            "amount_paid": 500,
            "status": "partial",
        },
        headers=auth_headers,
    )
    assert created.status_code == 201, created.text
    charge = created.json()
    assert charge["cold_rent"] == 900
    assert charge["service_charge"] == 120
    assert charge["heating_charge"] == 80
    assert charge["other_charges"] == 15
    assert charge["amount_paid"] == 500


def test_notification_template_page_payload_matches_backend_model(client, auth_headers):
    created = client.post(
        "/api/v1/notifications/templates",
        json={
            "name": "Mahnung Standard",
            "notification_type": "overdue_payment",
            "title_template": "Mahnung {{tenant_name}}",
            "content_template": "Bitte zahlen Sie {{amount_due}} EUR bis {{due_date}}.",
            "severity": "warning",
        },
        headers=auth_headers,
    )
    assert created.status_code == 201, created.text
    template = created.json()
    assert template["title_template"] == "Mahnung {{tenant_name}}"
    assert template["content_template"].startswith("Bitte zahlen")


def test_document_ocr_analyze_route_exists_for_documents_page(client, auth_headers):
    uploaded = client.post(
        "/api/v1/files/upload?folder=documents",
        files={"file": ("scan.pdf", b"%PDF-1.4\n%%EOF", "application/pdf")},
        headers=auth_headers,
    )
    assert uploaded.status_code == 200, uploaded.text

    analyzed = client.post(
        "/api/v1/documents/ocr-analyze",
        json={"file_url": uploaded.json()["file_url"], "use_ai": False},
        headers=auth_headers,
    )
    assert analyzed.status_code == 200, analyzed.text
    body = analyzed.json()
    assert "success" in body
    assert "analyzed" in body
    assert "guessedType" in body


def test_meter_contract_fields_from_ui_are_persisted(client, auth_headers):
    unit_id = _create_unit(client, auth_headers)

    created = client.post(
        "/api/v1/meters",
        json={
            "unit_id": unit_id,
            "meter_type": "electricity",
            "serial_number": "M-001",
            "supplier": "Stadtwerke",
            "contract_number": "SW-2026-99",
            "contract_end_date": "2027-12-31",
        },
        headers=auth_headers,
    )
    assert created.status_code == 201, created.text
    meter = created.json()
    assert meter["contract_number"] == "SW-2026-99"
    assert meter["contract_end_date"] == "2027-12-31"
