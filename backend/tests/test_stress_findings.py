"""Findings of the extreme stress test (tools/xstress): roles, implausible input, imports, review hints."""

import json

import pytest
from fastapi.testclient import TestClient

from backend.app import app
from backend.auth import clear_users, create_access_token, register_user
from backend.dependencies import store
from backend.permissions import may_write
from backend.services.data_snapshot import clear_business_data


@pytest.fixture
def client():
    clear_business_data(store)
    clear_users()
    yield TestClient(app)
    clear_users()
    clear_business_data(store)


def _as(role: str) -> dict:
    user = register_user(f"u_{role}", f"{role}@example.com", role, "Secret123", role)
    return {"Authorization": f"Bearer {create_access_token(user.id)}"}


@pytest.fixture
def world(client):
    owner = _as("eigentuemer")
    pf = client.post("/api/v1/portfolios", headers=owner, json={"name": "P"}).json()
    prop = client.post("/api/v1/properties", headers=owner,
                       json={"portfolio_id": pf["id"], "name": "Haus", "property_type": "residential"}).json()
    other = client.post("/api/v1/properties", headers=owner,
                        json={"portfolio_id": pf["id"], "name": "Anderes Haus", "property_type": "residential"}).json()
    unit = client.post("/api/v1/units", headers=owner, json={"property_id": prop["id"], "label": "WE 1",
                                                             "unit_type": "Wohnung", "cold_rent": 600}).json()
    tenant = client.post("/api/v1/tenants", headers=owner, json={"full_name": "Anna Muster"}).json()
    contract = client.post("/api/v1/contracts", headers=owner, json={
        "contract_number": "V-1", "property_id": prop["id"], "unit_id": unit["id"], "tenant_id": tenant["id"],
        "start_date": "2024-01-01"}).json()
    account = client.post("/api/v1/accounts", headers=owner, json={"portfolio_id": pf["id"], "name": "Konto",
                                                                   "account_type": "bank"}).json()
    return {"owner": owner, "pf": pf, "prop": prop, "other": other, "unit": unit, "tenant": tenant,
            "contract": contract, "account": account}


@pytest.mark.parametrize("role, path, allowed", [
    ("buchhaltung", "/bookings", True),
    ("buchhaltung", "/contracts/x/dunning-campaign", True),
    ("buchhaltung", "/contracts", False),
    ("buchhaltung", "/tenants/x", False),
    ("buchhaltung", "/rent-adjustments/x/apply", False),
    ("techniker", "/maintenance", True),
    ("techniker", "/meters/x/readings", True),
    ("techniker", "/bookings", False),
    ("techniker", "/deposits/x", False),
    ("techniker", "/tasks", True),
    ("readonly", "/auth/users/me/preferences", True),
    ("readonly", "/tasks", False),
    ("verwalter", "/contracts/x", True),
    ("verwalter", "/admin/restore/backup.db", False),
    ("eigentuemer", "/admin/restore/backup.db", True),
])
def test_write_permissions_by_role(role, path, allowed):
    assert may_write(role, path) is allowed


def test_roles_are_refused_outside_their_area(client, world):
    """Regression: a technician could delete contracts and book payments."""
    tech, books = _as("techniker"), _as("buchhaltung")
    contract = world["contract"]
    denied = client.delete(f"/api/v1/contracts/{contract['id']}", headers=tech)
    assert denied.status_code == 403 and "Technik" in denied.json()["detail"]
    assert client.post("/api/v1/bookings", headers=tech, json={"account_id": world["account"]["id"],
                                                                "booking_date": "2025-01-02", "amount": 5}).status_code == 403
    assert client.post("/api/v1/maintenance", headers=tech,
                       json={"property_id": world["prop"]["id"], "title": "Heizung"}).status_code == 201
    assert client.post("/api/v1/bookings", headers=books, json={"account_id": world["account"]["id"],
                                                                 "booking_date": "2025-01-02", "amount": 5}).status_code == 201
    assert client.get("/api/v1/auth/me/permissions", headers=tech).json()["write"].count("/maintenance") == 1
    assert client.get("/api/v1/auth/me/permissions", headers=world["owner"]).json()["write"] is None


@pytest.mark.parametrize("path, body", [
    ("/tenants", {"full_name": "   "}),
    ("/units", {"label": "", "unit_type": "Wohnung"}),
    ("/units", {"label": "WE 9", "unit_type": "Wohnung", "cold_rent": -500}),
    ("/units", {"label": "WE\u00009", "unit_type": "Wohnung"}),
    ("/bookings", {"booking_date": "1900-01-01", "amount": 100}),
    ("/bookings", {"booking_date": "2025-01-02", "amount": True}),
    ("/invoices", {"supplier": "X", "invoice_date": "2026-01-10", "net_amount": 100, "vat_rate": 19,
                   "vat_amount": 19, "gross_amount": 150}),
    ("/invoices", {"supplier": "X", "invoice_date": "2026-01-10", "net_amount": 100, "vat_rate": 190,
                   "gross_amount": 290}),
    ("/properties", {"name": "T", "property_type": "raumschiff"}),
    ("/properties", {"name": "T", "property_type": "residential", "year_built": 3000}),
    ("/tasks", {"title": "T", "priority": "sofort"}),
    ("/billing/allocation-keys", {"name": "T", "key_type": "mondphase"}),
])
def test_implausible_input_is_refused(client, world, path, body):
    refs = {"/units": {"property_id": world["prop"]["id"]}, "/bookings": {"account_id": world["account"]["id"]},
            "/properties": {"portfolio_id": world["pf"]["id"]},
            "/billing/allocation-keys": {"property_id": world["prop"]["id"]}}
    resp = client.post(f"/api/v1{path}", headers=world["owner"], json={**refs.get(path, {}), **body})
    assert resp.status_code == 400, resp.text


