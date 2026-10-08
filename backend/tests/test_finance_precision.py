"""Finance figures in exact cents: cash view, period result and forecast kept apart, same filters
everywhere, reversals netted, partial payments and credits counted once.

Runs on the memory store and, with TEST_STORE_BACKEND=sql, on SQLite (PostgreSQL in
test_finance_precision_postgres.py). Expected values are worked out by hand in the comments.
"""

import math
from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from backend import auth
from backend.app import app
from backend.dependencies import store
from backend.domain.money import as_number, money, money_sum
from backend.models import (
    AccountCreate,
    BookingCreate,
    CategoryCreate,
    ContractCreate,
    InvoiceCreate,
    PortfolioCreate,
    PropertyCreate,
    TenantCreate,
    UnitCreate,
)
from backend.routers import reports
from backend.services import report_service
from backend.services.finance_ledger import FinanceFilter, booking_totals
from backend.services.payment_allocations import auto_allocate, credited_by_tenant, mirror_allocation, tenant_account

PERIOD = {"date_from": "2026-01-01", "date_to": "2026-05-31"}


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


def _owner() -> dict:
    return _bearer(auth.register_user("owner", "owner@example.com", "Owner", "Secret123", "eigentuemer"))


def _book(account, day, amount, **fields):
    """A booking as the API books it: tenant payments are credited to contracts."""
    booking = store.create_booking(BookingCreate(account_id=account.id, booking_date=date.fromisoformat(day),
                                                 amount=amount, status="booked", **fields))
    auto_allocate(store, booking)
    return booking


