"""Durable, resumable installation jobs with leases.

A run is claimed under a lease (owner, random fencing token, expiry). Work happens
in bounded chunks; every chunk commits its business writes, its occurrence-ledger
rows and the run's checkpoint in one transaction, fenced by the token. A worker that
lost its lease (expired, taken over after a restart) cannot commit anything more.

Claiming: PostgreSQL SELECT ... FOR UPDATE SKIP LOCKED; SQLite one conditional UPDATE
(the database has a single writer). Expired leases are claimable again, so a run
interrupted by a crash or restart resumes from its last checkpoint.

The in-memory store mode uses MemoryJobStore with the same interface (one process).
"""

from __future__ import annotations

import copy
import json
import logging
import os
import socket
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Protocol
from uuid import uuid4

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from ...db.job_models import JobOccurrenceORM, JobRunORM
from ..portfolio_scope import scope_context
from .schedule import utcnow

logger = logging.getLogger(__name__)

RUNS = JobRunORM.__table__
OCCURRENCES = JobOccurrenceORM.__table__
DEFAULT_LEASE_SECONDS = 120


class LeaseLost(RuntimeError):
    """The run was taken over (or finished) by another worker; stop without committing."""


@dataclass
class JobRun:
    id: str
    kind: str
    idempotency_key: str
    status: str
    payload: dict
    checkpoint: dict | None = None
    progress: dict | None = None
    attempts: int = 0
    max_attempts: int = 5
    available_at: datetime | None = None
    lease_owner: str | None = None
    lease_token: str | None = None
    lease_expires_at: datetime | None = None
    last_error: str | None = None
    created_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None


def default_owner() -> str:
    return f"{socket.gethostname()}:{os.getpid()}:{threading.get_ident()}"


def retry_delay(attempts: int) -> timedelta:
    return timedelta(seconds=min(3600, 30 * 2 ** max(0, attempts - 1)))


# --- occurrence ledger -------------------------------------------------------

class Ledger(Protocol):
    def record(self, rule_key: str, rule_version: str, occurrence_key: str, status: str,
               run_id: str | None = None) -> bool:
        """Insert the occurrence; False when this (rule, version, occurrence) exists already."""

    def latest(self, rule_key: str) -> str | None:
        """Highest occurrence key processed for the rule, over all its versions."""


class SqlLedger:
    """Writes into the caller's session; it commits together with the caller's work."""

    def __init__(self, session: Session):
        self.session = session

    def record(self, rule_key, rule_version, occurrence_key, status, run_id=None) -> bool:
        dialect = self.session.get_bind().dialect.name
        if dialect == "postgresql":
            from sqlalchemy.dialects.postgresql import insert as pg_insert
            statement: Any = pg_insert(OCCURRENCES).on_conflict_do_nothing()
        elif dialect == "sqlite":
            from sqlalchemy.dialects.sqlite import insert as sqlite_insert
            statement = sqlite_insert(OCCURRENCES).on_conflict_do_nothing()
        else:  # pragma: no cover - other dialects: rely on the primary key
            statement = OCCURRENCES.insert()
        values = dict(rule_key=rule_key, rule_version=rule_version, occurrence_key=occurrence_key,
                      status=status, run_id=run_id, created_at=utcnow())
        try:
            result = self.session.execute(statement.values(**values))
        except IntegrityError:  # pragma: no cover - only without ON CONFLICT
            return False
        return bool(getattr(result, "rowcount", 0))

    def latest(self, rule_key) -> str | None:
        return self.session.scalar(select(func.max(OCCURRENCES.c.occurrence_key))
                                   .where(OCCURRENCES.c.rule_key == rule_key))


