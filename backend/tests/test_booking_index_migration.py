"""Actual index migration preserves existing bookings on upgrade/downgrade."""
from importlib import import_module

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, select, text

from backend.db.orm_models import BookingORM
from backend.tests.test_booking_pages import bookings_store  # noqa: F401


def test_booking_index_migration_preserves_every_existing_row(bookings_store):  # noqa: F811 - imported pytest fixture
    if not hasattr(bookings_store, "db"):
        return
    migration = import_module("backend.db.migrations.versions.l1a2b3c4d5e6_booking_keyset_indexes")
    from backend.db.booking_indexes import BOOKING_INDEXES
    engine = bookings_store.db.get_bind()
    with engine.begin() as connection:
        original = connection.execute(select(BookingORM.__table__).order_by(BookingORM.id)).all()
        with Operations.context(MigrationContext.configure(connection)):
            migration.downgrade()
            assert not {index.name for index in BOOKING_INDEXES} & {index["name"] for index in inspect(connection).get_indexes("bookings")}
            migration.upgrade()
        assert {index.name for index in BOOKING_INDEXES} <= {index["name"] for index in inspect(connection).get_indexes("bookings")}
        assert connection.execute(select(BookingORM.__table__).order_by(BookingORM.id)).all() == original


def test_reduced_historical_schema_skips_unavailable_indexes_and_preserves_bytes():
    from backend.db.booking_indexes import ensure_booking_indexes
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE bookings (id TEXT PRIMARY KEY, account_id TEXT, amount NUMERIC)"))
        connection.execute(text("INSERT INTO bookings VALUES ('historic', 'account', 12.34)"))
        ensure_booking_indexes(connection)
        ensure_booking_indexes(connection)
        assert not inspect(connection).get_indexes("bookings")
        assert connection.execute(text("SELECT * FROM bookings")).all() == [("historic", "account", 12.34)]
        connection.execute(text("ALTER TABLE bookings ADD COLUMN booking_date DATE"))
        ensure_booking_indexes(connection)
        assert {value["name"] for value in inspect(connection).get_indexes("bookings")} == {
            "idx_bookings_date_id", "idx_bookings_account_date_id"}
    engine.dispose()