@pytest.fixture
def estate(client):
    """North: house A (flats A1 and A2), South: house B (flat B1); January to April 2026.

    A1: 500.00 + 100.00 + 33.33 = 633.33 a month from January (tenant Tom).
    A2: 400.00 + 50.00 = 450.00 a month from 15 February (Tina): February 14/28 = 225.00.
    B1: 700.00 a month from January (Sven).
    """
    north = store.create_portfolio(PortfolioCreate(name="Nord"))
    south = store.create_portfolio(PortfolioCreate(name="Süd"))
    house_a = store.create_property(PropertyCreate(portfolio_id=north.id, name="Haus A", property_type="residential"))
    house_b = store.create_property(PropertyCreate(portfolio_id=south.id, name="Haus B", property_type="residential"))
    a1 = store.create_unit(UnitCreate(property_id=house_a.id, label="A1", unit_type="residential", cold_rent=500.0,
                                      service_charge_advance=100.0, heating_advance=33.33))
    a2 = store.create_unit(UnitCreate(property_id=house_a.id, label="A2", unit_type="residential", cold_rent=400.0,
                                      service_charge_advance=50.0))
    b1 = store.create_unit(UnitCreate(property_id=house_b.id, label="B1", unit_type="residential", cold_rent=700.0))
    tom, tina, sven = (store.create_tenant(TenantCreate(full_name=name)) for name in ("Tom", "Tina", "Sven"))
    c1 = store.create_contract(ContractCreate(contract_number="A1", property_id=house_a.id, unit_id=a1.id,
                                              tenant_id=tom.id, start_date=date(2026, 1, 1), status="active"))
    c2 = store.create_contract(ContractCreate(contract_number="A2", property_id=house_a.id, unit_id=a2.id,
                                              tenant_id=tina.id, start_date=date(2026, 2, 15), status="active"))
    c3 = store.create_contract(ContractCreate(contract_number="B1", property_id=house_b.id, unit_id=b1.id,
                                              tenant_id=sven.id, start_date=date(2026, 1, 1), status="active"))
    acc_n = store.create_account(AccountCreate(portfolio_id=north.id, name="Konto Nord", account_type="bank",
                                               opening_balance=1000.0))
    acc_s = store.create_account(AccountCreate(portfolio_id=south.id, name="Konto Süd", account_type="bank",
                                               opening_balance=500.0))
    rent = store.create_category(CategoryCreate(portfolio_id=north.id, name="Miete", category_type="income"))
    repairs = store.create_category(CategoryCreate(portfolio_id=north.id, name="Instandhaltung",
                                                   category_type="expense"))
    interest = store.create_category(CategoryCreate(portfolio_id=north.id, name="Zinsen", category_type="income"))
    rent_s = store.create_category(CategoryCreate(portfolio_id=south.id, name="Miete Süd", category_type="income"))

    tom_pays = {"tenant_id": tom.id, "unit_id": a1.id, "property_id": house_a.id, "category_id": rent.id}
    b = {
        "jan": _book(acc_n, "2026-01-03", 633.33, **tom_pays),
        "feb": _book(acc_n, "2026-02-03", 633.33, **tom_pays),
        "feb_again": _book(acc_n, "2026-02-12", 633.33, **tom_pays),
        "mar_part": _book(acc_n, "2026-03-03", 300.0, **tom_pays),        # partial payment ...
        "mar_rest": _book(acc_n, "2026-03-20", 333.33, **tom_pays),       # ... and the rest
        "tina": _book(acc_n, "2026-02-20", 500.0, tenant_id=tina.id, unit_id=a2.id, property_id=house_a.id,
                      category_id=rent.id),                                 # 225.00 due: 275.00 credit
        "dime": _book(acc_n, "2026-01-10", -0.10, property_id=house_a.id, category_id=repairs.id),
        "two_dimes": _book(acc_n, "2026-01-11", -0.20, property_id=house_a.id, category_id=repairs.id),
        "interest": _book(acc_n, "2026-04-15", 12.34, category_id=interest.id),
        "unknown": _book(acc_n, "2026-04-02", 633.33, payment_text="Überweisung ohne Zuordnung"),
        "sven": _book(acc_s, "2026-01-05", 700.0, tenant_id=sven.id, unit_id=b1.id, property_id=house_b.id,
                      category_id=rent_s.id),
    }
    b["thirds"] = [_book(acc_n, "2026-03-05", -33.33, property_id=house_a.id, unit_id=a1.id,
                         category_id=repairs.id) for _ in range(3)]
    # the February debit comes back (Rücklastschrift), booked as its reversal through the API
    returned = client.post(f"/api/v1/bookings/{b['feb'].id}/reverse", headers=_owner(),
                           json={"booking_date": "2026-02-10", "payment_text": "Rücklastschrift"})
    assert returned.status_code == 201, returned.text
    b["return"] = store.get_booking(returned.json()["id"])
    auth.clear_users()
    return {"north": north, "south": south, "house_a": house_a, "house_b": house_b, "a1": a1, "a2": a2, "b1": b1,
            "tom": tom, "tina": tina, "sven": sven, "c1": c1, "c2": c2, "c3": c3, "acc_n": acc_n, "acc_s": acc_s,
            "rent": rent, "repairs": repairs, "bookings": b}


# ---------------------------------------------------------------------------
# Money in cents
# ---------------------------------------------------------------------------

def test_amounts_are_cents_rounded_half_up_and_summed_exactly():
    assert 0.1 + 0.2 != 0.3                                    # what the reports used to add up
    assert money(0.1) + money(0.2) == Decimal("0.30")
    assert money_sum([33.33] * 3) == Decimal("99.99")
    assert money_sum([11.11] * 100) == Decimal("1111.00")
    assert money(2.675) == Decimal("2.68") and money(-0.125) == Decimal("-0.13") and money(1.005) == Decimal("1.01")
    assert money(None) == Decimal("0.00") and money("12.5") == Decimal("12.50")
    assert as_number(Decimal("0.30")) == 0.3
    assert math.copysign(1, as_number(Decimal("-0.00"))) == 1.0      # never -0.0 in JSON
    # a booking arrives as cents; a zero amount is refused after rounding
    assert BookingCreate(account_id="a", booking_date=date(2026, 1, 1), amount=10.005).amount == 10.01
    with pytest.raises(ValueError):
        BookingCreate(account_id="a", booking_date=date(2026, 1, 1), amount=0.004)