class MemoryLedger:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._rows: dict[tuple[str, str, str], dict] = {}
        self._latest: dict[str, str] = {}

    def record(self, rule_key, rule_version, occurrence_key, status, run_id=None) -> bool:
        key = (rule_key, rule_version, occurrence_key)
        with self._lock:
            if key in self._rows:
                return False
            self._rows[key] = {"status": status, "run_id": run_id}
            if occurrence_key > self._latest.get(rule_key, ""):
                self._latest[rule_key] = occurrence_key
            return True

    def latest(self, rule_key) -> str | None:
        with self._lock:
            return self._latest.get(rule_key)

    def rows(self, rule_key: str) -> dict[tuple[str, str], str]:
        with self._lock:
            return {(v, o): row["status"] for (r, v, o), row in self._rows.items() if r == rule_key}


# --- one chunk of work ---------------------------------------------------------

@dataclass
class Unit:
    """Business store, ledger and checkpoint of one chunk; committed together."""
    store: Any
    ledger: Any
    run: JobRun
    saved: tuple[dict | None, dict | None] | None = None

    def save(self, checkpoint: dict | None, progress: dict | None = None) -> None:
        self.saved = (copy.deepcopy(checkpoint), copy.deepcopy(progress))


class JobStore:
    clock: Callable[[], datetime] = staticmethod(utcnow)
    lease_seconds: int = DEFAULT_LEASE_SECONDS

    def enqueue(self, kind: str, idempotency_key: str, payload: dict | None = None, *,
                max_attempts: int = 5, available_at: datetime | None = None) -> JobRun:
        raise NotImplementedError

    def claim(self, owner: str, kinds: tuple[str, ...] | None = None) -> JobRun | None:
        raise NotImplementedError

    def get(self, run_id: str) -> JobRun | None:
        raise NotImplementedError

    def find(self, idempotency_key: str) -> JobRun | None:
        raise NotImplementedError

    def heartbeat(self, run: JobRun) -> None:
        raise NotImplementedError

    def complete(self, run: JobRun) -> None:
        raise NotImplementedError

    def fail(self, run: JobRun, error: str, *, permanent: bool = False) -> None:
        raise NotImplementedError

    def unit(self, run: JobRun) -> Any:   # context manager yielding Unit
        raise NotImplementedError

    def list_runs(self, limit: int = 50) -> list[JobRun]:
        raise NotImplementedError


def _loads(value):
    return json.loads(value) if value else None


def _run_from_row(row) -> JobRun:
    data = dict(row._mapping)
    return JobRun(
        id=data["id"], kind=data["kind"], idempotency_key=data["idempotency_key"], status=data["status"],
        payload=_loads(data["payload"]) or {}, checkpoint=_loads(data["checkpoint"]),
        progress=_loads(data["progress"]), attempts=data["attempts"], max_attempts=data["max_attempts"],
        available_at=data["available_at"], lease_owner=data["lease_owner"], lease_token=data["lease_token"],
        lease_expires_at=data["lease_expires_at"], last_error=data["last_error"],
        created_at=data["created_at"], started_at=data["started_at"], finished_at=data["finished_at"],
    )


