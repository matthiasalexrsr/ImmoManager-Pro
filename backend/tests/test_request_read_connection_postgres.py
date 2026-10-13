"""Actual PostgreSQL request-read ownership, pool pressure and hidden DML guards."""

from typing import cast

import pytest
from sqlalchemy import create_engine, func, insert, select, text, update
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, scoped_session, sessionmaker
from test_document_versions_postgres import postgres  # noqa: F401
from test_request_read_connection import RequestBase, RequestRow
from test_request_read_connection import (
    test_two_request_reads_cannot_starve_their_owned_write_connections as _pool_case,
)

from backend import concurrency, dependencies
from backend.repositories import SQLAlchemyStore
from backend.services.portfolio_scope import scope_context


@pytest.fixture
def pool(postgres, monkeypatch):  # noqa: F811
    original, _ = postgres
    concurrency.track_database_changes()
    engine = create_engine(original.url, pool_size=2, max_overflow=0, pool_timeout=0.25)
    RequestBase.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(insert(RequestRow), [{"id": 1, "value": 1}, {"id": 2, "value": 2}])
    registry = scoped_session(sessionmaker(engine, autoflush=False), scopefunc=dependencies._session_scope)
    monkeypatch.setattr(dependencies, "_scoped_session", registry)
    with scope_context(None):
        yield engine, registry, SQLAlchemyStore(cast(Session, registry))
    registry.remove()
    engine.dispose()


def test_postgres_two_readers_can_both_acquire_their_owned_write_connection(pool):
    _pool_case(pool, release=True)


@pytest.mark.parametrize("kind", ["raw", "core", "cte"])
def test_postgres_direct_connection_and_cte_writes_are_never_discarded(pool, kind):
    engine, registry, target = pool
    token = dependencies.begin_request_scope()
    try:
        db = registry()
        assert db.scalar(select(RequestRow.value).where(RequestRow.id == 1)) == 1
        if kind == "raw":
            db.connection().exec_driver_sql("UPDATE request_read_connection_rows SET value=9 WHERE id=1")
        elif kind == "core":
            db.connection().execute(update(RequestRow).where(RequestRow.id == 1).values(value=9))
        else:
            changed = update(RequestRow).where(RequestRow.id == 1).values(value=9).returning(RequestRow.value).cte("changed")
            assert db.scalar(select(changed.c.value)) == 9
        assert db.info.get("cache_pending_write"), "Connection/CTE DML bypassed the read-only evidence guard"
        before = db.get_transaction()
        assert not dependencies.release_request_read_connection(target)
        assert db.get_transaction() is before
        assert db.scalar(select(RequestRow.value).where(RequestRow.id == 1)) == 9
        with Session(engine) as other:
            assert other.scalar(select(RequestRow.value).where(RequestRow.id == 1)) == 1
        db.commit()
        with Session(engine) as other:
            assert other.scalar(select(RequestRow.value).where(RequestRow.id == 1)) == 9
    finally:
        dependencies.end_request_scope(token)


@pytest.mark.parametrize("isolation", ["READ COMMITTED", "REPEATABLE READ", "SERIALIZABLE"])
def test_postgres_helper_releases_only_non_snapshot_request_reads(pool, monkeypatch, isolation):
    engine, _, _ = pool
    registry = scoped_session(sessionmaker(engine.execution_options(isolation_level=isolation)),
                              scopefunc=dependencies._session_scope)
    monkeypatch.setattr(dependencies, "_scoped_session", registry)
    token = dependencies.begin_request_scope()
    try:
        db = registry()
        assert db.scalar(select(RequestRow.value).where(RequestRow.id == 1)) == 1
        before = db.get_transaction()
        assert dependencies.release_request_read_connection(registry) is (isolation == "READ COMMITTED")
        if isolation == "READ COMMITTED":
            assert not db.in_transaction()
        else:
            assert db.get_transaction() is before and before is not None and before.is_active
    finally:
        dependencies.end_request_scope(token)


