"""Real PostgreSQL regressions for historical floating-point money columns.

Opt in with IMMO_TEST_POSTGRES_ADMIN_URL pointing at a disposable loopback
PostgreSQL server with CREATE DATABASE permission. Each test owns a new
immoqa_money_<uuid> database and drops only that database afterwards.
"""

import os
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.config import Config

import backend.models  # noqa: F401 (register the UI contract columns)
from backend.db.orm_models import Base

PREVIOUS_HEAD = "8c4d2e6f1a93"
MIGRATIONS = Path(__file__).resolve().parents[1] / "db" / "migrations"


@pytest.fixture
def postgres_money_db(monkeypatch):
    admin_url = os.getenv("IMMO_TEST_POSTGRES_ADMIN_URL")
    if not admin_url:
        pytest.skip("set IMMO_TEST_POSTGRES_ADMIN_URL for real PostgreSQL migration tests")
    url = sa.engine.make_url(admin_url)
    if url.get_backend_name() != "postgresql" or url.host not in {"localhost", "127.0.0.1", "::1"}:
        pytest.fail("PostgreSQL migration tests require an explicitly configured loopback server")
    name = f"immoqa_money_{uuid4().hex}"
    admin = sa.create_engine(url, isolation_level="AUTOCOMMIT")
    # Deliberately reduce ordinary float output precision. The migration must
    # independently request lossless float output when converting legacy rows.
    test_url = url.set(database=name)
    monkeypatch.setenv("PGOPTIONS", "-c extra_float_digits=-3")
    engine = sa.create_engine(test_url)
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS))
    monkeypatch.setenv("DATABASE_URL", test_url.render_as_string(hide_password=False))
    created = False
    try:
        with admin.connect() as connection:
            connection.exec_driver_sql(f'CREATE DATABASE "{name}"')
        created = True
        yield engine, config
    finally:
        engine.dispose()
        if created:
            with admin.connect() as connection:
                connection.exec_driver_sql(f'DROP DATABASE "{name}"')
        admin.dispose()


def _seed_bookings(engine, amounts):
    with engine.begin() as connection:
        connection.execute(sa.text("""
            INSERT INTO portfolios (id, name, currency, timezone, status, created_at, updated_at)
            VALUES ('pf', 'Synthetic money test', 'EUR', 'Europe/Berlin', 'active', now(), now())
        """))
        connection.execute(sa.text("""
            INSERT INTO accounts (id, portfolio_id, name, account_type, opening_balance, balance,
                                  created_at, updated_at)
            VALUES ('account', 'pf', 'Synthetic', 'checking', 0, 0, now(), now())
        """))
        connection.execute(sa.text("""
            INSERT INTO bookings (id, account_id, booking_date, amount, status, created_at, updated_at)
            VALUES (:id, 'account', '2026-10-07', :amount, 'booked', now(), now())
        """), [{"id": str(index), "amount": amount} for index, amount in enumerate(amounts)])


def _assert_decimal_schema(engine, *, below_head=False):
    inspector = sa.inspect(engine)
    existing = set(inspector.get_table_names())
    for table in Base.metadata.sorted_tables:
        if below_head and table.name not in existing:
            continue        # a table of a later revision
        declared = [column.name for column in table.columns
                    if isinstance(column.type, sa.Numeric) and not isinstance(column.type, sa.Float)]
        if not declared:
            continue
        columns = {column["name"]: column["type"] for column in inspector.get_columns(table.name)}
        for name in declared:
            assert isinstance(columns[name], sa.Numeric) and not isinstance(columns[name], sa.Float), (
                f"{table.name}.{name} is {columns[name]}, expected decimal storage"
            )
    # Quantities and meter measurements are deliberately outside this repair.
    measurements = {c["name"]: c["type"] for c in inspector.get_columns("standalone_meter_readings")}
    assert isinstance(measurements["value"], sa.Float)


