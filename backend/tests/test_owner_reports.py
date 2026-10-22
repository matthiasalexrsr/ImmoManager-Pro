"""Reports by owner: every amount counts with the owner's part, and the owners add up to the whole."""

from datetime import date

import pytest
from fastapi.testclient import TestClient

from backend.app import app
from backend.auth import clear_users, create_access_token, register_user
from backend.dependencies import store
from backend.finance_models import ReportDefinition
from backend.models import ContactPatch
from backend.services import finance_reports
from backend.services.data_snapshot import clear_business_data

API = "/api/v1"
MARCH = "date_from=2026-03-01&date_to=2026-03-31"


@pytest.fixture
def estate():
    """WE 1 (50 m²) Matthias, WE 2 (70 m²) Linda, WE 3 (80 m²) half each; rents 500, 700, 800."""
    clear_business_data(store)
    clear_users()
    client = TestClient(app)
    user = register_user("owner", "owner@example.com", "Owner", "Secret123", "eigentuemer")
    headers = {"Authorization": f"Bearer {create_access_token(user.id)}"}

    def post(path, body):
        response = client.post(API + path, headers=headers, json=body)
        assert response.status_code in (200, 201), response.text
        return response.json()

    def get(path):
        response = client.get(API + path, headers=headers)
        assert response.status_code == 200, response.text
        return response.json()

    def patch(path, body):
        response = client.patch(API + path, headers=headers, json=body)
        assert response.status_code == 200, response.text
        return response.json()

    pf = post("/portfolios", {"name": "P"})["id"]
    house = post("/properties", {"portfolio_id": pf, "name": "Haus", "property_type": "residential"})["id"]
    people = {name: post("/contacts", {"contact_type": "owner", "first_name": name})["id"]
              for name in ("Matthias", "Linda")}
    m, linda = people["Matthias"], people["Linda"]
    units = []
    for n, (area, rent) in enumerate(((50, 500), (70, 700), (80, 800)), start=1):
        unit = post("/units", {"property_id": house, "label": f"WE {n}", "unit_type": "Wohnung", "area_sqm": area,
                               "cold_rent": rent})["id"]
        tenant = post("/tenants", {"full_name": f"Mieter {n}"})["id"]
        post("/contracts", {"contract_number": f"V-{n}", "property_id": house, "unit_id": unit, "tenant_id": tenant,
                            "start_date": "2026-01-01", "cold_rent": rent})
        units.append(unit)
    for owner, unit, percent in ((m, units[0], 100), (linda, units[1], 100), (linda, units[2], 50), (m, units[2], 50)):
        post("/ownership-shares", {"owner_contact_id": owner, "property_id": house, "unit_id": unit,
                                   "share_percent": percent})
    account = post("/accounts", {"portfolio_id": pf, "name": "Konto", "account_type": "bank"})["id"]
    costs = post("/categories", {"portfolio_id": pf, "name": "Kosten", "category_type": "expense"})["id"]
    private = post("/categories", {"portfolio_id": pf, "name": "Entnahmen", "category_type": "private"})["id"]

    def book(amount, **extra):
        return post("/bookings", {"account_id": account, "booking_date": "2026-03-15", "amount": amount,
                                  "status": "booked", **extra})

    book(-200, category_id=costs, property_id=house, payment_text="Gebäudeversicherung")   # 45 % M, 55 % L
    book(-100, category_id=costs, property_id=house, unit_id=units[2], payment_text="Reparatur WE 3")
    book(-10, category_id=costs, payment_text="Kontoführung")                               # nobody recorded
    book(-1000, category_id=private, property_id=house, owner_contact_id=linda, payment_text="Entnahme Linda")
    yield {"get": get, "patch": patch, "post": post, "house": house, "m": m, "linda": linda, "units": units, "pf": pf,
           "account": account, "costs": costs}
    clear_users()
    clear_business_data(store)


def test_the_result_per_owner_adds_up_to_the_result_of_the_house(estate):
    data = estate["get"](f"/reports/owner-results?{MARCH}")
    rows = {row["name"]: row for row in data["owners"]}
    assert set(rows) == {"Matthias", "Linda", "Ohne Eigentümer"}
    assert (rows["Matthias"]["rent_due"], rows["Matthias"]["costs"], rows["Matthias"]["result"]) == (900, 140, 760)
    assert (rows["Linda"]["rent_due"], rows["Linda"]["costs"], rows["Linda"]["result"]) == (1100, 160, 940)
    assert (rows["Ohne Eigentümer"]["costs"], rows["Ohne Eigentümer"]["result"]) == (10, -10)
    assert (rows["Linda"]["withdrawal"], rows["Matthias"]["withdrawal"]) == (1000, 0)
    assert data["totals"]["result"] == 1690 == sum(row["result"] for row in rows.values())


