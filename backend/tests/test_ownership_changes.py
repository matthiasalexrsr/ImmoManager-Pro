"""Owners change: sale, division, inheritance; and every calculation follows the owners of each day."""

from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from backend.app import app
from backend.auth import clear_users, create_access_token, register_user
from backend.dependencies import store
from backend.services.data_snapshot import clear_business_data
from backend.services.ownership import Ownership, list_shares

API = "/api/v1"


def said(body):
    return body["error"]["message"] if "error" in body else str(body["detail"])


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
    units = {f"WE {n}": post("/units", {"property_id": house, "label": f"WE {n}", "unit_type": "Wohnung",
                                        "area_sqm": area})["id"] for n, area in ((1, 50), (2, 70), (3, 80))}
    people = {name: post("/contacts", {"contact_type": "owner", "first_name": name})["id"]
              for name in ("Matthias", "Linda", "Sebastian", "Sabine", "Richard")}

    def share(owner, percent, unit=None, prop=None, **extra):
        return post("/ownership-shares", {"owner_contact_id": people[owner], "property_id": prop or house,
                                          "unit_id": units.get(unit), "share_percent": percent, **extra})

    def transfer(giver, receivers, day, unit=None, prop=None, expected=(201,), **extra):
        return post("/ownership-shares/transfers", {
            "property_id": prop or house, "unit_id": units.get(unit), "effective_date": day,
            "from_owner_contact_id": people[giver],
            "receivers": [{"owner_contact_id": people[name], "percent": percent} for name, percent in receivers],
            **extra}, expected)

    yield {"call": call, "post": post, "share": share, "transfer": transfer, "house": house, "other": other,
           "units": units, "people": people, "pf": pf}
    clear_users()
    clear_business_data(store)


def held(estate, unit=None, prop=None):
    """(owner, percent, from, to) of the shares of one property or unit."""
    names = {value: key for key, value in estate["people"].items()}
    rows = [s for s in list_shares(store, property_id=prop or estate["house"]) if s.unit_id == estate["units"].get(unit)]
    return sorted((names[s.owner_contact_id], s.share_percent, s.valid_from and s.valid_from.isoformat(),
                   s.valid_to and s.valid_to.isoformat()) for s in rows)


def owners_on(estate, day, unit=None, prop=None):
    names = {value: key for key, value in estate["people"].items()}
    weights = Ownership(store).weights(prop or estate["house"], estate["units"].get(unit), day)
    return {names.get(owner, "nobody"): float(percent) for owner, percent in weights.items() if percent}


def test_matthias_sells_everything_to_linda_and_the_month_of_the_sale_is_split_by_days(estate):
    estate["share"]("Matthias", 100, "WE 1")
    sale = estate["transfer"]("Matthias", [("Linda", 100)], "2026-07-16", "WE 1", kind="purchase", note="Notarvertrag")
    assert held(estate, "WE 1") == [("Linda", 100, "2026-07-16", None), ("Matthias", 100, None, "2026-07-15")]
    assert owners_on(estate, date(2026, 7, 15), "WE 1") == {"Matthias": 100}
    assert owners_on(estate, date(2026, 7, 16), "WE 1") == {"Linda": 100}
    # July's rent: 15 days Matthias, 16 days Linda
    parts = Ownership(store).split_period(1000, estate["house"], estate["units"]["WE 1"], date(2026, 7, 1), date(2026, 7, 31))
    m, linda = estate["people"]["Matthias"], estate["people"]["Linda"]
    assert parts == {linda: Decimal("516.13"), m: Decimal("483.87")}
    assert sale["kind"] == "purchase" and sale["receivers"] == [{"owner_contact_id": linda, "percent": 100}]
    # the rent due follows: a contract of WE 1 at 1,000 € in July
    post = estate["post"]
    estate["call"]("PATCH", f"/units/{estate['units']['WE 1']}", {"cold_rent": 1000})
    tenant = post("/tenants", {"full_name": "Mieter"})["id"]
    post("/contracts", {"contract_number": "V-1", "property_id": estate["house"], "unit_id": estate["units"]["WE 1"],
                        "tenant_id": tenant, "start_date": "2026-01-01", "cold_rent": 1000})
    rows = {row["name"]: row for row in estate["call"]("GET", "/reports/owner-results?date_from=2026-07-01&date_to=2026-07-31")["owners"]}
    assert (rows["Matthias"]["rent_due"], rows["Linda"]["rent_due"]) == (483.87, 516.13)


