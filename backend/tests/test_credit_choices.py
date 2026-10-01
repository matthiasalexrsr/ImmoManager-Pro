"""Live credit choices remain bounded, scoped and recoverable across pages."""

from datetime import date

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import event

from backend.models import AccountCreate, BookingCreate, ContractCreate, ReceivableCreate
from backend.routers import billing
from backend.services.booking_lookup import BookingLookupQuery
from backend.services.booking_query import BookingQueryError
from backend.services.credit_choices import credit_choices
from backend.services.portfolio_scope import AccessScope, scope_context
from backend.storage import NotFoundError
from backend.tests.test_payments import payload, payment_store, seed  # noqa: F401


def seed_other(active, contract, kind):
    active.update_contract(contract.id, ContractCreate(**{
        **contract.model_dump(include=set(ContractCreate.model_fields)), "contract_number": "synthetic-first"}))
    return seed(active, kind)


def test_all_target_pages_preserve_cents_selected_choice_and_contract_boundary(payment_store):  # noqa: F811
    active = payment_store
    target = seed(active, "rent_charge")
    contract = active.get_contract(target.contract_id)
    other = seed_other(active, contract, "receivable")
    rows = [active.create_receivable(ReceivableCreate(contract_id=contract.id, due_date=date(2026, 10, 1),
            description="Synthetic choice " + str(index), amount_due=100.30)) for index in range(81)]
    active.record_payment("receivable", rows[0].id, payload("40.10"))
    active.record_payment("receivable", rows[1].id, payload("100.30"))
    ids, cursor = [], None
    for _ in range(20):
        page = credit_choices(active, contract.id, "receivable", BookingLookupQuery(page_size=7, cursor=cursor))
        assert len(page.items) <= 7
        ids.extend(row.id for row in page.items)
        if not page.has_more:
            break
        assert page.next_cursor
        cursor = page.next_cursor
    assert len(ids) == len(set(ids)) == 80
    assert set(ids) == {row.id for row in rows} - {rows[1].id}
    assert other.id not in ids
    filtered = credit_choices(active, contract.id, "receivable",
        BookingLookupQuery(search="does not match", selected_id=rows[0].id))
    assert filtered.items == [] and filtered.selected.available_amount == "60.20"
    paid = credit_choices(active, contract.id, "receivable", BookingLookupQuery(selected_id=rows[1].id))
    assert paid.selected is None
    rental = credit_choices(active, contract.id, "rent_charge", BookingLookupQuery())
    assert rental.items[0].id == target.id and rental.items[0].available_amount == "100.30"
    assert [row.id for row in credit_choices(active, contract.id, "rent_charge",
        BookingLookupQuery(search="2026-09")).items] == [target.id]
    assert credit_choices(active, contract.id, "rent_charge", BookingLookupQuery(search="2025-09")).items == []
    first = credit_choices(active, contract.id, "receivable", BookingLookupQuery(page_size=7))
    with pytest.raises(BookingQueryError) as error:
        credit_choices(active, other.contract_id, "receivable", BookingLookupQuery(page_size=7, cursor=first.next_cursor))
    assert error.value.clear_code == "cursor_filter_mismatch"


def test_bank_choices_apply_account_and_explicit_contract_assignments(payment_store):  # noqa: F811
    active = payment_store
    target = seed(active, "rent_charge")
    contract = active.get_contract(target.contract_id)
    portfolio = active.get_property(contract.property_id).portfolio_id
    other = seed_other(active, contract, "rent_charge")
    other_contract = active.get_contract(other.contract_id)
    account = active.create_account(AccountCreate(portfolio_id=portfolio, name="Synthetic", account_type="bank"))
    foreign_account = active.create_account(AccountCreate(
        portfolio_id=active.get_property(other_contract.property_id).portfolio_id, name="Foreign", account_type="bank"))
    valid = active.create_booking(BookingCreate(account_id=account.id, booking_date=date(2026, 10, 1), amount=-100.30, payment_text="Search% literal"))
    excluded = [active.create_booking(BookingCreate(account_id=foreign_account.id, booking_date=date(2026, 10, 1), amount=-200)),
        active.create_booking(BookingCreate(account_id=account.id, tenant_id=other_contract.tenant_id, booking_date=date(2026, 10, 1), amount=-200)),
        active.create_booking(BookingCreate(account_id=account.id, booking_date=date(2026, 10, 1), amount=200))]
    page = credit_choices(active, contract.id, "booking", BookingLookupQuery(search="Search%"))
    assert [(row.id, row.available_amount) for row in page.items] == [(valid.id, "100.30")]
    assert all(row.id not in {item.id for item in excluded} for row in page.items)
    assert [row.id for row in credit_choices(active, contract.id, "booking",
        BookingLookupQuery(search="2026-10-01")).items] == [valid.id]
    with scope_context(AccessScope("synthetic", "buchhaltung", False, (portfolio,))):
        assert credit_choices(active, contract.id, "booking", BookingLookupQuery(selected_id=excluded[0].id)).selected is None
        with pytest.raises(NotFoundError):
            credit_choices(active, other_contract.id, "booking", BookingLookupQuery())


def test_sql_choices_fetch_only_one_bounded_page(payment_store):  # noqa: F811
    if not hasattr(payment_store, "db"):
        pytest.skip("SQL query shape requires the SQL backend")
    target = seed(payment_store, "receivable")
    seen = []
    engine = payment_store.db.get_bind()
    def record(connection, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            seen.append((statement, parameters))
    event.listen(engine, "before_cursor_execute", record)
    try:
        credit_choices(payment_store, target.contract_id, "receivable", BookingLookupQuery(page_size=2))
    finally:
        event.remove(engine, "before_cursor_execute", record)
    queries = [statement for statement, parameters in seen if "FROM receivables" in statement]
    assert len(queries) == 1 and "LIMIT" in queries[0] and "WHERE" in queries[0]
    assert len(seen) <= 4 and all("count(" not in sql.lower() for sql, _ in seen)


def test_http_invalid_cursor_has_machine_readable_recovery_code(payment_store, monkeypatch):  # noqa: F811
    target = seed(payment_store, "receivable")
    monkeypatch.setattr(billing, "store", payment_store)
    app = FastAPI()
    app.include_router(billing.router)
    with TestClient(app) as client:
        response = client.get(f"/billing/contracts/{target.contract_id}/credit-choices/receivable?cursor=invalid")
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "cursor_invalid"
