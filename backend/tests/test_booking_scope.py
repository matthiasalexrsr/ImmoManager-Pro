"""Actual Core/HTTP reads and private snapshot streams keep captured grants."""

from datetime import date

import pytest
from fastapi import HTTPException
from sqlalchemy import update
from sqlalchemy.orm import sessionmaker

from backend import auth, dependencies
from backend.db.orm_models import BookingORM, PropertyORM
from backend.models import AccountCreate, BookingCreate
from backend.repositories.sql_store import SQLAlchemyStore
from backend.services.booking_export import booking_csv_chunks
from backend.services.booking_legacy import legacy_booking_list
from backend.services.booking_lookup import BookingLookupQuery, booking_choices
from backend.services.booking_query import (
    BookingFilters,
    BookingPageQuery,
    BookingQueryError,
    booking_statement,
    get_booking_page,
)
from backend.services.portfolio_scope import AccessScope, scope_context, scope_from_user
from backend.tests.test_booking_export import parsed_csv
from backend.tests.test_portfolio_access_http import access_http  # noqa: F401
from backend.tests.test_portfolio_scope import scoped_store  # noqa: F401
from backend.tests.test_private_server_concurrency import postgres_database  # noqa: F401


def _seed_bookings(store, portfolios, properties):
    with scope_context(None):
        accounts = [store.create_account(AccountCreate(portfolio_id=p.id, name=f"Bank {index}", account_type="bank"))
                    for index, p in enumerate(portfolios)]
        bookings = [[store.create_booking(BookingCreate(account_id=account.id, property_id=prop.id,
                    booking_date=date(2026, 9, 1 + offset), amount=100, payment_text=f"Private {index}-{offset}"))
                    for offset in range(3)] for index, (account, prop) in enumerate(zip(accounts, properties))]
    return accounts, bookings


@pytest.fixture
def booking_access(scoped_store, monkeypatch):  # noqa: F811 - imported pytest fixture
    store, engine, _, portfolios, properties, *_ = scoped_store
    factory = sessionmaker(engine)
    user_store = auth.SQLUserStore(factory) if hasattr(store, "db") else auth.InMemoryUserStore()
    monkeypatch.setattr(auth, "_user_store", user_store)
    monkeypatch.setattr(auth, "_auth_session_factory", factory if hasattr(store, "db") else None)
    monkeypatch.setattr(dependencies, "store", store)
    if engine.dialect.name == "sqlite":
        # Permit an independent writer while a private read snapshot is open.
        with engine.connect() as connection:
            connection.exec_driver_sql("PRAGMA journal_mode=WAL")
    with scope_context(None):
        member = auth.register_user("member", "member@example.test", "Synthetic member", "StrongPass123!", "verwalter",
                                    portfolio_access="selected", portfolio_ids=[portfolios[0].id])
    accounts, bookings = _seed_bookings(store, portfolios, properties)
    captured = scope_from_user(auth.get_user_by_id(member.id))
    return store, engine, captured, member, portfolios, properties, accounts, bookings


def test_page_legacy_lookup_and_selected_id_share_exact_boundary(booking_access):
    store, _, scope, _, _, properties, accounts, bookings = booking_access
    with scope_context(scope):
        assert {row.id for row in get_booking_page(store, BookingPageQuery()).items} == {row.id for row in bookings[0]}
        legacy = legacy_booking_list(store, skip=0, limit=100, filters={}, sort_by="booking_date", descending=True,
                                    date_from=date(2026, 9, 1), date_to=date(2026, 9, 30))
        assert [row.id for row in legacy] == [row.id for row in reversed(bookings[0])]
        for kind, visible, hidden in (("accounts", accounts[0].id, accounts[1].id),
                                      ("properties", properties[0].id, properties[1].id)):
            values = booking_choices(store, kind, BookingLookupQuery(selected_id=hidden))
            assert {row.id for row in values.items} == {visible}
            assert values.selected is None
            assert booking_choices(store, kind, BookingLookupQuery(search="absent", selected_id=visible)).selected.id == visible


