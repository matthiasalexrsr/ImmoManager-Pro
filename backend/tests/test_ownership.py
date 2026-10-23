"""Owners' shares of properties and units, and how amounts are split among them."""

from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from backend.app import app
from backend.auth import clear_users, create_access_token, register_user
from backend.dependencies import store
from backend.services.data_snapshot import clear_business_data
from backend.services.ownership import Ownership

API = "/api/v1"


@pytest.fixture
def estate():
    clear_business_data(store)
    clear_users()
    client = TestClient(app)
    user = register_user("owner", "owner@example.com", "Owner", "Secret123", "eigentuemer")
    headers = {"Authorization": f"Bearer {create_access_token(user.id)}"}

    def call(method, path, body=None, expected=(200, 201)):
        response = client.request(method, API + path, headers=headers, json=body)
        assert response.status_code in (expected if isinstance(expected, tuple) else (expected,)), response.text
        return response.json() if response.content else None

    def post(path, body, expected=(200, 201)):
        return call("POST", path, body, expected)

    pf = post("/portfolios", {"name": "P"})["id"]
    house = post("/properties", {"portfolio_id": pf, "name": "Haus", "property_type": "residential"})["id"]
    other = post("/properties", {"portfolio_id": pf, "name": "Anderes Haus", "property_type": "residential"})["id"]
    units = [post("/units", {"property_id": house, "label": f"WE {n}", "unit_type": "Wohnung", "area_sqm": area})["id"]
             for n, area in ((1, 50), (2, 70), (3, 80))]
    people = {name: post("/contacts", {"contact_type": "owner", "first_name": name})["id"]
              for name in ("Matthias", "Linda", "Sebastian")}
    tenant_contact = post("/contacts", {"contact_type": "tenant", "first_name": "Mieterin"})["id"]
    yield {"call": call, "post": post, "house": house, "other": other, "units": units, "people": people,
           "tenant_contact": tenant_contact}
    clear_users()
    clear_business_data(store)


def said(body):
    """The message of an error response."""
    return body["error"]["message"] if "error" in body else str(body["detail"])


def share(estate, owner, percent, unit=None, prop=None, **extra):
    return {"owner_contact_id": estate["people"][owner], "property_id": prop or estate["house"],
            "unit_id": unit, "share_percent": percent, **extra}


def test_units_of_one_house_belong_to_different_owners_and_the_common_costs_follow_the_areas(estate):
    post, (we1, we2, we3) = estate["post"], estate["units"]
    post("/ownership-shares", share(estate, "Matthias", 100, we1))
    post("/ownership-shares", share(estate, "Linda", 100, we2))
    post("/ownership-shares", share(estate, "Linda", 50, we3))
    post("/ownership-shares", share(estate, "Matthias", 50, we3))
    owners = Ownership(store)
    day = date(2026, 3, 1)
    m, linda = estate["people"]["Matthias"], estate["people"]["Linda"]
    assert owners.split(1000, estate["house"], we1, day) == {m: Decimal("1000.00")}
    assert owners.split(1000, estate["house"], we3, day) == {linda: Decimal("500.00"), m: Decimal("500.00")}
    # building insurance of the house: WE 1 50 m², WE 2 70 m², WE 3 80 m² (half each)
    assert owners.split(200, estate["house"], None, day) == {linda: Decimal("110.00"), m: Decimal("90.00")}
    overview = estate["call"]("GET", f"/ownership-shares/overview?property_id={estate['house']}&as_of=2026-03-01")
    assert overview["common_basis"] == "area"
    assert [(row["name"], row["percent"]) for row in overview["common"]] == [("Linda", 55.0), ("Matthias", 45.0)]
    assert [unit["basis"] for unit in overview["units"]] == ["unit", "unit", "unit"]


def test_a_property_owned_by_one_owner_and_the_parts_add_up_to_the_cent(estate):
    post = estate["post"]
    post("/ownership-shares", share(estate, "Sebastian", 100, prop=estate["other"]))
    for owner in ("Matthias", "Linda", "Sebastian"):
        post("/ownership-shares", share(estate, owner, 33.3333))
    owners = Ownership(store)
    day = date(2026, 3, 1)
    assert owners.split(-500, estate["other"], None, day) == {estate["people"]["Sebastian"]: Decimal("-500.00")}
    parts = owners.split(100, estate["house"], estate["units"][0], day)     # the unit follows its house
    assert sum(parts.values()) == Decimal("100.00") and parts[None] == Decimal("0.00")
    assert sorted(parts[estate["people"][o]] for o in ("Matthias", "Linda", "Sebastian")) == [
        Decimal("33.33"), Decimal("33.33"), Decimal("33.34")]
    # nobody recorded for a house without shares, and for money of no house at all
    assert Ownership(store).split(10, None, None, day) == {None: Decimal("10.00")}


