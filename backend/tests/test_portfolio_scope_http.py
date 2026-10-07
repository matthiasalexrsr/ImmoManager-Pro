"""A restricted account sees and changes only its portfolios: lists, IDs, nested records, files, writes.

Runs on the memory store and, with TEST_STORE_BACKEND=sql, on SQLite (PostgreSQL in
test_portfolio_scope_postgres.py).
"""

from datetime import date
from io import BytesIO

import pytest
from archive_helpers import lease_with_document
from fastapi.testclient import TestClient

from backend import auth
from backend.app import app
from backend.dependencies import store
from backend.models import AccountCreate, BookingCreate
from backend.services.file_storage import get_file_storage


@pytest.fixture(autouse=True)
def _clean():
    auth.clear_users()
    store.clear_all()
    yield
    auth.clear_users()
    store.clear_all()


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def estate():
    """Two portfolios with the same shape; the files exist on disk."""
    sides = {}
    for side, number in (("north", "N-1"), ("south", "S-1")):
        url = f"/uploads/documents/{side}-vertrag.pdf"
        get_file_storage().save(f"documents/{side}-vertrag.pdf", BytesIO(b"%PDF-1.4 " + side.encode()),
                                content_type="application/pdf")
        lease = lease_with_document(store, number=number, file_url=url)
        account = store.create_account(AccountCreate(portfolio_id=lease["portfolio"].id, name=f"Konto {side}",
                                                     account_type="bank"))
        lease["booking"] = store.create_booking(BookingCreate(
            account_id=account.id, property_id=lease["property"].id, unit_id=lease["unit"].id,
            booking_date=date(2026, 1, 3), amount=850.0, payment_text=f"Miete {side}"))
        lease["account"] = account
        sides[side] = lease
    return sides


def _bearer(user) -> dict:
    return {"Authorization": f"Bearer {auth.create_access_token(user.id)}"}


def _staff(name, *portfolios, role="verwalter", mode="selected"):
    return auth.register_user(name, f"{name}@example.com", name.title(), "Secret123", role,
                              portfolio_access=mode, portfolio_ids=[p.id for p in portfolios])


def _ids(response):
    assert response.status_code == 200, response.text
    body = response.json()
    items = body["items"] if isinstance(body, dict) and "items" in body else body
    return {item["id"] for item in items}


LISTS = ("portfolios", "properties", "units", "tenants", "contracts", "documents", "accounts", "bookings")


def test_lists_and_direct_reads_stop_at_the_portfolio(client, estate):
    north, south = estate["north"], estate["south"]
    staff = _bearer(_staff("staff", north["portfolio"]))
    keys = {"portfolios": "portfolio", "properties": "property", "units": "unit", "tenants": "tenant",
            "contracts": "contract", "documents": "document", "accounts": "account", "bookings": "booking"}
    for path in LISTS:
        assert _ids(client.get(f"/api/v1/{path}?limit=1000", headers=staff)) == {north[keys[path]].id}, path
    for path, key in (("properties", "property"), ("units", "unit"), ("tenants", "tenant"),
                      ("contracts", "contract"), ("documents", "document")):
        assert client.get(f"/api/v1/{path}/{south[key].id}", headers=staff).status_code == 404, path
        assert client.get(f"/api/v1/{path}/{north[key].id}", headers=staff).status_code == 200, path

    owner = _bearer(_staff("owner", role="eigentuemer", mode="all"))
    assert len(_ids(client.get("/api/v1/properties?limit=1000", headers=owner))) == 2


def test_files_of_other_portfolios_are_not_served(client, estate):
    staff = _bearer(_staff("staff", estate["north"]["portfolio"]))
    assert client.get(estate["north"]["document"].file_url, headers=staff).status_code == 200
    assert client.get(estate["south"]["document"].file_url, headers=staff).status_code == 404
    assert client.get("/api/v1/files/download", params={"key": "documents/south-vertrag.pdf"},
                      headers=staff).status_code == 404
    assert client.get("/api/v1/files/download", params={"key": "documents/north-vertrag.pdf"},
                      headers=staff).status_code == 200


