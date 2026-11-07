"""Whole-review source validation stays current while avoiding repeated SQL batches."""
from contextlib import ExitStack
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, event, insert, update
from sqlalchemy.orm import Session
from test_payment_allocation import client as client
from test_payment_allocation import yilmaz as yilmaz

from backend import concurrency
from backend.db import schema_state
from backend.db.finance_models import ReceivableSettlementORM
from backend.db.orm_models import AccountORM, BookingORM, PaymentAllocationORM
from backend.dependencies import store as app_store
from backend.models import (
    AccountCreate,
    ContractCreate,
    PortfolioCreate,
    PropertyCreate,
    ReceivableCreate,
    TenantCreate,
    UnitCreate,
)
from backend.repositories import SQLAlchemyStore
from backend.services import review as review_service
from backend.services.maintenance_rows import Rows
from backend.services.portfolio_scope import AccessScope, scope_context
from backend.services.receivable_residuals import cash_reserved
from backend.services.review import review_items
from backend.storage import NotFoundError


@pytest.fixture
def own_sources(tmp_path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'whole-review.db').as_posix()}")
    schema_state.initialise_empty(engine)
    try:
        with Session(engine) as db:
            store = SQLAlchemyStore(db)
            portfolio = store.create_portfolio(PortfolioCreate(name="Whole-review test"))
            account = store.create_account(AccountCreate(portfolio_id=portfolio.id, name="Own bank", account_type="bank"))
            yield engine, store, account
    finally:
        engine.dispose()


def source_row(account, identifier, **changes):
    return {"id": identifier, "account_id": account.id, "booking_date": date(2026, 1, 2),
            "amount": Decimal("1.01"), "status": "booked", **changes}


def add_sources(store, rows):
    store.db.execute(insert(BookingORM), rows)
    store.db.commit()


@pytest.fixture
def many_sources(own_sources):
    engine, store, account = own_sources
    add_sources(store, [source_row(account, f"whole-{index:05d}") for index in range(10001)])
    return engine, store, account


def source_reads(engine):
    """Observe only the canonical fresh booking-ID/parent authorization query."""
    queries = []

    def observe(_conn, _cursor, statement, _parameters, context, _many):
        expression = getattr(context.compiled, "statement", None)
        columns = getattr(expression, "selected_columns", ())
        if tuple(getattr(column, "key", None) for column in columns) == ("id", "reverses_booking_id"):
            queries.append((statement, _parameters))

    event.listen(engine, "before_cursor_execute", observe)
    return queries, observe


def test_whole_review_rechecks_all_10001_current_sources_in_one_scoped_projection(many_sources):
    engine, store, account = many_sources
    queries, observe = source_reads(engine)
    try:
        with scope_context(AccessScope("whole-review-reader", "readonly", False, (account.portfolio_id,))):
            items = review_items(store, date(2026, 1, 3))
    finally:
        event.remove(engine, "before_cursor_execute", observe)
    assert len(items) == 10001
    assert all(item["kind"] == "payment_without_tenant" for item in items)
    assert len(queries) == 1, "The whole review repeated its current source check in 500-ID batches"
    assert "WHERE" in queries[0][0]


def test_review_booking_projection_respects_scope_and_committed_edits(own_sources, monkeypatch):
    engine, store, account = own_sources
    other = store.create_portfolio(PortfolioCreate(name="Separate review portfolio"))
    foreign = store.create_account(AccountCreate(portfolio_id=other.id, name="Other bank", account_type="bank"))
    add_sources(store, [
        source_row(account, "visible", amount=Decimal("1.005"), tax_year=2026, payment_text="Visible cash"),
        source_row(foreign, "hidden", amount=Decimal("9.99"), payment_text="Other cash"),
    ])
    boundary = AccessScope("projection-reader", "readonly", False, (account.portfolio_id,))
    with scope_context(boundary):
        expected = review_items(store, date(2026, 1, 3))
        assert [item["entity_id"] for item in expected] == ["visible"]
        assert "1,01 €" in expected[0]["detail"]

    def unexpected_full_list():
        pytest.fail("A clean review should read the scoped booking fields directly")

    monkeypatch.setattr(store, "list_bookings", unexpected_full_list)
    with scope_context(boundary):
        assert review_items(store, date(2026, 1, 3)) == expected
    with Session(engine) as writer:
        writer.execute(update(BookingORM).where(BookingORM.id == "visible").values(amount=Decimal("2.005")))
        writer.commit()
    with scope_context(boundary):
        current = review_items(store, date(2026, 1, 3))
    assert [item["entity_id"] for item in current] == ["visible"]
    assert "2,01 €" in current[0]["detail"]


