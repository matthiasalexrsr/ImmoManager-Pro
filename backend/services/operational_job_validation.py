"""Pure staged-image validation/reset: no auth, Store or process startup imports."""

import sqlite3
from datetime import datetime
from time import monotonic
from uuid import UUID

from sqlalchemy import inspect, text

from .contract_lifecycle_validation import _hash, _object, _one, _rows
from .operational_job_types import FAMILIES, JobCreate

TABLES = ("operational_jobs", "operational_job_lanes", "operational_work_items")
FIELDS = {
    TABLES[0]: "id actor_id create_key request_hash scope_hash parameters revision state turn created_at updated_at",
    TABLES[1]: "id job_id family state cursor upper exhausted served fence lease_token lease_owner lease_expires_at next_attempt_at last_error scanned created updated skipped",
    TABLES[2]: "id job_id kind lane_id action_key source_id planned_revision state revision attempts next_attempt_at error_code result created_at",
}


class JobIntegrityError(ValueError):
    pass


def _check(deadline):
    if deadline is not None and monotonic() >= deadline:
        raise JobIntegrityError("operational_job_validation_timeout")


def _names(connection):
    return ({row["name"] for row in _rows(connection, "SELECT name FROM sqlite_master WHERE type='table'")}
            if isinstance(connection, sqlite3.Connection) else set(inspect(connection).get_table_names()))


def _hex(value):
    return isinstance(value, str) and len(value) == 64 and all(char in "0123456789abcdef" for char in value)