def test_writes_cannot_reach_into_another_portfolio(client, estate):
    north, south = estate["north"], estate["south"]
    staff = _bearer(_staff("staff", north["portfolio"]))

    unit = client.post("/api/v1/units", headers=staff,
                       json={"property_id": south["property"].id, "label": "Fremd", "unit_type": "residential"})
    assert unit.status_code in (400, 403, 404, 422)      # 400: "the property does not exist" for this account
    assert not [u for u in store.list_units() if u.label == "Fremd"]
    renamed = client.patch(f"/api/v1/properties/{south['property'].id}", headers=staff, json={"name": "Übernommen"})
    assert renamed.status_code in (403, 404)
    moved = client.put(f"/api/v1/units/{north['unit'].id}", headers=staff,
                       json={"property_id": south["property"].id, "label": "WE 3", "unit_type": "residential"})
    assert moved.status_code in (400, 403, 404, 422)
    assert client.delete(f"/api/v1/documents/{south['document'].id}", headers=staff).status_code in (403, 404)

    owner_view = {p.id: p.name for p in store.list_properties()}
    assert owner_view[south["property"].id] == "Bautzner Straße 61"
    assert store.get_unit(north["unit"].id).property_id == north["property"].id
    assert store.get_document(south["document"].id)


def test_records_without_parent_belong_to_the_portfolios_of_their_author(client, estate):
    north, south = estate["north"], estate["south"]
    nora = _bearer(_staff("nora", north["portfolio"]))
    sven = _bearer(_staff("sven", south["portfolio"]))
    created = client.post("/api/v1/contacts", headers=nora,
                          json={"contact_type": "supplier", "company_name": "Heizung Nord GmbH"})
    assert created.status_code in (200, 201), created.text
    contact = created.json()["id"]

    assert contact in _ids(client.get("/api/v1/contacts", headers=nora))
    assert contact not in _ids(client.get("/api/v1/contacts", headers=sven))
    assert client.get(f"/api/v1/contacts/{contact}", headers=sven).status_code == 404
    owner = _bearer(_staff("owner", role="eigentuemer", mode="all"))
    assert contact in _ids(client.get("/api/v1/contacts", headers=owner))


def test_a_changed_assignment_applies_to_the_token_already_issued(client, estate):
    north, south = estate["north"], estate["south"]
    user = _staff("staff", north["portfolio"])
    token = _bearer(user)
    assert _ids(client.get("/api/v1/properties", headers=token)) == {north["property"].id}

    auth.update_user(user.id, {"portfolio_access": "selected", "portfolio_ids": [south["portfolio"].id]})
    assert _ids(client.get("/api/v1/properties", headers=token)) == {south["property"].id}
    auth.update_user(user.id, {"portfolio_access": "selected", "portfolio_ids": []})
    assert _ids(client.get("/api/v1/properties", headers=token)) == set()


def test_an_account_without_portfolios_sees_and_creates_nothing(client, estate):
    nobody = _bearer(_staff("nobody"))
    for path in LISTS:
        assert _ids(client.get(f"/api/v1/{path}?limit=1000", headers=nobody)) == set(), path
    refused = client.post("/api/v1/contacts", headers=nobody, json={"contact_type": "supplier", "company_name": "X"})
    assert refused.status_code == 403


def test_installation_administration_needs_all_portfolios(client, estate):
    staff = _bearer(_staff("staff", estate["north"]["portfolio"], role="verwalter"))
    owner = _bearer(_staff("owner", role="eigentuemer", mode="all"))
    for path in ("/api/v1/audit", "/api/v1/data/export", "/api/v1/diagnostics/health"):
        assert client.get(path, headers=staff).status_code == 403, path
    assert client.get("/api/v1/audit", headers=owner).status_code != 403
    assert client.get("/api/v1/auth/me", headers=staff).status_code == 200


def test_shared_results_are_never_shared_across_portfolio_boundaries(client, estate):
    """Dashboard, reports and current rents keep results for seconds: never for another account's view."""
    owner = _bearer(_staff("owner", role="eigentuemer", mode="all"))
    staff = _bearer(_staff("staff", estate["north"]["portfolio"]))
    south_contract = estate["south"]["contract"].id

    everything = client.get("/api/v1/contracts/current-rents", headers=owner)
    assert everything.status_code == 200 and south_contract in everything.json()
    restricted = client.get("/api/v1/contracts/current-rents", headers=staff).json()
    assert south_contract not in restricted and estate["north"]["contract"].id in restricted

    owner_summary = client.get("/api/v1/dashboard/stats", headers=owner).json()
    staff_summary = client.get("/api/v1/dashboard/stats", headers=staff).json()
    assert owner_summary != staff_summary
    # and the other way round: the restricted result is not handed to the owner
    assert south_contract in client.get("/api/v1/contracts/current-rents", headers=owner).json()