@pytest.mark.parametrize("case", ["missing", "foreign", "revoked", "empty_scope"])
def test_current_source_boundary_rejects_before_any_unscoped_settlement_read(own_sources, monkeypatch, case):
    _, store, account = own_sources
    other = store.create_portfolio(PortfolioCreate(name="Other portfolio"))
    foreign = store.create_account(AccountCreate(portfolio_id=other.id, name="Other bank", account_type="bank"))
    add_sources(store, [source_row(account, "requested"), source_row(foreign, "foreign")])
    boundary = AccessScope("restricted-reader", "readonly", False, (account.portfolio_id,))
    with scope_context(boundary):
        assert [row.id for row in store.list_bookings()] == ["requested"]
    if case == "revoked":
        # The previously visible row remains real, but its current account is no longer visible.
        store.db.execute(update(AccountORM).where(AccountORM.id == account.id).values(portfolio_id=other.id))
        store.db.commit()
    elif case == "empty_scope":
        boundary = AccessScope("restricted-reader", "readonly", False, ())
    key = case if case in {"missing", "foreign"} else "requested"
    attempted = []
    original = Rows.find

    def watch(self, table, **criteria):
        if table == "receivable_settlements":
            attempted.append(criteria)
        return original(self, table, **criteria)

    monkeypatch.setattr(Rows, "find", watch)
    with scope_context(boundary), pytest.raises(NotFoundError, match="Buchung nicht gefunden"):
        cash_reserved(store, {key}, whole_visible=True)
    assert attempted == []


def test_new_visible_rows_cannot_add_unrequested_original_sources(own_sources, monkeypatch):
    engine, store, account = own_sources
    add_sources(store, [source_row(account, "requested")])
    boundary = AccessScope("restricted-reader", "readonly", False, (account.portfolio_id,))
    with scope_context(boundary):
        wanted = {row.id for row in store.list_bookings()}
    add_sources(store, [source_row(account, "new-original"), source_row(account, "new-return",
        amount=Decimal("-0.01"), reverses_booking_id="new-original")])
    observed = []
    original = Rows.find

    def watch(self, table, **criteria):
        if table == "receivable_settlements":
            observed.append(set(criteria["booking_id"]))
        return original(self, table, **criteria)

    monkeypatch.setattr(Rows, "find", watch)
    queries, observe = source_reads(engine)
    try:
        with scope_context(boundary):
            assert cash_reserved(store, wanted, whole_visible=True) == {}
    finally:
        event.remove(engine, "before_cursor_execute", observe)
    assert len(queries) == 1 and "requested" not in queries[0][1], "The actual full projection must run"
    assert observed == [{"requested"}]


def test_requested_return_still_follows_its_real_original_and_exact_reservation(own_sources):
    _, store, account = own_sources
    prop = store.create_property(PropertyCreate(portfolio_id=account.portfolio_id, name="Own house", property_type="residential"))
    unit = store.create_unit(UnitCreate(property_id=prop.id, label="Own unit", unit_type="residential"))
    tenant = store.create_tenant(TenantCreate(full_name="Own test tenant"))
    contract = store.create_contract(ContractCreate(contract_number="WHOLE-REVIEW", property_id=prop.id,
        unit_id=unit.id, tenant_id=tenant.id, start_date=date(2025, 1, 1)))
    claim = store.create_receivable(ReceivableCreate(contract_id=contract.id, amount_due=60, due_date=date(2026, 1, 2)))
    add_sources(store, [source_row(account, "original", amount=Decimal("100.00")), source_row(account, "returned",
        amount=Decimal("-30.00"), booking_date=date(2026, 1, 3), reverses_booking_id="original")])
    store.db.execute(insert(ReceivableSettlementORM).values(id="settlement", receivable_id=claim.id, booking_id="original",
        amount=Decimal("60.00"), effective_date=date(2026, 1, 2), reason="Test reservation", request_hash="0" * 64,
        created_at=datetime(2026, 1, 2, tzinfo=timezone.utc)))
    store.db.commit()
    with scope_context(AccessScope("restricted-reader", "readonly", False, (account.portfolio_id,))):
        expected = cash_reserved(store, {"returned"})
        assert expected == {"returned": Decimal("-18.00")}
        assert cash_reserved(store, {"returned"}, whole_visible=True) == expected


