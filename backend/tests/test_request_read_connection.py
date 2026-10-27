"""Release only proven request reads before acquiring a second pooled connection."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event
from typing import cast

import pytest
from sqlalchemy import Integer, create_engine, func, insert, select, text, update
from sqlalchemy.exc import TimeoutError as PoolTimeout
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, scoped_session, sessionmaker

from backend import concurrency, dependencies
from backend.repositories import SQLAlchemyStore
from backend.services.portfolio_scope import scope_context


class RequestBase(DeclarativeBase):
    pass


class RequestRow(RequestBase):
    __tablename__ = "request_read_connection_rows"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    value: Mapped[int] = mapped_column(Integer)


@pytest.fixture
def pool(tmp_path, monkeypatch):
    concurrency.track_database_changes()
    engine = create_engine(f"sqlite:///{(tmp_path / 'pool.db').as_posix()}",
                           pool_size=2, max_overflow=0, pool_timeout=0.25,
                           connect_args={"check_same_thread": False})
    RequestBase.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(insert(RequestRow), [{"id": 1, "value": 1}, {"id": 2, "value": 2}])
    registry = scoped_session(sessionmaker(engine, autoflush=False), scopefunc=dependencies._session_scope)
    monkeypatch.setattr(dependencies, "_scoped_session", registry)
    target = SQLAlchemyStore(cast(Session, registry))
    with scope_context(None):
        yield engine, registry, target
    registry.remove()
    engine.dispose()


@pytest.mark.parametrize("release", [False, True])
def test_two_request_reads_cannot_starve_their_owned_write_connections(pool, release):
    engine, registry, target = pool
    ready = [Event(), Event()]
    start = Barrier(3)
    attempted = Barrier(2)

    def write(index):
        token = dependencies.begin_request_scope()
        try:
            # Two real reads occupy the entire pool before either write begins.
            assert registry.scalar(select(RequestRow.value).where(RequestRow.id == index + 1)) == index + 1
            ready[index].set()
            start.wait(5)
            if release:
                assert dependencies.release_request_read_connection(target)
            try:
                with Session(engine) as owned:
                    owned.execute(update(RequestRow).where(RequestRow.id == index + 1).values(value=10 + index))
                    owned.commit()
                outcome = "committed"
            except PoolTimeout:
                outcome = "pool timeout"
            # In the control case, keep both original connections checked out
            # until both attempted writes time out; cleanup cannot rescue one.
            attempted.wait(5)
            return outcome
        finally:
            dependencies.end_request_scope(token)

    with ThreadPoolExecutor(2) as workers:
        futures = [workers.submit(write, index) for index in range(2)]
        assert all(event.wait(5) for event in ready)
        assert engine.pool.checkedout() == 2
        start.wait(5)
        outcomes = [future.result(10) for future in futures]
    assert outcomes == (["committed"] * 2 if release else ["pool timeout"] * 2)
    assert engine.pool.checkedout() == 0
    with Session(engine) as check:
        assert list(check.scalars(select(RequestRow.value).order_by(RequestRow.id))) == ([10, 11] if release else [1, 2])


@pytest.mark.parametrize("source", ["store", "proxy", "session"])
def test_clean_request_autobegin_is_released_without_replacing_its_session(pool, source):
    engine, registry, target = pool
    token = dependencies.begin_request_scope()
    try:
        db = registry()
        assert db.scalar(select(RequestRow.value).where(RequestRow.id == 1)) == 1
        candidate = {"store": target, "proxy": registry, "session": db}[source]
        assert dependencies.release_request_read_connection(candidate)
        assert registry() is db
        assert not db.in_transaction()
        assert engine.pool.checkedout() == 0
        assert db.scalar(select(RequestRow.value).where(RequestRow.id == 1)) == 1
    finally:
        dependencies.end_request_scope(token)


def test_builtin_aggregate_reads_do_not_invalidate_other_request_caches(pool):
    _, registry, target = pool
    token = dependencies.begin_request_scope()
    try:
        before = concurrency._version
        assert registry.scalar(select(func.sum(func.round(RequestRow.value, 2)))) == 3
        assert registry.scalar(select(func.count(RequestRow.id))) == 2
        assert not registry.info.get("cache_pending_write")
        assert concurrency._version == before
        assert dependencies.release_request_read_connection(target)
        assert concurrency._version == before
    finally:
        dependencies.end_request_scope(token)


@pytest.mark.parametrize("kind", ["new", "dirty", "deleted", "flushed", "core", "unknown", "connection_core",
                                 "connection_raw", "locking_read", "scoped_writer"])
def test_pending_request_work_is_never_rolled_back(pool, kind):
    _, registry, target = pool
    token = dependencies.begin_request_scope()
    try:
        db = registry()
        assert db.scalar(select(RequestRow.value).where(RequestRow.id == 1)) == 1
        row = None
        if kind == "new":
            row = RequestRow(id=3, value=3)
            db.add(row)
        elif kind in {"dirty", "deleted", "flushed"}:
            row = db.get(RequestRow, 1)
            assert row is not None
            if kind == "deleted":
                db.delete(row)
            else:
                row.value = 9
                if kind == "flushed":
                    db.flush()
        elif kind == "core":
            db.execute(update(RequestRow).where(RequestRow.id == 1).values(value=9))
        elif kind == "unknown":
            db.execute(text("UPDATE request_read_connection_rows SET value=9 WHERE id=1"))
        elif kind == "connection_core":
            db.connection().execute(update(RequestRow).where(RequestRow.id == 1).values(value=9))
            assert db.info.get("cache_pending_write")
        elif kind == "connection_raw":
            db.connection().exec_driver_sql("UPDATE request_read_connection_rows SET value=9 WHERE id=1")
            assert db.info.get("cache_pending_write")
        elif kind == "locking_read":
            assert db.scalar(select(RequestRow.value).where(RequestRow.id == 1).with_for_update()) == 1
            assert db.info.get("cache_pending_write")
        else:
            db.info["scoped_writer"] = object()
        before = db.get_transaction()
        assert not dependencies.release_request_read_connection(target)
        assert db.get_transaction() is before
        assert before is not None and before.is_active
        if kind == "new":
            assert row in db.new
        elif kind == "dirty":
            assert row is not None
            assert row in db.dirty and row.value == 9
        elif kind == "deleted":
            assert row in db.deleted
        elif kind in {"flushed", "core", "unknown", "connection_core", "connection_raw"}:
            assert db.scalar(select(RequestRow.value).where(RequestRow.id == 1)) == 9
        if kind == "scoped_writer":
            db.info.pop("scoped_writer")
    finally:
        dependencies.end_request_scope(token)


@pytest.mark.parametrize("kind", ["explicit", "nested", "sqlite_snapshot"])
def test_explicit_transactions_and_snapshots_stay_owned_by_the_caller(pool, kind):
    _, registry, target = pool
    token = dependencies.begin_request_scope()
    try:
        db = registry()
        if kind == "explicit":
            db.begin()
        assert db.scalar(select(RequestRow.value).where(RequestRow.id == 1)) == 1
        if kind == "nested":
            db.begin_nested()
        elif kind == "sqlite_snapshot":
            db.connection().exec_driver_sql("BEGIN")
        before = db.get_transaction()
        assert not dependencies.release_request_read_connection(target)
        assert db.get_transaction() is before
        assert before is not None and before.is_active
    finally:
        dependencies.end_request_scope(token)


def test_foreign_session_and_thread_scoped_direct_caller_are_not_released(pool):
    engine, registry, target = pool
    # Direct service calls outside request scope retain their transaction.
    assert registry.scalar(select(RequestRow.value).where(RequestRow.id == 1)) == 1
    before = registry().get_transaction()
    assert not dependencies.release_request_read_connection(target)
    assert registry().get_transaction() is before
    registry.remove()
    token = dependencies.begin_request_scope()
    try:
        assert registry.scalar(select(RequestRow.value).where(RequestRow.id == 1)) == 1
        with Session(engine) as foreign:
            assert foreign.scalar(select(RequestRow.value).where(RequestRow.id == 1)) == 1
            before = foreign.get_transaction()
            assert not dependencies.release_request_read_connection(foreign)
            assert foreign.get_transaction() is before
            assert registry().in_transaction()
    finally:
        dependencies.end_request_scope(token)


def test_caller_owned_connection_bind_is_not_released(pool, monkeypatch):
    engine, _, _ = pool
    with engine.connect() as connection:
        outer = connection.begin()
        registry = scoped_session(sessionmaker(connection), scopefunc=dependencies._session_scope)
        monkeypatch.setattr(dependencies, "_scoped_session", registry)
        token = dependencies.begin_request_scope()
        try:
            assert registry.scalar(select(RequestRow.value).where(RequestRow.id == 1)) == 1
            assert not dependencies.release_request_read_connection(registry)
            assert outer.is_active and registry().in_transaction()
        finally:
            dependencies.end_request_scope(token)


def test_no_release_without_tracking_or_without_an_existing_request_session(pool, monkeypatch):
    _, registry, target = pool
    token = dependencies.begin_request_scope()
    try:
        assert not registry.registry.has()
        assert not dependencies.release_request_read_connection(target)
        assert not registry.registry.has(), "the helper created an unused request Session"
        assert registry.scalar(select(RequestRow.value).where(RequestRow.id == 1)) == 1
        before = registry().get_transaction()
        monkeypatch.setattr(concurrency, "_tracking", False)
        assert not dependencies.release_request_read_connection(target)
        assert registry().get_transaction() is before
    finally:
        dependencies.end_request_scope(token)


def test_no_release_without_positive_connection_read_evidence(pool):
    _, registry, target = pool
    token = dependencies.begin_request_scope()
    try:
        db = registry()
        assert db.scalar(select(RequestRow.value).where(RequestRow.id == 1)) == 1
        before = db.get_transaction()
        assert db.info.get("request_read_connection_guard") is before
        db.info.pop("request_read_connection_guard")
        assert not dependencies.release_request_read_connection(target)
        assert db.get_transaction() is before
    finally:
        dependencies.end_request_scope(token)
