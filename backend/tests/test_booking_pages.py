"""Server pages must preserve complete financial meaning without full browser lists."""
import csv
import io
import json
from datetime import date, timedelta
from urllib.parse import urlencode

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event
from test_ownership_changes import estate  # noqa: F401

from backend import auth
from backend.app import app
from backend.dependencies import store
from backend.services import booking_pages


def seed(estate, count=31):  # noqa: F811
    account = estate["post"]("/accounts", {"portfolio_id": estate["pf"], "name": "Seitenkonto", "account_type": "bank"})
    records = [estate["post"]("/bookings", {"account_id": account["id"], "property_id": estate["house"],
               "booking_date": (date(2026, 1, 1) + timedelta(days=index)).isoformat(), "amount": index + 1,
               "payment_text": f"Quelle {index:03d}"}) for index in range(count)]
    return account, records


def request(estate, **options):  # noqa: F811
    return estate["call"]("GET", "/bookings/page?" + urlencode(options))


def test_page_totals_cover_records_beyond_the_visible_slice(estate):  # noqa: F811
    _, records = seed(estate)
    first = request(estate, skip=0, limit=10, sort_by="payment_text", sort_order="asc")
    second = request(estate, skip=10, limit=10, sort_by="payment_text", sort_order="asc")
    assert first["total"] == second["total"] == 31
    assert first["summary"] == second["summary"] == {"count": 31, "income": 496, "expense": 0,
        "withdrawal": 0, "contribution": 0, "no_category": 31, "no_receipt": 31}
    assert [row["id"] for row in first["items"]] == [row["id"] for row in records[:10]]
    assert [row["id"] for row in second["items"]] == [row["id"] for row in records[10:20]]
    assert len(first["items"]) == len(second["items"]) == 10


def test_search_and_cashflow_filters_are_applied_before_paging(estate):  # noqa: F811
    account, _ = seed(estate, 12)
    cost = estate["post"]("/categories", {"portfolio_id": estate["pf"], "name": "Kosten", "category_type": "expense"})
    for amount, text in [(-120, "Anlage %_Literal"), (20, "Erstattung %_Literal")]:
        estate["post"]("/bookings", {"account_id": account["id"], "category_id": cost["id"],
                      "property_id": estate["house"], "booking_date": "2026-02-01", "amount": amount, "payment_text": text})
    page = request(estate, search="%_Literal", flow="expense", limit=1)
    assert page["total"] == 2 and len(page["items"]) == 1
    assert page["summary"]["expense"] == 100 and page["summary"]["count"] == 2
    assert request(estate, search="%_Literal", flow="income")["total"] == 0
    assert request(estate, search="01.02.2026")["total"] == 2


def test_owner_pages_and_complete_csv_use_canonical_owner_parts(estate):  # noqa: F811
    _, records = seed(estate)
    estate["share"]("Linda", 100)
    owner = estate["people"]["Linda"]
    page = request(estate, owner_contact_id=owner, skip=20, limit=10, sort_by="payment_text", sort_order="asc")
    assert page["total"] == 31 and page["summary"]["income"] == 496
    assert [row["id"] for row in page["items"]] == [row["id"] for row in records[20:30]]
    assert [row["owner_part"] for row in page["items"]] == list(range(21, 31))
    owner_user = auth.register_user("csv_reader", "csv@example.test", "CSV", "Synthetic123!", "readonly")
    with TestClient(app, headers={"Authorization": "Bearer " + auth.create_access_token(owner_user.id)}) as client:
        response = client.get("/api/v1/bookings/page/export", params={"owner_contact_id": owner,
            "sort_by": "payment_text", "sort_order": "asc", "columns": "payment_text,owner_part"})
    assert response.status_code == 200 and response.content.startswith(b"\xef\xbb\xbf")
    rows = list(csv.reader(io.StringIO(response.content.decode("utf-8-sig")), delimiter=";"))
    assert rows[0] == ["Buchungstext", "Anteil des Eigentümers (€)"]
    assert len(rows) == 32 and rows[-1] == ["Quelle 030", "31,00"]


def test_saved_column_ranges_and_names_filter_the_complete_selection(estate):  # noqa: F811
    seed(estate, 31)
    filters = {"booking_date": ["2026-01-03", "2026-01-09"], "amount": ["4", "8"], "account_name": "seiten"}
    data = request(estate, column_filters=json.dumps(filters), skip=2, limit=2, sort_by="amount", sort_order="asc")
    assert data["total"] == data["summary"]["count"] == 5
    assert data["summary"]["income"] == 30
    assert [row["amount"] for row in data["items"]] == [6, 7]
    estate["call"]("GET", "/bookings/page?" + urlencode({"column_filters": json.dumps({"amount": ["NaN", "9"]})}), expected=422)