def test_cross_checks_use_the_stored_record(client, world):
    owner = world["owner"]
    wrong_house = client.post("/api/v1/bookings", headers=owner, json={
        "account_id": world["account"]["id"], "booking_date": "2025-01-02", "amount": 10,
        "property_id": world["other"]["id"], "unit_id": world["unit"]["id"]})
    assert wrong_house.status_code == 400 and "gehört nicht" in wrong_house.json()["error"]["message"]
    early = client.post("/api/v1/rent-adjustments", headers=owner, json={
        "contract_id": world["contract"]["id"], "adjustment_type": "index", "effective_date": "2020-01-01",
        "previous_rent": 600, "new_rent": 620})
    assert early.status_code == 400
    invoice = client.post("/api/v1/invoices", headers=owner, json={
        "supplier": "X", "invoice_date": "2026-01-10", "net_amount": 100, "vat_rate": 19, "vat_amount": 19,
        "gross_amount": 119}).json()
    # changing only the net amount must keep gross = net + VAT
    assert client.patch(f"/api/v1/invoices/{invoice['id']}", headers=owner, json={"net_amount": 200}).status_code == 400


def test_old_records_stay_editable(client, world):
    """A record stored before a rule existed can still be changed in other fields."""
    if not hasattr(store, "tenants"):
        pytest.skip("stored records can only be set directly in the memory store")
    tenant = world["tenant"]
    store.tenants[tenant["id"]] = store.get_tenant(tenant["id"]).model_copy(update={"full_name": ""})
    resp = client.patch(f"/api/v1/tenants/{tenant['id']}", headers=world["owner"], json={"phone": "+49 30 1"})
    assert resp.status_code == 200


def test_meter_readings_must_not_go_backwards(client, world):
    owner = world["owner"]
    meter = client.post("/api/v1/meters", headers=owner, json={"unit_id": world["unit"]["id"],
                                                               "meter_type": "water_cold"}).json()
    url = f"/api/v1/meters/{meter['id']}/readings"
    assert client.post(url, headers=owner, json={"meter_id": meter["id"], "reading_date": "2025-12-31",
                                                 "value": 120}).status_code == 201
    lower = client.post(url, headers=owner, json={"meter_id": meter["id"], "reading_date": "2026-06-30", "value": 100})
    assert lower.status_code == 400 and "kleiner" in lower.json()["error"]["message"]
    assert client.post(url, headers=owner, json={"meter_id": meter["id"], "reading_date": "2026-06-30",
                                                 "value": -1}).status_code == 400


@pytest.mark.parametrize("content", [
    {"format": "other-app", "tenants": []},
    {"format": "immomanager-snapshot", "format_version": 99, "tenants": []},
    {"Mieterliste": ["Müller"]},
])
def test_foreign_files_are_not_imported_as_success(client, world, content):
    """Regression: such files answered 200 with nothing imported."""
    resp = client.post("/api/v1/data/import", headers=world["owner"],
                       files={"file": ("x.json", json.dumps(content).encode(), "application/json")})
    assert resp.status_code == 400


def test_review_list_flags_implausible_entries(client, world):
    owner = world["owner"]
    client.patch(f"/api/v1/contracts/{world['contract']['id']}", headers=owner, json={"deposit_amount": 3000})
    client.post("/api/v1/rent-adjustments", headers=owner, json={
        "contract_id": world["contract"]["id"], "adjustment_type": "comparative", "effective_date": "2025-07-15",
        "previous_rent": 600, "new_rent": 900})
    client.post("/api/v1/billing/periods", headers=owner, json={
        "property_id": world["prop"]["id"], "label": "NK 23/24", "start_date": "2023-01-01", "end_date": "2024-12-31"})
    client.post("/api/v1/invoices", headers=owner, json={
        "supplier": "X", "invoice_date": "2026-03-10", "due_date": "2026-01-01", "net_amount": 100, "vat_rate": 19,
        "vat_amount": 19, "gross_amount": 119})

    kinds = {item["kind"] for item in client.get("/api/v1/review", headers=owner).json()["items"]}

    assert {"deposit_too_high", "increase_over_cap", "adjustment_mid_month", "statement_period_too_long",
            "invoice_due_before_date"} <= kinds
