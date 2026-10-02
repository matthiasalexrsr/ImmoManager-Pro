"""Bounded, process-local telemetry. No request, user, path or event history.

Counts describe this worker since its start, including static files and rejected
requests. They are neither a persistent audit journal nor a multiworker total.
Only fixed labels enter the accumulator; callers cannot add dimensions.
"""

import logging
import os
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from threading import RLock
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.orm import scoped_session

logger = logging.getLogger(__name__)

METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS", "OTHER")
GROUPS = ("auth", "administration", "finance", "property", "people", "files", "operations", "other", "unmatched")
OUTCOMES = ("success", "redirect", "client_error", "server_error", "aborted")
BUCKETS_MS = (10, 50, 100, 500, 1000, 5000, 30000)
_RESOURCES = {
    "auth": "auth",
    **dict.fromkeys(("admin", "updates", "diagnostics", "autotest", "dev-notes", "audit", "integrations"), "administration"),
    **dict.fromkeys(("accounts", "bookings", "bank-imports", "bank-matching", "billing", "invoices", "receivables", "rent-charges", "rent-adjustments", "rent-batches", "deposits", "budgets", "categories", "reports", "datev", "annual-tax"), "finance"),
    **dict.fromkeys(("portfolios", "properties", "units", "contracts", "contract-wizard", "maintenance", "insurances", "meters", "handover-protocols"), "property"),
    **dict.fromkeys(("tenants", "contacts", "leads", "viewings", "listings"), "people"),
    **dict.fromkeys(("files", "photos", "documents"), "files"),
    **dict.fromkeys(("tasks", "calendar", "notifications", "outbox", "messages"), "operations"),
}


def operation_group(scope: dict[str, Any]) -> str:
    """Inspect declared routes only; never parse or retain the incoming URL."""
    template = getattr(scope.get("route"), "path", None)
    if not isinstance(template, str) or template == "/{full_path:path}":
        return "unmatched"
    if template.startswith("/api/v1/"):
        return _RESOURCES.get(template[len("/api/v1/"):].split("/", 1)[0], "other")
    return "other"


class _Aggregate:
    def __init__(self) -> None:
        self.count = 0
        self.duration_ms = 0.0
        self.maximum_ms = 0.0
        self.buckets = [0] * (len(BUCKETS_MS) + 1)

    def add(self, elapsed_ms: float) -> None:
        self.count += 1
        self.duration_ms += elapsed_ms
        self.maximum_ms = max(self.maximum_ms, elapsed_ms)
        index = next((i for i, bound in enumerate(BUCKETS_MS) if elapsed_ms <= bound), len(BUCKETS_MS))
        self.buckets[index] += 1

    def snapshot(self) -> dict[str, Any]:
        return {"count": self.count, "total_ms": round(self.duration_ms, 3),
                "mean_ms": round(self.duration_ms / self.count, 3) if self.count else None,
                "max_ms": round(self.maximum_ms, 3) if self.count else None,
                # Non-cumulative buckets: every completed operation appears once.
                "histogram": [{"upper_ms": bound, "count": count} for bound, count in zip((*BUCKETS_MS, None), self.buckets)]}


class OperationalMetrics:
    def __init__(self, *, clock: Callable[[], float] = time.monotonic) -> None:
        self.clock = clock
        self.started_at = datetime.now(timezone.utc).isoformat()
        self.started = clock()
        self._lock = RLock()
        self._inflight = self._peak_inflight = 0
        self._exceptions = 0
        self._aborted = 0
        self._requests = {(group, method, outcome): _Aggregate() for group in GROUPS for method in METHODS for outcome in OUTCOMES}
        self._jobs = {outcome: _Aggregate() for outcome in ("success", "error")}
        self._db = {outcome: _Aggregate() for outcome in ("connected", "unavailable", "not_configured")}

    def begin_request(self) -> float:
        with self._lock:
            self._inflight += 1
            self._peak_inflight = max(self._peak_inflight, self._inflight)
        return self.clock()

    def finish_request(self, *, group: str, method: str, outcome: str, started: float, exception: bool = False, aborted: bool = False) -> None:
        # Validation happens before mutating counters. No caller-defined labels.
        aggregate = self._requests[(group, method if method in METHODS else "OTHER", outcome)]
        with self._lock:
            aggregate.add(max(0.0, (self.clock() - started) * 1000))
            self._inflight -= 1
            self._exceptions += int(exception)
            self._aborted += int(aborted or outcome == "aborted")

    def record_database(self, state: str, elapsed_ms: float) -> None:
        with self._lock:
            self._db[state].add(max(0.0, elapsed_ms))

    @contextmanager
    def operational_tick(self) -> Iterator[None]:
        started = self.clock()
        outcome = "error"
        try:
            yield
            outcome = "success"
        finally:
            elapsed = max(0.0, (self.clock() - started) * 1000)
            with self._lock:
                self._jobs[outcome].add(elapsed)
            # Existing RequestContextFilter correlates a manual tick with its
            # request; no business rows, tick UUIDs or exception values are logged.
            try:
                logger.info("Local operational tick %s", outcome, extra={"duration_ms": round(elapsed, 3)})
            except Exception:
                # A broken third-party log handler cannot turn a committed job
                # into an apparent failure or replace the original job error.
                pass

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            rows = [{"group": group, "method": method, "outcome": outcome, **aggregate.snapshot()}
                    for (group, method, outcome), aggregate in self._requests.items() if aggregate.count]
            return {"scope": "process_worker", "persistent": False, "started_at": self.started_at,
                    "uptime_seconds": round(max(0.0, self.clock() - self.started), 3),
                    "requests": {"completed": sum(row["count"] for row in rows), "inflight": self._inflight,
                                 "peak_inflight": self._peak_inflight, "exceptions": self._exceptions,
                                 "aborted": self._aborted, "series": rows},
                    "jobs": {"operational_tick": {outcome: aggregate.snapshot() for outcome, aggregate in self._jobs.items()}},
                    "database_probes": {state: aggregate.snapshot() for state, aggregate in self._db.items()}}


