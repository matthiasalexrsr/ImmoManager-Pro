"""Real bounded SQL reads, live keyset traversal and cursor integrity."""
from datetime import date, timedelta

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session

from backend.db.booking_indexes import BOOKING_INDEXES  # noqa: F401 registers additive indexes
from backend.db.orm_models import AccountORM, Base, BookingORM, PortfolioORM, PropertyORM, TenantORM
from backend.models import Booking
from backend.repositories.sql_store import SQLAlchemyStore
from backend.services.booking_query import (
    BookingPageQuery,
    BookingQueryError,
    decode_cursor,
    encode_cursor,
    get_booking_page,
)
from backend.storage import InMemoryStore


def seed_references(engine):
    with engine.begin() as connection:
        connection.execute(PortfolioORM.__table__.insert(), dict(id="portfolio", name="Synthetic"))
        connection.execute(AccountORM.__table__.insert(), [dict(id=f"account-{n}", portfolio_id="portfolio", name=f"Synthetic {n}", account_type="bank") for n in range(2)])
        connection.execute(PropertyORM.__table__.insert(), [dict(id=f"property-{n}", portfolio_id="portfolio", name=f"Synthetic {n}", property_type="residential") for n in range(2)])
        connection.execute(TenantORM.__table__.insert(), [dict(id=f"tenant-{n}", full_name=f"Synthetic {n}") for n in range(2)])


