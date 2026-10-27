"""A restricted account sees and changes the owners only of its portfolios: shares, changes, balances, bookings.

Runs on the memory store and, with TEST_STORE_BACKEND=sql, on SQLite.
"""

from datetime import date

import pytest
from fastapi.testclient import TestClient

from backend import auth
from backend.app import app
from backend.dependencies import store
from backend.models import AccountCreate, BookingCreate, ContactCreate, PortfolioCreate, PropertyCreate, UnitCreate


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


def _bearer(user) -> dict:
    return {"Authorization": f"Bearer {auth.create_access_token(user.id)}"}


@pytest.fixture
def estate(client):
    """Anna and Ben own a house in each of two portfolios; the south house changed hands once."""
    admin = _bearer(auth.register_user("owner", "owner@example.com", "Owner", "Secret123", "eigentuemer",
                                       portfolio_access="all"))
    anna = store.create_contact(ContactCreate(contact_type="owner", first_name="Anna", last_name="Eigen"))
    ben = store.create_contact(ContactCreate(contact_type="owner", first_name="Ben", last_name="Eigen"))
    sides = {}
    for side in ("north", "south"):
        portfolio = store.create_portfolio(PortfolioCreate(name=f"Bestand {side}"))
        prop = store.create_property(PropertyCreate(portfolio_id=portfolio.id, name=f"Haus {side}",
                                                    property_type="residential"))
        unit = store.create_unit(UnitCreate(property_id=prop.id, label=f"WE {side}", unit_type="residential"))
        account = store.create_account(AccountCreate(portfolio_id=portfolio.id, name=f"Konto {side}",
                                                     account_type="bank", opening_balance=100,
                                                     owner_contact_id=anna.id))
        booking = store.create_booking(BookingCreate(account_id=account.id, property_id=prop.id, unit_id=unit.id,
                                                     booking_date=date(2026, 3, 1), amount=1000.0,
                                                     payment_text=f"Miete {side}"))
        share = client.post("/api/v1/ownership-shares", headers=admin, json={
            "owner_contact_id": anna.id, "property_id": prop.id, "share_percent": 100})
        assert share.status_code == 201, share.text
        sides[side] = {"portfolio": portfolio, "property": prop, "unit": unit, "account": account,
                       "booking": booking, "share": share.json()["id"]}
    transfer = client.post("/api/v1/ownership-shares/transfers", headers=admin, json={
        "property_id": sides["south"]["property"].id, "scope": "all", "effective_date": "2026-07-01",
        "from_owner_contact_id": anna.id, "fraction_percent": 50, "kind": "gift",
        "receivers": [{"owner_contact_id": ben.id, "percent": 100}]})
    assert transfer.status_code == 201, transfer.text
    sides["south"]["transfer"] = transfer.json()["id"]
    staff = auth.register_user("staff", "staff@example.com", "Staff", "Secret123", "verwalter",
                               portfolio_access="selected", portfolio_ids=[sides["north"]["portfolio"].id])
    return {**sides, "anna": anna, "ben": ben, "admin": admin, "staff": _bearer(staff)}


def _south_ids(estate) -> list[str]:
    south = estate["south"]
    return [south[key].id for key in ("portfolio", "property", "unit", "account", "booking")] + [south["share"]]


def test_reads_name_only_the_owners_of_the_own_portfolios(client, estate):
    staff, anna, hidden = estate["staff"], estate["anna"], _south_ids(estate)
    for path in ("/ownership-shares", "/ownership-shares/owners", "/ownership-shares/current",
                 f"/ownership-shares/holdings?owner_contact_id={anna.id}", "/accounts/owner-balances",
                 f"/bookings?owner_contact_id={anna.id}", f"/bookings?owner_contact_id={estate['ben'].id}"):
        response = client.get("/api/v1" + path, headers=staff)
        assert response.status_code == 200, (path, response.text)
        assert not [i for i in hidden if i in response.text], path
        assert "Haus south" not in response.text and "Konto south" not in response.text, path
    holdings = client.get(f"/api/v1/ownership-shares/holdings?owner_contact_id={anna.id}", headers=staff).json()
    assert [row["property_name"] for row in holdings["shares"]] == ["Haus north"]
    balances = client.get("/api/v1/accounts/owner-balances", headers=staff).json()
    assert [(row["name"], row["balance"]) for row in balances["owners"]] == [("Anna Eigen", 1100.0)]
    owned = client.get(f"/api/v1/bookings?owner_contact_id={anna.id}", headers=staff).json()
    assert [b["id"] for b in owned] == [estate["north"]["booking"].id]