def test_sums_that_float_gets_wrong_are_exact_in_every_report():
    portfolio = store.create_portfolio(PortfolioCreate(name="P"))
    account = store.create_account(AccountCreate(portfolio_id=portfolio.id, name="K", account_type="bank"))
    for _ in range(100):
        _book(account, "2026-01-15", 11.11)
    _book(account, "2026-01-16", -0.10)
    _book(account, "2026-01-17", -0.20)

    cash = reports.get_cashflow_report(date_from=date(2026, 1, 1), date_to=date(2026, 1, 31))
    assert (cash["incomeTotal"], cash["expenseTotal"], cash["netTotal"]) == (1111.0, 0.3, 1110.7)
    assert reports.get_summary()["finance"]["bookingsTotal"] == 1110.7
    assert reports.get_finance_report()["uncategorizedTotal"] == 1110.7
    from backend.routers import accounts
    assert accounts.get_account(account.id).balance == 1110.7


# ---------------------------------------------------------------------------
# Cash view, period result, forecast on one known estate
# ---------------------------------------------------------------------------

def test_cash_view_nets_the_returned_debit_and_lists_every_month(estate):
    cash = reports.get_cashflow_report(date_from=date(2026, 1, 1), date_to=date(2026, 5, 31))
    # Jan: 633.33 + 700.00 in, 0.10 + 0.20 out | Feb: 633.33 - 633.33 (returned) + 633.33 + 500.00
    # Mar: 300.00 + 333.33 in, 3 x 33.33 out   | Apr: 12.34 interest + 633.33 unassigned | May: nothing
    assert cash["monthly"] == [
        {"month": "2026-01", "income": 1333.33, "expense": 0.3, "net": 1333.03},
        {"month": "2026-02", "income": 1133.33, "expense": 0.0, "net": 1133.33},
        {"month": "2026-03", "income": 633.33, "expense": 99.99, "net": 533.34},
        {"month": "2026-04", "income": 645.67, "expense": 0.0, "net": 645.67},
        {"month": "2026-05", "income": 0.0, "expense": 0.0, "net": 0.0},
    ]
    # the return lowers the income; it is no expense (it used to be: 4378.99 in, 733.62 out)
    assert (cash["incomeTotal"], cash["expenseTotal"], cash["netTotal"]) == (3745.66, 100.29, 3645.37)
    assert cash["basis"] == "cash" and cash["filters"]["date_to"] == "2026-05-31"


def test_period_result_counts_rent_due_once_and_not_the_payments(estate):
    result = reports.get_period_result(date_from=date(2026, 1, 1), date_to=date(2026, 5, 31))
    # rent due: A1 633.33 every month, A2 225.00 in Feb then 450.00, B1 700.00
    # other income: the interest (income category, no tenant, no unit); costs: repairs
    # the unassigned 633.33 may be rent: shown apart, not in the result
    assert result["monthly"] == [
        {"month": "2026-01", "rent_due": 1333.33, "other_income": 0.0, "costs": 0.3, "result": 1333.03,
         "unassigned_income": 0.0},
        {"month": "2026-02", "rent_due": 1558.33, "other_income": 0.0, "costs": 0.0, "result": 1558.33,
         "unassigned_income": 0.0},
        {"month": "2026-03", "rent_due": 1783.33, "other_income": 0.0, "costs": 99.99, "result": 1683.34,
         "unassigned_income": 0.0},
        {"month": "2026-04", "rent_due": 1783.33, "other_income": 12.34, "costs": 0.0, "result": 1795.67,
         "unassigned_income": 633.33},
        {"month": "2026-05", "rent_due": 1783.33, "other_income": 0.0, "costs": 0.0, "result": 1783.33,
         "unassigned_income": 0.0},
    ]
    assert result["totals"] == {"rent_due": 8241.65, "other_income": 12.34, "costs": 100.29, "result": 8153.7,
                                "unassigned_income": 633.33}
    assert result["basis"] == "accrual"


