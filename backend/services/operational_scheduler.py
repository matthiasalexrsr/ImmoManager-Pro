"""Persistent automatic generation binding; every business effect remains a job."""

from dataclasses import dataclass
from datetime import timedelta
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import func, update

from ..db.operational_scheduler_models import OperationalSchedulerORM
from . import operational_jobs as jobs
from .contract_lifecycle import digest
from .operational_job_types import FAMILIES, JobContinue, JobCreate, PacketPolicy


@dataclass(frozen=True)
class SchedulerClaim:
    generation: int
    generation_key: str
    token: str
    fence: int
    actor_id: str
    configuration_hash: str
    scope_hash: str
    as_of: str
    job_id: str | None


def _view(row):
    return {"generation": row.generation, "job_id": row.job_id, "state": row.state,
            "last_error": row.last_error, "next_due_at": row.next_due_at,
            "updated_at": row.updated_at, "families": list(FAMILIES)}


def _hash(parameters):
    return digest(parameters)


def reserve(store, actor_id, parameters, *, lease_seconds=45):
    """Reserve before job creation: the generation's key survives a lost worker."""
    captured = jobs._operator(actor_id)
    configuration = _hash(parameters)
    scope = jobs._scope_hash(captured)
    with jobs.atomic(store, captured) as unit:
        now = jobs._clock(unit.db)
        row = unit.row(OperationalSchedulerORM, "automatic")
        if row is not None and row.lease_expires_at is not None and row.lease_expires_at > now:
            return None
        if row is None:
            row = OperationalSchedulerORM(id="automatic", actor_id=actor_id,
                configuration_hash=configuration, scope_hash=scope, generation=1, generation_key=str(uuid4()),
                as_of=now.date(), job_id=None, state="reserved", next_due_at=None,
                fence=0, lease_token=None, lease_expires_at=None, last_error=None, updated_at=now)
            unit.add(row)
        else:
            unit.touch_row(row)
            changed = (row.actor_id, row.configuration_hash, row.scope_hash) != (actor_id, configuration, scope)
            if changed or row.state == "completed" and (row.next_due_at is None or row.next_due_at <= now):
                row.generation += 1
                row.generation_key = str(uuid4())
                row.actor_id, row.configuration_hash, row.scope_hash = actor_id, configuration, scope
                row.as_of, row.job_id, row.state = now.date(), None, "reserved"
                row.next_due_at = row.last_error = None
            elif row.state in {"completed", "attention", "cancelled"}:
                attached = jobs._job(unit, row.job_id) if row.job_id else None
                if row.state == "attention" and attached is not None and attached.state in {"queued", "running"}:
                    row.state, row.last_error = attached.state, None
                else:
                    return None
        row.fence += 1
        row.lease_token = str(uuid4())
        row.lease_expires_at = now + timedelta(seconds=lease_seconds)
        row.updated_at = now
        return SchedulerClaim(row.generation, row.generation_key, row.lease_token, row.fence, actor_id,
            configuration, scope, row.as_of.isoformat(), row.job_id)


def _checked(unit, claim):
    row = unit.row(OperationalSchedulerORM, "automatic")
    if (row is None or row.generation != claim.generation or row.generation_key != claim.generation_key or row.fence != claim.fence
            or row.lease_token != claim.token or row.lease_expires_at is None
            or row.lease_expires_at <= jobs._clock(unit.db)
            or (row.actor_id, row.configuration_hash, row.scope_hash)
            != (claim.actor_id, claim.configuration_hash, claim.scope_hash)):
        raise jobs.ClaimLost("Scheduler generation was superseded")
    return row


def _fence(unit, claim):
    if unit.db is None:
        _checked(unit, claim)
        return
    now = func.timezone("UTC", func.clock_timestamp()) if unit.db.get_bind().dialect.name == "postgresql" else func.strftime("%Y-%m-%d %H:%M:%f", "now")
    result = unit.db.execute(update(OperationalSchedulerORM).where(
        OperationalSchedulerORM.id == "automatic", OperationalSchedulerORM.generation == claim.generation,
        OperationalSchedulerORM.lease_token == claim.token, OperationalSchedulerORM.fence == claim.fence,
        OperationalSchedulerORM.lease_expires_at > now).values(fence=claim.fence).execution_options(synchronize_session=False))
    if result.rowcount != 1:
        raise jobs.ClaimLost("Scheduler finishing fence expired")


def attach(store, claim, identifier):
    captured = jobs._operator(claim.actor_id)
    with jobs.atomic(store, captured) as unit:
        row = _checked(unit, claim)
        job = jobs._job(unit, identifier)
        if (job.create_key != digest("automatic:" + claim.generation_key)
                or job.actor_id != claim.actor_id or job.scope_hash != claim.scope_hash):
            raise HTTPException(409, "Der Arbeitslauf gehört nicht zur automatischen Generation.")
        if row.job_id is not None and row.job_id != identifier:
            raise jobs.ClaimLost("Scheduler already attached another job")
        unit.touch_row(row)
        row.job_id, row.state = identifier, "running"
        _fence(unit, claim)


def finish(store, claim, result, *, interval_seconds):
    captured = jobs._operator(claim.actor_id)
    with jobs.atomic(store, captured) as unit:
        row = _checked(unit, claim)
        if row.job_id != result["id"]:
            raise jobs.ClaimLost("Scheduler completion belongs to another job")
        current = jobs._job(unit, row.job_id)
        unit.touch_row(row)
        row.state = current.state
        row.updated_at = jobs._clock(unit.db)
        row.last_error = "job_needs_attention" if current.state == "attention" else None
        row.next_due_at = row.updated_at + timedelta(seconds=interval_seconds) if row.state == "completed" else None
        _fence(unit, claim)
        row.lease_token = row.lease_expires_at = None
        return _view(row)


def advance(store, actor_id, parameters, *, policy=PacketPolicy(), worker_id=None):
    claim = reserve(store, actor_id, parameters, lease_seconds=max(45, policy.lease_seconds * 2))
    if claim is None:
        return status(store, actor_id)
    identifier = claim.job_id
    if identifier is None:
        result = jobs.create_job(store, JobCreate(idempotency_key="automatic:" + claim.generation_key,
            as_of=claim.as_of, lookback_days=parameters["lookback_days"],
            full_catch_up=parameters.get("full_catch_up", False), families=FAMILIES), actor_id)
        identifier = result["id"]
        attach(store, claim, identifier)
    result = jobs.continue_job(store, identifier, JobContinue(max_items=parameters["max_items"]),
                               actor_id, policy=policy, worker_id=worker_id)
    return finish(store, claim, result, interval_seconds=parameters["interval_seconds"])


def status(store, actor_id):
    captured = jobs._operator(actor_id)
    with jobs.atomic(store, captured) as unit:
        row = unit.row(OperationalSchedulerORM, "automatic")
        if row is None:
            return {"state": "not_started", "families": list(FAMILIES)}
        if (row.actor_id, row.scope_hash) != (actor_id, jobs._scope_hash(captured)):
            return {"state": "configuration_changed", "families": list(FAMILIES)}
        return _view(row)
