"""Prepared native fixture recovery: no auth/app/store imports or runtime claim."""

import os
from contextlib import contextmanager

import pytest
from psycopg2.extensions import TRANSACTION_STATUS_INERROR, TRANSACTION_STATUS_INTRANS
from sqlalchemy import Integer, String, event, func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column
from sqlalchemy.sql.elements import ReleaseSavepointClause, RollbackToSavepointClause, SavepointClause

from backend.tests.notification_inbox_pg_proposal_support import (
    dedicated_url,
    postgres_proposal_database,
)


class _FixtureBase(DeclarativeBase):
    pass


class _Marker(_FixtureBase):
    __tablename__ = "savepoint_fixture_marker"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    payload: Mapped[str] = mapped_column(String, nullable=False)


@contextmanager
def _record_native_control(engine):
    history = []

    def record(phase, connection, context):
        compiled = getattr(context, "compiled", None)
        clause = getattr(compiled, "statement", None)
        if isinstance(clause, RollbackToSavepointClause):
            kind = "rollback"
        elif isinstance(clause, ReleaseSavepointClause):
            kind = "release"
        elif isinstance(clause, SavepointClause):
            kind = "savepoint"
        else:
            return
        driver = connection.connection.driver_connection
        history.append((phase, kind, driver.get_transaction_status()))

    def before(connection, cursor, statement, parameters, context, executemany):
        record("before", connection, context)

    def after(connection, cursor, statement, parameters, context, executemany):
        record("after", connection, context)

    event.listen(engine, "before_cursor_execute", before)
    event.listen(engine, "after_cursor_execute", after)
    try:
        yield history
    finally:
        event.remove(engine, "before_cursor_execute", before)
        event.remove(engine, "after_cursor_execute", after)


def _unique_violation(error):
    assert getattr(error.value.orig, "pgcode", None) == "23505", "Expected genuine PostgreSQL unique violation"


def _normal_query_resets_both_actual_budgets(connection):
    # Deliberately override BOTH settings on the actual owned driver; startup
    # defaults alone cannot satisfy the following normal-statement assertion.
    cursor = connection.connection.driver_connection.cursor()
    try:
        cursor.execute("SELECT pg_catalog.set_config('statement_timeout','30000',true),"
                       "pg_catalog.set_config('lock_timeout','30000',true)")
        cursor.fetchone()
        cursor.execute("SELECT name,setting::integer,unit FROM pg_catalog.pg_settings "
                       "WHERE name IN ('statement_timeout','lock_timeout')")
        widened = {name: (milliseconds, unit) for name, milliseconds, unit in cursor.fetchall()}
        assert widened == {"statement_timeout": (30000, "ms"), "lock_timeout": (30000, "ms")}
    finally:
        cursor.close()
    budgets = {row.name: (row.milliseconds, row.unit) for row in connection.execute(text(
        "SELECT name,setting::integer AS milliseconds,unit FROM pg_catalog.pg_settings "
        "WHERE name IN ('statement_timeout','lock_timeout')"
    ))}
    assert set(budgets) == {"statement_timeout", "lock_timeout"}
    assert all(unit == "ms" and value > 0 for value, unit in budgets.values())
    assert budgets["statement_timeout"][0] <= 5000
    assert budgets["lock_timeout"][0] <= 1500


def _core(engine, handles):
    table = _Marker.__table__
    with engine.connect() as connection:
        handles.append(connection.connection.driver_connection)
        with connection.begin() as outer:
            connection.execute(table.insert(), {"id": 2, "payload": "before errors"})
            for identifier in (3, 4):
                with pytest.raises(IntegrityError) as error:
                    with connection.begin_nested():
                        connection.execute(table.insert(), {"id": 1, "payload": "duplicate"})
                _unique_violation(error)
                assert outer.is_active and connection.get_transaction() is outer
                assert connection.get_nested_transaction() is None
                assert connection.connection.driver_connection.get_transaction_status() == TRANSACTION_STATUS_INTRANS
                connection.execute(table.insert(), {"id": identifier, "payload": "after " + str(identifier)})
            with connection.begin_nested():
                assert connection.scalar(select(func.count()).select_from(table)) == 4
            assert outer.is_active and connection.get_transaction() is outer
            _normal_query_resets_both_actual_budgets(connection)
        assert not connection.in_transaction()


def _orm(engine, handles):
    with Session(bind=engine) as db:
        with db.begin() as outer:
            db.add(_Marker(id=2, payload="before errors"))
            db.flush()
            connection = db.connection()
            handles.append(connection.connection.driver_connection)
            for identifier in (3, 4):
                with pytest.raises(IntegrityError) as error:
                    with db.begin_nested():
                        db.add(_Marker(id=1, payload="duplicate"))
                        db.flush()
                _unique_violation(error)
                assert db.is_active and outer.is_active and db.get_transaction() is outer
                assert not db.in_nested_transaction()
                assert connection.connection.driver_connection.get_transaction_status() == TRANSACTION_STATUS_INTRANS
                db.add(_Marker(id=identifier, payload="after " + str(identifier)))
                db.flush()
            with db.begin_nested():
                assert db.scalar(select(func.count()).select_from(_Marker)) == 4
            assert db.is_active and outer.is_active and db.get_transaction() is outer
            _normal_query_resets_both_actual_budgets(connection)
        assert not db.in_transaction()


@pytest.mark.parametrize("mode", ["core", "orm"], ids=["core", "orm"])
def test_native_duplicate_savepoints_keep_outer_transaction_usable(mode):
    source = dedicated_url(os.environ.get("TEST_SERVER_DATABASE_URL"))  # No skip or ambient target.
    handles = []
    with postgres_proposal_database(source) as engine:
        _FixtureBase.metadata.create_all(engine)
        with engine.begin() as connection:
            connection.execute(_Marker.__table__.insert(), {"id": 1, "payload": "initial committed"})
        with _record_native_control(engine) as history:
            if mode == "core":
                _core(engine, handles)
            else:
                _orm(engine, handles)
        assert [(phase, status) for phase, kind, status in history if kind == "rollback"] == [
            ("before", TRANSACTION_STATUS_INERROR), ("after", TRANSACTION_STATUS_INTRANS),
            ("before", TRANSACTION_STATUS_INERROR), ("after", TRANSACTION_STATUS_INTRANS),
        ]
        assert sum(kind == "savepoint" and phase == "after" for phase, kind, _status in history) == 3
        assert [(phase, status) for phase, kind, status in history if kind == "release"] == [
            ("before", TRANSACTION_STATUS_INTRANS), ("after", TRANSACTION_STATUS_INTRANS),
        ]
        with engine.connect() as connection:
            actual = connection.execute(select(_Marker.__table__).order_by(_Marker.id)).all()
            assert [(row.id, row.payload) for row in actual] == [
                (1, "initial committed"), (2, "before errors"), (3, "after 3"), (4, "after 4"),
            ]
        assert engine.pool.checkedout() == 0
    assert handles and all(handle.closed for handle in handles), "Actual own PG driver survived fixture cleanup"
