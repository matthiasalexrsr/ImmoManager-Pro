"""Small numerical counterexamples for dates, report dimensions and source totals."""

from datetime import date
from decimal import Decimal
from typing import Literal

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from backend import auth
from backend.app import app
from backend.dependencies import store
from backend.finance_models import ReportDefinition
from backend.maintenance_models import InvoicePayment
from backend.models import (
    AccountCreate,
    BillingPeriodCreate,
    Booking,
    BookingCreate,
    InvoiceCreate,
    PortfolioCreate,
    PropertyCreate,
    UnitCreate,
    UtilityStatementCreate,
)
from backend.services import finance_reports, report_service
from backend.services.finance_ledger import FinanceFilter, booking_totals
from backend.services.maintenance_projects import work
from backend.services.maintenance_rows import Rows
from backend.tests.test_finance_packages_v2 import clean  # noqa: F401
from backend.tests.test_finance_packages_v2 import estate as _estate_fixture  # noqa: F401


@pytest.fixture(name="estate")
def finance_fixture(request):
    return request.getfixturevalue("_estate_fixture")


def other_place():
    portfolio = store.create_portfolio(PortfolioCreate(name="Anderes Portfolio"))
    house = store.create_property(PropertyCreate(portfolio_id=portfolio.id, name="Anderes Haus", property_type="residential"))
    unit = store.create_unit(UnitCreate(property_id=house.id, label="Andere Einheit", unit_type="residential"))
    return portfolio, house, unit


@pytest.mark.parametrize("report", ["cash", "performance", "v2-performance", "v2-liquidity"])
@pytest.mark.parametrize("conflict", ["portfolio_property", "property_unit", "portfolio_unit"])
def test_contradictory_dimensions_fail_instead_of_silently_returning_zero(estate, report, conflict):
    other_portfolio, other_house, other_unit = other_place()
    filters = {"portfolio_property": {"portfolio_id": estate[0].id, "property_id": other_house.id},
               "property_unit": {"property_id": estate[1].id, "unit_id": other_unit.id},
               "portfolio_unit": {"portfolio_id": other_portfolio.id, "unit_id": estate[2].id}}[conflict]
    with pytest.raises(HTTPException) as failure:
        if report == "cash":
            report_service.compute_cashflow(store, FinanceFilter(**filters))
        elif report == "performance":
            report_service.compute_period_result(store, FinanceFilter(**filters), today=date(2026, 1, 15))
        else:
            kind: Literal["performance-period-v2", "liquidity-v2"] = "performance-period-v2" if report == "v2-performance" else "liquidity-v2"
            finance_reports.compute(store, ReportDefinition(kind=kind, as_of=date(2026, 1, 15), **filters))
    assert failure.value.status_code == 422


def test_payment_outside_forecast_cannot_remove_an_invoice_due_inside_it(estate):
    invoice = store.create_invoice(InvoiceCreate(property_id=estate[1].id, supplier="100 Euro Rechnung",
        invoice_date=date(2026, 1, 1), due_date=date(2026, 2, 10), net_amount=100, gross_amount=100))
    booking = store.create_booking(BookingCreate(account_id=estate[5].id, property_id=estate[1].id,
        booking_date=date(2027, 1, 10), amount=-100))
    with work(store, None, ()) as unit:
        Rows.of(unit).add("invoice_payments", InvoicePayment(id="outside-horizon-payment", invoice_id=invoice.id,
                                                           booking_id=booking.id, amount=100))
    result = finance_reports.compute(store, ReportDefinition(kind="liquidity-v2", as_of=date(2026, 1, 15), months=3))
    assert result["opening_balance"] == "1000.00"
    assert sum(Decimal(month["expense"]) for month in result["monthly"]) == Decimal("100.00")
    assert result["closing_balance"] == "1100.00"  # opening1000 + Feb/Mar rent200 - invoice100
    assert all(source["day"] <= "2026-03-31" for source in result["sources"])


@pytest.mark.parametrize("boundary", [{"date_from": date(2027, 1, 1)}, {"date_to": date(2025, 12, 31)}])
def test_effective_performance_bounds_include_the_default_year(estate, boundary):
    with pytest.raises(HTTPException) as failure:
        finance_reports.compute(store, ReportDefinition(kind="performance-period-v2", as_of=date(2026, 6, 15), **boundary))
    assert failure.value.status_code == 422


def test_vacancy_scenario_cannot_name_a_unit_outside_the_selected_property(estate):
    _, _, other_unit = other_place()
    with pytest.raises(HTTPException) as failure:
        finance_reports.compute(store, ReportDefinition(kind="liquidity-v2", as_of=date(2026, 1, 15),
            property_id=estate[1].id, vacant_unit_ids=[other_unit.id]))
    assert failure.value.status_code == 422