class SqlJobStore(JobStore):
    def __init__(self, engine: Engine, store_factory: Callable[[Session], Any] | None = None,
                 lease_seconds: int = DEFAULT_LEASE_SECONDS):
        self.engine = engine
        self.sessions = sessionmaker(bind=engine, autoflush=False)
        self.store_factory = store_factory or _sql_store
        self.lease_seconds = lease_seconds
        self.dialect = engine.dialect.name

    def enqueue(self, kind, idempotency_key, payload=None, *, max_attempts=5, available_at=None) -> JobRun:
        existing = self.find(idempotency_key)
        if existing is not None:
            return existing
        now = self.clock()
        values = dict(id=str(uuid4()), kind=kind, idempotency_key=idempotency_key, scope="installation",
                      status="queued", payload=json.dumps(payload or {}, sort_keys=True), attempts=0,
                      max_attempts=max_attempts, available_at=available_at or now, created_at=now, updated_at=now)
        try:
            with self.engine.begin() as connection:
                connection.execute(RUNS.insert().values(**values))
        except IntegrityError:
            pass   # another worker enqueued the same key first
        run = self.find(idempotency_key)
        assert run is not None
        return run

    def get(self, run_id):
        with self.engine.connect() as connection:
            row = connection.execute(select(RUNS).where(RUNS.c.id == run_id)).first()
        return _run_from_row(row) if row else None

    def find(self, idempotency_key):
        with self.engine.connect() as connection:
            row = connection.execute(select(RUNS).where(RUNS.c.idempotency_key == idempotency_key)).first()
        return _run_from_row(row) if row else None

    def list_runs(self, limit=50):
        with self.engine.connect() as connection:
            rows = connection.execute(select(RUNS).order_by(RUNS.c.created_at.desc(), RUNS.c.id).limit(limit))
            return [_run_from_row(row) for row in rows]

    def claim(self, owner, kinds=None):
        now = self.clock()
        token = uuid4().hex
        def due_in(table):
            condition = or_(and_(table.c.status == "queued", table.c.available_at <= now),
                            and_(table.c.status == "running", table.c.lease_expires_at < now))
            return and_(condition, table.c.kind.in_(kinds)) if kinds else condition

        expired = and_(RUNS.c.status == "running", RUNS.c.lease_expires_at < now)
        due = due_in(RUNS)
        claimed = dict(status="running", lease_owner=owner, lease_token=token,
                       lease_expires_at=now + timedelta(seconds=self.lease_seconds), heartbeat_at=now,
                       attempts=RUNS.c.attempts + 1, started_at=func.coalesce(RUNS.c.started_at, now),
                       updated_at=now)
        with self.engine.begin() as connection:
            # a run that kept dying under its lease is given up, not retried forever
            connection.execute(update(RUNS).where(expired, RUNS.c.attempts >= RUNS.c.max_attempts).values(
                status="failed", finished_at=now, updated_at=now, lease_token=None, lease_owner=None,
                last_error=func.coalesce(RUNS.c.last_error, "Lease expired after the last attempt")))
            order = (RUNS.c.available_at, RUNS.c.created_at, RUNS.c.id)
            if self.dialect == "postgresql":
                run_id = connection.execute(select(RUNS.c.id).where(due).order_by(*order).limit(1)
                                            .with_for_update(skip_locked=True)).scalar()
                if run_id is None:
                    return None
                connection.execute(update(RUNS).where(RUNS.c.id == run_id).values(**claimed))
            else:
                # single statement: the write lock makes the re-checked condition authoritative
                pick = RUNS.alias("pick")
                candidate = (select(pick.c.id).where(due_in(pick))
                             .order_by(pick.c.available_at, pick.c.created_at, pick.c.id).limit(1).scalar_subquery())
                result = connection.execute(update(RUNS).where(RUNS.c.id == candidate, due).values(**claimed))
                if not result.rowcount:
                    return None
            row = connection.execute(select(RUNS).where(RUNS.c.lease_token == token)).first()
        return _run_from_row(row)

    def _fenced(self, connection, run: JobRun, **values) -> None:
        result = connection.execute(update(RUNS).where(
            RUNS.c.id == run.id, RUNS.c.lease_token == run.lease_token, RUNS.c.status == "running",
        ).values(updated_at=self.clock(), **values))
        if not result.rowcount:
            raise LeaseLost(f"Job {run.id} is no longer leased by {run.lease_owner}")

    def _extend(self) -> dict:
        now = self.clock()
        return dict(lease_expires_at=now + timedelta(seconds=self.lease_seconds), heartbeat_at=now)

    def heartbeat(self, run):
        values = self._extend()
        with self.engine.begin() as connection:
            self._fenced(connection, run, **values)
        run.lease_expires_at = values["lease_expires_at"]

    def complete(self, run):
        with self.engine.begin() as connection:
            self._fenced(connection, run, status="succeeded", finished_at=self.clock(), lease_token=None,
                         lease_expires_at=None, last_error=None)
        run.status = "succeeded"

    def fail(self, run, error, *, permanent=False):
        now = self.clock()
        final = permanent or run.attempts >= run.max_attempts
        values: dict[str, Any] = dict(last_error=error[:4000], lease_token=None, lease_expires_at=None)
        if final:
            values.update(status="failed", finished_at=now)
        else:
            values.update(status="queued", available_at=now + retry_delay(run.attempts))
        with self.engine.begin() as connection:
            self._fenced(connection, run, **values)
        run.status = values["status"]

    @contextmanager
    def unit(self, run) -> Iterator[Unit]:
        session = self.sessions()
        try:
            unit = Unit(store=self.store_factory(session), ledger=SqlLedger(session), run=run)
            yield unit
            values = self._extend()
            if unit.saved is not None:
                checkpoint, progress = unit.saved
                values.update(checkpoint=json.dumps(checkpoint, sort_keys=True) if checkpoint is not None else None,
                              progress=json.dumps(progress, sort_keys=True) if progress is not None else None)
            # same transaction as the chunk's work: a lost lease rolls the chunk back
            self._fenced(session, run, **values)
            session.commit()
            run.lease_expires_at = values["lease_expires_at"]
            if unit.saved is not None:
                run.checkpoint, run.progress = unit.saved
        except BaseException:
            session.rollback()
            raise
        finally:
            session.close()


