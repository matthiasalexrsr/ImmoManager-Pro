"""Durable jobs: leases, checkpoints, restart, concurrent workers, catch-up, DST, rule versions."""

import asyncio
import threading
from datetime import date, datetime, timedelta, timezone
from typing import Any

import pytest
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import Session
from test_document_versions_postgres import postgres  # noqa: F401  (fixture: own database per test)

from backend import db as _db  # noqa: F401  (registers every table with Base)
from backend import models as _models  # noqa: F401  (UI contract columns)
from backend.db.job_models import JobOccurrenceORM
from backend.db.orm_models import Base, TaskORM
from backend.models import TaskCreate
from backend.repositories import SQLAlchemyStore
from backend.services.jobs import recurring
from backend.services.jobs.core import JobContext, JobRunner, LeaseLost, MemoryJobStore, SqlJobStore
from backend.services.jobs.schedule import BERLIN, DailyAt, local_today
from backend.services.jobs.scheduler import ESCALATION_KIND, PERIODIC, SERVICE_CONTRACT_KIND, enqueue_due, tick
from backend.services.portfolio_scope import AccessScope, current_scope, scope_context
from backend.storage import InMemoryStore

T0 = datetime(2026, 10, 7, 8, 0)


class Clock:
    def __init__(self, start=T0):
        self.now = start

    def __call__(self):
        return self.now

    def advance(self, **delta):
        self.now += timedelta(**delta)


def sqlite_engine(path):
    engine = create_engine(f"sqlite:///{path}", connect_args={"check_same_thread": False, "timeout": 30})

    @event.listens_for(engine, "connect")
    def _pragmas(dbapi_conn, _record):
        dbapi_conn.execute("PRAGMA journal_mode=WAL")
        dbapi_conn.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    return engine


class Backend:
    """A job store plus a way to create and read tasks, for SQL and memory alike."""

    def __init__(self, kind, tmp_path, engine=None):
        self.kind = kind
        self.clock = Clock()
        self.jobs: Any
        if kind == "sql":
            self.engine = engine or sqlite_engine(tmp_path / "jobs.db")
            self.jobs = SqlJobStore(self.engine)
        else:
            self.memory = InMemoryStore()
            self.jobs = MemoryJobStore(store_factory=lambda: self.memory)
        self.jobs.clock = self.clock

    def store(self):
        return SQLAlchemyStore(Session(self.engine)) if self.kind == "sql" else self.memory

    def template(self, **fields):
        store = self.store()
        try:
            return store.create_task(TaskCreate(title=fields.pop("title", "Treppenhaus"), **fields))
        finally:
            if self.kind == "sql":
                store.db.close()

    def children(self, template_id):
        if self.kind == "sql":
            with Session(self.engine) as session:
                return sorted(session.scalars(select(TaskORM.due_date).where(TaskORM.parent_task_id == template_id)))
        return sorted(t.due_date for t in self.memory.list_tasks() if t.parent_task_id == template_id)

    def ledger_rows(self, template_id):
        key = recurring.rule_key(template_id)
        if self.kind == "sql":
            with Session(self.engine) as session:
                rows = session.execute(select(JobOccurrenceORM.rule_version, JobOccurrenceORM.occurrence_key,
                                              JobOccurrenceORM.status).where(JobOccurrenceORM.rule_key == key))
                return {(v, o): s for v, o, s in rows}
        return self.jobs.ledger.rows(key)

    def runner(self, chunk=recurring.CHUNK, mode=None, owner="worker-a"):
        return JobRunner(self.jobs, {recurring.KIND: recurring.make_handler(chunk, mode)}, owner=owner)


@pytest.fixture(params=["sql", "memory"])
def backend(request, tmp_path):
    return Backend(request.param, tmp_path)


def _enqueue(jobs, as_of, mode="all", key=None):
    return jobs.enqueue(recurring.KIND, key or f"{recurring.KIND}@{as_of}", {"as_of": as_of, "mode": mode})


