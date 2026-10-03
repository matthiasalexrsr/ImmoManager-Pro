"""Offline coordinator validation/reset; no application, auth or store imports."""

import sqlite3
from uuid import UUID

from sqlalchemy import inspect, text

from .contract_lifecycle_validation import _hash, _one, _rows
from .operational_job_validation import JobIntegrityError, _check, _hex

TABLE = "operational_scheduler_state"
FIELDS = frozenset("id actor_id configuration_hash scope_hash generation generation_key as_of job_id state next_due_at fence lease_token lease_expires_at last_error updated_at".split())


def validate_scheduler(connection, *, deadline=None):
    sqlite = isinstance(connection, sqlite3.Connection)
    names = {row["name"] for row in _rows(connection, "SELECT name FROM sqlite_master WHERE type='table'")} if sqlite else set(inspect(connection).get_table_names())
    if TABLE not in names:
        return False
    columns = ({row["name"] for row in _rows(connection, 'PRAGMA table_info("' + TABLE + '")')} if sqlite
               else {column["name"] for column in inspect(connection).get_columns(TABLE)})
    if not FIELDS <= columns:
        raise JobIntegrityError("scheduler_schema_incomplete")
    try:
        for row in _rows(connection, "SELECT * FROM " + TABLE):
            _check(deadline)
            UUID(row["generation_key"])
            if (row["id"] != "automatic" or not row["actor_id"] or not _hex(row["configuration_hash"])
                    or not _hex(row["scope_hash"]) or row["generation"] <= 0 or row["fence"] < 0
                    or row["state"] not in {"reserved", "running", "completed", "attention", "cancelled"}):
                raise ValueError
            if (row["lease_token"] is None) != (row["lease_expires_at"] is None):
                raise ValueError
            if row["lease_token"] is not None:
                UUID(row["lease_token"])
            if row["job_id"] is None:
                if row["state"] != "reserved":
                    raise ValueError
            else:
                job = _one(connection, "SELECT actor_id,create_key,scope_hash,state FROM operational_jobs WHERE id=:id", {"id": row["job_id"]})
                if (not job or (job["actor_id"], job["scope_hash"], job["create_key"])
                        != (row["actor_id"], row["scope_hash"], _hash("automatic:" + row["generation_key"]))
                        or row["state"] == "completed" and job["state"] != "completed"):
                    raise ValueError
        return True
    except JobIntegrityError:
        raise
    except Exception:
        raise JobIntegrityError("scheduler_state_invalid") from None


def reset_scheduler_claims(connection, *, deadline=None):
    if not validate_scheduler(connection, deadline=deadline):
        return 0
    _check(deadline)
    sql = "UPDATE operational_scheduler_state SET fence=fence+1,lease_token=NULL,lease_expires_at=NULL"
    return connection.execute(sql if isinstance(connection, sqlite3.Connection) else text(sql)).rowcount