def test_period_result_runs_in_whole_months():
    applied = report_service.compute_period_result(
        store, FinanceFilter(date_from=date(2026, 3, 15), date_to=date(2026, 4, 2)))
    assert [m["month"] for m in applied["monthly"]] == ["2026-03", "2026-04"]
    assert (applied["filters"]["date_from"], applied["filters"]["date_to"]) == ("2026-03-01", "2026-04-30")
    default = report_service.compute_period_result(store, FinanceFilter(), today=date(2026, 5, 20))
    assert [m["month"] for m in default["monthly"]][::11] == ["2025-06", "2026-05"]
    assert len(default["monthly"]) == 12 and default["totals"]["result"] == 0.0


def test_forecast_expects_the_contracts_rent_and_averages_over_months_without_bookings(estate):
    forecast = report_service.compute_liquidity_forecast(store, FinanceFilter(), months=3,
                                                         today=date(2026, 5, 20))
    # history: January to April (none before the first booking); costs 100.29 / 4 = 25.0725 -> 25.07,
    # February and April had none and count as zero; other income 12.34 / 4 = 3.085 -> 3.09
    assert forecast["history_months"] == 4
    assert (forecast["avg_monthly_expense"], forecast["forecast"][0]["projected_other_income"]) == (25.07, 3.09)
    # balance today: opening 1000.00 + 500.00 plus every booking 3645.37
    assert forecast["current_balance"] == 5145.37
    # each future month: rent 633.33 + 450.00 + 700.00 = 1783.33, + 3.09 other income, - 25.07
    assert forecast["forecast"] == [
        {"month": "2026-06", "projected_rent": 1783.33, "projected_other_income": 3.09, "projected_income": 1786.42,
         "projected_expense": 25.07, "projected_balance": 6906.72},
        {"month": "2026-07", "projected_rent": 1783.33, "projected_other_income": 3.09, "projected_income": 1786.42,
         "projected_expense": 25.07, "projected_balance": 8668.07},
        {"month": "2026-08", "projected_rent": 1783.33, "projected_other_income": 3.09, "projected_income": 1786.42,
         "projected_expense": 25.07, "projected_balance": 10429.42},
    ]
    assert (forecast["avg_monthly_income"], forecast["avg_monthly_net"]) == (1786.42, 1761.35)
    assert forecast["basis"] == "forecast"


def test_forecast_ends_with_the_contract_and_ignores_bookings_after_today(estate):
    from backend.models import ContractCreate as _ContractCreate

    c2 = estate["c2"]
    store.update_contract(c2.id, _ContractCreate(**{**c2.model_dump(include=set(_ContractCreate.model_fields)),
                                                    "end_date": date(2026, 6, 15), "status": "terminated"}))
    _book(estate["acc_n"], "2026-12-24", 999.99, category_id=estate["rent"].id, unit_id=estate["a2"].id,
          property_id=estate["house_a"].id, tenant_id=estate["tina"].id)          # not yet
    forecast = report_service.compute_liquidity_forecast(
        store, FinanceFilter(unit_id=estate["a2"].id), months=2, today=date(2026, 5, 20))
    # A2 alone: no opening balance (accounts belong to the portfolio), its payment 500.00;
    # June: 15 of 30 days of 450.00 = 225.00, July: nothing
    assert forecast["current_balance"] == 500.0
    assert [(m["month"], m["projected_rent"]) for m in forecast["forecast"]] == [("2026-06", 225.0), ("2026-07", 0.0)]


# ---------------------------------------------------------------------------
# Tenant accounts: partial payments, credits, reversals
# ---------------------------------------------------------------------------

def test_tenant_account_counts_partial_payments_and_the_return_once(estate):
    tom = estate["tom"].id
    # up to 31 March: 3 x 633.33 = 1899.99 due; paid 633.33 + 633.33 - 633.33 + 633.33 + 300.00 + 333.33
    end_of_march = tenant_account(store, tom, date(2026, 3, 31))
    assert end_of_march["contracts"][0] | {"contract_id": None} == {
        "contract_id": None, "contract_number": "A1", "expected": 1899.99, "paid": 1899.99,
        "outstanding": 0.0, "overpaid": 0.0}
    assert end_of_march["unassigned"] == []
    # on 10 March the rest of March (333.33, paid on the 20th) is still open: later payments do not count yet
    tenth = tenant_account(store, tom, date(2026, 3, 10))
    assert (tenth["contracts"][0]["paid"], tenth["contracts"][0]["outstanding"]) == (1566.66, 333.33)
    assert tenth["totals"]["balance"] == 333.33 and tenth["paid_total"] == 1566.66