@pytest.mark.parametrize("state", ["explicit", "nested", "snapshot", "private_connection", "new", "dirty", "deleted", "pending"])
def test_ineligible_sessions_keep_requested_id_recheck_without_flushing(own_sources, state):
    engine, original, account = own_sources
    add_sources(original, [source_row(account, "requested")])
    with ExitStack() as stack:
        db = original.db
        if state == "private_connection":
            connection = stack.enter_context(engine.connect())
            db = stack.enter_context(Session(connection))
        elif state == "explicit":
            stack.enter_context(db.begin())
        elif state == "nested":
            stack.enter_context(db.begin_nested())
        elif state == "snapshot":
            db.connection().exec_driver_sql("BEGIN")
        elif state == "new":
            db.add(BookingORM(**source_row(account, "unflushed")))
        elif state in {"dirty", "deleted"}:
            row = db.get(BookingORM, "requested")
            assert row is not None
            if state == "dirty":
                row.amount = Decimal("2.02")
            else:
                db.delete(row)
        else:
            db.info["cache_pending_write"] = True
        pending = (set(db.new), set(db.dirty), set(db.deleted))
        queries, observe = source_reads(engine)
        try:
            with db.no_autoflush:
                assert cash_reserved(SQLAlchemyStore(db), {"requested"}, whole_visible=True) == {}
            assert len(queries) == 1 and "requested" in queries[0][1]
            assert (set(db.new), set(db.dirty), set(db.deleted)) == pending
        finally:
            event.remove(engine, "before_cursor_execute", observe)
            if state not in {"explicit", "nested", "private_connection"}:
                db.rollback()


@pytest.mark.parametrize("kind", ["stored", "legacy_reversal", "fractional_cent"])
def test_real_review_response_matches_the_canonical_path_byte_for_byte(client, yilmaz, monkeypatch, kind):
    if kind == "fractional_cent" and not hasattr(app_store, "db"):
        pytest.skip("Legacy fractional-cent stored values are an SQLite fixture")
    booking = client.post("/api/v1/bookings", json={"account_id": yilmaz["account"]["id"],
        "tenant_id": yilmaz["tenant"]["id"], "booking_date": "2025-12-23", "amount": 1600.17}).json()
    if kind == "legacy_reversal":
        returned = client.post(f"/api/v1/bookings/{booking['id']}/reverse", json={"booking_date": "2025-12-27", "amount": 0.01})
        assert returned.status_code == 201, returned.text
        for allocation in app_store.list_payment_allocations(booking_id=returned.json()["id"]):
            app_store.delete_payment_allocation(allocation.id)
    elif kind == "fractional_cent":
        allocation = app_store.list_payment_allocations(booking_id=booking["id"])[0]
        app_store.db.execute(update(PaymentAllocationORM).where(PaymentAllocationORM.id == allocation.id).values(amount=0.005))
        app_store.db.commit()
    original = review_service.accounted_by_booking

    def canonical(store, bookings, **_options):
        return original(store, bookings)

    with monkeypatch.context() as patch:
        patch.setattr(review_service, "accounted_by_booking", canonical)
        patch.setattr(review_service._ReviewReads, "review_bookings", review_service._ReviewReads.list_bookings)
        expected = client.get("/api/v1/review", params={"as_of": "2025-12-31"})
    concurrency.note_write()  # force the independently computed second response
    current = client.get("/api/v1/review", params={"as_of": "2025-12-31"})
    assert current.status_code == expected.status_code == 200
    assert current.content == expected.content
    assert any(item["entity_id"] == booking["id"] and item["kind"] == "turn_of_year_payment" for item in current.json()["items"])
