"""The owners' own money: withdrawals (distributions) and contributions of private means.

A category of type "private" moves the account balance but is neither income nor expense: no
result, cost or budget counts it, the cash view reports it beside income and expenses.
"""

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


@pytest.fixture
def estate():
    clear_business_data(store)
    clear_users()
    client = TestClient(app)
    user = register_user("owner", "owner@example.com", "Owner", "Secret123", "eigentuemer")
    headers = {"Authorization": f"Bearer {create_access_token(user.id)}"}

    def post(path, body):
        response = client.post(API + path, headers=headers, json=body)
        assert response.status_code == 201, response.text
        return response.json()

    pf = post("/portfolios", {"name": "P"})["id"]
    house = post("/properties", {"portfolio_id": pf, "name": "Haus", "property_type": "residential"})["id"]
    account = post("/accounts", {"portfolio_id": pf, "name": "Konto", "account_type": "bank", "opening_balance": 1000})
    rent = post("/categories", {"portfolio_id": pf, "name": "Sonstige Einnahme", "category_type": "income"})["id"]
    repairs = post("/categories", {"portfolio_id": pf, "name": "Reparaturen", "category_type": "expense"})["id"]
    owner = post("/categories", {"portfolio_id": pf, "name": "Ausschüttung / Einlage", "category_type": "private"})["id"]

    def book(day, amount, category, **extra):
        return post("/bookings", {"account_id": account["id"], "booking_date": day, "amount": amount,
                                  "category_id": category, "status": "booked", "property_id": house, **extra})

    book("2026-03-02", 1200, rent)
    book("2026-03-05", -200, repairs)
    book("2026-03-31", -500, owner, payment_text="Ausschüttung an die Eigentümer")
    wrong = book("2026-04-01", -100, owner, payment_text="Entnahme, falsch gebucht")
    book("2026-04-02", 100, owner, reverses_booking_id=wrong["id"])
    book("2026-04-15", 300, owner, payment_text="Einlage aus Privatmitteln für die Heizung")
    yield {"client": client, "headers": headers, "account": account["id"], "house": house, "owner": owner}
    clear_users()
    clear_business_data(store)


def get(estate, path):
    response = estate["client"].get(API + path, headers=estate["headers"])
    assert response.status_code == 200, response.text
    return response.json()


def test_owner_money_moves_the_balance_but_is_no_income_or_expense(estate):
    cash = get(estate, "/reports/cashflow?date_from=2026-01-01&date_to=2026-12-31")
    assert (cash["incomeTotal"], cash["expenseTotal"], cash["netTotal"]) == (1200, 200, 1000)
    # the reversal nets the wrong withdrawal; it is no contribution
    assert (cash["withdrawalTotal"], cash["contributionTotal"]) == (500, 300)
    april = next(month for month in cash["monthly"] if month["month"] == "2026-04")
    assert (april["withdrawal"], april["contribution"], april["net"]) == (0, 300, 0)

    # the account holds all of it: 1000 + 1200 - 200 - 500 - 100 + 100 + 300
    assert get(estate, f"/accounts/{estate['account']}")["balance"] == 1800


def test_the_result_and_the_reports_leave_owner_money_out(estate):
    result = get(estate, "/reports/period-result?date_from=2026-03-01&date_to=2026-04-30")["totals"]
    assert (result["other_income"], result["costs"], result["unassigned_income"]) == (1200, 200, 0)

    definition = ReportDefinition(kind="performance-period-v2", as_of=date(2026, 12, 31),
                                  date_from=date(2026, 1, 1), date_to=date(2026, 12, 31))
    performance = finance_reports.compute(store, definition)
    assert (performance["totals"]["other_income"], performance["totals"]["costs"]) == ("1200.00", "200.00")

    cash = finance_reports.compute(store, ReportDefinition(kind="cash-v2", as_of=date(2026, 12, 31),
                                                           date_from=date(2026, 1, 1)))
    assert cash["totals"] == {"income": "1200.00", "expense": "200.00", "net": "1000.00",
                              "withdrawal": "500.00", "contribution": "300.00"}


def test_owner_money_is_no_budget_spending(estate):
    response = estate["client"].post(f"{API}/budgets", headers=estate["headers"], json={
        "property_id": estate["house"], "year": 2026, "category": "other", "planned_amount": 100,
        "booking_category_ids": [estate["owner"]]})
    assert response.status_code == 400 and "keine Ausgabenkategorie" in response.text