def test_explicit_engine_statement_obeys_scope_without_ambient_context(booking_access):
    store, engine, scope, _, _, _, _, bookings = booking_access
    if not hasattr(store, "db"):
        pytest.skip("Independent Core connection belongs to SQL")
    with scope_context(None), engine.connect() as independent:
        found = independent.execute(booking_statement(BookingFilters(), limit=100, scope=scope)).mappings().all()
    assert {row["id"] for row in found} == {row.id for row in bookings[0]}


def test_booking_and_lookup_cursors_cannot_continue_after_scope_switch(booking_access):
    store, _, scope, _, portfolios, _, _, _ = booking_access
    with scope_context(scope):
        cursor = get_booking_page(store, BookingPageQuery(page_size=1)).next_cursor
        # Properties have one row per scope; unrestricted mode gives a genuine
        # continuation cursor before switching to the second selected portfolio.
    with scope_context(AccessScope(scope.user_id, scope.role, True)):
        lookup_cursor = booking_choices(store, "properties", BookingLookupQuery(page_size=1)).next_cursor
    switched = AccessScope(scope.user_id, scope.role, False, (portfolios[1].id,))
    with scope_context(switched):
        for operation in (lambda: get_booking_page(store, BookingPageQuery(page_size=1, cursor=cursor)),
                          lambda: booking_choices(store, "properties", BookingLookupQuery(page_size=1, cursor=lookup_cursor))):
            with pytest.raises(BookingQueryError) as caught:
                operation()
            assert caught.value.clear_code == "cursor_filter_mismatch"


def test_export_captures_request_scope_even_when_worker_has_other_context(booking_access):
    store, _, scope, _, portfolios, _, _, bookings = booking_access
    with scope_context(scope):
        body = booking_csv_chunks(store, BookingFilters(), chunk_size=1)
    with scope_context(AccessScope("another-worker", "eigentuemer", True, (portfolios[1].id,))):
        values = parsed_csv(body)
    assert {row["id"] for row in values} == {row.id for row in bookings[0]}


@pytest.mark.parametrize("timing", ["before_header", "after_header", "after_data"])
def test_export_reloads_actual_user_grants_and_closes_snapshot_on_change(booking_access, timing):
    store, engine, scope, member, portfolios, *_ = booking_access
    with scope_context(scope):
        body = booking_csv_chunks(store, BookingFilters(), chunk_size=1)
    if timing != "before_header":
        assert next(body).startswith(b"\xef\xbb\xbf")
    if timing == "after_data":
        assert b"Private 0-2" in next(body)
    # SQLUserStore opens a separate Session/transaction, so the snapshot cannot
    # conceal the revocation. This is a real auth mutation, not a mocked guard.
    with scope_context(None):
        auth.update_user(member.id, {"portfolio_access": "selected", "portfolio_ids": [portfolios[1].id]})
    with pytest.raises(HTTPException) as caught:
        next(body)
    assert caught.value.status_code == 403
    if hasattr(store, "db"):
        assert engine.pool.checkedout() == 0


@pytest.mark.parametrize("changed_resource", ["property", "booking"])
def test_export_rechecks_live_parent_assignment_outside_read_snapshot(booking_access, changed_resource):
    store, engine, scope, _, portfolios, properties, accounts, bookings = booking_access
    with scope_context(scope):
        body = booking_csv_chunks(store, BookingFilters(), chunk_size=1)
    next(body)
    next(body)
    with scope_context(None):
        if hasattr(store, "db"):
            # Independent live connection, without the read snapshot or ORM cache.
            with engine.begin() as second:
                if changed_resource == "property":
                    second.execute(update(PropertyORM.__table__).where(PropertyORM.id == properties[0].id)
                                   .values(portfolio_id=portfolios[1].id))
                else:
                    second.execute(update(BookingORM.__table__).where(BookingORM.id == bookings[0][1].id)
                                   .values(account_id=accounts[1].id, property_id=properties[1].id))
        else:
            if changed_resource == "property":
                original = store.properties[properties[0].id]
                store.properties[original.id] = original.model_copy(update={"portfolio_id": portfolios[1].id})
            else:
                original = store.bookings[bookings[0][1].id]
                store.bookings[original.id] = original.model_copy(update={"account_id": accounts[1].id, "property_id": properties[1].id})
    with pytest.raises(HTTPException) as caught:
        next(body)
    assert caught.value.status_code == 403
    if hasattr(store, "db"):
        assert engine.pool.checkedout() == 0