def test_unassigned_filter_uses_cash_budget_without_misclassifying_nontenant_money(estate):  # noqa: F811
    account, _ = seed(estate, 1)
    tenant = estate["post"]("/tenants", {"full_name": "Zahlung ohne Vertrag"})
    unassigned = estate["post"]("/bookings", {"account_id": account["id"], "tenant_id": tenant["id"],
        "booking_date": "2026-01-01", "amount": 50, "payment_text": "Noch zu klären"})
    data = request(estate, flow="unassigned")
    assert data["total"] == 1 and [row["id"] for row in data["items"]] == [unassigned["id"]]
    assert data["summary"]["count"] == 2 and data["summary"]["income"] == 51


@pytest.mark.skipif(not hasattr(store, "db"), reason="HTTP cache/query budget requires the SQL matrix")
def test_authenticated_http_owner_page_two_reuses_materialization_and_writes_invalidate(estate, monkeypatch):  # noqa: F811
    account, records = seed(estate)
    estate["share"]("Linda", 100)
    owner = estate["people"]["Linda"]
    booking_pages._CACHE.clear()
    materialize = booking_pages._materialize
    calls = []

    def counted(*args, **kwargs):
        calls.append(1)
        return materialize(*args, **kwargs)

    monkeypatch.setattr(booking_pages, "_materialize", counted)
    first = request(estate, owner_contact_id=owner, skip=0, limit=10, sort_by="payment_text", sort_order="asc")
    statements = []

    def capture(connection, cursor, statement, parameters, context, executemany):
        statements.append((statement.lower(), parameters))

    engine = store.db.get_bind()
    event.listen(engine, "before_cursor_execute", capture)
    try:
        second = request(estate, owner_contact_id=owner, skip=10, limit=10, sort_by="payment_text", sort_order="asc")
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    assert calls == [1], "The actual authenticated request path rebuilt the complete owner selection"
    assert first["total"] == second["total"] == 31
    assert [r["id"] for r in second["items"]] == [r["id"] for r in records[10:20]]
    row_selects = [sql for sql, _ in statements if "bookings.payment_text" in sql and "from bookings" in sql]
    assert row_selects and all(" in (" in sql and "limit" in sql for sql in row_selects)
    estate["post"]("/bookings", {"account_id": account["id"], "property_id": estate["house"],
                  "booking_date": "2026-02-02", "amount": 50, "payment_text": "Neue Quelle"})
    assert request(estate, owner_contact_id=owner)["summary"]["income"] == 546
    assert len(calls) == 2


def test_scope_and_receipt_filters_do_not_expose_hidden_bookings_or_totals(estate):  # noqa: F811
    account, _ = seed(estate, 1)
    private = estate["post"]("/portfolios", {"name": "Ausgeblendeter Bestand"})
    hidden = estate["post"]("/accounts", {"portfolio_id": private["id"], "name": "Geheimkonto", "account_type": "bank"})
    estate["post"]("/bookings", {"account_id": hidden["id"], "booking_date": "2026-01-01", "amount": 999999, "payment_text": "Geheim"})
    estate["post"]("/bookings", {"account_id": account["id"], "booking_date": "2026-01-01", "amount": 2,
                  "receipt_url": "/uploads/../../secret", "payment_text": "Ungültiger Beleg"})
    estate["post"]("/bookings", {"account_id": account["id"], "booking_date": "2026-01-01", "amount": 3,
                  "receipt_url": "/uploads/receipt.pdf", "payment_text": "Beleg vorhanden"})
    user = auth.register_user("scoped_page", "scoped@example.test", "Beschränkt", "Synthetic123!", "readonly",
                              portfolio_access="selected", portfolio_ids=[estate["pf"]])
    with TestClient(app, headers={"Authorization": "Bearer " + auth.create_access_token(user.id)}) as client:
        data = client.get("/api/v1/bookings/page?flow=no_receipt").json()
        assert data["total"] == 2 and data["summary"]["income"] == 6
        assert {row["payment_text"] for row in data["items"]} == {"Quelle 000", "Ungültiger Beleg"}
        assert "Geheim" not in str(data)