def test_an_owner_changes_on_a_day(estate):
    post, house = estate["post"], estate["house"]
    post("/ownership-shares", share(estate, "Matthias", 100, valid_to="2026-06-30"))
    post("/ownership-shares", share(estate, "Sebastian", 100, valid_from="2026-07-01"))
    owners = Ownership(store)
    assert owners.split(10, house, None, date(2026, 6, 30)) == {estate["people"]["Matthias"]: Decimal("10.00")}
    assert owners.split(10, house, None, date(2026, 7, 1)) == {estate["people"]["Sebastian"]: Decimal("10.00")}


def test_shares_over_100_percent_and_other_mistakes_are_refused(estate):
    post, (we1, *_rest) = estate["post"], estate["units"]
    post("/ownership-shares", share(estate, "Matthias", 60, valid_from="2026-01-01"))
    refused = said(post("/ownership-shares", share(estate, "Linda", 50, valid_from="2026-04-01"), expected=409))
    assert "am 01.04.2026 zusammen 110 %" in refused
    assert "schon einen Anteil" in said(post("/ownership-shares", share(estate, "Matthias", 10), expected=409))
    post("/ownership-shares", share(estate, "Linda", 40))                    # 60 + 40 = 100 is fine
    tenant = {**share(estate, "Linda", 10, prop=estate["other"]), "owner_contact_id": estate["tenant_contact"]}
    assert "Eigentümer" in said(post("/ownership-shares", tenant, expected=422))
    assert "gehört nicht" in said(post("/ownership-shares", share(estate, "Linda", 10, we1, prop=estate["other"]),
                                       expected=422))
    post("/ownership-shares", share(estate, "Linda", 10, valid_from="2026-05-01", valid_to="2026-04-01"), expected=422)
    post("/ownership-shares", share(estate, "Linda", 0), expected=422)
    post("/ownership-shares", share(estate, "Linda", 12.34567), expected=422)


def test_shares_can_be_changed_and_keep_the_owners_from_being_deleted(estate):
    call, post, (we1, *_rest) = estate["call"], estate["post"], estate["units"]
    created = post("/ownership-shares", share(estate, "Matthias", 100, we1))
    changed = call("PUT", f"/ownership-shares/{created['id']}", share(estate, "Matthias", 75, we1))
    assert changed["share_percent"] == 75
    assert [row["share_percent"] for row in call("GET", f"/ownership-shares?unit_id={we1}")] == [75]
    assert "Eigentumsanteil" in said(call("DELETE", f"/contacts/{estate['people']['Matthias']}", expected=409))
    assert "Eigentumsanteil" in said(call("DELETE", f"/units/{we1}", expected=409))
    owners = call("GET", "/ownership-shares/owners")
    assert [(o["name"], o["shares"]) for o in owners] == [("Linda", 0), ("Matthias", 1), ("Sebastian", 0)]
    call("DELETE", f"/ownership-shares/{created['id']}", expected=204)
    call("DELETE", f"/contacts/{estate['people']['Matthias']}", expected=204)


def test_a_booking_belongs_to_one_owner_and_its_reversal_too(estate):
    post, call = estate["post"], estate["call"]
    pf = call("GET", "/portfolios")[0]["id"]
    account = post("/accounts", {"portfolio_id": pf, "name": "Konto", "account_type": "bank"})["id"]
    post("/bookings", {"account_id": account, "booking_date": "2026-03-01", "amount": -100,
                       "owner_contact_id": estate["tenant_contact"]}, expected=422)
    withdrawal = post("/bookings", {"account_id": account, "property_id": estate["house"], "booking_date": "2026-03-01",
                                    "amount": -100, "owner_contact_id": estate["people"]["Linda"]})
    assert Ownership(store).booking_split(store.get_booking(withdrawal["id"])) == {
        estate["people"]["Linda"]: Decimal("-100.00")}
    reversal = post(f"/bookings/{withdrawal['id']}/reverse", {"amount": 40})
    assert reversal["owner_contact_id"] == estate["people"]["Linda"]
    assert "Buchung" in said(call("DELETE", f"/contacts/{estate['people']['Linda']}", expected=409))