metrics = OperationalMetrics()


class OperationalMetricsMiddleware:
    """Count responses once and measure complete streams, including aborts."""

    def __init__(self, app, *, collector: OperationalMetrics | None = None):
        self.app = app
        self.collector = collector if collector is not None else metrics

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        started = self.collector.begin_request()
        status = None
        complete = False
        failed = False
        send_failed = False

        async def tracked_send(message):
            nonlocal status, complete, send_failed
            try:
                await send(message)
            except BaseException:
                send_failed = True
                raise
            if message["type"] == "http.response.start":
                status = message["status"]
            elif message["type"] == "http.response.body" and not message.get("more_body", False):
                complete = True

        try:
            await self.app(scope, receive, tracked_send)
        except Exception:
            failed = True
            raise
        finally:
            if status is not None and status >= 500:
                outcome = "server_error"
            elif send_failed and not complete:
                outcome = "aborted"
            elif failed and status is None:
                outcome = "server_error"
            elif not complete:
                outcome = "aborted"
            elif status is not None and status >= 400:
                outcome = "client_error"
            elif status is not None and status >= 300:
                outcome = "redirect"
            else:
                outcome = "success"
            self.collector.finish_request(group=operation_group(scope), method=scope.get("method", "OTHER"), outcome=outcome, started=started, exception=failed, aborted=not complete and (status is not None or send_failed))


def _persistent_storage(bind: Connection | Engine) -> bool:
    engine = bind.engine if isinstance(bind, Connection) else bind
    if engine.dialect.name != "sqlite":
        return True
    url = engine.url
    database = url.database or ""
    uri = str(url.query.get("uri", "false")).lower() in {"true", "1"}
    return bool(database and database != ":memory:" and not (
        uri and (database.startswith("file::memory:") or url.query.get("mode") == "memory")
    ))


@contextmanager
def _probe_connection(bind: Connection | Engine) -> Iterator[Connection]:
    if isinstance(bind, Connection):
        if bind.in_transaction():
            # Borrow the active transaction without committing, rolling it back,
            # or closing the caller's connection.
            yield bind
        else:
            # Only this newly created read transaction belongs to the probe.
            # Opening another pooled connection could exhaust a one-slot pool.
            transaction = bind.begin()
            try:
                yield bind
            finally:
                transaction.rollback()
    else:
        with bind.connect() as connection:
            yield connection


def database_health(store, *, collector: OperationalMetrics = metrics) -> dict[str, Any]:
    """Probe the active SQL bind; connectivity never implies durable storage.

    Uses the configured driver's connection/statement timeout. No extra worker
    threads, replacement engines or silent replacement database are created.
    This is connectivity only, not a migration/integrity/backup verification.
    """
    started = collector.clock()
    state = "not_configured"
    backend = "memory"
    persistent = False
    if hasattr(store, "db"):
        state = "unavailable"
        backend = "sql"
        try:
            session = store.db() if isinstance(store.db, scoped_session) else store.db
            bind = session.get_bind()
            if isinstance(bind, Engine) and session.in_transaction():
                # Reuse an existing session transaction. SQLite memory pools can
                # share one driver connection; closing a second checkout could
                # otherwise roll back the caller's pending business writes.
                bind = session.connection()
            dialect = bind.dialect.name
            backend = dialect if dialect in {"sqlite", "postgresql"} else "sql"
            persistent = _persistent_storage(bind)
            with _probe_connection(bind) as connection:
                state = "connected" if connection.execute(text("SELECT 1")).scalar_one() == 1 else "unavailable"
                if dialect == "sqlite" and state == "connected":
                    # The actual bind also covers URI/connect_args/creator-based
                    # SQLite memory and temporary databases. No path is returned.
                    persistent = any(name == "main" and bool(filename)
                                     for _, name, filename in connection.exec_driver_sql("PRAGMA database_list"))
        except Exception:
            # No exception text, connection URL, file path or credential leaves
            # this function. Ordinary diagnostics already carry safe locations.
            state = "unavailable"
    elapsed_ms = max(0.0, (collector.clock() - started) * 1000)
    collector.record_database(state, elapsed_ms)
    return {"state": state, "backend": backend, "persistent": persistent,
            "duration_ms": round(elapsed_ms, 3), "check": "connectivity_only"}


def process_health() -> dict[str, Any]:
    # No hostnames, usernames, environment, command line, PIDs or local paths.
    return {"cpu_seconds": round(time.process_time(), 3), "logical_cpus": os.cpu_count()}
