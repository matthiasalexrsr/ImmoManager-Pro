"""Actual snapshots, all rows, text formula protection and cleanup on abort."""
import asyncio
import csv
import io
from datetime import date

import pytest
from sqlalchemy import event
from sqlalchemy.orm import Session

from backend.db.orm_models import BookingORM
from backend.services.booking_export import booking_csv_chunks, closing_chunks, csv_cell
from backend.services.booking_query import BookingFilters
from backend.tests.test_booking_pages import bookings_store, insert_rows, row  # noqa: F401


def parsed_csv(chunks):
    return list(csv.DictReader(io.StringIO(b"".join(chunks).decode("utf-8-sig")), delimiter=";"))


@pytest.mark.parametrize("text", ["=1+1", "+SUM(A1)", "-danger", "@command", "  =1", "\t=1", "\r=1", "\n=1", "\0=1"])
def test_text_formulas_are_escaped_but_actual_numbers_are_preserved(text):
    assert csv_cell(text) == "'" + text
    assert csv_cell(-12.50) == -12.50
    assert csv_cell("Synthetic") == "Synthetic"


def test_csv_uses_all_filtered_rows_in_small_chunks(bookings_store):  # noqa: F811 - imported pytest fixture
    insert_rows(bookings_store, [row(200, payment_text='=HYPERLINK("https://example.invalid")', amount=-12.5)])
    chunks = list(booking_csv_chunks(bookings_store, BookingFilters(view="expense"), chunk_size=3))
    exported = parsed_csv(chunks)
    assert len(chunks) > 5
    assert len(exported) == 28
    danger, = [value for value in exported if value["id"] == "booking-00000200"]
    assert danger["payment_text"].startswith("'=HYPERLINK")
    assert float(danger["amount"]) == -12.5
    assert all(float(value["amount"]) < 0 for value in exported)


def test_csv_snapshot_excludes_later_inserts_and_later_edits(bookings_store):  # noqa: F811 - imported pytest fixture
    chunks = booking_csv_chunks(bookings_store, BookingFilters(), chunk_size=3)
    header = next(chunks)
    if hasattr(bookings_store, "db"):
        with Session(bookings_store.db.get_bind()) as second:
            second.execute(BookingORM.__table__.insert(), row(1000, booking_date=date(2026, 10, 1)))
            second.execute(BookingORM.__table__.update().where(BookingORM.id == "booking-00000052").values(payment_text="Changed after snapshot"))
            second.commit()
    else:
        insert_rows(bookings_store, [row(1000, booking_date=date(2026, 10, 1))])
        previous = bookings_store.bookings["booking-00000052"]
        bookings_store.bookings[previous.id] = previous.model_copy(update={"payment_text": "Changed after snapshot"})
    exported = parsed_csv([header, *chunks])
    assert len(exported) == 53
    assert "booking-00001000" not in {value["id"] for value in exported}
    final, = [value for value in exported if value["id"] == "booking-00000052"]
    assert final["payment_text"] == "Prüfung 100%_literal"


def test_client_abort_closes_its_private_snapshot_connection(bookings_store):  # noqa: F811 - imported pytest fixture
    if not hasattr(bookings_store, "db"):
        pytest.skip("Actual SQL pool cleanup gate")
    engine = bookings_store.db.get_bind()
    async def abort():
        body = closing_chunks(booking_csv_chunks(bookings_store, BookingFilters(), chunk_size=3))
        assert (await anext(body)).startswith(b"\xef\xbb\xbf")
        assert engine.pool.checkedout() == 1
        await body.aclose()
    asyncio.run(abort())
    assert engine.pool.checkedout() == 0


def test_query_failure_closes_snapshot_instead_of_leaking_connection(bookings_store):  # noqa: F811 - imported pytest fixture
    if not hasattr(bookings_store, "db"):
        pytest.skip("Actual SQL query fault gate")
    engine = bookings_store.db.get_bind()
    calls = 0
    def fail_second_query(connection, cursor, statement, parameters, context, many):
        nonlocal calls
        if statement.lstrip().upper().startswith("SELECT"):
            calls += 1
            if calls == 2:
                raise RuntimeError("Synthetic export fault")
    event.listen(engine, "before_cursor_execute", fail_second_query)
    try:
        with pytest.raises(RuntimeError, match="Synthetic export fault"):
            list(booking_csv_chunks(bookings_store, BookingFilters(), chunk_size=3))
    finally:
        event.remove(engine, "before_cursor_execute", fail_second_query)
    assert engine.pool.checkedout() == 0


def test_sql_export_passes_ten_thousand_rows_without_business_cap(bookings_store):  # noqa: F811 - imported pytest fixture
    if not hasattr(bookings_store, "db"):
        pytest.skip("Large SQL streaming regression; memory reference is intentionally transient")
    insert_rows(bookings_store, [row(index) for index in range(53, 12053)])
    # Count rows as each buffer is consumed; do not collect the complete export.
    chunks = booking_csv_chunks(bookings_store, BookingFilters(), chunk_size=128)
    next(chunks)
    count = sum(sum(1 for _ in csv.reader(io.StringIO(chunk.decode()), delimiter=";")) for chunk in chunks)
    assert count == 12053