# --- restart and leases -----------------------------------------------------------

def test_a_restart_resumes_from_the_checkpoint(backend):
    template = backend.template(due_date=date(2026, 1, 1), recurrence_rule="FREQ=DAILY")
    run = _enqueue(backend.jobs, "2026-03-01")

    crashed = backend.runner(chunk=10).run_one(max_chunks=2)       # the process dies after two chunks
    assert crashed.status == "running" and crashed.checkpoint is not None
    assert len(backend.children(template.id)) == 20
    assert backend.runner(owner="worker-b").run_one() is None      # the lease still holds

    backend.clock.advance(seconds=backend.jobs.lease_seconds + 1)  # restart: the lease expired
    resumed = backend.runner(chunk=10, owner="worker-b").run_one()
    assert resumed.id == run.id and resumed.status == "succeeded"
    stored = backend.jobs.get(run.id)
    assert stored.attempts == 2 and stored.progress["created"] == 59
    dues = backend.children(template.id)
    assert dues[0] == date(2026, 1, 2) and dues[-1] == date(2026, 3, 1)
    assert len(dues) == len(set(dues)) == 59                        # nothing redone, nothing missing


def test_a_worker_that_lost_its_lease_cannot_commit(backend):
    template = backend.template(due_date=date(2026, 1, 1), recurrence_rule="FREQ=DAILY")
    _enqueue(backend.jobs, "2026-01-31")
    stale = backend.jobs.claim("worker-a", (recurring.KIND,))
    backend.clock.advance(seconds=backend.jobs.lease_seconds + 1)
    taken = backend.jobs.claim("worker-b", (recurring.KIND,))
    assert taken.id == stale.id and taken.lease_token != stale.lease_token

    with pytest.raises(LeaseLost):
        recurring.make_handler(chunk=5)(JobContext(backend.jobs, stale))
    if backend.kind == "sql":                                        # the zombie's chunk rolled back
        assert backend.children(template.id) == []
    with pytest.raises(LeaseLost):
        backend.jobs.complete(stale)

    handler = recurring.make_handler(chunk=5)
    ctx = JobContext(backend.jobs, taken)
    while not handler(ctx):
        pass
    backend.jobs.complete(taken)
    assert len(set(backend.children(template.id))) == len(backend.children(template.id)) == 30


def _ran(runner):
    run = runner.run_one()
    assert run is not None
    return run


def test_failures_retry_with_backoff_and_then_give_up(backend):
    calls = []

    def broken(ctx):
        calls.append(ctx.run.attempts)
        raise RuntimeError("Netzwerk weg")

    run = backend.jobs.enqueue("broken", "broken@1", {}, max_attempts=2)
    runner = JobRunner(backend.jobs, {"broken": broken})
    assert _ran(runner).status == "queued"
    assert runner.run_one() is None                                  # backoff
    backend.clock.advance(minutes=5)
    assert _ran(runner).status == "failed"
    stored = backend.jobs.get(run.id)
    assert calls == [1, 2] and stored.status == "failed" and "Netzwerk weg" in stored.last_error


def test_a_run_that_keeps_dying_is_given_up(backend):
    run = backend.jobs.enqueue("dying", "dying@1", {}, max_attempts=1)
    assert backend.jobs.claim("w", ("dying",)).id == run.id
    backend.clock.advance(seconds=backend.jobs.lease_seconds + 1)
    assert backend.jobs.claim("w", ("dying",)) is None
    assert backend.jobs.get(run.id).status == "failed"


def test_jobs_run_as_the_installation_even_inside_a_restricted_request(backend):
    seen = []

    def probe(ctx):
        seen.append(current_scope())
        return True

    backend.jobs.enqueue("probe", "probe@1")
    restricted = AccessScope("staff", "verwalter", False, ("north",))
    with scope_context(restricted):
        JobRunner(backend.jobs, {"probe": probe}).run_one()
        assert current_scope() == restricted
    assert seen == [None]


