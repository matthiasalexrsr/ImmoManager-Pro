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
    ("readonly", "/notifications/abc", True),
    ("readonly", "/notifications/abc/read", True),
    ("readonly", "/notifications/templates", False),
    ("techniker", "/notifications/templates/abc", False),
    ("buchhaltung", "/notifications/generate/overdue-payments", True),
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


@pytest.mark.parametrize("body, text", [
    ({"cold_rent": "1.200,50"}, "cold_rent: Bitte eine gültige Zahl angeben"),
    ({"area_sqm": 0}, "Fläche muss größer als 0 m² sein"),
    ({"person_count": 2.5}, "person_count: Bitte eine ganze Zahl angeben"),
])
def test_input_errors_read_as_german_sentences(client, world, body, text):
    """Regression: the UI showed pydantic's English texts (e.g. 'Input should be a valid number')."""
    resp = client.post("/api/v1/units", headers=world["owner"],
                       json={"property_id": world["prop"]["id"], "label": "WE 2", "unit_type": "Wohnung", **body})
    assert resp.status_code == 422
    assert resp.json()["detail"][0]["msg"] == text


def test_missing_and_malformed_dates_are_explained(client, world):
    resp = client.post("/api/v1/contracts", headers=world["owner"], json={
        "contract_number": "V-9", "property_id": world["prop"]["id"], "unit_id": world["unit"]["id"],
        "tenant_id": world["tenant"]["id"], "start_date": "01.02.2026"})
    assert resp.json()["detail"][0]["msg"] == "start_date: Bitte ein gültiges Datum angeben (JJJJ-MM-TT)"
    resp = client.post("/api/v1/tenants", headers=world["owner"], json={})
    assert resp.json()["detail"][0]["msg"] == "Pflichtangabe fehlt: full_name"


@pytest.mark.parametrize("path, body", [
    ("/accounts", {"name": "Konto 2", "account_type": "bank", "iban": "DE00370400440532013000"}),
    ("/properties", {"name": "T", "property_type": "residential", "postal_code": "ABCDE", "country": "DE"}),
    ("/tenants", {"full_name": "Test", "phone": "abc"}),
    ("/units", {"label": "WE 3", "unit_type": "Wohnung", "cold_rent": 1e12}),
    ("/units", {"label": "Ä" * 300, "unit_type": "Wohnung"}),
    ("/bookings", {"booking_date": "2025-01-02", "amount": 1e12}),
])
def test_typos_with_too_many_digits_or_wrong_format_are_refused(client, world, path, body):
    refs = {"/accounts": {"portfolio_id": world["pf"]["id"]}, "/properties": {"portfolio_id": world["pf"]["id"]},
            "/units": {"property_id": world["prop"]["id"]}, "/bookings": {"account_id": world["account"]["id"]}}
    resp = client.post(f"/api/v1{path}", headers=world["owner"], json={**refs.get(path, {}), **body})
    assert resp.status_code == 400, resp.text


def test_a_valid_iban_with_spaces_and_a_foreign_postcode_pass(client, world):
    owner = world["owner"]
    assert client.post("/api/v1/accounts", headers=owner, json={
        "portfolio_id": world["pf"]["id"], "name": "Konto 2", "account_type": "bank",
        "iban": "DE89 3704 0044 0532 0130 00"}).status_code == 201
    assert client.post("/api/v1/properties", headers=owner, json={
        "portfolio_id": world["pf"]["id"], "name": "Wien", "property_type": "residential", "postal_code": "1010",
        "country": "AT"}).status_code == 201


def test_a_manual_rent_period_starts_on_the_first(client, world):
    """A change in mid-month would only be charged from the following month."""
    url = f"/api/v1/contracts/{world['contract']['id']}/rent-periods"
    body = {"contract_id": world["contract"]["id"], "cold_rent": 650, "service_charge_advance": 0, "heating_advance": 0}
    assert client.post(url, headers=world["owner"], json={**body, "valid_from": "2025-03-15"}).status_code == 400
    assert client.post(url, headers=world["owner"], json={**body, "valid_from": "2025-03-01"}).status_code == 201


def test_framework_errors_are_german(client, world):
    assert client.get("/api/v1/gibt-es-nicht", headers=world["owner"]).json()["error"]["message"] == "Nicht gefunden"
    resp = client.put("/api/v1/review", headers=world["owner"], json={})
    assert resp.status_code == 405 and resp.json()["error"]["message"] == "Diese Aktion ist hier nicht möglich"


@pytest.mark.parametrize("path, body", [
    ("/contracts", {"contract_number": "V-9", "start_date": "2200-01-01"}),
    ("/contracts", {"contract_number": "V-9", "start_date": "2026-01-01", "end_date": "2300-01-01"}),
    ("/units", {"label": "WE 9", "area_sqm": 30, "rooms": 25}),
    ("/tenants", {"full_name": "Test", "payment_method": "bitcoin"}),
    ("/tenants", {"full_name": "<img src=x onerror=alert(1)>"}),
])
def test_more_implausible_input_is_refused(client, world, path, body):
    """Second full run: a contract starting in 2200, 25 rooms on 30 m², an unknown payment method, HTML in a name."""
    refs = {"/contracts": {"property_id": world["prop"]["id"], "unit_id": world["unit"]["id"],
                           "tenant_id": world["tenant"]["id"]},
            "/units": {"property_id": world["prop"]["id"], "unit_type": "Wohnung"}}
    resp = client.post(f"/api/v1{path}", headers=world["owner"], json={**refs.get(path, {}), **body})
    assert resp.status_code == 400, resp.text


