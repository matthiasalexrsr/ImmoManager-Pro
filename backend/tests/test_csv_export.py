import csv
import io
from datetime import date
from decimal import Decimal

import pytest

from backend.models import AccountCreate, BookingCreate, CategoryCreate, PortfolioCreate
from backend.routers import reports, search
from backend.services.csv_export import spreadsheet_cell
from backend.storage import InMemoryStore


@pytest.mark.parametrize("text", ["=1+1", "+SUM(1)", "-CMD()", "@SUM(1)", "  =1+1", "\tName", "\rName", "\n=1+1", "\u00a0+SUM(1)"])
def test_spreadsheet_text_is_literal(text: str) -> None:
    assert spreadsheet_cell(text) == "'" + text
    assert search._csv_cell(text) == "'" + text


def test_numbers_and_ordinary_unicode_text_keep_their_value() -> None:
    assert spreadsheet_cell(-123.45) == "-123.45"
    assert spreadsheet_cell(Decimal("-0.01")) == "-0.01"
    assert spreadsheet_cell(None) == ""
    assert spreadsheet_cell("Öztürk, Straße\r\nWohnung 1") == "Öztürk, Straße\r\nWohnung 1"
    assert spreadsheet_cell("'=1+1") == "'=1+1"


def test_report_csv_protects_actual_category_names_and_keeps_negative_numbers(monkeypatch) -> None:
    store = InMemoryStore()
    monkeypatch.setattr(reports, "store", store)
    portfolio = store.create_portfolio(PortfolioCreate(name="CSV"))
    account = store.create_account(AccountCreate(portfolio_id=portfolio.id, name="Konto", account_type="bank"))
    category = store.create_category(CategoryCreate(
        portfolio_id=portfolio.id, name='  =HYPERLINK("example.invalid","Öztürk")\r\nZweite Zeile',
        category_type="expense"))
    store.create_booking(BookingCreate(account_id=account.id, category_id=category.id,
                                       booking_date=date(2026, 1, 2), amount=-123.45))
    response = reports.get_finance_report(format="csv")
    rows = list(csv.DictReader(io.StringIO(bytes(response.body).decode()), delimiter=";"))
    assert len(rows) == 1
    assert rows[0]["Kategorie"] == "'" + category.name
    assert rows[0]["Betrag"] == "-123.45"
    assert rows[0]["Typ"] == "expense"
