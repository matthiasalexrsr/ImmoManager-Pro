"""Regressions for complete date pages, ephemeral caches and real cancellation."""

import inspect
import sqlite3
import threading
import time
from datetime import date
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, insert, text
from sqlalchemy.orm import Session

from backend import concurrency
from backend.db.orm_models import Base, BookingORM, ContractORM, InvoiceORM, MaintenanceCaseORM
from backend.models import Booking, Contract, Invoice, MaintenanceCase
from backend.repositories.sql_store import SQLAlchemyStore
from backend.routers import bookings, contracts, invoices, maintenance
from backend.services.task_queue import SyncQueue, ThreadPoolQueue
from backend.storage import InMemoryStore

ENTITIES = [
    ("booking", "bookings", BookingORM, Booking, bookings, "list_bookings", "booking_date",
     {"account_id": "account", "amount": 1}),
    ("contract", "contracts", ContractORM, Contract, contracts, "list_contracts", "start_date",
     {"contract_number": "contract", "property_id": "property", "unit_id": "unit", "tenant_id": "tenant"}),
    ("invoice", "invoices", InvoiceORM, Invoice, invoices, "list_invoices", "invoice_date",
     {"supplier": "supplier", "net_amount": 1, "gross_amount": 1}),
    ("maintenance", "maintenance_cases", MaintenanceCaseORM, MaintenanceCase, maintenance,
     "list_maintenance_cases", "due_date", {"property_id": "property", "title": "case"}),
]


@pytest.fixture(params=["memory", "sql"])
def paged_store(request):
    if request.param == "memory":
        yield InMemoryStore()
        return
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        yield SQLAlchemyStore(db)
    engine.dispose()


def _seed(store, spec):
    entity, collection, orm, model, _module, _name, day_field, payload = spec
    rows = []
    for i, day in enumerate([date(2026, 1, 1)] * 10001 + [
        date(2026, 10, 6), date(2026, 10, 7), date(2026, 10, 8), date(2026, 10, 8),
        date(2026, 10, 9), date(2026, 10, 10),
    ]):
        fields = {**payload, "id": f"row-{i:05}", day_field: day}
        if entity == "contract":
            fields["end_date"] = day
            fields["contract_number"] = fields["id"]
        rows.append(model(**fields))
    # Matching dates with a different equality filter must not shift the pages.
    extra = rows[-3].model_copy(update={"id": "other-status", "contract_number": "other-status",
                                      "status": "terminated" if entity == "contract" else "closed"})
    rows.append(extra)
    if entity in {"contract", "maintenance"}:
        rows.append(rows[-2].model_copy(update={"id": "no-date", "contract_number": "no-date",
                                              "end_date" if entity == "contract" else day_field: None}))
    if isinstance(store, InMemoryStore):
        getattr(store, collection).update({row.id: row for row in rows})
    else:
        store.db.execute(insert(orm.__table__), [row.model_dump() for row in rows])
        store.db.commit()


@pytest.mark.parametrize("spec", ENTITIES, ids=[row[0] for row in ENTITIES])
def test_date_filters_include_tail_boundaries_and_stable_following_pages(paged_store, spec, monkeypatch):
    """Filtering after a 10k intermediate limit loses every matching tail row."""
    _seed(paged_store, spec)
    _entity, _collection, _orm, _model, module, name, field, _payload = spec
    monkeypatch.setattr(module, "store", paged_store)
    route = getattr(module, name)
    defaults = {key: getattr(param.default, "default", param.default)
                for key, param in inspect.signature(route).parameters.items()}
    defaults.update(date_from=date(2026, 10, 7), date_to=date(2026, 10, 9), limit=2,
                    sort_by=field, status_filter="active" if spec[0] == "contract" else "open")
    first = route(**{**defaults, "skip": 0})
    second = route(**{**defaults, "skip": 2})
    assert [row.id for row in first] == ["row-10002", "row-10003"]
    assert [row.id for row in second] == ["row-10004", "row-10005"]
    assert route(**{**defaults, "skip": 4}) == []
    assert [row.id for row in route(**{**defaults, "sort_order": "desc", "skip": 0})] == [
        "row-10005", "row-10003"]


@pytest.mark.parametrize("bounds,want", [
    ((date(2026, 10, 8), date(2026, 10, 8)), ["b", "c"]),
    ((None, date(2026, 10, 8)), ["a", "b", "c"]),
    ((date(2026, 10, 8), None), ["b", "c", "d"]),
    ((None, None), ["a", "b", "c", "d", "null"]),
    ((date(2026, 10, 9), date(2026, 10, 7)), []),
])
def test_store_ranges_apply_before_offset_with_open_and_null_bounds(paged_store, bounds, want):
    rows = [MaintenanceCase(id=key, property_id="p", title=key, due_date=day)
            for key, day in [("a", date(2026, 10, 7)), ("b", date(2026, 10, 8)),
                             ("c", date(2026, 10, 8)), ("d", date(2026, 10, 9)), ("null", None)]]
    if isinstance(paged_store, InMemoryStore):
        paged_store.maintenance_cases.update({row.id: row for row in rows})
    else:
        paged_store.db.execute(insert(MaintenanceCaseORM.__table__), [row.model_dump() for row in rows])
        paged_store.db.commit()
    result = paged_store._list_paginated("maintenance", range_filters={"due_date": bounds}, skip=1, limit=2)
    assert [row.id for row in result] == want[1:3]