def test_an_overpayment_is_the_contracts_credit_not_an_unassigned_payment(estate):
    tina = estate["tina"].id
    february = tenant_account(store, tina, date(2026, 2, 28))
    assert (february["contracts"][0]["expected"], february["contracts"][0]["overpaid"]) == (225.0, 275.0)
    assert february["totals"] == {"expected": 225.0, "paid": 500.0, "outstanding": 0.0, "overpaid": 275.0,
                                  "balance": -275.0, "unassigned": 0.0}
    assert february["unassigned"] == []
    # the credit is used up by March's rent: 225.00 + 450.00 - 500.00 = 175.00 open
    march = tenant_account(store, tina, date(2026, 3, 31))
    assert (march["totals"]["outstanding"], march["totals"]["overpaid"]) == (175.0, 0.0)


def test_the_reversal_is_credited_like_its_original(client, estate):
    b = estate["bookings"]
    reversal = b["return"]
    assert (reversal.amount, reversal.reverses_booking_id, reversal.account_id, reversal.category_id,
            reversal.tenant_id, reversal.unit_id) == (-633.33, b["feb"].id, estate["acc_n"].id, estate["rent"].id,
                                                      estate["tom"].id, estate["a1"].id)
    allocations = client.get(f"/api/v1/bookings/{reversal.id}/allocations", headers=_owner()).json()
    assert [(a["contract_id"], a["amount"]) for a in allocations] == [(estate["c1"].id, -633.33)]


def test_a_reversal_mirrors_its_original_also_without_stored_allocations(estate):
    # a split payment, reversed in part: same contracts, same proportions, cents adding up exactly
    pairs = [("flat", Decimal("600.00")), ("garage", Decimal("33.33"))]
    assert mirror_allocation(Decimal("633.33"), pairs, Decimal("-100.00")) == [
        ("flat", Decimal("-94.74")), ("garage", Decimal("-5.26"))]
    # half of an original that was only half assigned: half of the assigned part
    assert mirror_allocation(Decimal("800.00"), [("flat", Decimal("400.00"))], Decimal("-400.00")) == [
        ("flat", Decimal("-200.00"))]
    assert mirror_allocation(Decimal("800.00"), [], Decimal("-800.00")) == []
    # imported bookings carry no allocations: the account credits them on the fly by the same rules
    b = estate["bookings"]
    for booking in (b["feb"], b["return"]):
        for allocation in store.list_payment_allocations(booking_id=booking.id):
            store.delete_payment_allocation(allocation.id)
    credited = {booking.id: (contract, amount) for booking, contract, amount
                in credited_by_tenant(store, [estate["tom"].id])[estate["tom"].id]}
    assert credited[b["return"].id] == (estate["c1"].id, Decimal("-633.33"))
    assert tenant_account(store, estate["tom"].id, date(2026, 3, 31))["totals"]["paid"] == 1899.99


# ---------------------------------------------------------------------------
# Filters: period, portfolio, property, unit; the account's portfolios on top
# ---------------------------------------------------------------------------