def test_fresh_postgres_money_totals_are_exact(postgres_money_db):
    """The migration chain used to sum 100 * 11.11 as 1111.0000000000002."""
    engine, config = postgres_money_db
    command.upgrade(config, "head")
    _seed_bookings(engine, [Decimal("11.11")] * 100)
    with engine.connect() as connection:
        connection.exec_driver_sql("SET LOCAL extra_float_digits = 3")
        total = connection.execute(sa.text("SELECT sum(amount) FROM bookings")).scalar_one()
    assert total == Decimal("1111.00")
    assert isinstance(total, Decimal)
    _assert_decimal_schema(engine)


def test_postgres_upgrade_preserves_legacy_precision_and_range(postgres_money_db):
    """Rounding to cents or a direct float::numeric cast loses accepted legacy values."""
    engine, config = postgres_money_db
    command.upgrade(config, PREVIOUS_HEAD)
    values = ["11.111", "-11.119", "1.2345678901234567", "10000000000000.125",
              "1e-100", "5e-324", "1.7976931348623157e308", "0"]
    _seed_bookings(engine, [Decimal(value) for value in values])
    with engine.begin() as connection:
        before = connection.execute(sa.text(
            "SELECT id, encode(float8send(amount), 'hex') FROM bookings ORDER BY id"
        )).all()
        connection.execute(sa.text("""
            INSERT INTO properties (id, portfolio_id, name, property_type, status, purchase_price,
                                    market_value, created_at, updated_at)
            VALUES ('property', 'pf', 'Synthetic', 'residential', 'active', NULL, 123.456, now(), now())
        """))

    command.upgrade(config, "head")
    _assert_decimal_schema(engine)
    with engine.connect() as connection:
        rows = connection.execute(sa.text("SELECT amount FROM bookings ORDER BY id")).scalars().all()
        assert rows == [Decimal(value) for value in values]
        assert connection.execute(sa.text(
            "SELECT id, encode(float8send(amount::double precision), 'hex') FROM bookings ORDER BY id"
        )).all() == before
        assert connection.execute(sa.text("SELECT purchase_price, market_value FROM properties")).one() == (
            None, Decimal("123.456")
        )
        column = {c["name"]: c for c in sa.inspect(connection).get_columns("bookings")}["amount"]
        assert column["type"].precision is None
        assert column["type"].scale is None
        assert column["nullable"] is False
        assert "idx_bookings_tenant" in {i["name"] for i in sa.inspect(connection).get_indexes("bookings")}


def test_postgres_adopted_numeric_columns_keep_their_values_and_scale(postgres_money_db):
    """Adopting create_all databases must not narrow or rewrite their decimal columns."""
    engine, config = postgres_money_db
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.exec_driver_sql("ALTER TABLE bookings ALTER COLUMN amount TYPE NUMERIC")
    _seed_bookings(engine, [Decimal("12345678901234567890.1234567890123456789")])
    before = {table: {c["name"]: str(c["type"]) for c in sa.inspect(engine).get_columns(table)}
              for table in ("bookings", "accounts", "payment_allocations")}

    command.upgrade(config, "head")
    command.upgrade(config, "head")

    _assert_decimal_schema(engine)
    after = {table: {c["name"]: str(c["type"]) for c in sa.inspect(engine).get_columns(table)}
             for table in before}
    assert after == before
    with engine.connect() as connection:
        assert connection.execute(sa.text("SELECT amount FROM bookings")).scalar_one() == Decimal(
            "12345678901234567890.1234567890123456789"
        )


def test_postgres_downgrade_and_reupgrade_keep_decimal_precision(postgres_money_db):
    """Downgrade must not silently turn newer precise decimals back into binary floats."""
    engine, config = postgres_money_db
    command.upgrade(config, "head")
    _seed_bookings(engine, [Decimal("12345678901234567890.1234567890123456789")])

    command.downgrade(config, PREVIOUS_HEAD)
    _assert_decimal_schema(engine, below_head=True)
    command.upgrade(config, "head")
    command.upgrade(config, "head")
    with engine.connect() as connection:
        assert connection.execute(sa.text("SELECT amount FROM bookings")).scalar_one() == Decimal(
            "12345678901234567890.1234567890123456789"
        )