def test_sebastian_shares_his_house_with_linda_half_and_half_and_the_budget_year_is_split(estate):
    estate["share"]("Sebastian", 100, prop=estate["other"])
    estate["transfer"]("Sebastian", [("Linda", 100)], "2026-04-01", prop=estate["other"], fraction_percent=50, kind="division")
    assert held(estate, prop=estate["other"]) == [("Linda", 50, "2026-04-01", None), ("Sebastian", 50, "2026-04-01", None),
                                                 ("Sebastian", 100, None, "2026-03-31")]
    assert owners_on(estate, date(2026, 5, 1), prop=estate["other"]) == {"Sebastian": 50, "Linda": 50}
    from backend.models import BudgetCreate
    store.create_budget(BudgetCreate(property_id=estate["other"], year=2026, category="maintenance", planned_amount=1000))
    get = lambda owner: estate["call"]("GET", f"/budgets/analysis?year=2026&owner_contact_id={estate['people'][owner]}")  # noqa: E731
    # 90 days alone, 275 days half: 227.5 / 365 of the year for Sebastian
    assert (get("Sebastian")["total_planned"], get("Linda")["total_planned"]) == (623.29, 376.71)


def test_two_heirs_pass_their_halves_to_linda_on_one_day(estate):
    estate["share"]("Sabine", 50, "WE 2")
    estate["share"]("Richard", 50, "WE 2")
    for heir in ("Sabine", "Richard"):
        estate["transfer"](heir, [("Linda", 100)], "2026-09-01", "WE 2", kind="inheritance")
    assert held(estate, "WE 2") == [("Linda", 100, "2026-09-01", None), ("Richard", 50, None, "2026-08-31"),
                                    ("Sabine", 50, None, "2026-08-31")]
    history = estate["call"]("GET", f"/ownership-shares/history?property_id={estate['house']}")
    we2 = next(o for o in history["objects"] if o["label"] == "WE 2")
    assert [(p["from"], p["to"], [(o["name"], o["percent"]) for o in p["owners"]]) for p in we2["periods"]] == [
        (None, "2026-08-31", [("Richard", 50.0), ("Sabine", 50.0)]), ("2026-09-01", None, [("Linda", 100.0)])]
    assert [(t["kind_label"], t["from_name"]) for t in history["transfers"]] == [("Erbschaft", "Sabine"), ("Erbschaft", "Richard")]


def test_richard_sells_to_linda_and_matthias_who_already_holds_half(estate):
    estate["share"]("Richard", 50, "WE 3")
    estate["share"]("Matthias", 50, "WE 3")
    estate["transfer"]("Richard", [("Linda", 50), ("Matthias", 50)], "2026-10-01", "WE 3")
    assert held(estate, "WE 3") == [("Linda", 25, "2026-10-01", None), ("Matthias", 50, None, "2026-09-30"),
                                    ("Matthias", 75, "2026-10-01", None), ("Richard", 50, None, "2026-09-30")]
    assert owners_on(estate, date(2026, 10, 1), "WE 3") == {"Matthias": 75, "Linda": 25}


def test_everything_an_owner_holds_in_a_house_changes_hands_at_once(estate):
    estate["share"]("Matthias", 100, "WE 1")
    estate["share"]("Matthias", 50, "WE 3")
    estate["share"]("Linda", 50, "WE 3")
    estate["transfer"]("Matthias", [("Sebastian", 100)], "2026-02-01", scope="all", kind="gift")
    assert owners_on(estate, date(2026, 2, 1), "WE 1") == {"Sebastian": 100}
    assert owners_on(estate, date(2026, 2, 1), "WE 3") == {"Linda": 50, "Sebastian": 50}
    assert owners_on(estate, date(2026, 1, 31), "WE 3") == {"Linda": 50, "Matthias": 50}


def test_changes_that_do_not_fit_are_refused(estate):
    estate["share"]("Matthias", 100, "WE 1")
    transfer = estate["transfer"]
    assert "keinen Anteil" in said(transfer("Linda", [("Sebastian", 100)], "2026-07-01", "WE 1", expected=409))
    assert "Alle Anteile am Objekt" in said(transfer("Matthias", [("Linda", 100)], "2026-07-01", expected=409))
    transfer("Matthias", [("Linda", 100)], "2026-07-01", "WE 1")
    # an earlier change after a later one would rewrite history
    assert "der Reihe nach" in said(transfer("Matthias", [("Sebastian", 100)], "2026-03-01", "WE 1", expected=409))
    assert "100 %" in said(transfer("Linda", [("Sebastian", 60), ("Matthias", 30)], "2026-08-01", "WE 1", expected=422))
    assert "zugleich Empfänger" in said(transfer("Linda", [("Linda", 100)], "2026-08-01", "WE 1", expected=422))
    # a sale to someone outside: the part belongs to nobody recorded from that day
    transfer("Linda", [], "2026-12-01", "WE 1", kind="sale_external")
    assert owners_on(estate, date(2026, 12, 1), "WE 1") == {"nobody": 100}
    assert "Eigentümerwechsel" in said(estate["call"]("DELETE", f"/contacts/{estate['people']['Linda']}", expected=409))