def test_every_finance_report_takes_the_same_filters(estate):
    a1, house_a, north, south = estate["a1"].id, estate["house_a"].id, estate["north"].id, estate["south"].id
    start, end = date(2026, 1, 1), date(2026, 5, 31)

    def cash(**dims):
        data = reports.get_cashflow_report(date_from=start, date_to=end, **dims)
        return data["incomeTotal"], data["expenseTotal"], data["netTotal"]

    # house A: no interest, no unassigned transfer (no property), not Sven
    assert cash(property_id=house_a) == (2399.99, 100.29, 2299.7)
    # flat A1: Tom's payments and the repairs in A1; the dimes were for the house
    assert cash(unit_id=a1) == (1899.99, 99.99, 1800.0)
    assert cash(portfolio_id=north) == (3045.66, 100.29, 2945.37)
    assert cash(portfolio_id=south) == (700.0, 0.0, 700.0)
    assert cash(property_id=house_a, portfolio_id=south) == (0.0, 0.0, 0.0)

    by_unit = reports.get_period_result(date_from=start, date_to=end, unit_id=estate["a2"].id)
    assert [m["rent_due"] for m in by_unit["monthly"]] == [0.0, 225.0, 450.0, 450.0, 450.0]
    assert by_unit["totals"]["result"] == 1575.0

    finance = reports.get_finance_report(date_from=start, date_to=end, portfolio_id=north)
    assert {t["categoryName"]: t["total"] for t in finance["totalsByCategory"]} == {
        "Instandhaltung": -100.29, "Miete": 2399.99, "Zinsen": 12.34}
    assert finance["uncategorizedTotal"] == 633.33

    summary = reports.get_summary(property_id=house_a)
    assert summary["totals"] == {"properties": 1, "units": 2, "contracts": 2}
    assert summary["finance"]["bookingsTotal"] == 2299.7
    assert reports.get_summary(unit_id=a1)["totals"] == {"properties": 1, "units": 1, "contracts": 1}
    assert reports.get_summary(date_from=date(2026, 4, 1))["finance"]["bookingsTotal"] == 645.67


def test_a_period_starting_after_its_end_is_refused(client):
    response = client.get("/api/v1/reports/cashflow", params={"date_from": "2026-05-01", "date_to": "2026-04-01"},
                          headers=_owner())
    assert response.status_code == 422


def test_invoices_and_receivables_follow_the_filters(estate):
    from backend.models import ReceivableCreate

    store.create_invoice(InvoiceCreate(property_id=estate["house_a"].id, supplier="Dach GmbH",
                                       invoice_date=date(2026, 3, 1), net_amount=100.0, gross_amount=119.0))
    store.create_invoice(InvoiceCreate(property_id=estate["house_b"].id, supplier="Garten",
                                       invoice_date=date(2026, 3, 1), net_amount=10.0, gross_amount=11.9))
    store.create_receivable(ReceivableCreate(contract_id=estate["c1"].id, due_date=date(2026, 3, 3),
                                             amount_due=33.33, status="open"))
    store.create_receivable(ReceivableCreate(contract_id=estate["c3"].id, due_date=date(2026, 3, 3),
                                             amount_due=66.67, status="open"))
    everything = reports.get_summary()["finance"]
    assert (everything["invoicesTotal"], everything["openReceivables"]) == (130.9, 100.0)
    north = reports.get_summary(portfolio_id=estate["north"].id)["finance"]
    assert (north["invoicesTotal"], north["openReceivables"]) == (119.0, 33.33)
    # invoices belong to the house, never to one flat
    assert reports.get_summary(unit_id=estate["a1"].id)["finance"]["invoicesTotal"] == 0.0
    aging = reports.get_receivables_aging(property_id=estate["house_b"].id)
    assert aging["openTotal"] == 66.67


def test_a_restricted_account_sees_only_its_portfolio_in_every_view(client, estate):
    staff = _bearer(auth.register_user("staff", "s@example.com", "Staff", "Secret123", "verwalter",
                                       portfolio_access="selected", portfolio_ids=[estate["north"].id]))
    owner = _owner()

    def get(path, headers, **params):
        response = client.get(f"/api/v1/reports/{path}", params={**PERIOD, **params}, headers=headers)
        assert response.status_code == 200, response.text
        return response.json()

    restricted = get("cashflow", staff)
    assert (restricted["incomeTotal"], restricted["netTotal"]) == (3045.66, 2945.37)
    assert get("cashflow", owner, portfolio_id=estate["north"].id)["monthly"] == restricted["monthly"]
    # asking for the other portfolio shows nothing of it
    assert get("cashflow", staff, portfolio_id=estate["south"].id)["incomeTotal"] == 0.0
    assert get("period-result", staff, property_id=estate["house_b"].id)["totals"]["rent_due"] == 0.0
    assert get("period-result", staff)["totals"]["rent_due"] == 4741.65       # without B1's 5 x 700.00
    forecast = client.get("/api/v1/reports/liquidity-forecast", params={"months": 1}, headers=staff).json()
    assert forecast["current_balance"] == 3945.37                             # 1000.00 + 2945.37, not South
    accounts = client.get("/api/v1/accounts", headers=staff).json()
    assert [(a["name"], a["balance"]) for a in accounts] == [("Konto Nord", 3945.37)]


