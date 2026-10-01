"""Genuine PostgreSQL pages and export snapshot, in generated isolated schemas."""
import csv
import io
from datetime import date

from backend.db.orm_models import BookingORM
from backend.repositories.sql_store import SQLAlchemyStore
from backend.services.booking_export import booking_csv_chunks
from backend.services.booking_query import BookingFilters, BookingPageQuery, get_booking_page
from backend.tests.test_booking_pages import all_pages, insert_rows, row, seed_references
from backend.tests.test_private_server_concurrency import postgres_database  # noqa: F401


def test_pg_bytewise_tie_order_and_composite_filter_pagination(postgres_database):  # noqa: F811 - imported pytest fixture
    engine, factory, _, _ = postgres_database
    seed_references(engine)
    with factory() as db:
        active = SQLAlchemyStore(db)
        insert_rows(active, [row(n) for n in range(103)])
        insert_rows(active, [row(1000 + n, id=value, booking_date=date(2026, 10, 1)) for n, value in enumerate(["a", "B", "b"])])
        assert [item.id for item in get_booking_page(active, BookingPageQuery(page_size=3)).items] == ["b", "a", "B"]
        expected = sorted((row(n) for n in range(103) if n % 2), key=lambda value: (value["booking_date"], value["id"]), reverse=True)
        assert all_pages(active, page_size=7, account_id="account-1", search="miete") == [value["id"] for value in expected]
    assert engine.pool.checkedout() == 0


def test_pg_snapshot_preserves_original_rows_during_independent_insert_and_edit(postgres_database):  # noqa: F811 - imported pytest fixture
    engine, factory, _, _ = postgres_database
    seed_references(engine)
    with factory() as db:
        active = SQLAlchemyStore(db)
        insert_rows(active, [row(n) for n in range(31)])
        body = booking_csv_chunks(active, BookingFilters(), chunk_size=3)
        header = next(body)
        with factory() as second:
            second.execute(BookingORM.__table__.insert(), row(1000, booking_date=date(2026, 10, 1)))
            second.execute(BookingORM.__table__.update().where(BookingORM.id == "booking-00000030").values(payment_text="Later edit"))
            second.commit()
        values = list(csv.DictReader(io.StringIO(b"".join([header, *body]).decode("utf-8-sig")), delimiter=";"))
        assert len(values) == 31
        assert all(value["id"] != "booking-00001000" for value in values)
        last, = [value for value in values if value["id"] == "booking-00000030"]
        assert last["payment_text"] == "Prüfung 100%_literal"
    assert engine.pool.checkedout() == 0