# --- several workers --------------------------------------------------------------

def _hammer(jobs, workers, handlers):
    barrier = threading.Barrier(workers)
    errors = []

    def work(index):
        try:
            barrier.wait()
            JobRunner(jobs, handlers, owner=f"worker-{index}").run_until_idle(max_jobs=1000)
        except Exception as exc:  # pragma: no cover - reported below
            errors.append(exc)

    threads = [threading.Thread(target=work, args=(i,)) for i in range(workers)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert errors == []


def _concurrency_case(jobs):
    """Every job once; 40 jobs record the same 50 occurrences: each occurrence exactly once."""
    lock = threading.Lock()
    executed: list[str] = []
    recorded: list[str] = []

    def shared(ctx):
        with ctx.unit() as unit:
            for n in range(50):
                if unit.ledger.record("shared", "v1", f"o-{n:03d}", "created", ctx.run.id):
                    with lock:
                        recorded.append(f"o-{n:03d}")
            unit.save({"done": True})
        with lock:
            executed.append(ctx.run.id)
        return True

    barrier = threading.Barrier(4)

    def enqueue_all():
        barrier.wait()
        for n in range(40):
            jobs.enqueue("shared", f"shared@{n}")

    threads = [threading.Thread(target=enqueue_all) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(jobs.list_runs(limit=100)) == 40                      # idempotent enqueue under a race

    _hammer(jobs, 6, {"shared": shared})
    assert len(executed) == len(set(executed)) == 40
    assert sorted(recorded) == [f"o-{n:03d}" for n in range(50)]
    assert {run.status for run in jobs.list_runs(limit=100)} == {"succeeded"}


def test_concurrent_workers_never_share_a_job_or_an_occurrence(backend):
    _concurrency_case(backend.jobs)


def test_concurrent_workers_catch_up_one_series_once(backend):
    template = backend.template(due_date=date(2025, 1, 1), recurrence_rule="FREQ=DAILY")
    for n in range(8):   # eight runs for the same work, e.g. manual and scheduled
        _enqueue(backend.jobs, "2025-12-31", key=f"catch-up-{n}")
    _hammer(backend.jobs, 4, {recurring.KIND: recurring.make_handler(chunk=25)})
    dues = backend.children(template.id)
    assert len(dues) == len(set(dues)) == 364


def test_postgres_workers_skip_locked_runs(postgres):  # noqa: F811
    engine, _ = postgres
    jobs = SqlJobStore(engine)
    _concurrency_case(jobs)
    pg = Backend("sql", None, engine=engine)
    template = pg.template(due_date=date(2025, 1, 1), recurrence_rule="FREQ=DAILY")
    for n in range(8):
        _enqueue(pg.jobs, "2025-12-31", key=f"catch-up-{n}")
    _hammer(pg.jobs, 4, {recurring.KIND: recurring.make_handler(chunk=25)})
    assert len(set(pg.children(template.id))) == len(pg.children(template.id)) == 364


# --- catch-up -----------------------------------------------------------------------

def test_more_than_10000_occurrences_are_caught_up_in_bounded_chunks(backend):
    template = backend.template(due_date=date(1990, 1, 1), recurrence_rule="FREQ=DAILY")
    run = _enqueue(backend.jobs, "2020-01-01", mode="all")
    runner = backend.runner(chunk=2000)
    first = runner.run_one(max_chunks=1)
    assert first.progress["created"] == 2000                        # one chunk is bounded
    backend.clock.advance(seconds=backend.jobs.lease_seconds + 1)
    assert runner.run_one().status == "succeeded"
    expected = (date(2020, 1, 1) - date(1990, 1, 1)).days            # 10957
    assert expected > 10_000
    dues = backend.children(template.id)
    assert len(dues) == len(set(dues)) == expected
    assert backend.jobs.get(run.id).progress["created"] == expected


def test_latest_mode_records_missed_occurrences_and_creates_only_the_newest(backend):
    template = backend.template(due_date=date(1990, 1, 1), recurrence_rule="FREQ=DAILY")
    _enqueue(backend.jobs, "2020-01-01", mode="latest")
    assert backend.runner(chunk=3000).run_one().status == "succeeded"
    assert backend.children(template.id) == [date(2020, 1, 1)]
    rows = backend.ledger_rows(template.id)
    assert len(rows) == 10957 and list(rows.values()).count("created") == 1

    # an open child blocks the next one; the occurrence is recorded as skipped
    _enqueue(backend.jobs, "2020-01-03", mode="latest")
    backend.runner().run_one()
    assert backend.children(template.id) == [date(2020, 1, 1)]
    assert len(backend.ledger_rows(template.id)) == 10959


def test_a_changed_rule_continues_after_the_last_processed_occurrence(backend):
    template = backend.template(due_date=date(2026, 1, 5), recurrence_rule="FREQ=WEEKLY")
    _enqueue(backend.jobs, "2026-02-28")
    backend.runner().run_one()
    weekly = backend.children(template.id)
    assert weekly[-1] == date(2026, 2, 23) and len(weekly) == 7
    first_version = recurring.rule_version(template)

    store = backend.store()
    changed = store.update_task(template.id, TaskCreate(title=template.title, due_date=template.due_date,
                                                        recurrence_rule="FREQ=MONTHLY"))
    if backend.kind == "sql":
        store.db.close()
    assert recurring.rule_version(changed) != first_version

    _enqueue(backend.jobs, "2026-06-30")
    backend.runner().run_one()
    dues = backend.children(template.id)
    assert dues[:7] == weekly                                         # history untouched
    assert dues[7:] == [date(2026, 3, 23), date(2026, 4, 23), date(2026, 5, 23), date(2026, 6, 23)]
    versions = {version for version, _ in backend.ledger_rows(template.id)}
    assert versions == {first_version, recurring.rule_version(changed)}


def test_the_endpoint_and_the_job_share_the_ledger(backend, monkeypatch):
    from backend.routers import tasks as tasks_router

    template = backend.template(due_date=date(2026, 1, 15), recurrence_rule="FREQ=MONTHLY")
    _enqueue(backend.jobs, "2026-02-15", mode="all")
    backend.runner().run_one()
    created = backend.children(template.id)
    assert created == [date(2026, 2, 15)]

    store = backend.store()
    child = next(t for t in store.list_tasks() if t.parent_task_id == template.id)
    store.delete_task(child.id)               # deleted by a user: the occurrence stays processed
    monkeypatch.setattr(tasks_router, "store", store)
    if backend.kind == "memory":
        monkeypatch.setattr(recurring, "ledger_for", lambda _store: backend.jobs.ledger)
    assert tasks_router.generate_recurring_tasks(as_of=date(2026, 2, 15)) == []
    assert [t.due_date for t in tasks_router.generate_recurring_tasks(as_of=date(2026, 3, 15))] == [date(2026, 3, 15)]
    if backend.kind == "sql":
        store.db.close()


# --- time zone / DST -------------------------------------------------------------------

def _utc(year, month, day, hour=0, minute=0):
    return datetime(year, month, day, hour, minute, tzinfo=timezone.utc)


def test_daily_slots_exist_once_per_local_day_across_both_dst_switches():
    schedule = DailyAt(2, 30)
    spring = list(schedule.occurrences(_utc(2026, 3, 27), _utc(2026, 3, 31)))
    assert [day for day, _ in spring] == [date(2026, 3, d) for d in (27, 28, 29, 30)]
    assert dict(spring)[date(2026, 3, 29)] == _utc(2026, 3, 29, 1, 30)       # 02:30 does not exist: 03:30 CEST
    assert dict(spring)[date(2026, 3, 30)] == _utc(2026, 3, 30, 0, 30)
    autumn = list(schedule.occurrences(_utc(2026, 10, 23), _utc(2026, 10, 27)))
    assert [day for day, _ in autumn] == [date(2026, 10, d) for d in (23, 24, 25, 26)]
    assert dict(autumn)[date(2026, 10, 25)] == _utc(2026, 10, 25, 0, 30)     # first of the two 02:30
    assert dict(autumn)[date(2026, 10, 26)] == _utc(2026, 10, 26, 1, 30)
    assert schedule.latest_due(_utc(2026, 10, 25, 1, 15)) == date(2026, 10, 25)   # the repeated hour: no new day


@pytest.mark.parametrize("start", [datetime(2026, 3, 27), datetime(2026, 10, 23)])
def test_ticking_through_a_dst_switch_enqueues_each_slot_once(start):
    jobs = MemoryJobStore(store_factory=InMemoryStore)
    moment = start
    while moment < start + timedelta(days=4):
        enqueue_due(jobs, moment)
        moment += timedelta(minutes=10)
    for item in PERIODIC:
        keys = sorted(run.idempotency_key for run in jobs.list_runs(limit=100) if run.kind == item.kind)
        days = [start.date() + timedelta(days=n) for n in range(-1, 4)]
        assert keys == [item.key(day) for day in days]


def test_the_installation_date_is_the_berlin_date():
    assert BERLIN.key == "Europe/Berlin"
    assert local_today(datetime(2026, 3, 28, 23, 30)) == date(2026, 3, 29)     # UTC still says the 28th
    assert local_today(datetime(2026, 10, 25, 21, 59)) == date(2026, 10, 25)
    assert local_today(datetime(2026, 10, 25, 23, 0)) == date(2026, 10, 26)


# --- scheduler -------------------------------------------------------------------------

def test_the_scheduler_runs_each_periodic_job_once_per_slot(backend):
    template = backend.template(due_date=date(2026, 10, 1), recurrence_rule="FREQ=DAILY")
    first = tick(backend.jobs, now=datetime(2026, 10, 7, 5, 0))       # 07:00 Berlin: every slot of today due
    assert sorted((run.kind, run.status) for run in first) == [(ESCALATION_KIND, "succeeded"),
                                                               (SERVICE_CONTRACT_KIND, "succeeded"),
                                                               (recurring.KIND, "succeeded")]
    assert tick(backend.jobs, now=datetime(2026, 10, 7, 5, 30)) == []
    assert backend.children(template.id) == [date(2026, 10, 7)]       # default mode: newest only
    assert len(backend.ledger_rows(template.id)) == 6


def test_job_tables_are_installation_internal():
    from backend.services.portfolio_scope import INTERNAL

    assert {"job_runs", "job_occurrences"} <= INTERNAL


def test_a_failed_chunk_leaves_no_ledger_rows(tmp_path):
    engine = sqlite_engine(tmp_path / "unit.db")
    jobs = SqlJobStore(engine)
    jobs.enqueue("x", "x@1")
    run = jobs.claim("w", ("x",))
    with pytest.raises(ZeroDivisionError):
        with jobs.unit(run) as unit:
            unit.ledger.record("r", "v", "o", "created", run.id)
            1 / 0
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(JobOccurrenceORM)) == 0



def test_the_app_lifespan_ticks_the_scheduler_off_the_event_loop(monkeypatch):
    from fastapi.testclient import TestClient

    from backend.app import app
    from backend.config import settings
    from backend.services.jobs import scheduler

    ticked = threading.Event()
    threads = []

    def fake_tick(jobs=None, runner=None, now=None):
        try:
            asyncio.get_running_loop()
            threads.append("event loop")
        except RuntimeError:
            threads.append("worker thread")
        ticked.set()
        return []

    monkeypatch.setattr(settings, "job_scheduler_enabled", True)
    monkeypatch.setattr(scheduler, "tick", fake_tick)
    monkeypatch.setattr(scheduler, "get_job_store", lambda: MemoryJobStore(store_factory=InMemoryStore))
    with TestClient(app):
        assert ticked.wait(10)
    assert threads[0] == "worker thread"
