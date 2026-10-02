"""Independent G51 regressions, using actual SQLAlchemy connections."""

import sqlite3

import pytest
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import Session

from backend.repositories.sql_store import SQLAlchemyStore
from backend.services.operational_metrics import OperationalMetrics, database_health


@pytest.mark.parametrize("url", [
    "sqlite:///:memory:",
    "sqlite://",
    "sqlite:///file::memory:?cache=shared&uri=true",
    "sqlite:///file:g51-review?mode=memory&cache=shared&uri=true",
])
def test_actual_sqlite_memory_probe_reports_connection_without_claiming_durable_storage(url):
    engine = create_engine(url)
    try:
        with Session(engine) as session:
            result = database_health(SQLAlchemyStore(session), collector=OperationalMetrics())
        assert result["backend"] == "sqlite" and result["state"] == "connected"
        assert result["check"] == "connectivity_only"
        assert result["persistent"] is False
    finally:
        engine.dispose()


def test_actual_sqlite_driver_memory_cannot_be_misrepresented_by_file_url(tmp_path):
    alleged_file = tmp_path / "g51-file.sqlite"
    engine = create_engine("sqlite:///" + alleged_file.as_posix(),
                           creator=lambda: sqlite3.connect(":memory:"))
    try:
        with Session(engine) as session:
            result = database_health(SQLAlchemyStore(session), collector=OperationalMetrics())
        assert result["state"] == "connected" and result["persistent"] is False
        assert not alleged_file.exists()
    finally:
        engine.dispose()


def test_actual_connection_bound_sql_store_remains_reachable(tmp_path):
    engine = create_engine("sqlite:///" + (tmp_path / "memory-in-name.sqlite").as_posix())
    try:
        with engine.connect() as connection, Session(bind=connection) as session:
            assert connection.exec_driver_sql("SELECT 1").scalar_one() == 1
            result = database_health(SQLAlchemyStore(session), collector=OperationalMetrics())
            assert result["state"] == "connected"
            assert result["backend"] == "sqlite" and result["persistent"] is True
            # The diagnostic must not close its caller's connection.
            assert connection.exec_driver_sql("SELECT 1").scalar_one() == 1
    finally:
        engine.dispose()


def test_connection_probe_preserves_active_transaction_and_uncommitted_business_rows(tmp_path):
    engine = create_engine("sqlite:///" + (tmp_path / "g51-transaction.sqlite").as_posix())
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql("CREATE TABLE review_sentinel (id INTEGER PRIMARY KEY)")
        with engine.connect() as connection, Session(bind=connection) as session:
            transaction = connection.begin()
            connection.exec_driver_sql("INSERT INTO review_sentinel VALUES (1)")
            boundaries = []
            event.listen(connection, "commit", lambda _: boundaries.append("commit"))
            event.listen(connection, "rollback", lambda _: boundaries.append("rollback"))
            result = database_health(SQLAlchemyStore(session), collector=OperationalMetrics())
            assert result["state"] == "connected" and result["persistent"] is True
            assert connection.get_transaction() is transaction and transaction.is_active
            assert boundaries == []
            assert connection.exec_driver_sql("SELECT id FROM review_sentinel").scalar_one() == 1
            transaction.rollback()
        with engine.connect() as connection:
            assert connection.exec_driver_sql("SELECT COUNT(*) FROM review_sentinel").scalar_one() == 0
    finally:
        engine.dispose()


def test_memory_engine_bound_session_probe_does_not_rollback_shared_pending_business_write():
    engine = create_engine("sqlite:///:memory:")
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql("CREATE TABLE review_sentinel (id INTEGER PRIMARY KEY)")
        with Session(engine) as session:
            session.execute(text("INSERT INTO review_sentinel VALUES (1)"))
            transaction = session.get_transaction()
            result = database_health(SQLAlchemyStore(session), collector=OperationalMetrics())
            assert result["state"] == "connected" and result["persistent"] is False
            assert session.get_transaction() is transaction and transaction.is_active
            assert session.execute(text("SELECT id FROM review_sentinel")).scalar_one() == 1
            session.rollback()
        with engine.connect() as connection:
            assert connection.exec_driver_sql("SELECT COUNT(*) FROM review_sentinel").scalar_one() == 0
    finally:
        engine.dispose()


def test_idle_connection_probe_releases_only_its_read_transaction_without_extra_pool_slot(tmp_path):
    engine = create_engine("sqlite:///" + (tmp_path / "g51-idle.sqlite").as_posix(),
                           pool_size=1, max_overflow=0, pool_timeout=0.1)
    try:
        with engine.connect() as connection, Session(bind=connection) as session:
            assert not connection.in_transaction()
            result = database_health(SQLAlchemyStore(session), collector=OperationalMetrics())
            assert result["state"] == "connected" and result["persistent"] is True
            assert not connection.closed and not connection.in_transaction()
            assert not session.in_transaction()
            assert connection.exec_driver_sql("SELECT 1").scalar_one() == 1
    finally:
        engine.dispose()


def test_closed_caller_connection_is_not_replaced_by_a_healthy_database(tmp_path):
    engine = create_engine("sqlite:///" + (tmp_path / "g51-closed.sqlite").as_posix())
    try:
        connection = engine.connect()
        connection.close()
        with Session(bind=connection) as session:
            result = database_health(SQLAlchemyStore(session), collector=OperationalMetrics())
        assert result["state"] == "unavailable" and result["persistent"] is True
        assert connection.closed
    finally:
        engine.dispose()
