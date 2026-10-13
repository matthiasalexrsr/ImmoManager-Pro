"""FIFO admission, per-engine isolation and connection checkout after admission."""

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from typing import cast

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, scoped_session, sessionmaker
from test_booking_writes import payload
from test_rent_payments import seed

from backend import auth
from backend.audit import SQLAuditStore
from backend.models import AuditLogEntry
from backend.repositories import SQLAlchemyStore
from backend.services import document_versions as archive
from backend.services import sqlite_writes as writes
from backend.services.booking_writes import booking_write
from backend.services.payment_allocations import auto_allocate


def test_queue_is_fifo_and_nested_owner_does_not_jump_waiters(monkeypatch):
    queue = writes.WriterQueue()
    admitted, queued = [], [threading.Event() for _ in range(3)]
    original_wait = queue.condition.wait
    names: dict[int, int] = {}

    def waiting(timeout=None):
        queued[names[threading.get_ident()]].set()
        return original_wait(timeout)

    monkeypatch.setattr(queue.condition, "wait", waiting)
    queue.acquire()
    queue.acquire()

    def worker(index):
        names[threading.get_ident()] = index
        queue.acquire()
        try:
            admitted.append(index)
        finally:
            queue.release()

    with ThreadPoolExecutor(3) as pool:
        futures = []
        for index in range(3):
            futures.append(pool.submit(worker, index))
            assert queued[index].wait(timeout=5)
        queue.release()
        assert admitted == []
        queue.release()
        for future in futures:
            future.result(timeout=5)
    assert admitted == [0, 1, 2]
    assert queue.owner is None and queue.depth == 0 and not queue.waiters


def test_cancelled_waiter_is_removed_and_does_not_block_following_writers(monkeypatch):
    queue = writes.WriterQueue()
    queue.acquire()

    def interrupted(*_):
        raise RuntimeError("wait interrupted")

    monkeypatch.setattr(queue.condition, "wait", interrupted)
    with ThreadPoolExecutor(1) as pool:
        with pytest.raises(RuntimeError, match="wait interrupted"):
            pool.submit(queue.acquire).result(timeout=5)
    assert not queue.waiters
    queue.release()
    queue.acquire()
    queue.release()


def test_different_engines_and_postgres_do_not_wait_for_sqlite_owner():
    first, second = create_engine("sqlite:///:memory:"), create_engine("sqlite:///:memory:")
    entered = threading.Event()

    def other():
        with writes.sqlite_write_gate(second, "archive"):
            entered.set()

    with writes.sqlite_write_gate(first, "booking"):
        with ThreadPoolExecutor(1) as pool:
            future = pool.submit(other)
            assert entered.wait(timeout=5)
            future.result(timeout=5)
        pg = SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))
        with writes.sqlite_write_gate(pg, "booking") as timing:
            assert timing is None
    first.dispose()
    second.dispose()


def test_gate_releases_after_failure_and_reenters_same_engine():
    engine = create_engine("sqlite:///:memory:")
    with pytest.raises(RuntimeError):
        with writes.sqlite_write_gate(engine, "booking"):
            with writes.sqlite_write_gate(engine, "archive"):
                raise RuntimeError("fail")
    entered = threading.Event()

    def retry():
        with writes.sqlite_write_gate(engine, "booking"):
            entered.set()

    with ThreadPoolExecutor(1) as pool:
        pool.submit(retry).result(timeout=5)
    assert entered.is_set()
    engine.dispose()


def test_eight_booking_writers_share_one_pool_slot_and_emit_separate_timings(tmp_path, caplog):
    from backend.db.orm_models import Base

    engine = create_engine(f"sqlite:///{(tmp_path / 'queue.db').as_posix()}", pool_size=1, max_overflow=0, pool_timeout=5)
    Base.metadata.create_all(engine)
    sessions = scoped_session(sessionmaker(engine))
    target = SQLAlchemyStore(cast(Session, sessions))
    data = seed(target)
    gate = threading.Barrier(8)
    active, maximum = 0, 0
    lock = threading.Lock()

    @event.listens_for(engine, "checkout")
    def checkout(*_):
        nonlocal active, maximum
        with lock:
            active += 1
            maximum = max(maximum, active)

    @event.listens_for(engine, "checkin")
    def checkin(*_):
        nonlocal active
        with lock:
            active -= 1

    caplog.set_level("INFO", logger=writes.__name__)

    def pay(_):
        try:
            gate.wait(timeout=5)
            with booking_write(target, changes=payload(data).model_dump()) as unit:
                booking = unit.create_booking(payload(data))
                auto_allocate(unit, booking)
            return booking.id
        finally:
            sessions.remove()

    try:
        with ThreadPoolExecutor(8) as pool:
            ids = list(pool.map(pay, range(8)))
        assert len(set(ids)) == len(target.list_bookings()) == len(target.list_payment_allocations()) == 8
        assert maximum == 1
        timings = [json.loads(record.getMessage().removeprefix("sqlite_write_timing "))
                   for record in caplog.records if record.name == writes.__name__]
        assert len(timings) == 8
        for timing in timings:
            assert timing["kind"] == "booking" and timing["outcome"] == "committed"
            assert {"queue_wait_ms", "connection_ms", "begin_ms", "commit_ms", "held_ms"} <= timing.keys()
            assert all(timing[key] >= 0 for key in ("queue_wait_ms", "connection_ms", "begin_ms", "commit_ms"))
    finally:
        sessions.remove()
        engine.dispose()