def test_fresh_schema_indexes_tenant_booking_lookups():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with engine.connect() as db:
        plan = db.execute(text("EXPLAIN QUERY PLAN SELECT * FROM bookings WHERE tenant_id='tenant'")).all()
        assert any("SEARCH bookings USING INDEX idx_bookings_tenant" in row[-1] for row in plan)
    engine.dispose()


def test_booking_tenant_index_upgrade_preserves_rows_and_downgrade_is_additive(tmp_path, monkeypatch):
    path = tmp_path / "migration.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{path}")
    config = Config()
    config.set_main_option("script_location", str(Path(__file__).resolve().parents[1] / "db" / "migrations"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{path}")
    command.upgrade(config, "6e2f8a4c9b71")
    with sqlite3.connect(path) as db:
        db.executescript("""
            INSERT INTO portfolios(id,name,currency,timezone,status,created_at,updated_at)
                VALUES('p','Synthetic','EUR','Europe/Berlin','active','2026-01-01','2026-01-01');
            INSERT INTO accounts(id,portfolio_id,name,account_type,opening_balance,balance,created_at,updated_at)
                VALUES('a','p','Synthetic','bank',0,0,'2026-01-01','2026-01-01');
            INSERT INTO tenants(id,full_name,created_at,updated_at)
                VALUES('t','Synthetic','2026-01-01','2026-01-01');
            INSERT INTO bookings(id,account_id,tenant_id,booking_date,amount,status,created_at,updated_at)
                VALUES('b','a','t','2026-10-07',12.34,'open','2026-01-01','2026-01-01');
        """)
        assert not any("SEARCH bookings USING INDEX idx_bookings_tenant" in row[-1] for row in
                       db.execute("EXPLAIN QUERY PLAN SELECT * FROM bookings WHERE tenant_id='t'"))
    command.upgrade(config, "head")
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT id,amount FROM bookings WHERE tenant_id='t'").fetchall() == [("b", 12.34)]
        assert any("SEARCH bookings USING INDEX idx_bookings_tenant" in row[-1] for row in
                   db.execute("EXPLAIN QUERY PLAN SELECT * FROM bookings WHERE tenant_id='t'"))
    command.downgrade(config, "6e2f8a4c9b71")
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT id,amount FROM bookings").fetchall() == [("b", 12.34)]
        assert "idx_bookings_tenant" not in {row[1] for row in db.execute("PRAGMA index_list(bookings)")}


@pytest.mark.parametrize("kind", ["result", "table"])
def test_concurrent_write_does_not_wait_for_compute_or_publish_stale_cache(cache, kind):
    started, release, written = threading.Event(), threading.Event(), threading.Event()
    calls, answers = [], []

    def load():
        calls.append(1)
        if len(calls) == 1:
            started.set()
            assert release.wait(5)
        return [len(calls)]

    read = concurrency.one_at_a_time(load) if kind == "result" else lambda: concurrency.whole_table("dirty", load)
    worker = threading.Thread(target=lambda: answers.append(read()))
    writer = threading.Thread(target=lambda: (concurrency.note_change(), written.set()))
    worker.start()
    try:
        assert started.wait(5)
        writer.start()
        assert written.wait(5), "cache invalidation waited for the computation lock"
    finally:
        release.set()
        worker.join(5)
        if writer.ident is not None:
            writer.join(5)
    assert answers == [[1]]
    assert read() == read() == [2]


@pytest.fixture
def cache(monkeypatch):
    monkeypatch.setattr(concurrency, "_tracking", True)
    monkeypatch.setattr(concurrency, "_results", {})
    monkeypatch.setattr(concurrency, "_table_rows", {})
    monkeypatch.setattr(concurrency, "_tables", {})
    clock = [0.0]
    monkeypatch.setattr(concurrency.time, "monotonic", lambda: clock[0])
    return clock


@pytest.mark.parametrize("kind", ["result", "table"])
def test_slow_cache_work_ages_from_completion(cache, kind):
    calls = []

    def load():
        calls.append(1)
        cache[0] += concurrency.KEEP_SECONDS + 1
        return [len(calls)]

    read = concurrency.one_at_a_time(load) if kind == "result" else lambda: concurrency.whole_table("slow", load)
    assert read() == read() == [1]
    assert calls == [1]
    cache[0] += concurrency.KEEP_SECONDS
    assert read() == [2]


@pytest.mark.parametrize("kind", ["result", "table"])
def test_write_during_cache_work_prevents_stale_reuse(cache, kind):
    calls = []

    def load():
        calls.append(1)
        if len(calls) == 1:
            concurrency.note_change()
        return [len(calls)]

    read = concurrency.one_at_a_time(load) if kind == "result" else lambda: concurrency.whole_table("dirty", load)
    assert read() == [1]
    assert read() == [2]
    assert read() == [2]


def test_expired_caches_release_other_keys_and_writes_release_stale_values(cache):
    @concurrency.one_at_a_time
    def report(key):
        return [key]

    for key in range(12000):
        report(key)
    assert len(concurrency._results) < 12000
    concurrency.whole_table("old", lambda: ["large result"])
    cache[0] += concurrency.KEEP_SECONDS
    report("new")
    assert len(concurrency._results) == 1
    assert concurrency._table_rows == {}
    concurrency.whole_table("bookings", lambda: ["large result"])
    concurrency._note_tables({"bookings"})
    assert concurrency._results == {}
    assert concurrency._table_rows == {}


def test_failed_cache_work_is_retried(cache):
    calls = []

    @concurrency.one_at_a_time
    def report():
        calls.append(1)
        if len(calls) == 1:
            raise ValueError("first calculation failed")
        return ["ok"]

    with pytest.raises(ValueError):
        report()
    assert report() == report() == ["ok"]
    assert len(calls) == 2


def test_cancelled_queued_job_never_runs_and_running_job_cannot_cancel():
    queue = ThreadPoolQueue(max_workers=1)
    started, release = threading.Event(), threading.Event()
    effects = []

    def block():
        started.set()
        assert release.wait(5), "test worker was never released"
        return "first"

    try:
        running = queue.enqueue(block)
        assert started.wait(5)
        pending = queue.enqueue(lambda: effects.append("cancelled work ran"))
        assert queue.cancel(running.task_id) is False
        assert queue.cancel(pending.task_id) is True
        assert queue.cancel(pending.task_id) is False
        assert queue.cancel("unknown") is False
    finally:
        release.set()
        queue._pool.shutdown(wait=True)
    assert effects == []
    assert queue.get_status(pending.task_id).status == "cancelled"
    assert queue.get_status(running.task_id).result == "first"


@pytest.mark.parametrize("queue_class", [SyncQueue, ThreadPoolQueue])
def test_job_retention_cleans_terminal_results_without_losing_recent_ids(queue_class, monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(time, "monotonic", lambda: clock[0])
    queue = queue_class(result_retention_seconds=60)
    jobs = [queue.enqueue(lambda i=i: i) for i in range(12000)]
    if isinstance(queue, ThreadPoolQueue):
        queue._pool.shutdown(wait=True)
    assert all(queue.get_status(job.task_id).result == i for i, job in enumerate(jobs))
    clock[0] = 60
    assert queue.cleanup_results() == 12000
    assert all(queue.get_status(job.task_id) is None for job in jobs)


def test_retention_never_removes_pending_or_running_work(monkeypatch):
    clock = [0.0]
    monkeypatch.setattr(time, "monotonic", lambda: clock[0])
    queue = ThreadPoolQueue(max_workers=1, result_retention_seconds=60)
    started, release = threading.Event(), threading.Event()

    def block():
        started.set()
        assert release.wait(5)

    try:
        running = queue.enqueue(block)
        assert started.wait(5)
        pending = queue.enqueue(lambda: "later")
        clock[0] = 3600
        assert queue.cleanup_results() == 0
        assert queue.get_status(running.task_id).status == "running"
        assert queue.get_status(pending.task_id).status == "pending"
    finally:
        release.set()
        queue._pool.shutdown(wait=True)
    assert queue.get_status(pending.task_id).result == "later"
    clock[0] += 60
    assert queue.cleanup_results() == 2


def test_thread_job_failures_release_future_and_keep_error():
    queue = ThreadPoolQueue()

    def fail():
        raise ValueError("synthetic failure")

    failed = queue.enqueue(fail)
    queue._pool.shutdown(wait=True)
    assert queue.get_status(failed.task_id).status == "failed"
    assert queue.get_status(failed.task_id).error == "synthetic failure"
    assert queue._futures == {}


def test_racing_start_and_cancel_never_runs_an_accepted_cancellation():
    queue = ThreadPoolQueue(max_workers=4)
    effects, accepted = [], []
    try:
        for i in range(500):
            job = queue.enqueue(lambda i=i: effects.append(i))
            if queue.cancel(job.task_id):
                accepted.append((i, job.task_id))
    finally:
        queue._pool.shutdown(wait=True)
    assert all(i not in effects and queue.get_status(task_id).status == "cancelled" for i, task_id in accepted)
    assert len(effects) + len(accepted) == 500
