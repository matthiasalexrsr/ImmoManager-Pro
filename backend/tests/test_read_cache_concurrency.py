"""Shared reads across real connections: isolation, invalidation and bounded thread races."""

import sys
import threading
from contextvars import ContextVar
from types import SimpleNamespace

import pytest
from sqlalchemy import Integer, create_engine, event, select, text, update
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, scoped_session, sessionmaker
from test_stress_findings import client, world  # noqa: F401

from backend import concurrency
from backend.dependencies import store as app_store
from backend.repositories import SQLAlchemyStore
from backend.services.portfolio_scope import AccessScope, current_scope, scope_context


class CacheBase(DeclarativeBase):
    pass


class CacheRow(CacheBase):
    __tablename__ = "cache_test_rows"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    value: Mapped[int] = mapped_column(Integer)


@pytest.fixture
def cache(monkeypatch):
    # Register real SQLAlchemy hooks before resetting the test-local cache state.
    concurrency.track_database_changes()
    monkeypatch.setattr(concurrency, "_results", {})
    monkeypatch.setattr(concurrency, "_table_rows", {})
    monkeypatch.setattr(concurrency, "_tables", {})
    with scope_context(None):
        yield


def _engine(path, value):
    engine = create_engine(f"sqlite:///{path.as_posix()}", connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def wal(connection, _):
        connection.execute("PRAGMA journal_mode=WAL")

    CacheBase.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(CacheRow.__table__.insert().values(id=1, value=value))
    return engine


@pytest.fixture
def engine(cache, tmp_path):
    target = _engine(tmp_path / "cache.db", 1)
    yield target
    target.dispose()


def _report():
    calls = []

    @concurrency.one_at_a_time
    def report(db, year=2026):
        calls.append(year)
        return {"value": db.get(CacheRow, 1).value, "year": year}

    return report, calls


def _fresh(engine, report):
    with Session(engine, autoflush=False) as db:
        return report(db)


def test_equivalent_arguments_and_independent_sessions_share_one_result(engine):
    report, calls = _report()
    with Session(engine) as first, Session(engine) as second:
        assert report(first) == report(db=second, year=2026) == report(second, 2026)
        assert first is not second
        assert calls == [2026]
        assert not second.in_transaction(), "the hit executed no SQL"


def test_global_store_resolves_each_request_session_and_database(engine, cache, tmp_path, monkeypatch):
    request = ContextVar("cache_test_request", default="first")
    proxy = scoped_session(sessionmaker(bind=engine), scopefunc=request.get)
    monkeypatch.setattr(sys.modules[__name__], "store", SQLAlchemyStore(proxy), raising=False)
    calls = []

    @concurrency.one_at_a_time
    def report():
        calls.append(1)
        return {"value": store.db.get(CacheRow, 1).value}  # noqa: F821 (module store is swapped deliberately)

    other = _engine(tmp_path / "other.db", 9)
    try:
        assert report() == {"value": 1}
        proxy.remove()
        request.set("second")
        assert report() == {"value": 1}
        assert not proxy().in_transaction()
        assert calls == [1]
        with Session(other) as db:
            monkeypatch.setattr(sys.modules[__name__], "store", SQLAlchemyStore(db))
            assert report() == {"value": 9}
        assert calls == [1, 1]
    finally:
        proxy.remove()
        other.dispose()


def test_read_only_auth_style_select_does_not_disable_sqlite_hits(engine):
    report, calls = _report()
    assert _fresh(engine, report)["value"] == 1
    with Session(engine) as db:
        assert db.scalar(select(CacheRow.value)) == 1
        assert db.in_transaction()
        assert not db.connection().connection.driver_connection.in_transaction
        assert report(db)["value"] == 1
    assert calls == [2026]


def test_caller_held_orm_identity_map_stays_local_after_another_connection_commits(engine):
    report, _ = _report()
    with Session(engine) as reader:
        held = reader.get(CacheRow, 1)
        with Session(engine) as writer:
            writer.execute(update(CacheRow).values(value=2))
            writer.commit()
        assert _fresh(engine, report)["value"] == 2
        assert held.value == report(reader)["value"] == 1
        assert _fresh(engine, report)["value"] == 2


def test_portfolio_boundaries_never_share_results(cache):
    calls = []

    @concurrency.one_at_a_time
    def report():
        calls.append(1)
        return {"portfolios": list(current_scope().portfolio_ids)}

    for ids in (("north",), ("south",), ("north",)):
        with scope_context(AccessScope("staff", "verwalter", False, ids)):
            assert report() == {"portfolios": list(ids)}
    assert len(calls) == 2


@pytest.mark.parametrize("kind", ["result", "table"])
def test_returned_nested_values_cannot_mutate_shared_cache(engine, kind):
    loads = []

    class Loader:
        def __init__(self, db):
            self.db = db

        def load(self):
            loads.append(1)
            return [{"values": [self.db.get(CacheRow, 1).value]}]

    @concurrency.one_at_a_time
    def report(db):
        return Loader(db).load()

    with Session(engine) as db:
        def read():
            return report(db) if kind == "result" else concurrency.whole_table("cache_test_rows", Loader(db).load)

        first = read()
        first[0]["values"].append(9)
        second = read()
        assert second == [{"values": [1]}]
        second[0]["values"][0] = 7
        assert read() == [{"values": [1]}]
        assert len(loads) == 1


def test_table_cache_is_namespaced_by_database(engine, cache, tmp_path):
    other = _engine(tmp_path / "other.db", 9)

    class Loader:
        def __init__(self, db):
            self.db = db

        def load(self):
            return [self.db.get(CacheRow, 1).value]

    try:
        with Session(engine) as first, Session(other) as second:
            assert concurrency.whole_table("cache_test_rows", Loader(first).load) == [1]
            assert concurrency.whole_table("cache_test_rows", Loader(second).load) == [9]
    finally:
        other.dispose()


@pytest.mark.parametrize("write_kind", ["core", "text", "orm", "bulk"])
@pytest.mark.parametrize("finish", ["commit", "rollback"])
def test_writer_local_reads_and_commit_rollback_fences(engine, write_kind, finish):
    report, calls = _report()
    assert _fresh(engine, report)["value"] == 1
    with Session(engine, autoflush=False) as writer:
        if write_kind == "core":
            writer.execute(update(CacheRow).values(value=2))
        elif write_kind == "text":
            writer.execute(text("UPDATE cache_test_rows SET value=2"))
        elif write_kind == "bulk":
            writer.query(CacheRow).update({"value": 2})
        else:
            writer.get(CacheRow, 1).value = 2
            writer.flush()
        # The writer sees its private change; another connection still sees the
        # committed row and may cache it while the write is pending.
        assert report(writer)["value"] == 2
        assert _fresh(engine, report)["value"] == 1
        before = len(calls)
        getattr(writer, finish)()
        assert _fresh(engine, report)["value"] == (2 if finish == "commit" else 1)
        assert len(calls) == before + 1, "transaction completion invalidated the intervening read"


@pytest.mark.parametrize("finish", ["commit", "rollback"])
def test_savepoint_completion_preserves_outer_write_fence(engine, finish):
    report, calls = _report()
    with Session(engine) as writer:
        writer.execute(update(CacheRow).values(value=2))
        nested = writer.begin_nested()
        writer.execute(update(CacheRow).values(value=3))
        getattr(nested, finish)()
        assert writer.info.get("cache_pending_write"), "savepoint completion lost the outer transaction fence"
        assert report(writer)["value"] == (3 if finish == "commit" else 2)
        assert _fresh(engine, report)["value"] == 1
        before = len(calls)
        writer.commit()
        assert _fresh(engine, report)["value"] == (3 if finish == "commit" else 2)
        assert len(calls) == before + 1
        assert "cache_pending_write" not in writer.info


@pytest.mark.parametrize("kind", ["result", "table"])
def test_unflushed_orm_changes_bypass_shared_reads(engine, kind):
    report, _ = _report()

    class Loader:
        def __init__(self, db):
            self.db = db

        def load(self):
            return [{"value": self.db.get(CacheRow, 1).value, "year": 2026}]

    def read(db):
        return report(db) if kind == "result" else concurrency.whole_table("cache_test_rows", Loader(db).load)[0]

    with Session(engine, autoflush=False) as writer, Session(engine) as reader:
        assert read(reader)["value"] == 1
        writer.get(CacheRow, 1).value = 2
        assert read(writer)["value"] == 2
        assert read(reader)["value"] == 1
        writer.rollback()
        assert read(reader)["value"] == 1


@pytest.mark.parametrize("connection_bound", [False, True])
def test_existing_sqlite_snapshot_neither_consumes_nor_publishes_shared_results(engine, connection_bound):
    report, _ = _report()
    with engine.connect() as connection:
        snapshot = Session(connection if connection_bound else engine, autoflush=False)
        try:
            snapshot.connection().exec_driver_sql("BEGIN")
            assert report(snapshot)["value"] == 1
            with Session(engine) as writer:
                writer.execute(update(CacheRow).values(value=2))
                writer.commit()
            assert _fresh(engine, report)["value"] == 2
            assert report(snapshot)["value"] == 1
            assert _fresh(engine, report)["value"] == 2
        finally:
            snapshot.rollback()
            snapshot.close()


def test_hot_hit_finishes_while_unrelated_report_holds_compute_lock(cache):
    started, release, hit_finished = threading.Event(), threading.Event(), threading.Event()
    errors = []

    @concurrency.one_at_a_time
    def report(key):
        if key == "slow":
            started.set()
            assert release.wait(5)
        return {"key": key}

    assert report("hot") == {"key": "hot"}

    def run(key, finished=None):
        try:
            assert report(key) == {"key": key}
            if finished:
                finished.set()
        except BaseException as error:
            errors.append(error)

    slow = threading.Thread(target=run, args=("slow",))
    hot = threading.Thread(target=run, args=("hot", hit_finished))
    slow.start()
    try:
        assert started.wait(5)
        hot.start()
        assert hit_finished.wait(2), "the hot hit waited behind unrelated heavy computation"
    finally:
        release.set()
        slow.join(5)
        if hot.ident is not None:
            hot.join(5)
    assert not slow.is_alive() and not hot.is_alive()
    assert not errors, errors


def test_simultaneous_sql_session_misses_compute_once_and_lock_is_reentrant(engine):
    gate = threading.Barrier(4)
    calls, answers, errors = [], [], []

    @concurrency.one_at_a_time
    def inner(db):
        calls.append(1)
        return {"value": db.scalar(select(CacheRow.value))}

    @concurrency.one_at_a_time
    def outer(db):
        return inner(db)

    def read():
        try:
            with Session(engine) as db:
                gate.wait(5)
                answers.append(outer(db))
        except BaseException as error:
            errors.append(error)

    threads = [threading.Thread(target=read) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(5)
        assert not thread.is_alive(), "reentrant/single-compute read deadlocked"
    assert not errors, errors
    assert answers == [{"value": 1}] * 4
    assert calls == [1]


def test_memory_store_and_unknown_repr_arguments_never_share_results(cache):
    from backend.storage import InMemoryStore

    calls = []

    @concurrency.one_at_a_time
    def report(source):
        calls.append(1)
        return {"call": len(calls)}

    for source in (InMemoryStore(), SimpleNamespace()):
        assert report(source) != report(source)


@pytest.mark.skipif(not hasattr(app_store, "db"), reason="real HTTP session sharing requires TEST_STORE_BACKEND=sql")
def test_repeated_real_http_requests_reuse_computation(cache, client, world, monkeypatch):  # noqa: F811
    from backend.routers import review

    real = review.review_items
    calls = []

    def counted(*args, **kwargs):
        calls.append(1)
        return real(*args, **kwargs)

    monkeypatch.setattr(review, "review_items", counted)
    first = client.get("/api/v1/review", headers=world["owner"])
    second = client.get("/api/v1/review", headers=world["owner"])
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    assert calls == [1], "fresh authenticated request sessions did not reuse the shared result"