def test_archive_and_audit_wait_in_same_queue_before_connection_checkout(tmp_path, caplog, monkeypatch):
    from backend.db.orm_models import Base

    engine = create_engine(f"sqlite:///{(tmp_path / 'shared.db').as_posix()}", pool_size=1, max_overflow=0, pool_timeout=5)
    Base.metadata.create_all(engine)
    sessions = scoped_session(sessionmaker(engine))
    target = SQLAlchemyStore(cast(Session, sessions))
    monkeypatch.setattr(auth, "_user_store", auth.InMemoryUserStore())
    owner = auth.register_user("owner", "owner@test.invalid", "Owner", "Secret123", "eigentuemer")
    audit = SQLAuditStore(sessionmaker(engine))
    entry = AuditLogEntry(id="audit-one", action="create", entity_type="bookings", entity_id="new")
    caplog.set_level("INFO", logger=writes.__name__)
    admitted, checkouts = [], []
    event.listen(engine, "checkout", lambda *_: checkouts.append(1))
    names: dict[int, int] = {}
    queued = [threading.Event(), threading.Event()]

    def archive_writer():
        names[threading.get_ident()] = 0
        try:
            with archive.work(target, owner.id, write_areas=("/bookings",)):
                admitted.append("archive")
        finally:
            sessions.remove()

    def audit_writer():
        names[threading.get_ident()] = 1
        audit.add(entry)
        admitted.append("audit")

    try:
        with ThreadPoolExecutor(2) as pool:
            with writes.sqlite_write_gate(engine, "held"):
                queue = writes._queues[engine]
                original_wait = queue.condition.wait

                def waiting(timeout=None):
                    queued[names[threading.get_ident()]].set()
                    return original_wait(timeout)

                monkeypatch.setattr(queue.condition, "wait", waiting)
                first = pool.submit(archive_writer)
                assert queued[0].wait(timeout=5)
                second = pool.submit(audit_writer)
                assert queued[1].wait(timeout=5)
                assert checkouts == []
            first.result(timeout=5)
            second.result(timeout=5)
        assert admitted == ["archive", "audit"]
        timings = [json.loads(record.getMessage().removeprefix("sqlite_write_timing "))
                   for record in caplog.records if record.name == writes.__name__]
        assert {row["kind"] for row in timings} == {"held", "archive", "audit"}
        audit_timing = next(row for row in timings if row["kind"] == "audit")
        assert audit_timing["outcome"] == "committed" and "flush_ms" in audit_timing
        # A duplicate audit row remains non-fatal and releases its gate on rollback.
        audit.add(entry)
        with writes.sqlite_write_gate(engine, "after_failed_audit"):
            pass
    finally:
        sessions.remove()
        engine.dispose()


def test_unbound_audit_session_failure_remains_nonfatal():
    audit = SQLAuditStore(lambda: Session())
    audit.add(AuditLogEntry(id="unbound", action="create", entity_type="bookings", entity_id="new"))


def test_outer_audit_worker_receives_inner_request_id_and_resets_context(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from backend import middleware
    from backend.logging_config import request_id_var

    app = FastAPI()
    app.add_middleware(middleware.RequestLoggingMiddleware)
    app.add_middleware(middleware.AuditMiddleware)

    @app.post("/api/v1/bookings")
    def write():
        return {"ok": True}

    observed = []
    monkeypatch.setattr(middleware, "log_action", lambda **_: observed.append(request_id_var.get()))
    before = request_id_var.get()
    with TestClient(app) as client:
        response = client.post("/api/v1/bookings")
    assert response.status_code == 200
    assert observed == [response.headers["X-Request-ID"]]
    assert request_id_var.get() == before
