"""Explicit date-index migration: preserved finance totals and selective query plans."""

from datetime import date, timedelta
from typing import Any

import pytest
import sqlalchemy as sa
from alembic import command
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session
from test_postgres_money_migration import postgres_money_db  # noqa: F401

import backend.models  # noqa: F401 (register all ORM columns)
from backend.db.orm_models import AccountORM, Base, BookingORM, PortfolioORM
from backend.db.schema_state import SchemaUpgradeRequired, alembic_config, ensure_current
from backend.repositories import SQLAlchemyStore
from backend.services.finance_ledger import FinanceFilter, booking_totals

PARENT = "3c7e9a1d5f20"
REVISION = "7a2c8e4f1b90"
INDEX = "idx_bookings_date"


def _indexes(engine: Engine) -> dict:
    return {index["name"]: index for index in sa.inspect(engine).get_indexes("bookings")}


def _seed(engine: Engine) -> None:
    with engine.begin() as connection:
        connection.execute(sa.insert(PortfolioORM), {"id": "pf", "name": "Synthetic date-index test"})
        connection.execute(sa.insert(AccountORM), [
            {"id": f"a{index}", "portfolio_id": "pf", "name": f"Account {index}", "account_type": "bank"}
            for index in range(32)])
        for start in range(0, 12000, 1000):
            connection.execute(sa.insert(BookingORM), [
                {"id": f"b{index}", "account_id": f"a{index % 32}", "amount": 10.25,
                 "booking_date": date(2020, 1, 1) + timedelta(days=index % 1200), "status": "booked"}
                for index in range(start, start + 1000)])


def _totals_and_plan(engine: Engine) -> tuple[list, Any]:
    statements: list[tuple[str, Any]] = []

    def capture(connection, cursor, statement, parameters, context, executemany):
        if "FROM bookings" in statement and statement.lstrip().startswith("SELECT"):
            statements.append((statement, parameters))

    sa.event.listen(engine, "before_cursor_execute", capture)
    try:
        with Session(engine) as db:
            totals = booking_totals(SQLAlchemyStore(db), FinanceFilter(
                date_from=date(2021, 5, 1), date_to=date(2021, 5, 3)), by=("month",))
    finally:
        sa.event.remove(engine, "before_cursor_execute", capture)
    assert len(statements) == 1
    statement, parameters = statements[0]
    with engine.connect() as connection:
        if engine.dialect.name == "sqlite":
            plan = [row[3] for row in connection.exec_driver_sql("EXPLAIN QUERY PLAN " + statement, parameters)]
        else:
            plan = connection.exec_driver_sql("EXPLAIN (FORMAT JSON) " + statement, parameters).scalar_one()
    return totals, plan


def _plan_indexes(node: Any) -> set[str]:
    if isinstance(node, list):
        return set().union(*(_plan_indexes(child) for child in node))
    if isinstance(node, dict):
        own = {node["Index Name"]} if "Index Name" in node else set()
        return own.union(*(_plan_indexes(child) for child in node.values()))
    return set()


def _exercise_migration(engine: Engine, config) -> None:
    command.upgrade(config, PARENT)
    original_indexes = _indexes(engine)
    assert INDEX not in original_indexes
    _seed(engine)
    if engine.dialect.name == "postgresql":
        with engine.begin() as connection:
            connection.exec_driver_sql("ANALYZE bookings")
    before, before_plan = _totals_and_plan(engine)
    assert sum(row.amount for row in before) == 307.50
    if engine.dialect.name == "sqlite":
        assert any("SCAN bookings" in line for line in before_plan), before_plan
    command.upgrade(config, REVISION)
    command.upgrade(config, REVISION)
    # Explicit upgrades run outside the app process. Reconnect as the subsequent
    # app start does; sqlite3 may otherwise reuse a cached EXPLAIN across external DDL.
    engine.dispose()
    assert _indexes(engine)[INDEX]["column_names"] == ["booking_date"]
    assert _indexes(engine).keys() == original_indexes.keys() | {INDEX}
    after, after_plan = _totals_and_plan(engine)
    assert after == before
    if engine.dialect.name == "sqlite":
        assert any(f"SEARCH bookings USING INDEX {INDEX}" in line for line in after_plan), after_plan
    else:
        assert INDEX in _plan_indexes(after_plan), after_plan
    print(f"{engine.dialect.name}: before={before_plan}; after={after_plan}")
    command.downgrade(config, PARENT)
    engine.dispose()
    assert _indexes(engine) == original_indexes
    assert _totals_and_plan(engine)[0] == before
    command.upgrade(config, REVISION)
    engine.dispose()
    assert _totals_and_plan(engine)[0] == before
    with engine.connect() as connection:
        assert connection.exec_driver_sql("SELECT count(*) FROM bookings").scalar_one() == 12000


def test_sqlite_date_index_migrates_and_improves_the_actual_finance_plan(tmp_path):
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'date-index.db'}")
    try:
        _exercise_migration(engine, alembic_config(str(engine.url)))
    finally:
        engine.dispose()


def test_normal_start_refuses_old_schema_and_does_not_create_the_index(tmp_path):
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'old-schema.db'}")
    try:
        config = alembic_config(str(engine.url))
        command.upgrade(config, PARENT)
        with pytest.raises(SchemaUpgradeRequired):
            ensure_current(engine)
        assert INDEX not in _indexes(engine)
        with engine.connect() as connection:
            assert connection.exec_driver_sql("SELECT version_num FROM alembic_version").scalar_one() == PARENT
        command.upgrade(config, REVISION)
        ensure_current(engine)
    finally:
        engine.dispose()


def test_fresh_orm_schema_has_the_same_index_and_explicit_upgrade_accepts_it(tmp_path):
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'fresh-schema.db'}")
    try:
        Base.metadata.create_all(engine)
        assert _indexes(engine)[INDEX]["column_names"] == ["booking_date"]
        config = alembic_config(str(engine.url))
        command.upgrade(config, REVISION)
        assert _indexes(engine)[INDEX]["column_names"] == ["booking_date"]
    finally:
        engine.dispose()


def test_postgres_date_index_upgrade_downgrade_and_actual_finance_plan(postgres_money_db):  # noqa: F811
    engine, config = postgres_money_db
    _exercise_migration(engine, config)
