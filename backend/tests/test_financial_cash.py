"""Cash provenance, exact money, context filters, source change and complete export."""

import csv
import io
from datetime import date, datetime, timezone
from decimal import Decimal
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi import HTTPException
from sqlalchemy import event

from backend.db.orm_models import BookingORM
from backend.models import (
    AccountCreate,
    Booking,
    BookingCreate,
    CategoryCreate,
    PortfolioCreate,
    PropertyCreate,
    UnitCreate,
)
from backend.services import financial_cash as service
from backend.services.payments import PaymentCreate
from backend.services.report_service import compute_liquidity_forecast
from backend.tests.test_contract_workspace import active as active
from backend.tests.test_payments import seed as payment_target
from backend.tests.test_portfolio_access_http import access_http as access_http


def setup(store):
    portfolio = store.create_portfolio(PortfolioCreate(name="Finance synthetic"))
    prop = store.create_property(PropertyCreate(portfolio_id=portfolio.id, name="Finance source", property_type="residential"))
    unit = store.create_unit(UnitCreate(property_id=prop.id, label="Source unit", unit_type="apartment"))
    account = store.create_account(AccountCreate(portfolio_id=portfolio.id, name="Source account", account_type="bank", opening_balance=23.45))
    category = store.create_category(CategoryCreate(portfolio_id=portfolio.id, name="Rental", category_type="income"))
    return portfolio, prop, unit, account, category


def booking(store, account, amount, **values):
    return store.create_booking(BookingCreate(account_id=account.id, amount=amount,
        **({"booking_date": date(2026, 1, 1), "status": "confirmed"} | values)))


def test_exact_cash_context_and_unassigned_object_costs(active):
    portfolio, prop, unit, account, category = setup(active)
    booking(active, account, .1, property_id=prop.id, unit_id=unit.id, category_id=category.id)
    booking(active, account, .2, unit_id=unit.id, category_id=category.id)
    booking(active, account, -.1, property_id=prop.id)
    booking(active, account, -5, property_id=prop.id, status="open")
    booking(active, account, 20, status="cancelled")
    booking(active, account, 50, booking_date=date(2027, 1, 1))
    filters = service.CashFilters(portfolio_id=portfolio.id, date_from="2026-01-01", date_to="2027-12-31", as_of="2026-10-03")
    total = service.report(active, filters)
    assert (total["income"], total["expense"], total["net"], total["currency"]) == ("0.30", "0.10", "0.20", "EUR")
    assert (total["source_count"], total["excluded_count"]) == (3, 3)
    assert {(row["unit_id"], row["net"]) for row in total["locations"]} == {(unit.id, "0.30"), (None, "-0.10")}
    unit_report = service.report(active, filters.model_copy(update={"unit_id": unit.id}))
    assert unit_report["net"] == "0.30"
    object_report = service.report(active, filters.model_copy(update={"property_ids": [prop.id]}))
    assert object_report["net"] == "0.20"
    page = service.report(active, filters, details=True)
    assert sorted(row["exclusion_reason"] for row in page["items"] if not row["included"]) == ["after_cutoff", "cancelled", "unconfirmed"]
    csv_rows = list(csv.DictReader(io.StringIO(b"".join(service.csv_chunks(active, filters)).decode("utf-8-sig")), delimiter=";"))
    assert len(csv_rows) == 6
    assert sum(service.cents(row["amount"]) for row in csv_rows if row["included"] == "True") == service.cents(total["net"])


def test_cash_sources_are_complete_and_detect_changed_source_and_cursor(active):
    _, _, _, account, _ = setup(active)
    stamp = datetime.now(timezone.utc)
    rows = [{**BookingCreate(account_id=account.id, booking_date=date(2026, 1, 1), status="confirmed", amount=.01).model_dump(),
             "id": f"cash-{index:06d}", "allocated_amount": 0, "created_at": stamp, "updated_at": stamp}
            for index in range(10_001)]
    if hasattr(active, "db"):
        active.db.execute(BookingORM.__table__.insert(), rows)
        active.db.commit()
    else:
        active.__dict__["bookings"].update({row["id"]: Booking.model_validate(row) for row in rows})
    filters = service.CashFilters(account_id=account.id, as_of=date(2026, 10, 3))
    first = service.report(active, filters, details=True, limit=500)
    assert first["net"] == "100.01"
    assert first["source_count"] == 10_001
    assert first["has_more"]
    with pytest.raises(HTTPException) as missing:
        service.report(active, filters, after=first["next_after"], details=True, limit=500)
    assert missing.value.status_code == 422
    second = service.report(active, filters, after=first["next_after"], source_hash=first["source_hash"], details=True, limit=500)
    assert second["items"][0]["id"] == "cash-000500"
    assert second["source_hash"] == first["source_hash"]
    csv_rows = list(csv.DictReader(io.StringIO(b"".join(service.csv_chunks(active, filters)).decode("utf-8-sig")), delimiter=";"))
    assert len(csv_rows) == len(set(row["id"] for row in csv_rows)) == 10_001
    assert csv_rows[-1]["id"] == "cash-010000"
    booking(active, account, .05)
    with pytest.raises(HTTPException) as stale:
        service.report(active, filters, after=second["next_after"], source_hash=second["source_hash"], details=True, limit=500)
    assert stale.value.status_code == 409