def test_zero_months_reconcile_with_booking_sources_and_current_day_is_in_opening(estate):
    for day, amount in [(date(2026, 1, 15), 0.10), (date(2026, 3, 31), 0.20)]:
        store.create_booking(BookingCreate(account_id=estate[5].id, booking_date=day, amount=amount))
    cash = report_service.compute_cashflow(store, FinanceFilter(date_from=date(2026, 1, 1), date_to=date(2026, 3, 31)))
    assert [row["month"] for row in cash["monthly"]] == ["2026-01", "2026-02", "2026-03"]
    assert cash["monthly"][1]["net"] == 0
    assert sum(Decimal(str(row["net"])) for row in cash["monthly"]) == Decimal(str(cash["netTotal"])) == Decimal("0.30")
    assert sum((row.amount for row in booking_totals(store, FinanceFilter())), Decimal(0)) == Decimal("0.30")
    forecast = finance_reports.compute(store, ReportDefinition(kind="liquidity-v2", as_of=date(2026, 1, 15), months=3))
    assert forecast["opening_balance"] == "1000.10"
    future_cash = [source for source in forecast["sources"] if source["identity"].startswith("booking:")]
    assert len(future_cash) == 1 and future_cash[0]["amount"] == "0.20"


def test_cash_v2_reuses_cash_totals_and_dated_booking_sources_including_returns(estate):
    bookings: list[Booking] = []
    for day, amount in [(date(2026, 1, 3), 100.0), (date(2026, 1, 15), -40.0), (date(2026, 3, 31), 0.20)]:
        bookings.append(store.create_booking(BookingCreate(account_id=estate[5].id, property_id=estate[1].id,
            booking_date=day, amount=amount, reverses_booking_id=bookings[0].id if amount < 0 else None)))
    definition = ReportDefinition(kind="cash-v2", as_of=date(2026, 3, 31), date_from=date(2026, 1, 1),
                                  property_id=estate[1].id)
    result = finance_reports.compute(store, definition)
    legacy = report_service.compute_cashflow(store, FinanceFilter(date_from=date(2026, 1, 1), date_to=date(2026, 3, 31),
                                                                 property_id=estate[1].id))
    assert result["totals"] == {"income": "60.20", "expense": "0.00", "net": "60.20"}
    assert Decimal(result["totals"]["net"]) == Decimal(str(legacy["netTotal"]))
    assert result["monthly"][1] == {"month": "2026-02", "income": "0.00", "expense": "0.00", "net": "0.00"}
    assert sum(Decimal(source["amount"]) for source in result["sources"]) == Decimal(result["totals"]["net"])
    assert all(source["url"].startswith("/bookings?booking_id=") for source in result["sources"])
    assert all(source["label"] == "Buchung " + source["day"] for source in result["sources"])
    assert result["result_hash"] == finance_reports.compute(store, definition)["result_hash"]


def test_cash_property_filter_does_not_relabel_foreign_currency_bookings_as_euros(estate):
    dollars = store.create_portfolio(PortfolioCreate(name="Dollar-Konto", currency="USD"))
    account = store.create_account(AccountCreate(portfolio_id=dollars.id, name="Dollar", account_type="bank"))
    store.create_booking(BookingCreate(account_id=account.id, property_id=estate[1].id,
                                       booking_date=date(2026, 1, 15), amount=10))
    with pytest.raises(HTTPException) as failure:
        finance_reports.compute(store, ReportDefinition(kind="cash-v2", as_of=date(2026, 1, 31), property_id=estate[1].id))
    assert failure.value.status_code == 422


def test_performance_warnings_only_name_sources_in_the_selected_place_and_period(estate):
    _, other_house, _ = other_place()
    store.create_invoice(InvoiceCreate(property_id=other_house.id, supplier="Anderes Haus",
        invoice_date=date(2026, 1, 15), net_amount=40, gross_amount=40))
    store.create_invoice(InvoiceCreate(property_id=estate[1].id, supplier="Anderes Jahr",
        invoice_date=date(2025, 1, 15), net_amount=60, gross_amount=60))
    result = finance_reports.compute(store, ReportDefinition(kind="performance-period-v2", as_of=date(2026, 12, 31),
                                                             property_id=estate[1].id))
    assert result["totals"]["costs"] == "0.00"
    assert result["warnings"] == []