def _sql_store(session: Session):
    from ...repositories import SQLAlchemyStore

    return SQLAlchemyStore(session)


class MemoryJobStore(JobStore):
    """Same contract for the in-memory store mode; durable only for the process lifetime."""

    def __init__(self, store_factory: Callable[[], Any] | None = None, lease_seconds: int = DEFAULT_LEASE_SECONDS):
        self._lock = threading.RLock()
        self._runs: dict[str, JobRun] = {}
        self._keys: dict[str, str] = {}
        self.ledger = MemoryLedger()
        self.store_factory = store_factory or _memory_store
        self.lease_seconds = lease_seconds

    def enqueue(self, kind, idempotency_key, payload=None, *, max_attempts=5, available_at=None):
        with self._lock:
            if idempotency_key in self._keys:
                return copy.deepcopy(self._runs[self._keys[idempotency_key]])
            now = self.clock()
            run = JobRun(id=str(uuid4()), kind=kind, idempotency_key=idempotency_key, status="queued",
                         payload=copy.deepcopy(payload or {}), max_attempts=max_attempts,
                         available_at=available_at or now, created_at=now)
            self._runs[run.id] = run
            self._keys[idempotency_key] = run.id
            return copy.deepcopy(run)

    def get(self, run_id):
        with self._lock:
            run = self._runs.get(run_id)
            return copy.deepcopy(run) if run else None

    def find(self, idempotency_key):
        with self._lock:
            run_id = self._keys.get(idempotency_key)
            return copy.deepcopy(self._runs[run_id]) if run_id else None

    def list_runs(self, limit=50):
        with self._lock:
            runs = sorted(self._runs.values(), key=lambda r: (r.created_at or datetime.min, r.id), reverse=True)
            return [copy.deepcopy(run) for run in runs[:limit]]

    def claim(self, owner, kinds=None):
        with self._lock:
            now = self.clock()
            for run in self._runs.values():
                if run.status == "running" and run.lease_expires_at and run.lease_expires_at < now \
                        and run.attempts >= run.max_attempts:
                    run.status, run.finished_at, run.lease_token = "failed", now, None
                    run.last_error = run.last_error or "Lease expired after the last attempt"
            candidates = [run for run in self._runs.values()
                          if (not kinds or run.kind in kinds) and (
                              (run.status == "queued" and run.available_at and run.available_at <= now)
                              or (run.status == "running" and run.lease_expires_at and run.lease_expires_at < now))]
            if not candidates:
                return None
            run = min(candidates, key=lambda r: (r.available_at, r.created_at, r.id))
            run.status, run.lease_owner, run.lease_token = "running", owner, uuid4().hex
            run.lease_expires_at = now + timedelta(seconds=self.lease_seconds)
            run.attempts += 1
            run.started_at = run.started_at or now
            return copy.deepcopy(run)

    def _fenced(self, run: JobRun) -> JobRun:
        stored = self._runs.get(run.id)
        if stored is None or stored.status != "running" or stored.lease_token != run.lease_token:
            raise LeaseLost(f"Job {run.id} is no longer leased by {run.lease_owner}")
        return stored

    def heartbeat(self, run):
        with self._lock:
            stored = self._fenced(run)
            stored.lease_expires_at = run.lease_expires_at = self.clock() + timedelta(seconds=self.lease_seconds)

    def complete(self, run):
        with self._lock:
            stored = self._fenced(run)
            stored.status, stored.finished_at, stored.lease_token = "succeeded", self.clock(), None
            stored.lease_expires_at, stored.last_error = None, None
            run.status = "succeeded"

    def fail(self, run, error, *, permanent=False):
        with self._lock:
            stored = self._fenced(run)
            now = self.clock()
            stored.last_error, stored.lease_token, stored.lease_expires_at = error[:4000], None, None
            if permanent or run.attempts >= run.max_attempts:
                stored.status, stored.finished_at = "failed", now
            else:
                stored.status, stored.available_at = "queued", now + retry_delay(run.attempts)
            run.status = stored.status

    @contextmanager
    def unit(self, run):
        unit = Unit(store=self.store_factory(), ledger=self.ledger, run=run)
        yield unit
        with self._lock:
            stored = self._fenced(run)
            stored.lease_expires_at = run.lease_expires_at = self.clock() + timedelta(seconds=self.lease_seconds)
            if unit.saved is not None:
                stored.checkpoint, stored.progress = copy.deepcopy(unit.saved)
                run.checkpoint, run.progress = copy.deepcopy(unit.saved)