def validate_job_journal(connection, *, deadline=None):
    """False for complete pre-c2 images; rejects partial schema before any DML."""
    names = _names(connection)
    if not names.intersection(TABLES):
        return False
    if not set(TABLES).issubset(names):
        raise JobIntegrityError("operational_job_schema_incomplete")
    try:
        for table, expected in FIELDS.items():
            columns = ({row["name"] for row in _rows(connection, 'PRAGMA table_info("' + table + '")')}
                       if isinstance(connection, sqlite3.Connection)
                       else {column["name"] for column in inspect(connection).get_columns(table)})
            if not set(expected.split()) <= columns:
                raise JobIntegrityError("operational_job_columns_incomplete")
        for values in _rows(connection, "SELECT * FROM operational_jobs ORDER BY id"):
            _check(deadline)
            job = _object(values, ("parameters",))
            UUID(job.id)
            if (not _hex(job.create_key) or not _hex(job.scope_hash) or not _hex(job.request_hash) or _hash(job.parameters) != job.request_hash
                    or job.parameters.get("semantics_version") not in {1, 2} or job.revision <= 0 or job.turn < 0
                    or job.state not in {"queued", "running", "completed", "attention", "cancelled"}):
                raise ValueError
            request = JobCreate.model_validate({key: value for key, value in job.parameters.items() if key != "semantics_version"}
                                               | {"idempotency_key": job.create_key})
            if (any(family.startswith("recurring_") for family in request.families)
                    and job.parameters["semantics_version"] != 2):
                raise ValueError
            lanes = list(_rows(connection, "SELECT family,state FROM operational_job_lanes WHERE job_id=:job LIMIT " + str(len(FAMILIES) + 1), {"job": job.id}))
            if sorted(row["family"] for row in lanes) != sorted(request.families):
                raise ValueError
            if job.state == "completed" and any(row["state"] != "completed" for row in lanes):
                raise ValueError
            if job.state == "cancelled" and any(row["state"] != "cancelled" for row in lanes):
                raise ValueError
        for values in _rows(connection, "SELECT * FROM operational_job_lanes ORDER BY id"):
            _check(deadline)
            lane = _object(values, ())
            UUID(lane.id)
            if lane.family not in FAMILIES or lane.state not in {"ready", "completed", "attention", "cancelled"}:
                raise ValueError
            job = _one(connection, "SELECT id,turn FROM operational_jobs WHERE id=:id", {"id": lane.job_id})
            if not job or lane.served > job["turn"]:
                raise ValueError
            if any(type(getattr(lane, key)) is not int or getattr(lane, key) < 0 for key in ("served", "fence", "scanned", "created", "updated", "skipped")):
                raise ValueError
            if lane.cursor is not None and (lane.upper is None or lane.cursor > lane.upper):
                raise ValueError
            lease = [lane.lease_token, lane.lease_owner, lane.lease_expires_at]
            if any(value is not None for value in lease):
                if any(value is None for value in lease) or lane.state != "ready" or lane.fence < 1:
                    raise ValueError
                UUID(lane.lease_token)
                if isinstance(lane.lease_expires_at, str):
                    datetime.fromisoformat(lane.lease_expires_at)
            if lane.created + lane.updated + lane.skipped > lane.scanned:
                raise ValueError
            unfinished = _one(connection, "SELECT id FROM operational_work_items WHERE lane_id=:lane AND state='ready' LIMIT 1", {"lane": lane.id})
            issues = _one(connection, "SELECT id FROM operational_work_items WHERE lane_id=:lane AND state='attention' LIMIT 1", {"lane": lane.id})
            if lane.state == "completed" and (not lane.exhausted or unfinished or issues):
                raise ValueError
        for values in _rows(connection, "SELECT * FROM operational_work_items ORDER BY id"):
            _check(deadline)
            item = _object(values, ("result",))
            UUID(item.id)
            if not _one(connection, "SELECT id FROM operational_jobs WHERE id=:id", {"id": item.job_id}):
                raise ValueError
            if item.kind not in {"source", "command"} or item.state not in {"ready", "done", "attention"} or item.revision <= 0 or item.attempts < 0:
                raise ValueError
            if item.kind == "command":
                result = item.result
                if item.lane_id is not None or item.state != "done" or _hash(result["request"]) != result["request_hash"]:
                    raise ValueError
                if (result["request"]["operation"] not in {"cancel", "retry", "retry_lane"}
                        or result["receipt"]["id"] != item.job_id
                        or item.action_key != "command:" + _hash(result["request"]["request"]["idempotency_key"])):
                    raise ValueError
            else:
                lane = _one(connection, "SELECT job_id,family FROM operational_job_lanes WHERE id=:id", {"id": item.lane_id})
                if (not lane or lane["job_id"] != item.job_id or not item.source_id
                        or item.action_key != lane["family"] + ":" + item.source_id or not _hex(item.planned_revision)):
                    raise ValueError
                if lane["family"].startswith("recurring_"):
                    if (not isinstance(item.result, dict) or set(item.result) - {"created_count", "next_index", "adoption_cursor", "adoption_done"}
                            or any(type(item.result[key]) is not int or item.result[key] < 0
                                   for key in ("created_count", "next_index") if key in item.result)
                            or "adoption_cursor" in item.result and not isinstance(item.result["adoption_cursor"], str)
                            or "adoption_done" in item.result and type(item.result["adoption_done"]) is not bool):
                        raise ValueError
                key, target = item.result.get("effect_key"), item.result.get("target_id")
                if key:
                    if lane["family"] == "correspondence":
                        original = _one(connection, "SELECT target_id,target_kind,schedule_id FROM operational_occurrences WHERE key=:key", {"key": key})
                        if not original or original["target_id"] != target or original["target_kind"] != "calendar" or not original["schedule_id"].startswith("contract-correspondence:" + item.source_id + ":"):
                            raise ValueError
                    else:
                        original = _one(connection, "SELECT notification_id,entity_type,entity_id FROM operational_dispatches WHERE key=:key", {"key": key})
                        if not original or original["notification_id"] != target or original["entity_id"] != item.source_id or original["entity_type"] != lane["family"].removeprefix("overdue_"):
                            raise ValueError
        return True
    except JobIntegrityError:
        raise
    except Exception:
        raise JobIntegrityError("operational_job_journal_invalid") from None


def reset_restored_job_claims(connection, *, deadline=None):
    """Offline staged transaction only; caller owns rollback/publication/commit."""
    if not validate_job_journal(connection, deadline=deadline):
        return 0
    _check(deadline)
    sql = "UPDATE operational_job_lanes SET fence=fence+1,lease_token=NULL,lease_owner=NULL,lease_expires_at=NULL,next_attempt_at=NULL WHERE state='ready'"
    if isinstance(connection, sqlite3.Connection):
        count = connection.execute(sql).rowcount
        connection.execute("UPDATE operational_work_items SET next_attempt_at=NULL WHERE state='ready'")
        connection.execute("UPDATE operational_jobs SET revision=revision+1 WHERE state IN ('queued','running','attention')")
    else:
        count = connection.execute(text(sql)).rowcount
        connection.execute(text("UPDATE operational_work_items SET next_attempt_at=NULL WHERE state='ready'"))
        connection.execute(text("UPDATE operational_jobs SET revision=revision+1 WHERE state IN ('queued','running','attention')"))
    _check(deadline)
    return count