def test_invalid_amount_and_broken_sources_cannot_return_zero(active):
    _, _, _, account, _ = setup(active)
    row = booking(active, account, .1)
    filters = service.CashFilters()
    if hasattr(active, "db"):
        def fail(_connection, _cursor, statement, *_args):
            if "FROM bookings" in statement:
                raise RuntimeError("Synthetic financial source unavailable")
        engine = active.db.get_bind()
        event.listen(engine, "before_cursor_execute", fail)
        try:
            with pytest.raises(RuntimeError, match="financial source unavailable"):
                service.report(active, filters)
        finally:
            event.remove(engine, "before_cursor_execute", fail)
    else:
        active.__dict__["bookings"][row.id] = row.model_copy(update={"amount": float("nan")})
        with pytest.raises(HTTPException) as bad:
            service.report(active, filters)
        assert bad.value.status_code == 409


def test_cash_http_pages_filters_and_current_permissions(access_http):
    client, store, owner_headers, member_headers, member, portfolios, properties, *_ = access_http
    account = store.create_account(AccountCreate(portfolio_id=portfolios[0].id, name="CashHTTP", account_type="bank"))
    for index in range(3):
        booking(store, account, .1, property_id=properties[0].id, payment_text=f"HTTP-{index}")
    params = {"account_id": account.id, "date_from": "2026-01-01", "date_to": "2026-12-31"}
    response = client.get("/api/v1/reports/cash", headers=member_headers, params=params)
    assert response.status_code == 200, response.text
    assert response.json()["net"] == "0.30"
    assert response.headers["cache-control"] == "private, no-store"
    legacy = client.get("/api/v1/reports/finance", headers=member_headers, params={
        "property_id": properties[0].id, "portfolio_id": portfolios[0].id, "date_from": "2026-01-01", "date_to": "2026-12-31"})
    assert legacy.status_code == 200, legacy.text
    provenance = legacy.json()
    source_query = parse_qs(urlsplit(provenance["source_url"]).query)
    assert source_query["basis"] == ["recorded_bookings"]
    assert source_query["property_ids"] == [properties[0].id]
    matched = client.get(provenance["source_url"], headers=member_headers)
    assert matched.status_code == 200, matched.text
    assert matched.json()["source_hash"] == provenance["source_hash"]
    assert matched.json()["net"] == provenance["exactTotal"]
    page = client.get("/api/v1/reports/cash/sources", headers=member_headers, params=params | {"limit": 2})
    assert page.status_code == 200, page.text
    body = page.json()
    second_params = params | {"limit": 2, "source_hash": body["source_hash"], "after": body["next_after"]}
    second = client.get("/api/v1/reports/cash/sources", headers=member_headers, params=second_params)
    assert second.status_code == 200, second.text
    assert len(second.json()["items"]) == 1
    assert client.get("/api/v1/reports/cash", headers=member_headers, params=params | {"date_to": "2025-01-01"}).status_code == 422
    changed = client.patch(f"/api/v1/auth/users/{member.id}", headers=owner_headers,
        json={"portfolio_access": "selected", "portfolio_ids": []})
    assert changed.status_code == 200
    assert client.get("/api/v1/reports/cash/sources", headers=member_headers, params=second_params).status_code in {403, 404, 422}


def test_cent_accumulator_has_no_artificial_total_capacity_or_float_rounding():
    assert service.money(service.cents("9999999999.99") * 1_000_000) == "9999999999990000.00"
    assert service.cents("-0.10") + service.cents("0.20") == 10
    with pytest.raises(ValueError, match="fractional_cent"):
        service.cents("1.001")


