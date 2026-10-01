"""No truncation before filtering, even for a historical large ledger."""
from datetime import date

import pytest
from sqlalchemy import event

from backend.services.booking_legacy import legacy_booking_list
from backend.tests.test_booking_pages import bookings_store, insert_rows, row  # noqa: F401


def read(active, **overrides):
    return legacy_booking_list(active, skip=0, limit=5, filters={"account_id": None, "tenant_id": None, "status": None},
        sort_by="id", descending=False, date_from=date(2046, 1, 1), date_to=date(2046, 1, 31), **overrides)


def test_matching_rows_beyond_ten_thousand_are_filtered_before_pagination(bookings_store):  # noqa: F811
    insert_rows(bookings_store, [row(n, booking_date=date(2006, 1, 1)) for n in range(53, 10054)])
    insert_rows(bookings_store, [row(n, booking_date=date(2046, 1, 15)) for n in range(10054, 10061)])
    first = read(bookings_store)
    assert [item.id for item in first] == [row(n)["id"] for n in range(10054, 10059)]
    following = legacy_booking_list(bookings_store, skip=5, limit=5, filters={"account_id": None}, sort_by="id",
        descending=False, date_from=date(2046, 1, 1), date_to=date(2046, 1, 31))
    assert [item.id for item in following] == [row(n)["id"] for n in range(10059, 10061)]


def test_legacy_date_read_uses_where_limit_offset_and_a_static_sort_allowlist(bookings_store):  # noqa: F811
    if not hasattr(bookings_store, "db"):
        pytest.skip("SQL-specific query inspection")
    calls = []
    engine = bookings_store.db.get_bind()
    def capture(_connection, _cursor, statement, parameters, _context, _many):
        if statement.lstrip().upper().startswith("SELECT"):
            calls.append((statement, parameters))
    event.listen(engine, "before_cursor_execute", capture)
    try:
        read(bookings_store)
        legacy_booking_list(bookings_store, skip=7, limit=3, filters={}, sort_by="payment_text; DROP TABLE bookings",
            descending=False, date_from=date(2026, 1, 1), date_to=None)
    finally:
        event.remove(engine, "before_cursor_execute", capture)
    assert len(calls) == 2
    assert all("WHERE" in text and "LIMIT" in text and "COUNT" not in text for text, _ in calls)
    assert calls[1][1][-2:] == (3, 7)
    assert "DROP" not in calls[1][0]
