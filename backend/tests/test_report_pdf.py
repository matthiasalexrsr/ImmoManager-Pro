"""The PDF must carry the selected data and every row, including long Unicode labels."""

from datetime import date
from io import BytesIO

import pdfplumber
import pytest
from fastapi.testclient import TestClient

from backend import auth
from backend.app import app
from backend.concurrency import note_change
from backend.dependencies import store
from backend.models import AccountCreate, BookingCreate, PortfolioCreate, PropertyCreate, UnitCreate
from backend.services.report_render import render_report_pdf


@pytest.fixture
def estate():
    auth.clear_users()
    store.clear_all()
    note_change()
    owner = auth.register_user("pdfowner", "pdf@example.com", "PDF Owner", "Secret123", "eigentuemer")
    headers = {"Authorization": f"Bearer {auth.create_access_token(owner.id)}"}
    pf = store.create_portfolio(PortfolioCreate(name="PDF Portfolio"))
    acc = store.create_account(AccountCreate(portfolio_id=pf.id, name="PDF Bank", account_type="bank"))
    props = [store.create_property(PropertyCreate(portfolio_id=pf.id, name=name,
                                                   property_type="residential")) for name in ("Haus Nord", "Haus Süd")]
    units = [store.create_unit(UnitCreate(property_id=p.id, label=name, unit_type="residential"))
             for p, name in zip(props, ("Wohnung Nord", "Wohnung Süd"))]
    for p, u, day, amount in ((props[0], units[0], date(2026, 1, 2), 123.45),
                              (props[0], units[0], date(2026, 2, 2), 777.77),
                              (props[1], units[1], date(2026, 1, 2), 888.88)):
        store.create_booking(BookingCreate(account_id=acc.id, property_id=p.id, unit_id=u.id,
                                           booking_date=day, amount=amount))
    yield TestClient(app), headers, pf, props, units
    store.clear_all()
    auth.clear_users()
    note_change()


def text_of(content):
    with pdfplumber.open(BytesIO(content)) as pdf:
        return "\n".join(p.extract_text() or "" for p in pdf.pages)


@pytest.mark.parametrize("report", ["summary", "finance", "cashflow", "receivables-aging", "period-result"])
def test_report_pdf_uses_json_filters(estate, report):
    client, headers, pf, props, units = estate
    params = {"date_from": "2026-01-01", "date_to": "2026-01-31", "portfolio_id": pf.id,
              "property_id": props[0].id, "unit_id": units[0].id}
    response = client.get(f"/api/v1/reports/pdf/{report}", params=params, headers=headers)
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "application/pdf"
    text = text_of(response.content)
    assert "2026-01-01 bis 2026-01-31" in text
    assert "Haus Nord" in text and "Wohnung Nord" in text and "PDF Portfolio" in text
    assert "777,77" not in text and "888,88" not in text
    if report in {"summary", "finance", "cashflow"}:
        assert "123,45 EUR" in text


def test_pdf_rejects_ignored_filters_and_applies_occupancy_selection(estate):
    client, headers, _, props, _ = estate
    for params in ({"date_from": "2027-01-01", "date_to": "2026-01-01"},):
        assert client.get("/api/v1/reports/pdf/cashflow", params=params, headers=headers).status_code == 422
    assert client.get("/api/v1/reports/pdf/occupancy?date_from=2026-01-01", headers=headers).status_code == 422
    assert client.get("/api/v1/reports/pdf/finance?months=12", headers=headers).status_code == 422
    assert client.get("/api/v1/reports/pdf/unknown", headers=headers).status_code == 400
    params = {"property_id": props[0].id}
    data = client.get("/api/v1/reports/occupancy", params=params, headers=headers).json()
    assert data["totalUnits"] == 1
    pdf = client.get("/api/v1/reports/pdf/occupancy", params=params, headers=headers)
    assert "Haus Nord" in text_of(pdf.content)
    missing = client.get("/api/v1/reports/pdf/cashflow?property_id=missing", headers=headers)
    assert missing.status_code == 200
    assert "Nicht verfügbar" in text_of(missing.content)


def test_pdf_months_alias_matches_cashflow_json(estate):
    client, headers, *_ = estate
    from backend.routers import reports
    expected = reports.get_cashflow_report(months=12)
    response = client.get("/api/v1/reports/pdf/cashflow?months=12", headers=headers)
    assert response.status_code == 200
    text = text_of(response.content)
    assert expected["filters"]["date_from"] in text
    assert expected["filters"]["date_to"] in text


def test_pdf_does_not_disclose_other_portfolio_labels_or_amounts(estate):
    client, _, _, props, units = estate
    other = store.create_portfolio(PortfolioCreate(name="Visible portfolio"))
    staff = auth.register_user("pdfstaff", "pdfstaff@example.com", "Staff", "Secret123", "readonly",
                               portfolio_access="selected", portfolio_ids=[other.id])
    headers = {"Authorization": f"Bearer {auth.create_access_token(staff.id)}"}
    response = client.get("/api/v1/reports/pdf/cashflow", headers=headers,
                          params={"property_id": props[0].id, "unit_id": units[0].id})
    assert response.status_code == 200
    text = text_of(response.content)
    assert "Haus Nord" not in text and "Wohnung Nord" not in text
    assert "123,45" not in text and "777,77" not in text
    assert "Nicht verfügbar" in text and "0,00 EUR" in text


def test_long_unicode_labels_and_all_rows_fit_pages():
    name = "Äußere Straße <Nord> & Süd " * 18 + " ENDE-Łukasz-Жан"
    data = {"totalsByCategory": [{"categoryName": f"{i:03d} {name}", "categoryType": "income", "total": 1.25}
                                 for i in range(40)], "bookingsTotal": 50, "filters": {}}
    content = render_report_pdf("finance", data)
    with pdfplumber.open(BytesIO(content)) as pdf:
        assert len(pdf.pages) > 1
        text = "\n".join(page.extract_text() or "" for page in pdf.pages)
        assert text.count("ENDE-Łukasz-Жан") == 40
        assert "000" in text and "039" in text
        assert "<Nord> & Süd" in text
        for page in pdf.pages:
            assert all(40 <= c["x0"] and c["x1"] <= page.width - 40 for c in page.chars)
            assert all(c["top"] >= 30 and c["bottom"] <= page.height - 20 for c in page.chars)


def test_empty_report_is_a_real_pdf():
    data = {"totalsByCategory": [], "bookingsTotal": 0, "filters": {}}
    text = text_of(render_report_pdf("finance", data))
    assert "Keine Einträge" in text and "0,00 EUR" in text