def _memory_store():
    from ...dependencies import store

    return store


# --- running ------------------------------------------------------------------

@dataclass
class JobContext:
    jobs: JobStore
    run: JobRun

    @property
    def checkpoint(self) -> dict:
        return copy.deepcopy(self.run.checkpoint) or {}

    @property
    def progress(self) -> dict:
        return copy.deepcopy(self.run.progress) or {}

    def unit(self):
        return self.jobs.unit(self.run)

    def heartbeat(self) -> None:
        self.jobs.heartbeat(self.run)


# A handler performs one bounded chunk inside ctx.unit() and returns True when done.
Handler = Callable[[JobContext], bool]


@dataclass
class JobRunner:
    jobs: JobStore
    handlers: dict[str, Handler]
    owner: str = field(default_factory=default_owner)
    stop: threading.Event = field(default_factory=threading.Event)

    def run_one(self, *, max_chunks: int | None = None) -> JobRun | None:
        """Claim and run one job. max_chunks stops early like a crash (the lease stays)."""
        run = self.jobs.claim(self.owner, tuple(self.handlers))
        if run is None:
            return None
        ctx = JobContext(self.jobs, run)
        chunks = 0
        try:
            # installation scope, explicitly: never the scope of a request that happens to be active
            with scope_context(None):
                while True:
                    if self.handlers[run.kind](ctx):
                        break
                    chunks += 1
                    if (max_chunks is not None and chunks >= max_chunks) or self.stop.is_set():
                        return ctx.run          # resumes from the checkpoint once the lease expires
            self.jobs.complete(ctx.run)
        except LeaseLost:
            logger.warning("Job %s (%s) was taken over by another worker", run.id, run.kind)
        except Exception as exc:
            logger.exception("Job %s (%s) failed in attempt %d", run.id, run.kind, run.attempts)
            try:
                self.jobs.fail(ctx.run, f"{type(exc).__name__}: {exc}")
            except LeaseLost:
                pass
        return ctx.run

    def run_until_idle(self, max_jobs: int = 20) -> list[JobRun]:
        done = []
        for _ in range(max_jobs):
            if self.stop.is_set():
                break
            run = self.run_one()
            if run is None:
                break
            done.append(run)
        return done
