"""Independent monetary examples for forecast reservations and report source evidence."""
from datetime import date
from decimal import Decimal
from io import BytesIO

import pdfplumber
import pytest
from fastapi.testclient import TestClient

from backend import auth
from backend.app import app
from backend.dependencies import store
from backend.finance_models import ReportDefinition
from backend.models import AccountCreate, BookingCreate, InvoiceCreate, PortfolioCreate
from backend.services import finance_reports
from backend.services.payment_allocations import auto_allocate
from backend.tests.test_finance_packages_v2 import clean  # noqa: F401
from backend.tests.test_finance_packages_v2 import estate as _estate_fixture  # noqa: F401


@pytest.fixture(name="estate")
def report_estate(request):
    return request.getfixturevalue("_estate_fixture")


@pytest.mark.parametrize("day,amount,percent,expected", [
    ("2026-02-01", 300, "100", "1300.00"),
    ("2026-01-20", 300, "100", "1300.00"),
    ("2026-02-01", 250, "50", "1275.00"),
])
def test_future_rent_cash_reserves_all_fifo_months_once(estate, day, amount, percent, expected):
    # Jan/Feb/Mar each owe100. A known future payment settles oldest rent first,
    # including prepayment of later months; collection assumptions apply to the rest.
    _, house, unit, tenant, _, account = estate
    booking = store.create_booking(BookingCreate(account_id=account.id, property_id=house.id,
        unit_id=unit.id, tenant_id=tenant.id, booking_date=date.fromisoformat(day), amount=amount))
    auto_allocate(store, booking)
    result = finance_reports.compute(store, ReportDefinition(kind="liquidity-v2", as_of=date(2026, 1, 15),
        months=3, rent_collection_percent=Decimal(percent)))
    assert result["opening_balance"] == "1000.00"
    assert result["closing_balance"] == expected
    assert sum((Decimal(s["amount"]) for s in result["sources"]), Decimal(0)) == Decimal(expected) - 1000


def test_cancelled_invoice_does_not_create_performance_costs(estate):
    store.create_invoice(InvoiceCreate(property_id=estate[1].id, supplier="Stornierter Auftrag",
        invoice_date=date(2026, 1, 1), net_amount=400, gross_amount=400, status="cancelled"))
    result = finance_reports.compute(store, ReportDefinition(kind="performance-period-v2", as_of=date(2026, 1, 15)))
    assert result["totals"]["costs"] == "0.00"
    assert not any(source["identity"].startswith("invoice:") for source in result["sources"])


def test_opening_balance_and_basis_forecast_have_their_own_reconciling_sources(estate):
    store.create_booking(BookingCreate(account_id=estate[5].id, property_id=estate[1].id,
        booking_date=date(2026, 1, 15), amount=42, payment_text="Anfangssaldo-Beleg"))
    result = finance_reports.compute(store, ReportDefinition(kind="liquidity-v2", as_of=date(2026, 1, 15),
        months=3, rent_collection_percent=Decimal(50)))
    assert sum((Decimal(s["amount"]) for s in result["opening_sources"]), Decimal(0)) == Decimal(result["opening_balance"])
    assert Decimal(result["opening_balance"]) + sum((Decimal(s["amount"]) for s in result["baseline_sources"]), Decimal(0)) == Decimal(result["baseline_monthly"][-1]["balance"])
    assert result["closing_balance"] == "1142.00" and result["baseline_monthly"][-1]["balance"] == "1242.00"
    assert {s["label"] for s in result["opening_sources"]} == {"Eröffnungssaldo Bank", "Anfangssaldo-Beleg"}


def test_property_opening_sources_exclude_unassigned_account_opening_balance(estate):
    result = finance_reports.compute(store, ReportDefinition(kind="liquidity-v2", as_of=date(2026, 1, 15),
        months=3, property_id=estate[1].id))
    assert result["opening_balance"] == "0.00" and result["opening_sources"] == []


@pytest.mark.parametrize("kind", ["performance-period-v2", "liquidity-v2"])
def test_source_account_currency_is_checked_for_all_report_bases(estate, kind):
    from fastapi import HTTPException

    dollars = store.create_portfolio(PortfolioCreate(name="USD-Quellen", currency="USD"))
    account = store.create_account(AccountCreate(portfolio_id=dollars.id, name="USD-Bank", account_type="bank"))
    store.create_booking(BookingCreate(account_id=account.id, property_id=estate[1].id,
        booking_date=date(2026, 1, 10), amount=-10))
    with pytest.raises(HTTPException) as failure:
        finance_reports.compute(store, ReportDefinition(kind=kind, as_of=date(2026, 1, 15), property_id=estate[1].id))
    assert failure.value.status_code == 422


def test_future_cash_return_restores_only_the_receipts_not_covered_by_known_cash(estate):
    _, house, unit, tenant, _, account = estate
    for day, amount in [(date(2026, 2, 1), 300), (date(2026, 2, 20), -100)]:
        booking = store.create_booking(BookingCreate(account_id=account.id, property_id=house.id,
            unit_id=unit.id, tenant_id=tenant.id, booking_date=day, amount=amount))
        auto_allocate(store, booking)
    result = finance_reports.compute(store, ReportDefinition(kind="liquidity-v2", as_of=date(2026, 1, 15), months=3))
    assert result["closing_balance"] == "1300.00"  # 1000 + known net200 + remaining March100
    assert result["monthly"][2]["income"] == "100.00"


def test_csv_negative_money_is_numeric_and_pdf_contains_totals_names_and_sources(estate):
    store.create_booking(BookingCreate(account_id=estate[5].id, property_id=estate[1].id,
        booking_date=date(2026, 1, 15), amount=-1234.56, payment_text="=1+1"))
    actor = auth.register_user("source-reports", "source@example.test", "Quellenprüfung", "Secret123", "eigentuemer")
    client = TestClient(app, headers={"Authorization": "Bearer " + auth.create_access_token(actor.id)})
    definition = ReportDefinition(kind="cash-v2", as_of=date(2026, 1, 31), property_id=estate[1].id)
    query = {"definition": definition.model_dump_json()}
    result = client.get("/api/v1/reports/v2/preview", params=query).json()
    for format_ in ("csv", "pdf"):
        response = client.get("/api/v1/reports/v2/preview", params={**query, "format": format_, "expected_result_hash": result["result_hash"]})
        assert response.status_code == 200, response.text
        if format_ == "csv":
            assert "-1234.56" in response.text and "'-1234.56" not in response.text
            assert "'=1+1" in response.text and "totals" in response.text
        else:
            with pdfplumber.open(BytesIO(response.content)) as document:
                text = "\n".join(page.extract_text() or "" for page in document.pages)
            assert "Haus" in text and "1.234,56 EUR" in text and "-1.234,56 EUR" in text
            assert "Gesamtwerte" in text and "=1+1" in text