def test_cash_v2_json_csv_pdf_share_the_same_checked_result_and_as_of_default(estate):
    store.create_booking(BookingCreate(account_id=estate[5].id, booking_date=date(2026, 1, 15), amount=42,
                                       payment_text="Bankzinsen Januar"))
    store.create_booking(BookingCreate(account_id=estate[5].id, booking_date=date(2026, 2, 1), amount=99))
    actor = auth.register_user("cash-reader", "cash@example.test", "Cash reader", "Secret123", "readonly")
    client = TestClient(app, headers={"Authorization": "Bearer " + auth.create_access_token(actor.id)})
    definition = ReportDefinition(kind="cash-v2", as_of=date(2026, 1, 31))
    query = {"definition": definition.model_dump_json()}
    result = client.get("/api/v1/reports/v2/preview", params=query)
    assert result.status_code == 200, result.text
    data = result.json()
    assert data["totals"]["net"] == "42.00"
    assert data["sources"][0]["label"] == "Bankzinsen Januar"
    assert data["filters"]["date_to"] == "2026-01-31"
    assert data["filters"]["date_from"] == "2026-01-15"
    for format_ in ("csv", "pdf"):
        response = client.get("/api/v1/reports/v2/preview", params={**query, "format": format_, "expected_result_hash": data["result_hash"]})
        assert response.status_code == 200, response.text
        if format_ == "csv":
            assert data["result_hash"] in response.text and "42.00" in response.text
        else:
            assert response.content.startswith(b"%PDF")
    store.create_booking(BookingCreate(account_id=estate[5].id, booking_date=date(2026, 1, 20), amount=1))
    changed = client.get("/api/v1/reports/v2/preview", params={**query, "format": "csv", "expected_result_hash": data["result_hash"]})
    assert changed.status_code == 409


def test_sql_cash_sources_do_not_load_the_entire_booking_store(estate, monkeypatch):
    store.create_booking(BookingCreate(account_id=estate[5].id, booking_date=date(2026, 1, 15), amount=42))
    if hasattr(store, "db"):
        def unexpected_full_scan(*args, **kwargs):
            raise AssertionError("cash-v2 must filter SQL booking sources before materializing them")
        monkeypatch.setattr(store, "list_bookings", unexpected_full_scan)
    result = finance_reports.compute(store, ReportDefinition(kind="cash-v2", as_of=date(2026, 1, 31),
        date_from=date(2026, 1, 1), portfolio_id=estate[0].id))
    assert result["totals"]["net"] == "42.00" and len(result["sources"]) == 1


def test_invalid_legacy_invoice_only_blocks_its_own_report_scope(estate, monkeypatch):
    _, other_house, _ = other_place()
    invoice = store.create_invoice(InvoiceCreate(property_id=other_house.id, supplier="Legacyquelle",
        invoice_date=date(2026, 1, 1), net_amount=40, gross_amount=40))
    # Explicitly emulate a legacy reader returning incomplete performance data;
    # current creation/read validators reject such a row before it can be saved.
    invalid = invoice.model_copy(update={"performance_start": date(2026, 1, 1), "performance_end": None})
    monkeypatch.setattr(store, "list_invoices", lambda: [invalid])
    result = finance_reports.compute(store, ReportDefinition(kind="performance-period-v2", as_of=date(2026, 1, 31),
                                                             property_id=estate[1].id))
    assert result["totals"]["costs"] == "0.00"
    with pytest.raises(HTTPException) as failure:
        finance_reports.compute(store, ReportDefinition(kind="performance-period-v2", as_of=date(2026, 1, 31),
                                                         property_id=other_house.id))
    assert failure.value.status_code == 409


def test_performance_contributions_reconcile_each_metric_with_its_sources(estate):
    period = store.create_billing_period(BillingPeriodCreate(property_id=estate[1].id, label="Januar",
        start_date=date(2026, 1, 1), end_date=date(2026, 1, 31), status="finalized"))
    store.create_utility_statement(UtilityStatementCreate(billing_period_id=period.id, contract_id=estate[4].id,
        unit_id=estate[2].id, total_cost=6, advance_paid=0, balance=6, status="finalized"))
    store.create_invoice(InvoiceCreate(property_id=estate[1].id, supplier="Januarkosten",
        invoice_date=date(2026, 1, 15), net_amount=12, gross_amount=12))
    for amount in (3, -2):
        store.create_booking(BookingCreate(account_id=estate[5].id, property_id=estate[1].id,
            booking_date=date(2026, 1, 15), amount=amount))
    result = finance_reports.compute(store, ReportDefinition(kind="performance-period-v2", as_of=date(2026, 1, 31),
        date_from=date(2026, 1, 1), date_to=date(2026, 1, 31), property_id=estate[1].id))
    assert result["totals"] == {"rent_due": "100.00", "other_income": "9.00", "costs": "14.00", "result": "95.00"}
    for field in ("rent_due", "other_income", "costs"):
        sources = [source for source in result["sources"] if source["contribution"] == field]
        assert sum(Decimal(source["amount"]) for source in sources) == Decimal(result["totals"][field])
    by_kind = {source["identity"].split(":")[0]: source["contribution"] for source in result["sources"]}
    assert by_kind["utility-statement"] == "other_income"
    assert by_kind["rent"] == "rent_due"
    assert by_kind["invoice"] == "costs"