# ---------------------------------------------------------------------------
# Reversals (Storno)
# ---------------------------------------------------------------------------

def test_reversal_rules(client, estate):
    owner = _owner()
    b = estate["bookings"]
    expense = b["thirds"][0]
    # partly, then the rest
    first = client.post(f"/api/v1/bookings/{expense.id}/reverse", headers=owner,
                        json={"amount": 10.0, "booking_date": "2026-03-06"})
    assert first.status_code == 201 and first.json()["amount"] == 10.0
    rest = client.post(f"/api/v1/bookings/{expense.id}/reverse", headers=owner, json={"booking_date": "2026-03-07"})
    assert rest.status_code == 201 and rest.json()["amount"] == 23.33
    # without a date the reversal is booked today
    assert client.post(f"/api/v1/bookings/{b['two_dimes'].id}/reverse",
                       headers=owner).json()["booking_date"] == date.today().isoformat()
    again = client.post(f"/api/v1/bookings/{expense.id}/reverse", headers=owner)
    assert again.status_code == 400 and "vollständig" in again.json()["error"]["message"]
    # a reversal is not reversed, and no reversal exceeds or repeats the sign of its booking
    assert client.post(f"/api/v1/bookings/{rest.json()['id']}/reverse", headers=owner).status_code == 400
    too_much = client.post(f"/api/v1/bookings/{b['dime'].id}/reverse", headers=owner, json={"amount": 0.11})
    assert too_much.status_code == 400
    same_sign = client.post("/api/v1/bookings", headers=owner, json={
        "account_id": estate["acc_n"].id, "booking_date": "2026-03-06", "amount": -1.0,
        "property_id": estate["house_a"].id, "category_id": estate["repairs"].id,
        "reverses_booking_id": b["dime"].id})
    assert same_sign.status_code == 400
    other_assignment = client.post("/api/v1/bookings", headers=owner, json={
        "account_id": estate["acc_n"].id, "booking_date": "2026-03-06", "amount": 0.1,
        "reverses_booking_id": b["dime"].id})
    assert other_assignment.status_code == 400
    early = client.post(f"/api/v1/bookings/{b['dime'].id}/reverse", headers=owner,
                        json={"booking_date": "2025-12-31"})
    assert early.status_code == 400
    # the expense is gone from the reports, without an income
    cash = reports.get_cashflow_report(date_from=date(2026, 3, 1), date_to=date(2026, 3, 31))
    assert (cash["incomeTotal"], cash["expenseTotal"]) == (633.33, 66.66)


def test_a_reversed_booking_keeps_its_reversal(client, estate):
    owner = _owner()
    b = estate["bookings"]
    original, reversal = b["feb"], b["return"]
    # deleting the original alone would leave an income or expense of its own
    refused = client.delete(f"/api/v1/bookings/{original.id}", headers=owner)
    assert refused.status_code == 409 and "Stornobuchung" in refused.json()["error"]["message"]
    # the booking form sends no link: editing the reversal keeps it
    form = {k: v for k, v in reversal.model_dump(mode="json").items()
            if k in {"account_id", "category_id", "property_id", "unit_id", "tenant_id", "booking_date", "amount",
                     "status"}}
    edited = client.put(f"/api/v1/bookings/{reversal.id}", headers=owner, json={**form, "payment_text": "RLS"})
    assert edited.status_code == 200 and edited.json()["reverses_booking_id"] == original.id
    unlinked = client.patch(f"/api/v1/bookings/{reversal.id}", headers=owner, json={"reverses_booking_id": None})
    assert unlinked.status_code in (400, 422) or unlinked.json()["reverses_booking_id"] == original.id
    # the reversed booking keeps its assignment and covers its reversal
    moved = client.patch(f"/api/v1/bookings/{original.id}", headers=owner,
                         json={"category_id": estate["repairs"].id})
    assert moved.status_code == 400
    shrunk = client.patch(f"/api/v1/bookings/{original.id}", headers=owner, json={"amount": 100.0})
    assert shrunk.status_code == 400
    # without the reversal the original can go
    assert client.delete(f"/api/v1/bookings/{reversal.id}", headers=owner).status_code == 204
    assert client.delete(f"/api/v1/bookings/{original.id}", headers=owner).status_code == 204