def test_the_other_portfolio_cannot_be_read_or_changed_by_its_ids(client, estate):
    staff, south = estate["staff"], estate["south"]
    for path in (f"/ownership-shares/overview?property_id={south['property'].id}",
                 f"/ownership-shares/history?property_id={south['property'].id}"):
        assert client.get("/api/v1" + path, headers=staff).status_code in (403, 404), path
    revert = client.post(f"/api/v1/ownership-shares/transfers/{south['transfer']}/revert", headers=staff)
    assert revert.status_code in (403, 404), revert.text
    assert client.put(f"/api/v1/ownership-shares/{south['share']}", headers=staff, json={
        "owner_contact_id": estate["ben"].id, "property_id": south["property"].id,
        "share_percent": 100}).status_code in (403, 404)
    assert client.delete(f"/api/v1/ownership-shares/{south['share']}", headers=staff).status_code in (403, 404)
    # nothing changed: the change is still in force and undoable by an account of that portfolio
    history = client.get(f"/api/v1/ownership-shares/history?property_id={south['property'].id}",
                         headers=estate["admin"]).json()
    assert [(t["reverted_at"], t["revertible"]) for t in history["transfers"]] == [(None, True)]
    undone = client.post(f"/api/v1/ownership-shares/transfers/{south['transfer']}/revert", headers=estate["admin"])
    assert undone.status_code == 200, undone.text


def test_a_restricted_account_keeps_the_owners_of_its_portfolio(client, estate):
    """The owners are address book contacts nobody bound to the portfolio: reading them is enough."""
    staff, north, south, anna = estate["staff"], estate["north"], estate["south"], estate["anna"]
    share = {"owner_contact_id": anna.id, "property_id": north["property"].id, "unit_id": north["unit"].id}
    created = client.post("/api/v1/ownership-shares", headers=staff, json=share | {"share_percent": 40})
    assert created.status_code == 201, created.text
    changed = client.put(f"/api/v1/ownership-shares/{created.json()['id']}", headers=staff,
                         json=share | {"share_percent": 30})
    assert changed.status_code == 200, changed.text
    assert client.delete(f"/api/v1/ownership-shares/{created.json()['id']}", headers=staff).status_code == 204
    # the other portfolio's houses stay out of reach, and so does the contact itself
    refused = client.post("/api/v1/ownership-shares", headers=staff, json={
        "owner_contact_id": anna.id, "property_id": south["property"].id, "share_percent": 10})
    assert refused.status_code in (403, 404), refused.text
    assert client.patch(f"/api/v1/contacts/{anna.id}", headers=staff,
                        json={"last_name": "Fremd"}).status_code in (403, 404)


def test_a_restricted_account_undoes_a_change_in_its_own_portfolio(client, estate):
    staff, north = estate["staff"], estate["north"]
    transfer = client.post("/api/v1/ownership-shares/transfers", headers=staff, json={
        "property_id": north["property"].id, "scope": "all", "effective_date": "2026-07-01",
        "from_owner_contact_id": estate["anna"].id, "fraction_percent": 100, "kind": "purchase",
        "receivers": [{"owner_contact_id": estate["ben"].id, "percent": 100}]})
    assert transfer.status_code == 201, transfer.text
    undone = client.post(f"/api/v1/ownership-shares/transfers/{transfer.json()['id']}/revert", headers=staff)
    assert undone.status_code == 200, undone.text
    shares = client.get(f"/api/v1/ownership-shares?property_id={north['property'].id}", headers=staff).json()
    assert [(s["owner_contact_id"], s["share_percent"], s["valid_to"]) for s in shares] == [
        (estate["anna"].id, 100.0, None)]
