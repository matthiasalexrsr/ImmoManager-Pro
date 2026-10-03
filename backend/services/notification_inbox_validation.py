"""Pure, read-only personal read-state proof for native/offline callers."""

import sqlite3
from datetime import datetime
from time import monotonic

from sqlalchemy import DateTime, String, inspect, text

TABLE = "notification_read_states"
TABLES = (TABLE,)
FIELDS = ("actor_id", "notification_id", "read_at")


class InboxIntegrityError(ValueError):
    pass


def _check(deadline):
    if deadline is not None and monotonic() >= deadline:
        raise InboxIntegrityError("notification_inbox_validation_timeout")


def _rows(connection, sql, parameters=None, *, deadline=None):
    """Close every cursor; never buffer a complete read-state stock."""
    _check(deadline)
    if isinstance(connection, sqlite3.Connection):
        cursor = connection.execute(sql, parameters or {})
        try:
            names = [column[0] for column in cursor.description]
            while batch := cursor.fetchmany(64):
                for values in batch:
                    _check(deadline)
                    yield dict(zip(names, values))
        finally:
            cursor.close()
    else:
        old_stream = connection.get_execution_options().get("stream_results", False)
        result = None
        try:
            result = connection.execution_options(stream_results=True).execute(
                text(sql), parameters or {}
            ).mappings()
            while batch := result.fetchmany(64):
                for row in batch:
                    _check(deadline)
                    yield dict(row)
        finally:
            if result is not None:
                result.close()
            connection.execution_options(stream_results=old_stream)


def _names(connection, deadline):
    if isinstance(connection, sqlite3.Connection):
        return {row["name"] for row in _rows(
            connection, "SELECT name FROM sqlite_master WHERE type='table'", deadline=deadline
        )}
    return set(inspect(connection).get_table_names())


def _schema(connection, deadline):
    _check(deadline)
    names = _names(connection, deadline)
    if TABLE not in names:
        return False
    if not {"users", "notifications"} <= names:
        raise InboxIntegrityError("notification_inbox_parent_schema_incomplete")

    if isinstance(connection, sqlite3.Connection):
        columns = {row["name"]: row for row in _rows(
            connection, 'PRAGMA table_info("notification_read_states")', deadline=deadline
        )}
        if not set(FIELDS) <= set(columns):
            raise InboxIntegrityError("notification_inbox_columns_incomplete")
        if any(not columns[field]["notnull"] for field in FIELDS):
            raise InboxIntegrityError("notification_inbox_nullability_invalid")
        primary = {field for field, row in columns.items() if row["pk"]}
        if primary != {"actor_id", "notification_id"}:
            raise InboxIntegrityError("notification_inbox_primary_key_invalid")
        if (any(not columns[field]["type"].upper().startswith(("VARCHAR", "TEXT"))
                for field in ("actor_id", "notification_id"))
                or columns["read_at"]["type"].upper() not in {"DATETIME", "TIMESTAMP"}):
            raise InboxIntegrityError("notification_inbox_column_types_invalid")
        foreign = {(row["from"], row["table"], row["to"], row["on_delete"].upper())
                   for row in _rows(connection,
                       'PRAGMA foreign_key_list("notification_read_states")', deadline=deadline)}
    else:
        inspector = inspect(connection)
        columns = {column["name"]: column for column in inspector.get_columns(TABLE)}
        if not set(FIELDS) <= set(columns):
            raise InboxIntegrityError("notification_inbox_columns_incomplete")
        if any(columns[field]["nullable"] for field in FIELDS):
            raise InboxIntegrityError("notification_inbox_nullability_invalid")
        if set(inspector.get_pk_constraint(TABLE)["constrained_columns"]) != {
            "actor_id", "notification_id"
        }:
            raise InboxIntegrityError("notification_inbox_primary_key_invalid")
        if (any(not isinstance(columns[field]["type"], String)
                for field in ("actor_id", "notification_id"))
                or not isinstance(columns["read_at"]["type"], DateTime)
                or columns["read_at"]["type"].timezone):
            raise InboxIntegrityError("notification_inbox_column_types_invalid")
        foreign = set()
        if connection.dialect.name == "postgresql":
            actual_schema = connection.execute(text("SELECT current_schema()")).scalar_one()
            constraints = inspector.get_foreign_keys(TABLE, postgresql_ignore_search_path=True)
        else:
            actual_schema = inspector.default_schema_name
            constraints = inspector.get_foreign_keys(TABLE)
        for item in constraints:
            if (len(item["constrained_columns"]) == len(item["referred_columns"]) == 1
                    and item.get("referred_schema") in {None, actual_schema}):
                foreign.add((item["constrained_columns"][0], item["referred_table"],
                             item["referred_columns"][0],
                             item.get("options", {}).get("ondelete", "").upper()))
    if not {
        ("actor_id", "users", "id", "CASCADE"),
        ("notification_id", "notifications", "id", "CASCADE"),
    } <= foreign:
        raise InboxIntegrityError("notification_inbox_foreign_keys_invalid")
    _check(deadline)
    return True


def validate_notification_inbox_schema(connection, *, deadline=None) -> bool:
    """False for fully absent legacy metadata; reject damage without repair/DML."""
    try:
        return _schema(connection, deadline)
    except InboxIntegrityError:
        raise
    except Exception:
        raise InboxIntegrityError("notification_inbox_schema_invalid") from None


def _time(value):
    if isinstance(value, str):
        if len(value) < 19:
            raise ValueError("Full UTC datetime required")
        value = datetime.fromisoformat(value)
    if not isinstance(value, datetime) or value.tzinfo is not None:
        raise ValueError("Stored read time must be naive UTC")
    return value


def validate_notification_inbox_database(connection, *, deadline=None) -> bool:
    """Caller owns a consistent snapshot. Does not create, commit or mutate it."""
    if not validate_notification_inbox_schema(connection, deadline=deadline):
        return False
    try:
        for row in _rows(connection, """
            SELECT r.actor_id, r.notification_id, r.read_at,
                   u.id AS existing_actor, n.id AS existing_notification
            FROM notification_read_states AS r
            LEFT JOIN users AS u ON u.id=r.actor_id
            LEFT JOIN notifications AS n ON n.id=r.notification_id
            ORDER BY r.actor_id, r.notification_id
        """, deadline=deadline):
            if (not isinstance(row["actor_id"], str) or not row["actor_id"].strip()
                    or not isinstance(row["notification_id"], str)
                    or not row["notification_id"].strip()
                    or row["existing_actor"] is None
                    or row["existing_notification"] is None):
                raise InboxIntegrityError("notification_inbox_read_parent_invalid")
            _time(row["read_at"])
        _check(deadline)
        return True
    except InboxIntegrityError:
        raise
    except Exception:
        raise InboxIntegrityError("notification_inbox_read_state_invalid") from None
