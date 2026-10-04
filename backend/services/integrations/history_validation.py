"""Offline, bounded, callback-free validation using explicit restored keys."""

import hashlib
import json
import sqlite3
import time

from sqlalchemy import JSON, String, Text, case, cast, func

from ...db.integration_history_models import HISTORY_MODELS
from ...db.integration_history_schema import ensure_history_schema
from .history_crypto import CHUNK_BYTES, decrypt, digest, event_identity, ring_for, run_identity, stamp
from .history_types import HistoryError, HistoryLimits

TERMINAL = frozenset({"completed", "rejected", "observation_failed", "outcome_uncertain"})
ARTIFACT_KINDS = frozenset({"request", "response", "schema"})


def ciphertext_limit(limits):
    return 256 + 4 * ((limits.artifact_bytes + 28 + 2) // 3)


def bounded_projection(table, limits):
    """CASE limits damaged SQL text before transfer, including JSON columns."""
    projected = []
    for column in table.columns:
        if isinstance(column.type, (String, JSON)):
            value = cast(column, Text) if isinstance(column.type, JSON) else column
            maximum = ciphertext_limit(limits) if column.name == "metadata_ciphertext" else limits.artifact_bytes
            projected.append(case((func.length(value) <= maximum, value), else_=None).label(column.name))
        else:
            projected.append(column)
    return projected


def raw_projection(table, limits):
    projected = []
    for column in table.columns:
        name = column.name
        if isinstance(column.type, (String, JSON)):
            value = "CAST(" + name + " AS TEXT)" if isinstance(column.type, JSON) else name
            maximum = ciphertext_limit(limits) if name == "metadata_ciphertext" else limits.artifact_bytes
            projected.append(f"CASE WHEN length({value})<={maximum} THEN {value} ELSE NULL END AS {name}")
        else:
            projected.append(name)
    return ", ".join(projected)


def check_row(row, table):
    if any(not column.nullable and row[column.name] is None for column in table.columns):
        raise HistoryError("HISTORY_CORRUPT")


def check_transition(previous, event, number):
    state = event["state"]
    if number > 3 or state not in TERMINAL | {"accepted", "execution_started"}:
        raise HistoryError("HISTORY_CORRUPT")
    if previous is None:
        valid = state == "accepted"
    elif previous == "accepted":
        valid = state in TERMINAL - {"completed"} | {"execution_started"}
    elif previous == "execution_started":
        valid = state in TERMINAL - {"rejected"}
    else:
        valid = False
    if not valid:
        raise HistoryError("HISTORY_CORRUPT")


def checked_json(raw):
    def unique(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError()
            result[key] = value
        return result

    try:
        return json.loads(raw, object_pairs_hook=unique, parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    except (ValueError, UnicodeError, RecursionError, TypeError):
        raise HistoryError("HISTORY_CORRUPT") from None


def check_deadline(deadline):
    if deadline is not None and time.monotonic() > deadline:
        raise HistoryError("HISTORY_BUDGET_EXCEEDED")


def rows(connection, sql, parameters=()):
    """One record at a time; PG uses server-side cursor, no ORM scope filtering."""
    if isinstance(connection, sqlite3.Connection):
        cursor = connection.execute(sql, parameters)
        names = [description[0] for description in cursor.description]
        try:
            for row in cursor:
                yield dict(zip(names, row, strict=True))
        finally:
            cursor.close()
    else:
        original = connection.get_execution_options().get("stream_results", False)
        result = connection.execution_options(stream_results=True).exec_driver_sql(sql, parameters)
        try:
            yield from result.mappings()
        finally:
            result.close()
            connection.execution_options(stream_results=original)


def placeholder(connection):
    return "?" if isinstance(connection, sqlite3.Connection) or connection.dialect.name == "sqlite" else "%s"


def decode_manifest(value):
    value = checked_json(value) if isinstance(value, str) else value
    if not isinstance(value, dict) or not set(value).issubset(ARTIFACT_KINDS) or any(not isinstance(info, dict) or set(info) != {"bytes", "chunks", "sha256"}
            or type(info["bytes"]) is not int or info["bytes"] < 0 or type(info["chunks"]) is not int or info["chunks"] < 1
            or info["chunks"] != max(1, (info["bytes"] + CHUNK_BYTES - 1) // CHUNK_BYTES)
            or not isinstance(info["sha256"], str) or len(info["sha256"]) != 64
            or any(character not in "0123456789abcdef" for character in info["sha256"]) for info in value.values()):
        raise HistoryError("HISTORY_CORRUPT")
    return value


def verified_artifacts(connection, run, event, ring, limits, *, deadline=None, collect=True):
    event = dict(event)
    event["manifest"] = decode_manifest(event["manifest"])
    identity = event_identity(run, event)
    metadata = checked_json(decrypt(event["metadata_ciphertext"], {"kind": "event", "identity": identity}, ring))
    if metadata != identity or digest(identity) != event["event_hash"] or event["integration_id"] != run["integration_id"]:
        raise HistoryError("HISTORY_CORRUPT")
    mark = placeholder(connection)
    result = {}
    # Check all bindings and kinds, including otherwise hidden extra chunks.
    seen = 0
    for kind, info in event["manifest"].items():
        if info["bytes"] > limits.artifact_bytes:
            raise HistoryError("HISTORY_BUDGET_EXCEEDED")
        size, count, checksum = 0, 0, hashlib.sha256()
        content = bytearray() if collect else None
        for row in rows(connection, f"SELECT position, CASE WHEN length(ciphertext)<={mark} THEN ciphertext ELSE NULL END AS ciphertext FROM integration_run_chunks WHERE event_id={mark} AND kind={mark} ORDER BY position", (128 + 4 * ((CHUNK_BYTES + 28 + 2) // 3), event["id"], kind)):
            check_deadline(deadline)
            if row["position"] != count or not isinstance(row["ciphertext"], str):
                raise HistoryError("HISTORY_CORRUPT")
            block = decrypt(row["ciphertext"], {"kind": kind, "position": count, "event": identity}, ring)
            expected = min(CHUNK_BYTES, info["bytes"] - size)
            if len(block) != expected:
                raise HistoryError("HISTORY_CORRUPT")
            size += len(block)
            count += 1
            checksum.update(block)
            if content is not None:
                content.extend(block)
        if count != info["chunks"] or size != info["bytes"] or checksum.hexdigest() != info["sha256"]:
            raise HistoryError("HISTORY_CORRUPT")
        seen += count
        if content is not None:
            result[kind] = checked_json(content)
    # Count is scoped to one bounded event, not a global total/pagination query.
    total = next(rows(connection, f"SELECT COUNT(*) AS count FROM integration_run_chunks WHERE event_id={mark}", (event["id"],)))["count"]
    if total != seen:
        raise HistoryError("HISTORY_CORRUPT")
    return result


def check_artifacts(event, artifacts):
    state = event["state"]
    if state == "accepted":
        valid = set(artifacts) == {"request", "schema"} and isinstance(artifacts["request"], dict) and event["success"] is None
    elif state == "execution_started":
        valid = not artifacts and event["success"] is None
    else:
        response = artifacts.get("response")
        valid = (set(artifacts) == {"response", "schema"} and isinstance(response, dict)
                 and type(response.get("success")) is bool and response["success"] == bool(event["success"])
                 and event["success"] is not None and isinstance(response.get("message"), str))
    if not valid or (artifacts and not isinstance(artifacts.get("schema"), dict)):
        raise HistoryError("HISTORY_CORRUPT")


def validate_history_journal(connection, configuration, *, deadline=None, limits=None):
    try:
        return _validate_history_journal(connection, configuration, deadline=deadline, limits=limits)
    except (TypeError, ValueError, KeyError, OverflowError):
        raise HistoryError("HISTORY_CORRUPT") from None


def _validate_history_journal(connection, configuration, *, deadline=None, limits=None):
    """Mapping[str,str] G44 config or explicit IBANKeyring; never ambient keys.

    Entire absent family returns False before key resolution. No mutation,
    provider, auth, audit callback or session factory occurs in this function.
    """
    if not ensure_history_schema(connection):
        return False
    if configuration is None:
        raise HistoryError("HISTORY_KEY_UNAVAILABLE")
    ring = ring_for(configuration)
    limits = limits or HistoryLimits()
    mark = placeholder(connection)
    head_table, run_table, event_table, _, clear_table = [model.__table__ for model in HISTORY_MODELS]
    for head in rows(connection, f"SELECT {raw_projection(head_table, limits)} FROM integration_history_heads ORDER BY integration_id"):
        check_row(head, head_table)
        check_deadline(deadline)
        run_count, event_count, cleared_count, cleared_events, epoch = 0, 0, 0, 0, 0
        for run in rows(connection, f"SELECT {raw_projection(run_table, limits)} FROM integration_runs WHERE integration_id={mark} ORDER BY run_sequence", (head["integration_id"],)):
            check_row(run, run_table)
            check_deadline(deadline)
            run_count += 1
            identity = run_identity(run)
            metadata = checked_json(decrypt(run["metadata_ciphertext"], {"kind": "run", "identity": identity}, ring))
            if not isinstance(metadata, dict) or metadata.get("identity") != identity or not isinstance(metadata.get("ticket_hash"), str) or len(metadata["ticket_hash"]) != 64:
                raise HistoryError("HISTORY_CORRUPT")
            previous, number, last_state, last_sequence = "", 0, None, 0
            for event in rows(connection, f"SELECT {raw_projection(event_table, limits)} FROM integration_run_events WHERE run_id={mark} ORDER BY event_number", (run["id"],)):
                check_row(event, event_table)
                event_count += 1
                if event["event_number"] != number + 1 or event["previous_hash"] != previous or event["journal_sequence"] <= last_sequence or event["journal_sequence"] > head["event_sequence"]:
                    raise HistoryError("HISTORY_CORRUPT")
                check_transition(last_state, event, number + 1)
                artifacts = verified_artifacts(connection, run, event, ring, limits, deadline=deadline)
                check_artifacts(event, artifacts)
                number, previous, last_state, last_sequence = event["event_number"], event["event_hash"], event["state"], event["journal_sequence"]
            if number == 0 or run["run_sequence"] > head["run_sequence"] or run["scope_kind"] != "installation" or not run["actor_id"]:
                raise HistoryError("HISTORY_CORRUPT")
        for clear in rows(connection, f"SELECT {raw_projection(clear_table, limits)} FROM integration_history_clears WHERE integration_id={mark} ORDER BY clear_epoch", (head["integration_id"],)):
            check_row(clear, clear_table)
            check_deadline(deadline)
            identity = {key: stamp(clear[key]) if key == "created_at" else clear[key] for key in ("id", "integration_id", "clear_epoch", "actor_id", "created_at", "cleared")}
            proof = checked_json(decrypt(clear["metadata_ciphertext"], {"kind": "clear", "identity": identity}, ring))
            if not isinstance(proof, dict) or proof.get("identity") != identity or clear["clear_epoch"] != epoch + 1 or type(proof.get("event_count")) is not int or proof["event_count"] < 0:
                raise HistoryError("HISTORY_CORRUPT")
            epoch += 1
            cleared_count += clear["cleared"]
            cleared_events += proof["event_count"]
        if run_count != head["active_runs"] or run_count + cleared_count != head["run_sequence"] or event_count + cleared_events != head["event_sequence"] or epoch != head["clear_epoch"]:
            raise HistoryError("HISTORY_CORRUPT")
    # Reject orphan rows even when constraints have been removed in a damaged image.
    for sql in (
        "SELECT 1 AS bad FROM integration_runs r LEFT JOIN integration_history_heads h ON r.integration_id=h.integration_id WHERE h.integration_id IS NULL LIMIT 1",
        "SELECT 1 AS bad FROM integration_run_events e LEFT JOIN integration_runs r ON e.run_id=r.id WHERE r.id IS NULL OR e.integration_id<>r.integration_id OR e.integration_id IS NULL LIMIT 1",
        "SELECT 1 AS bad FROM integration_run_chunks c LEFT JOIN integration_run_events e ON c.event_id=e.id WHERE e.id IS NULL LIMIT 1",
        "SELECT 1 AS bad FROM integration_history_clears c LEFT JOIN integration_history_heads h ON c.integration_id=h.integration_id WHERE h.integration_id IS NULL LIMIT 1",
    ):
        if next(rows(connection, sql), None) is not None:
            raise HistoryError("HISTORY_CORRUPT")
    return True