@pytest.mark.parametrize("updates", [{"role": "readonly"}, {"is_active": False}])
def test_export_stops_after_actual_role_or_activation_change(booking_access, updates):
    store, engine, scope, member, *_ = booking_access
    with scope_context(scope):
        body = booking_csv_chunks(store, BookingFilters(), chunk_size=1)
    next(body)
    next(body)
    with scope_context(None):
        auth.update_user(member.id, updates)
    with pytest.raises(HTTPException) as caught:
        next(body)
    assert caught.value.status_code == 403
    if hasattr(store, "db"):
        assert engine.pool.checkedout() == 0


def test_http_page_lookup_legacy_and_csv_do_not_leak_other_portfolio(access_http):  # noqa: F811
    client, _, _, member, _, _, _, _, _, bank, _ = access_http
    page = client.get("/api/v1/bookings/page", headers=member)
    assert page.status_code == 200, page.text
    assert [row["id"] for row in page.json()["items"]] == [bank[0].id]
    assert [row["id"] for row in client.get("/api/v1/bookings", headers=member).json()] == [bank[0].id]
    lookup = client.get(f"/api/v1/bookings/lookup/accounts?selected_id={bank[1].account_id}", headers=member)
    assert lookup.status_code == 200, lookup.text
    assert [row["id"] for row in lookup.json()["items"]] == [bank[0].account_id]
    assert lookup.json()["selected"] is None
    exported = client.get("/api/v1/bookings/export.csv", headers=member)
    assert exported.status_code == 200, exported.text
    assert [row["id"] for row in parsed_csv([exported.content])] == [bank[0].id]


def test_pg_export_second_connection_observes_changed_grants_and_live_parent(postgres_database, monkeypatch):  # noqa: F811
    from backend.models import PortfolioCreate, PropertyCreate

    engine, factory, _, _ = postgres_database
    user_store = auth.SQLUserStore(factory)
    monkeypatch.setattr(auth, "_user_store", user_store)
    monkeypatch.setattr(auth, "_auth_session_factory", factory)
    with factory() as db:
        store = SQLAlchemyStore(db)
        monkeypatch.setattr(dependencies, "store", store)
        with scope_context(None):
            portfolios = [store.create_portfolio(PortfolioCreate(name=f"Synthetic {index}")) for index in range(2)]
            properties = [store.create_property(PropertyCreate(portfolio_id=p.id, name=f"Private {index}", property_type="residential"))
                          for index, p in enumerate(portfolios)]
            member = auth.register_user("member", "member@example.test", "Synthetic", "StrongPass123!", "verwalter",
                                        portfolio_access="selected", portfolio_ids=[portfolios[0].id])
        _seed_bookings(store, portfolios, properties)
        captured = scope_from_user(auth.get_user_by_id(member.id))
        with scope_context(captured):
            body = booking_csv_chunks(store, BookingFilters(), chunk_size=1)
        next(body)
        with scope_context(None), engine.begin() as second:
            second.execute(update(PropertyORM.__table__).where(PropertyORM.id == properties[0].id)
                           .values(portfolio_id=portfolios[1].id))
        with pytest.raises(HTTPException):
            next(body)
        assert engine.pool.checkedout() == 0
        # A separate fresh stream sees the new portfolio, then SQL auth changes
        # through its own connection while that stream has an active snapshot.
        with scope_context(None):
            auth.update_user(member.id, {"portfolio_ids": [portfolios[1].id]})
        captured = scope_from_user(auth.get_user_by_id(member.id))
        with scope_context(captured):
            body = booking_csv_chunks(store, BookingFilters(), chunk_size=1)
        next(body)
        with scope_context(None):
            auth.update_user(member.id, {"portfolio_ids": []})
        with pytest.raises(HTTPException):
            next(body)
        assert engine.pool.checkedout() == 0