def row(index, **changes):
    return {"id": f"booking-{index:08d}", "account_id": f"account-{index % 2}",
            "property_id": f"property-{index % 2}", "tenant_id": f"tenant-{index % 2}",
            "booking_date": date(2026, 9, 30) - timedelta(days=index // 5),
            "amount": 10 if index % 2 else -10, "status": ["open", "matched", "booked"][index % 3],
            "payment_text": "Miete Synthetic" if index % 2 else "Prüfung 100%_literal", **changes}


def insert_rows(active, rows):
    if hasattr(active, "db"):
        active.db.execute(BookingORM.__table__.insert(), rows)
        active.db.commit()
    else:
        active.bookings.update({value["id"]: Booking(**value) for value in rows})


@pytest.fixture(params=["memory", "sql"])
def bookings_store(request, tmp_path):
    if request.param == "memory":
        active = InMemoryStore()
        insert_rows(active, [row(index) for index in range(53)])
        yield active
    else:
        engine = create_engine(f"sqlite:///{tmp_path / 'bookings.db'}", connect_args={"check_same_thread": False})
        @event.listens_for(engine, "connect")
        def sqlite_settings(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("PRAGMA journal_mode=WAL")
        Base.metadata.create_all(engine)
        seed_references(engine)
        with Session(engine) as db:
            active = SQLAlchemyStore(db)
            insert_rows(active, [row(index) for index in range(53)])
            yield active
        engine.dispose()


def all_pages(active, **filters):
    ids, cursor = [], None
    while True:
        page = get_booking_page(active, BookingPageQuery(**filters, cursor=cursor))
        assert len(page.items) <= filters.get("page_size", 100)
        assert page.has_more == (page.next_cursor is not None)
        ids.extend(item.id for item in page.items)
        if not page.has_more:
            return ids
        cursor = page.next_cursor


def test_all_pages_have_exact_stable_date_and_id_order_without_duplicates(bookings_store):
    expected = [value["id"] for value in sorted((row(n) for n in range(53)), key=lambda value: (value["booking_date"], value["id"]), reverse=True)]
    assert all_pages(bookings_store, page_size=7) == expected
    assert all_pages(bookings_store, page_size=1) == expected


@pytest.mark.parametrize("filters,predicate", [
    ({"account_id": "account-1"}, lambda value: value["account_id"] == "account-1"),
    ({"property_id": "property-0", "tenant_id": "tenant-0", "status": "open"}, lambda value: value["property_id"] == "property-0" and value["status"] == "open"),
    ({"date_from": "2026-09-25", "date_to": "2026-09-27"}, lambda value: date(2026, 9, 25) <= value["booking_date"] <= date(2026, 9, 27)),
    ({"search": "100%_literal"}, lambda value: "100%_literal" in value["payment_text"]),
    ({"search": "mIeTe", "view": "income"}, lambda value: value["amount"] > 0),
    ({"view": "expense"}, lambda value: value["amount"] < 0),
])
def test_actual_filters_are_applied_before_the_page_limit(bookings_store, filters, predicate):
    expected = sorted((row(n) for n in range(53) if predicate(row(n))), key=lambda value: (value["booking_date"], value["id"]), reverse=True)
    assert all_pages(bookings_store, page_size=3, **filters) == [value["id"] for value in expected]


def test_cursor_is_signed_and_binds_every_filter_size_and_order(bookings_store):
    query = BookingPageQuery(page_size=3)
    cursor = get_booking_page(bookings_store, query).next_cursor
    damaged = cursor[:-1] + ("A" if cursor[-1] != "A" else "B")
    with pytest.raises(BookingQueryError, match="geprüft") as error:
        get_booking_page(bookings_store, query.model_copy(update={"cursor": damaged}))
    assert error.value.clear_code == "cursor_invalid"
    for change in ({"page_size": 4}, {"account_id": "account-1"}, {"property_id": "property-1"},
                   {"tenant_id": "tenant-1"}, {"status": "open"}, {"date_from": date(2026, 9, 1)},
                   {"date_to": date(2026, 9, 30)}, {"search": "Miete"}, {"view": "income"}):
        with pytest.raises(BookingQueryError) as error:
            get_booking_page(bookings_store, query.model_copy(update={"cursor": cursor, **change}))
        assert error.value.clear_code == "cursor_filter_mismatch"


def test_expired_cursor_has_an_explicit_recoverable_error():
    query = BookingPageQuery(page_size=2)
    token = encode_cursor(query, Booking(**row(1)), now=100)
    with pytest.raises(BookingQueryError) as error:
        decode_cursor(query.model_copy(update={"cursor": token}), now=3700)
    assert error.value.clear_code == "cursor_expired"
    assert error.value.detail["recovery"] == "restart_page"


def test_concurrent_newer_insert_does_not_shift_old_page_boundary(bookings_store):
    query = BookingPageQuery(page_size=5)
    first = get_booking_page(bookings_store, query)
    insert_rows(bookings_store, [row(1000, booking_date=date(2026, 10, 1))])
    next_page = get_booking_page(bookings_store, query.model_copy(update={"cursor": first.next_cursor}))
    assert not set(item.id for item in first.items) & set(item.id for item in next_page.items)
    assert "booking-00001000" not in {item.id for item in next_page.items}
    assert get_booking_page(bookings_store, query).items[0].id == "booking-00001000"


def test_case_sensitive_id_ties_have_same_bytewise_order(bookings_store):
    insert_rows(bookings_store, [row(1000 + n, id=value, booking_date=date(2026, 10, 1)) for n, value in enumerate(["a", "B", "b"])])
    first = get_booking_page(bookings_store, BookingPageQuery(page_size=3))
    assert [item.id for item in first.items] == ["b", "a", "B"]


def test_sql_page_does_not_flush_an_unrelated_pending_write(bookings_store):
    if not hasattr(bookings_store, "db"):
        pytest.skip("SQL Session read-only regression")
    pending = BookingORM(**row(1000, booking_date=date(2026, 10, 1)))
    bookings_store.db.add(pending)
    first = get_booking_page(bookings_store, BookingPageQuery(page_size=2))
    assert pending in bookings_store.db.new
    assert pending.id not in {item.id for item in first.items}


def test_sql_asks_only_for_a_bounded_page_and_never_count_or_offset(bookings_store):
    if not hasattr(bookings_store, "db"):
        pytest.skip("SQL query shape gate")
    statements = []
    engine = bookings_store.db.get_bind()
    def observe(connection, cursor, statement, parameters, context, many):
        if statement.lstrip().upper().startswith("SELECT"):
            statements.append((statement, parameters))
    event.listen(engine, "before_cursor_execute", observe)
    try:
        first = get_booking_page(bookings_store, BookingPageQuery(page_size=7))
        get_booking_page(bookings_store, BookingPageQuery(page_size=7, cursor=first.next_cursor))
    finally:
        event.remove(engine, "before_cursor_execute", observe)
    assert len(statements) == 2
    assert all("COUNT(" not in sql.upper() and "OFFSET" in sql.upper() and params[-2:] == (8, 0) for sql, params in statements)
    # SQLite emits OFFSET 0 for LIMIT, not a growing offset. Deep traversal uses
    # the composite tuple predicate instead of skipping historic records.
    assert '(bookings.booking_date, bookings.id COLLATE "BINARY") <' in statements[1][0]


@pytest.mark.parametrize("values", [{"account_id": "x;drop table bookings"}, {"property_id": ""},
    {"tenant_id": "a\n"}, {"status": "arbitrary"}, {"search": "x" * 201}, {"search": "x\n"},
    {"date_from": "20260930"}, {"date_from": "2026-10-01", "date_to": "2026-01-01"},
    {"order": "amount DESC"}, {"sort_by": "amount"}, {"page_size": 0}, {"page_size": 5001}] )
def test_query_rejects_invalid_inputs(values):
    with pytest.raises(ValidationError):
        BookingPageQuery.model_validate(values)


def test_configured_page_size_is_a_transfer_limit_with_more_pages(monkeypatch, bookings_store):
    import backend.services.booking_query as service
    monkeypatch.setattr(service, "maximum_page_size", lambda: 25)
    with pytest.raises(BookingQueryError) as error:
        get_booking_page(bookings_store, BookingPageQuery(page_size=26))
    assert error.value.clear_code == "page_size_exceeded"
    assert len(all_pages(bookings_store, page_size=25)) == 53