def test_review_list_and_invoice_matching_skip_what_was_reversed(client, estate):
    owner = _owner()
    b = estate["bookings"]
    review = client.get("/api/v1/review", headers=owner).json()["items"]
    flagged = {item["entity_id"] for item in review}
    assert b["unknown"].id in flagged and b["feb"].id not in flagged and b["return"].id not in flagged
    assert client.post(f"/api/v1/bookings/{b['unknown'].id}/reverse", headers=owner).status_code == 201
    review = client.get("/api/v1/review", headers=owner).json()["items"]
    assert b["unknown"].id not in {item["entity_id"] for item in review}

    dime = b["dime"]
    store.update_booking(dime.id, BookingCreate(**{**dime.model_dump(include=set(BookingCreate.model_fields)),
                                                   "status": "open"}))
    invoice = store.create_invoice(InvoiceCreate(supplier="Baumarkt", invoice_date=date(2026, 1, 10),
                                                 net_amount=0.08, gross_amount=0.10))
    matched = client.post(f"/api/v1/invoices/{invoice.id}/match", headers=owner).json()
    assert [a["booking_id"] for a in matched["allocations"]] == [dime.id]
    assert client.post(f"/api/v1/bookings/{dime.id}/reverse", headers=owner).status_code == 201
    matched = client.post(f"/api/v1/invoices/{invoice.id}/match", headers=owner).json()
    assert matched["allocations"] == []


def test_datev_lists_the_reversal_as_its_own_line(client, estate):
    response = client.get("/api/v1/reports/datev-export", headers=_owner(),
                          params={"start_date": "2026-02-01", "end_date": "2026-02-28",
                                  "property_id": estate["house_a"].id})
    lines = response.text.strip().splitlines()[1:]
    assert [line.split(";")[:2] for line in lines] == [
        ["633,33", "S"], ["633,33", "H"], ["633,33", "S"], ["500,00", "S"]]


# ---------------------------------------------------------------------------
# One classification for both stores
# ---------------------------------------------------------------------------

def test_sql_cents_round_like_the_memory_store(tmp_path):
    """Legacy rows can hold more than two decimals; the database sum rounds each like domain.money."""
    from sqlalchemy import create_engine, insert
    from sqlalchemy.orm import Session

    from backend.db.orm_models import AccountORM, Base, BookingORM, PortfolioORM
    from backend.repositories import SQLAlchemyStore

    engine = create_engine(f"sqlite:///{tmp_path / 'cents.db'}")
    Base.metadata.create_all(engine)
    values = [2.675, 1.005, 0.285, -1.005, -2.675, 0.1, 0.2, 33.33, 33.33, 33.33, 1234567.895]
    with Session(engine) as db:
        db.execute(insert(PortfolioORM).values(id="p", name="P"))
        db.execute(insert(AccountORM).values(id="a", portfolio_id="p", name="K", account_type="bank"))
        db.execute(insert(BookingORM), [{"id": f"b{i}", "account_id": "a", "booking_date": date(2026, 1, 1),
                                         "amount": value, "status": "booked"} for i, value in enumerate(values)])
        db.commit()
    sql_store = SQLAlchemyStore(Session(engine))
    rows = booking_totals(sql_store, FinanceFilter())
    assert sum((row.amount for row in rows), Decimal("0")) == money_sum(values) == Decimal("1234668.48")
    sql_store.db.close()
    engine.dispose()