def test_the_latest_change_can_be_undone_while_its_shares_are_untouched(estate):
    call = estate["call"]
    estate["share"]("Richard", 50, "WE 3")
    estate["share"]("Matthias", 50, "WE 3")
    first = estate["transfer"]("Richard", [("Linda", 50), ("Matthias", 50)], "2026-10-01", "WE 3")
    second = estate["transfer"]("Linda", [("Sabine", 100)], "2026-11-01", "WE 3")
    # only the latest change can be undone
    assert "letzten Wechsel" in said(call("POST", f"/ownership-shares/transfers/{first['id']}/revert", expected=409))
    history = call("GET", f"/ownership-shares/history?property_id={estate['house']}")
    assert [(t["id"] == second["id"], t["revertible"]) for t in history["transfers"]] == [(False, False), (True, True)]
    call("POST", f"/ownership-shares/transfers/{second['id']}/revert")
    assert held(estate, "WE 3") == [("Linda", 25, "2026-10-01", None), ("Matthias", 50, None, "2026-09-30"),
                                    ("Matthias", 75, "2026-10-01", None), ("Richard", 50, None, "2026-09-30")]
    call("POST", f"/ownership-shares/transfers/{first['id']}/revert")
    assert held(estate, "WE 3") == [("Matthias", 50, None, None), ("Richard", 50, None, None)]
    assert owners_on(estate, date(2026, 12, 1), "WE 3") == {"Matthias": 50, "Richard": 50}
    # the journal keeps both, marked as undone
    journal = call("GET", f"/ownership-shares/history?property_id={estate['house']}")["transfers"]
    assert all(t["reverted_at"] for t in journal) and not any(t["revertible"] for t in journal)
    assert "schon rückgängig" in said(call("POST", f"/ownership-shares/transfers/{first['id']}/revert", expected=409))


def test_a_change_whose_shares_were_edited_by_hand_is_not_undone(estate):
    call = estate["call"]
    estate["share"]("Matthias", 100, "WE 1")
    sale = estate["transfer"]("Matthias", [("Linda", 100)], "2026-07-16", "WE 1")
    linda = next(s for s in list_shares(store, property_id=estate["house"]) if s.owner_contact_id == estate["people"]["Linda"])
    call("PUT", f"/ownership-shares/{linda.id}", {"owner_contact_id": linda.owner_contact_id, "property_id": linda.property_id,
                                                 "unit_id": linda.unit_id, "share_percent": 90, "valid_from": "2026-07-16"})
    assert "von Hand" in said(call("POST", f"/ownership-shares/transfers/{sale['id']}/revert", expected=409))


def test_two_heirs_on_one_day_are_undone_one_after_the_other(estate):
    call = estate["call"]
    estate["share"]("Sabine", 50, "WE 2")
    estate["share"]("Richard", 50, "WE 2")
    firsts = [estate["transfer"](heir, [("Linda", 100)], "2026-09-01", "WE 2", kind="inheritance") for heir in ("Sabine", "Richard")]
    call("POST", f"/ownership-shares/transfers/{firsts[1]['id']}/revert")
    assert held(estate, "WE 2") == [("Linda", 50, "2026-09-01", None), ("Richard", 50, None, None),
                                    ("Sabine", 50, None, "2026-08-31")]
    call("POST", f"/ownership-shares/transfers/{firsts[0]['id']}/revert")
    assert held(estate, "WE 2") == [("Richard", 50, None, None), ("Sabine", 50, None, None)]


def test_a_restored_backup_keeps_account_holders_and_owner_changes_with_their_undo(estate):
    from backend.services.data_snapshot import export_snapshot, import_snapshot

    call = estate["call"]
    estate["share"]("Richard", 100, "WE 1")
    account = estate["post"]("/accounts", {"portfolio_id": estate["pf"], "name": "Konto Richard", "account_type": "bank",
                                           "owner_contact_id": estate["people"]["Richard"]})
    first = estate["transfer"]("Richard", [("Linda", 100)], "2026-10-01", "WE 1")
    second = estate["transfer"]("Linda", [("Sabine", 100)], "2026-11-01", "WE 1")
    call("POST", f"/ownership-shares/transfers/{second['id']}/revert")
    snapshot = export_snapshot(store)
    import_snapshot(store, snapshot, replace=True)
    assert call("GET", f"/accounts/{account['id']}")["owner_contact_id"] == estate["people"]["Richard"]
    journal = {t["id"]: t for t in call("GET", f"/ownership-shares/history?property_id={estate['house']}")["transfers"]}
    assert journal[second["id"]]["reverted_at"] and not journal[second["id"]]["revertible"]
    assert journal[first["id"]]["revertible"]
    # the restored change still knows what it did, so it can be undone
    call("POST", f"/ownership-shares/transfers/{first['id']}/revert")
    assert held(estate, "WE 1") == [("Richard", 100, None, None)]