def test_forecast_twelve_full_months_include_zero_and_expense_only_months(active):
    _, _, _, account, _ = setup(active)
    for amount, day, status in ((120, "2025-10-01", "confirmed"), (-60, "2026-02-01", "confirmed"),
                               (1000, "2026-10-01", "confirmed"), (9999, "2026-11-01", "confirmed"),
                               (7777, "2026-01-01", "cancelled")):
        booking(active, account, amount, booking_date=date.fromisoformat(day), status=status)
    result = compute_liquidity_forecast(bookings=active.list_bookings(), today=date(2026, 10, 3),
        months=241, starting_balance="23.45")
    assert result["history_months"] == 12
    assert (result["history_from"], result["history_until"]) == ("2025-10-01", "2026-10-01")
    assert result["exact"] == {"current_balance": "23.45", "avg_monthly_income": "10.00",
        "avg_monthly_expense": "5.00", "avg_monthly_net": "5.00"}
    assert result["forecast"][0]["exact"]["balance"] == "28.45"
    assert result["forecast"][-1]["exact"]["balance"] == "1228.45"
    assert result["balance_basis"] == "explicit_scenario_start"
    stored = compute_liquidity_forecast(bookings=active.list_bookings(), today=date(2026, 10, 3))
    assert stored["exact"]["current_balance"] == "1060.00"
    assert stored["opening_balance_included"] is False


def test_cash_context_rejects_foreign_or_conflicting_selection(active):
    _, _, unit, account, _ = setup(active)
    foreign = active.create_portfolio(PortfolioCreate(name="Foreign finance"))
    with pytest.raises(HTTPException) as invalid:
        service.report(active, service.CashFilters(portfolio_id=foreign.id, unit_id=unit.id))
    assert invalid.value.status_code == 422
    assert service.report(active, service.CashFilters(account_id=account.id))["net"] == "0.00"


def test_linked_payment_receipt_does_not_duplicate_its_bank_booking(active):
    target = payment_target(active, "receivable")
    prop = active.get_property(active.get_contract(target.contract_id).property_id)
    account = active.create_account(AccountCreate(portfolio_id=prop.portfolio_id, name="Linked source", account_type="bank"))
    row = booking(active, account, "40.10")
    payment = active.record_payment("receivable", target.id, PaymentCreate(idempotency_key="cash-linked-receipt",
        amount=Decimal("40.10"), payment_date=date(2026, 1, 1), booking_id=row.id))
    report = service.report(active, service.CashFilters(account_id=account.id))
    assert report["net"] == "40.10"
    assert report["source_count"] == 1
    assert payment.booking_id == row.id
    assert report["source_count"] == len(service.report(active, service.CashFilters(account_id=account.id), details=True)["items"])


def test_financial_reference_choices_are_complete_scoped_and_portfolio_filtered(access_http):
    client, store, _owner, member, _user, portfolios, properties, *_ = access_http
    accounts = [store.create_account(AccountCreate(portfolio_id=portfolios[0].id, name=f"Financial choice {index:03}", account_type="bank"))
        for index in range(27)]
    params = {"portfolio_id": portfolios[0].id, "search": "Financial choice", "page_size": 25, "selected_id": accounts[0].id}
    first = client.get("/api/v1/workflow-references/accounts", headers=member, params=params)
    assert first.status_code == 200, first.text
    first_data = first.json()
    assert len(first_data["items"]) == 25 and first_data["has_more"]
    assert first_data["selected"]["id"] == accounts[0].id
    second = client.get("/api/v1/workflow-references/accounts", headers=member, params=params | {"cursor": first_data["next_cursor"]})
    assert second.status_code == 200, second.text
    assert len(second.json()["items"]) == 2 and second.json()["has_more"] is False
    assert len({row["id"] for row in first_data["items"] + second.json()["items"]}) == 27
    available = client.get("/api/v1/workflow-references/portfolios", headers=member)
    assert available.status_code == 200, available.text
    assert [row["id"] for row in available.json()["items"]] == [portfolios[0].id]
    property_page = client.get("/api/v1/workflow-references/properties", headers=member, params={"portfolio_id": portfolios[0].id})
    assert property_page.status_code == 200, property_page.text
    assert [row["id"] for row in property_page.json()["items"]] == [properties[0].id]
    assert client.get("/api/v1/workflow-references/accounts", headers=member, params={"portfolio_id": portfolios[1].id}).status_code == 404
    assert client.get("/api/v1/workflow-references/accounts", headers=member, params={"unit_id": "unknown"}).status_code == 422