def test_a_storeroom_with_one_room_and_names_with_angles_in_words_pass(client, world):
    owner = world["owner"]
    assert client.post("/api/v1/units", headers=owner, json={
        "property_id": world["prop"]["id"], "label": "Abstellraum", "unit_type": "Abstellraum", "area_sqm": 3,
        "rooms": 1}).status_code == 201
    assert client.post("/api/v1/tenants", headers=owner, json={
        "full_name": "Meier & Söhne (Zins < 3 %)", "payment_method": "sepa_direct_debit"}).status_code == 201


@pytest.mark.parametrize("given, stored", [("transfer", "bank_transfer"), ("SEPA", "sepa_direct_debit"),
                                           ("Überweisung", "bank_transfer"), ("bar", "cash"), ("cash", "cash")])
def test_common_spellings_of_a_payment_method_are_understood(client, world, given, stored):
    """Imports and other systems write "transfer" or "SEPA"; the app stores its own codes."""
    resp = client.post("/api/v1/tenants", headers=world["owner"], json={"full_name": "Test", "payment_method": given})
    assert resp.status_code == 201 and resp.json()["payment_method"] == stored
    patched = client.patch(f"/api/v1/tenants/{resp.json()['id']}", headers=world["owner"],
                           json={"payment_method": "Lastschrift"})
    assert patched.json()["payment_method"] == "sepa_direct_debit"


def test_saving_over_someone_elses_newer_change_is_refused(client, world):
    """Two forms open the same tenant; the second save must not silently overwrite the first one."""
    owner, manager = world["owner"], _as("verwalter")
    url = f"/api/v1/tenants/{world['tenant']['id']}"
    opened = client.get(url, headers=owner).json()

    first = client.put(url, headers=manager, json={"full_name": "Anna Muster", "notes": "Stand A",
                                                   "updated_at": opened["updated_at"]})
    assert first.status_code == 200, first.text
    second = client.put(url, headers=owner, json={"full_name": "Anna Muster", "notes": "Stand B",
                                                  "updated_at": opened["updated_at"]})

    assert second.status_code == 409 and "inzwischen geändert" in second.text
    assert client.get(url, headers=owner).json()["notes"] == "Stand A"
    # with the fresh state it saves; a client that sends no state keeps "the last one wins"
    fresh = client.get(url, headers=owner).json()["updated_at"]
    assert client.put(url, headers=owner, json={"full_name": "Anna Muster", "notes": "Stand B",
                                                "updated_at": fresh}).status_code == 200
    assert client.patch(url, headers=owner, json={"notes": "Stand C"}).status_code == 200


def test_review_list_flags_a_rent_decrease_and_a_negative_invoice(client, world):
    owner = world["owner"]
    client.post("/api/v1/rent-adjustments", headers=owner, json={
        "contract_id": world["contract"]["id"], "adjustment_type": "index", "effective_date": "2027-01-01",
        "previous_rent": 600, "new_rent": 300})
    client.post("/api/v1/invoices", headers=owner, json={
        "supplier": "X", "invoice_date": "2026-01-10", "net_amount": -100, "vat_rate": 19, "vat_amount": -19,
        "gross_amount": -119})

    kinds = {item["kind"] for item in client.get("/api/v1/review", headers=owner).json()["items"]}

    assert {"rent_decrease", "invoice_negative"} <= kinds


def test_long_calculations_run_one_after_the_other():
    """Reports read whole tables; side by side in threads they slowed each other down tenfold."""
    import threading
    import time

    from backend.concurrency import one_at_a_time

    running, overlaps = [], []

    @one_at_a_time
    def report():
        running.append(1)
        overlaps.append(len(running))
        time.sleep(0.02)
        running.pop()

    threads = [threading.Thread(target=report) for _ in range(5)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert overlaps == [1] * 5


def test_cached_reads_answer_like_the_store(client, world):
    from backend.services.read_cache import CachedReads

    contract = world["contract"]
    client.post(f"/api/v1/contracts/{contract['id']}/rent-periods", headers=world["owner"], json={
        "contract_id": contract["id"], "valid_from": "2025-01-01", "cold_rent": 650, "service_charge_advance": 0,
        "heating_advance": 0})
    cached = CachedReads(store)

    assert cached.list_contract_rent_periods(contract["id"]) == store.list_contract_rent_periods(contract["id"])
    assert sorted(p.id for p in cached.list_contract_rent_periods()) == \
        sorted(p.id for p in store.list_contract_rent_periods())
    assert cached.list_contract_rent_periods("gibt-es-nicht") == []
    assert [c.id for c in cached.list_contracts()] == [c.id for c in store.list_contracts()]
