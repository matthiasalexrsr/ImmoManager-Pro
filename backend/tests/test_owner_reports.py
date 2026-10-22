"""Reports by owner: every amount counts with the owner's part, and the owners add up to the whole."""

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
    yield {"get": get, "house": house, "m": m, "linda": linda, "units": units}
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