def test_an_owner_named_by_shares_stays_an_owner(estate):
    client = TestClient(app)
    user = register_user("other", "other@example.com", "Other", "Secret123", "eigentuemer")
    headers = {"Authorization": f"Bearer {create_access_token(user.id)}"}
    refused = client.patch(f"{API}/contacts/{estate['linda']}", headers=headers, json={"contact_type": "supplier"})
    assert refused.status_code == 409
    assert "2 Eigentumsanteile, 1 Buchung" in refused.json()["error"]["message"]
    contact = estate["get"](f"/contacts/{estate['linda']}")
    replaced = client.put(f"{API}/contacts/{estate['linda']}", headers=headers, json={**contact, "contact_type": "tenant"})
    assert replaced.status_code == 409
    # other changes and an owner without any entries are free
    estate["patch"](f"/contacts/{estate['linda']}", {"phone": "0351 123"})
    nobody = estate["post"]("/contacts", {"contact_type": "owner", "first_name": "Neu"})["id"]
    assert estate["patch"](f"/contacts/{nobody}", {"contact_type": "supplier"})["contact_type"] == "supplier"


def test_an_owner_whose_contact_type_changed_keeps_their_row(estate):
    # e.g. a restored backup from before the guard: the reports still find the owner by their shares
    store._patch_entity("contact", estate["linda"], ContactPatch(contact_type="supplier"))
    rows = {row["name"]: row for row in estate["get"](f"/reports/owner-results?{MARCH}")["owners"]}
    assert (rows["Linda"]["result"], rows["Linda"]["withdrawal"]) == (940, 1000)
    assert "Linda" in {owner["name"] for owner in estate["get"]("/ownership-shares/owners")}


def test_every_report_takes_the_owner_filter(estate):
    get, m = estate["get"], estate["m"]
    result = get(f"/reports/period-result?{MARCH}&owner_contact_id={m}")
    assert (result["totals"]["rent_due"], result["totals"]["costs"], result["totals"]["result"]) == (900, 140, 760)
    assert result["filters"]["owner_contact_id"] == m
    cash = get(f"/reports/cashflow?{MARCH}&owner_contact_id={estate['linda']}")
    assert (cash["expenseTotal"], cash["withdrawalTotal"]) == (160, 1000)
    nobody = get(f"/reports/cashflow?{MARCH}&owner_contact_id=none")
    assert nobody["expenseTotal"] == 10
    summary = get(f"/reports/summary?owner_contact_id={m}")
    assert summary["totals"] == {"properties": 1, "units": 2, "contracts": 2}
    occupancy = get(f"/reports/occupancy?owner_contact_id={estate['linda']}")
    assert occupancy["totalUnits"] == 2
    # without an owner nothing changes: the filters keep their shape
    assert "owner_contact_id" not in get(f"/reports/period-result?{MARCH}")["filters"]


def test_the_finance_reports_carry_the_owners_parts(estate):
    m = estate["m"]
    performance = finance_reports.compute(store, ReportDefinition(
        kind="performance-period-v2", as_of=date(2026, 12, 31), date_from=date(2026, 3, 1), date_to=date(2026, 3, 31),
        owner_contact_id=m))
    assert (performance["totals"]["rent_due"], performance["totals"]["costs"], performance["totals"]["result"]) == (
        "900.00", "140.00", "760.00")
    assert performance["definition"]["owner_contact_id"] == m
    cash = finance_reports.compute(store, ReportDefinition(
        kind="cash-v2", as_of=date(2026, 3, 31), date_from=date(2026, 3, 1), owner_contact_id=estate["linda"]))
    assert sorted(source["amount"] for source in cash["sources"]) == ["-1000.00", "-110.00", "-50.00"]
    forecast = finance_reports.compute(store, ReportDefinition(kind="liquidity-v2", as_of=date(2026, 3, 31),
                                                               months=3, owner_contact_id=m))
    # no account opening balances for an owner; Matthias' part of the bookings so far
    assert not [s for s in forecast["opening_sources"] if s["identity"].startswith("account-opening:")]
    assert forecast["opening_balance"] == "-140.00"
    plain = finance_reports.compute(store, ReportDefinition(kind="cash-v2", as_of=date(2026, 3, 31),
                                                            date_from=date(2026, 3, 1)))
    assert "owner_contact_id" not in plain["definition"]


def test_budgets_split_by_the_owners_part_of_the_house(estate):
    from backend.models import BudgetCreate
    budget = store.create_budget(BudgetCreate(property_id=estate["house"], year=2026, category="maintenance",
                                              planned_amount=1000, actual_amount=200))
    whole = estate["get"]("/budgets/analysis?year=2026")
    mine = estate["get"](f"/budgets/analysis?year=2026&owner_contact_id={estate['m']}")
    hers = estate["get"](f"/budgets/analysis?year=2026&owner_contact_id={estate['linda']}")
    # WE 1 (50 m²) Matthias, WE 3 (80 m²) half: 45 % of the house
    assert (mine["total_planned"], mine["total_actual"]) == (450, 90)
    assert (hers["total_planned"], hers["total_actual"]) == (550, 110)
    assert whole["total_planned"] == mine["total_planned"] + hers["total_planned"]
    assert [row["id"] for row in mine["by_category"]] == [budget.id]