@pytest.mark.parametrize("share", [False, True])
def test_postgres_caller_rowlocks_are_not_released(pool, share):
    engine, registry, target = pool
    token = dependencies.begin_request_scope()
    try:
        db = registry()
        assert db.scalar(select(RequestRow.value).where(RequestRow.id == 1).with_for_update(read=share)) == 1
        assert db.info.get("cache_pending_write")
        before = db.get_transaction()
        assert not dependencies.release_request_read_connection(target)
        assert db.get_transaction() is before
        with Session(engine) as blocked:
            blocked.execute(text("SET LOCAL lock_timeout = '100ms'"))
            with pytest.raises(OperationalError, match="lock timeout"):
                blocked.execute(update(RequestRow).where(RequestRow.id == 1).values(value=9))
    finally:
        dependencies.end_request_scope(token)


def test_postgres_function_acquired_caller_lock_is_not_released(pool):
    engine, registry, target = pool
    token = dependencies.begin_request_scope()
    try:
        db = registry()
        db.execute(select(func.pg_advisory_xact_lock(7130001)))
        assert db.info.get("cache_pending_write")
        before = db.get_transaction()
        assert not dependencies.release_request_read_connection(target)
        assert db.get_transaction() is before
        with Session(engine) as other:
            assert other.scalar(select(func.pg_try_advisory_xact_lock(7130001))) is False
    finally:
        dependencies.end_request_scope(token)


def test_postgres_raw_dbapi_cursor_update_is_detected_by_server_xid_and_preserved(pool):
    engine, registry, target = pool
    token = dependencies.begin_request_scope()
    try:
        db = registry()
        assert db.scalar(select(RequestRow.value).where(RequestRow.id == 1)) == 1
        driver = db.connection().connection.driver_connection
        assert driver is not None
        with driver.cursor() as cursor:
            cursor.execute("UPDATE request_read_connection_rows SET value=9 WHERE id=1")
        assert not db.info.get("cache_pending_write"), "control: raw DBAPI bypasses SQLAlchemy hooks"
        before = db.get_transaction()
        assert not dependencies.release_request_read_connection(target)
        assert db.get_transaction() is before and db.info.get("cache_pending_write")
        assert db.scalar(select(RequestRow.value).where(RequestRow.id == 1)) == 9
        with Session(engine) as other:
            assert other.scalar(select(RequestRow.value).where(RequestRow.id == 1)) == 1
        db.commit()
        with Session(engine) as other:
            assert other.scalar(select(RequestRow.value).where(RequestRow.id == 1)) == 9
    finally:
        dependencies.end_request_scope(token)


@pytest.mark.parametrize("kind", ["advisory", "relation"])
def test_postgres_raw_dbapi_caller_locks_without_xid_are_preserved(pool, kind):
    engine, registry, target = pool
    token = dependencies.begin_request_scope()
    try:
        db = registry()
        assert db.scalar(select(RequestRow.value).where(RequestRow.id == 1)) == 1
        driver = db.connection().connection.driver_connection
        assert driver is not None
        with driver.cursor() as cursor:
            if kind == "advisory":
                cursor.execute("SELECT pg_catalog.pg_advisory_xact_lock(7130002)")
            else:
                cursor.execute("LOCK TABLE request_read_connection_rows IN SHARE MODE")
            cursor.execute("SELECT pg_catalog.pg_current_xact_id_if_assigned()")
            assert cursor.fetchone() == (None,), "this lock is not covered by the XID-only guard"
        assert not db.info.get("cache_pending_write"), "control: raw DBAPI locks bypass SQLAlchemy hooks"
        before = db.get_transaction()
        assert not dependencies.release_request_read_connection(target)
        assert db.get_transaction() is before and db.info.get("cache_pending_write")
        with Session(engine) as blocked:
            if kind == "advisory":
                assert blocked.scalar(select(func.pg_try_advisory_xact_lock(7130002))) is False
            else:
                blocked.execute(text("SET LOCAL lock_timeout = '100ms'"))
                with pytest.raises(OperationalError, match="lock timeout"):
                    blocked.execute(update(RequestRow).where(RequestRow.id == 1).values(value=9))
    finally:
        dependencies.end_request_scope(token)
