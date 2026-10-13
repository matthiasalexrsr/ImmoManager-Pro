"""FIFO SQLite writers per Engine, before connection checkout, with separate timings.

The gate coordinates this process only. External connections still obey SQLite's
busy timeout. PostgreSQL and independent Engine instances never share this gate.
Participants are booking_write, document_versions.work and SQLAuditStore.add.
Legacy CRUD, billing_write and maintenance_projects.work still use native SQLite
contention; their conversion needs a separate transaction-ownership review.
"""

import json
import logging
import threading
import time
from collections import deque
from contextlib import contextmanager
from weakref import WeakKeyDictionary

logger = logging.getLogger(__name__)
_TIMING = "sqlite_write_timing"
_registry_lock = threading.Lock()
_queues: WeakKeyDictionary = WeakKeyDictionary()


class WriterQueue:
    """FIFO admission, reentrant for a thread already inside its engine's gate."""

    def __init__(self):
        self.condition = threading.Condition()
        self.waiters: deque[object] = deque()
        self.owner: int | None = None
        self.depth = 0

    def acquire(self):
        owner = threading.get_ident()
        with self.condition:
            if self.owner == owner:
                self.depth += 1
                return
            ticket = object()
            self.waiters.append(ticket)
            try:
                while self.owner is not None or self.waiters[0] is not ticket:
                    self.condition.wait()
                self.waiters.popleft()
                self.owner, self.depth = owner, 1
            except BaseException:
                self.waiters.remove(ticket)
                self.condition.notify_all()
                raise

    def release(self):
        with self.condition:
            if self.owner != threading.get_ident():
                raise RuntimeError("SQLite write gate released by a different thread")
            self.depth -= 1
            if not self.depth:
                self.owner = None
                self.condition.notify_all()


class WriteTiming:
    def __init__(self, kind, queue_wait_ms):
        self.values = {"kind": kind, "queue_wait_ms": queue_wait_ms, "outcome": "failed"}

    def attach(self, db):
        db.info[_TIMING] = self


@contextmanager
def sqlite_write_gate(bind, kind):
    engine = getattr(bind, "engine", bind)
    if engine.dialect.name != "sqlite":
        yield None
        return
    with _registry_lock:
        queue = _queues.setdefault(engine, WriterQueue())
    started = time.perf_counter()
    queue.acquire()
    admitted = time.perf_counter()
    timing = WriteTiming(kind, (admitted - started) * 1000)
    try:
        yield timing
    finally:
        timing.values["held_ms"] = (time.perf_counter() - admitted) * 1000
        queue.release()
        # JSON in the message also survives the app's existing JSON formatter.
        # The request-context logging filter supplies the request ID; no SQL,
        # IDs, actors, payloads or personal data are included in these timings.
        logger.info("sqlite_write_timing %s", json.dumps(timing.values, sort_keys=True))


@contextmanager
def write_stage(db, name):
    timing = db.info.get(_TIMING)
    if timing is None:
        yield
        return
    started = time.perf_counter()
    try:
        yield
    finally:
        timing.values[name] = timing.values.get(name, 0) + (time.perf_counter() - started) * 1000


def write_outcome(db, outcome):
    timing = db.info.get(_TIMING)
    if timing is not None:
        timing.values["outcome"] = outcome