def test_the_review_list_names_units_without_an_owner(estate):
    from backend.models import UnitCreate
    store.create_unit(UnitCreate(property_id=estate["house"], label="WE 4", unit_type="Wohnung", area_sqm=40))
    items = [item for item in estate["get"]("/review")["items"] if item["kind"] == "ownership_incomplete"]
    assert len(items) == 1 and "WE 4: 100 % ohne Eigentümer" in items[0]["detail"]


def test_the_bookings_list_shows_an_owners_bookings_with_their_part(estate):
    parts = lambda owner: sorted((b["payment_text"], b["owner_part"]) for b in estate["get"](f"/bookings?owner_contact_id={owner}"))  # noqa: E731
    assert parts(estate["linda"]) == [("Entnahme Linda", -1000), ("Gebäudeversicherung", -110), ("Reparatur WE 3", -50)]
    assert parts(estate["m"]) == [("Gebäudeversicherung", -90), ("Reparatur WE 3", -50)]
    assert parts("none") == [("Kontoführung", -10)]
    # every booking's parts add up to the booking
    everything = {b["id"]: b["amount"] for b in estate["get"]("/bookings")}
    added: dict[str, float] = {}
    for owner in (estate["linda"], estate["m"], "none"):
        for b in estate["get"](f"/bookings?owner_contact_id={owner}"):
            added[b["id"]] = round(added.get(b["id"], 0) + b["owner_part"], 2)
    assert added == everything



def test_account_balances_by_owner_add_up_and_an_owners_account_brings_its_opening_balance(estate):
    post, get = estate["post"], estate["get"]
    # Linda's own account with 500 € opening balance and the rent of WE 2 (100 % hers)
    own = post("/accounts", {"portfolio_id": estate["pf"], "name": "Konto Linda", "account_type": "bank",
                             "opening_balance": 500, "owner_contact_id": estate["linda"]})
    post("/bookings", {"account_id": own["id"], "booking_date": "2026-03-20", "amount": 700, "status": "booked",
                       "property_id": estate["house"], "unit_id": estate["units"][1], "payment_text": "Miete WE 2"})
    data = get("/accounts/owner-balances?as_of=2026-03-31")
    rows = {row["name"]: row for row in data["owners"]}
    # joint account: -200 (insurance 90/110), -100 (WE 3 50/50), -10 (nobody), -1000 (Linda alone)
    assert rows["Linda"]["balance"] == 500 + 700 - 110 - 50 - 1000
    assert rows["Matthias"]["balance"] == -90 - 50
    assert rows["Ohne Eigentümer"]["balance"] == -10
    accounts = {row["name"]: row["balance"] for row in data["accounts"]}
    assert accounts == {"Konto": -1310, "Konto Linda": 1200}
    assert sum(row["balance"] for row in data["owners"]) == sum(accounts.values())
    # the report per owner: the same balances at the period's end
    results = {row["name"]: row["balance"] for row in get(f"/reports/owner-results?{MARCH}")["owners"]}
    assert results == {"Linda": 40, "Matthias": -140, "Ohne Eigentümer": -10}


def test_an_account_holder_must_be_an_owner(estate):
    supplier = estate["post"]("/contacts", {"contact_type": "supplier", "company_name": "Handwerk GmbH"})
    with pytest.raises(AssertionError, match="Kontoinhaber"):
        estate["post"]("/accounts", {"portfolio_id": estate["pf"], "name": "X", "account_type": "bank",
                                     "owner_contact_id": supplier["id"]})


def test_an_owners_data_access_export_and_anonymization(estate):
    linda = estate["linda"]
    estate["patch"](f"/contacts/{linda}", {"last_name": "Reiser", "email": "linda@example.de", "iban": "DE02120300000000202051"})
    estate["post"]("/accounts", {"portfolio_id": estate["pf"], "name": "Konto Linda", "account_type": "bank",
                                 "owner_contact_id": linda})
    export = estate["get"](f"/admin/dsgvo/contact/{linda}/export")
    assert export["contact"]["email"] == "linda@example.de"
    assert (len(export["ownership_shares"]), len(export["bookings"]), len(export["accounts"])) == (2, 1, 1)
    assert export["bookings"][0]["payment_text"] == "Entnahme Linda"
    answer = estate["post"](f"/admin/dsgvo/contact/{linda}/anonymize", {})
    assert answer["retained_records"] == {"ownership_shares": 2, "bookings": 1, "accounts": 1}
    contact = estate["get"](f"/contacts/{linda}")
    assert (contact["first_name"], contact["email"], contact["iban"]) == (None, None, None)
    assert contact["last_name"] == f"Anonymisiert-{linda[:8]}" and contact["contact_type"] == "owner"
    # the shares keep counting, now for the placeholder
    rows = {row["name"]: row for row in estate["get"](f"/reports/owner-results?{MARCH}")["owners"]}
    assert rows[f"Anonymisiert-{linda[:8]}"]["result"] == 940 and "Linda" not in rows
