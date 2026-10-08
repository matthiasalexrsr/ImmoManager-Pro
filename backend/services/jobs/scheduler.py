"""The installation scheduler: daily slots become durable runs; every worker drains them.

Every process may tick. Enqueuing is idempotent per (job kind, local slot date), so
several workers enqueue one run per slot; claiming is exclusive. Missed slots are
coalesced: after downtime only the latest slot runs, and the job itself catches up
(recurring tasks walk every missed occurrence). DB work runs in a worker thread,
never on the event loop.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from dataclasses import dataclass
from datetime import date, datetime

from ...config import settings
from .core import JobContext, JobRun, JobRunner, JobStore, MemoryJobStore, SqlJobStore
from .recurring import KIND as RECURRING_KIND
from .recurring import make_handler as make_recurring_handler
from .schedule import DailyAt, MonthlyAt, parse_hh_mm, utcnow
from .service_contract_deadlines import KIND as SERVICE_CONTRACT_KIND
from .service_contract_deadlines import make_handler as make_service_contract_handler

logger = logging.getLogger(__name__)

ESCALATION_KIND = "escalation.run"
BACKUP_KIND = "ops.full_backup"
PROBE_KIND = "ops.restore_probe"


@dataclass(frozen=True)
class Periodic:
    kind: str
    schedule: DailyAt | MonthlyAt
    max_attempts: int = 5

    def key(self, slot: date) -> str:
        return f"{self.kind}@{slot.isoformat()}"


PERIODIC = (
    Periodic(RECURRING_KIND, DailyAt(5, 0)),
    Periodic(ESCALATION_KIND, DailyAt(6, 15)),
    Periodic(SERVICE_CONTRACT_KIND, DailyAt(6, 30)),
)


def ops_periodic() -> tuple[Periodic, ...]:
    """Daily full backup and monthly restore probe; only with a persistent (SQL) store."""
    if not settings.backup_schedule_enabled:
        return ()
    from ... import dependencies

    if dependencies._scoped_session is None:
        return ()
    return (
        Periodic(BACKUP_KIND, DailyAt(*parse_hh_mm(settings.backup_daily_at)), max_attempts=3),
        Periodic(PROBE_KIND, MonthlyAt(settings.restore_probe_day, *parse_hh_mm(settings.restore_probe_at)),
                 max_attempts=3),
    )


def active_periodic() -> tuple[Periodic, ...]:
    return PERIODIC + ops_periodic()


def escalation_handler(ctx) -> bool:
    from ...routers.escalation import execute_escalation

    with ctx.unit() as unit:
        result = execute_escalation(unit.store, date.fromisoformat(ctx.run.payload["as_of"]))
        unit.save({"done": True}, {k: result[k] for k in ("rules_checked", "notifications_generated")})
    return True


def backup_handler(ctx: JobContext) -> bool:
    from ..full_backup import create_full_backup

    event = create_full_backup("scheduled", heartbeat=ctx.heartbeat)
    with ctx.unit() as unit:
        unit.save({"done": True}, {key: event.get(key) for key in ("archive", "size", "sha256", "second_target")})
    return True


def probe_handler(ctx: JobContext) -> bool:
    from ..full_backup import restore_probe

    event = restore_probe(heartbeat=ctx.heartbeat)
    with ctx.unit() as unit:
        unit.save({"done": True}, {"archive": event["archive"], "warnings": event["warnings"]})
    return True


def default_handlers() -> dict:
    return {RECURRING_KIND: make_recurring_handler(), ESCALATION_KIND: escalation_handler,
            SERVICE_CONTRACT_KIND: make_service_contract_handler(),
            BACKUP_KIND: backup_handler, PROBE_KIND: probe_handler}


_lock = threading.Lock()
_jobs: JobStore | None = None


def get_job_store() -> JobStore:
    """SQL job store with the SQL business store; memory otherwise."""
    global _jobs
    with _lock:
        if _jobs is None:
            from ... import dependencies

            if dependencies._scoped_session is not None:
                from ...db.session import engine

                _jobs = SqlJobStore(engine)
            else:
                _jobs = MemoryJobStore()
        return _jobs


def set_job_store(jobs: JobStore | None) -> None:
    global _jobs
    with _lock:
        _jobs = jobs


def enqueue_due(jobs: JobStore, now: datetime | None = None,
                periodic: tuple[Periodic, ...] | None = None) -> list[JobRun]:
    moment = now or utcnow()
    runs = []
    for item in active_periodic() if periodic is None else periodic:
        slot = item.schedule.latest_due(moment)
        runs.append(jobs.enqueue(item.kind, item.key(slot), {"as_of": slot.isoformat(),
                                                             "schedule": item.schedule.version},
                                 max_attempts=item.max_attempts))
    return runs


def tick(jobs: JobStore | None = None, runner: JobRunner | None = None,
         now: datetime | None = None) -> list[JobRun]:
    jobs = jobs or get_job_store()
    enqueue_due(jobs, now)
    runner = runner or JobRunner(jobs, default_handlers())
    return runner.run_until_idle()


async def run_forever(interval_seconds: float, stop: threading.Event) -> None:
    runner = JobRunner(get_job_store(), default_handlers(), stop=stop)
    while not stop.is_set():
        try:
            await asyncio.to_thread(tick, runner.jobs, runner)
        except Exception:
            logger.exception("Scheduler tick failed (retrying next interval)")
        await asyncio.sleep(interval_seconds)
