"""Prepared isolated native/pure proofs. Root executes; no shared wiring here."""

import sqlite3
from contextlib import closing
from time import monotonic

import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from backend.services.notification_inbox_sqlite_check import (
    SQLiteInboxCheckError,
    SQLiteInboxCheckLimits,
    parse_sqlite_notification_identity_ddl,
    validate_sqlite_notification_identity_check,
)

CANONICAL = "length(actor_id)>0 AND length(notification_id)>0"


def _ddl(expression=CANONICAL, *, extra="", guard=True):
    clause = f", CONSTRAINT ck_notification_read_identity CHECK ({expression})" if guard else ""
    return f"""CREATE TABLE notification_read_states (
        actor_id VARCHAR NOT NULL, notification_id VARCHAR NOT NULL,
        read_at DATETIME NOT NULL{extra}, PRIMARY KEY(actor_id,notification_id)
        {clause})"""


def _database(ddl=None, encoding="UTF-8"):
    connection = sqlite3.connect(":memory:")
    try:
        connection.execute(f"PRAGMA encoding='{encoding}'")
        connection.execute(_ddl() if ddl is None else ddl)
        return connection
    except BaseException:
        connection.close()
        raise


@pytest.mark.parametrize("expression", [
    CANONICAL,
    'length("actor_id") > 0 AND length([notification_id]) > 0',
    "(length((actor_id))>00) AND (((length(`notification_id`))>0))",
    "length(notification_id)>0 /* NOT OR */ AND length(actor_id)>0",
    '"length"("ACTOR_ID")>0 AND LENGTH(notification_id)>0',
])
def test_actual_native_canonical_and_grouped_identity_guards(expression):
    with closing(_database(_ddl(expression))) as connection:
        assert validate_sqlite_notification_identity_check(connection) is True


@pytest.mark.parametrize("expression", [
    "1", "length(actor_id)>0 OR 1", "length(actor_id)>0",
    "length('actor_id')>0 AND length('notification_id')>0",
    "length(actor_id)>=0 AND length(notification_id)>0",
    "length(actor_id)>0 AND length(actor_id)>0",
    "length(actor_id)>0 AND length(notification_id)>0 OR 1",
    "length(actor_id || 'x')>0 AND length(notification_id)>0",
    "CASE WHEN length(actor_id)>0 THEN 1 ELSE 0 END AND length(notification_id)>0",
    "length(actor_id)>CAST(0 AS INTEGER) AND length(notification_id)>0",
    "length(actor_id)>0 COLLATE BINARY AND length(notification_id)>0",
])
def test_actual_native_unknown_or_weakened_semantics_refuse(expression):
    with closing(_database(_ddl(expression))) as connection:
        with pytest.raises(SQLiteInboxCheckError):
            validate_sqlite_notification_identity_check(connection)


@pytest.mark.parametrize("ddl", [
    _ddl(guard=False),
    _ddl(guard=False, extra=", CHECK(1)"),
    _ddl(guard=False, extra=", note TEXT DEFAULT 'CONSTRAINT ck_notification_read_identity CHECK (length(actor_id)>0 AND length(notification_id)>0)'"),
    _ddl(guard=False, extra=", note TEXT /* CONSTRAINT ck_notification_read_identity CHECK (length(actor_id)>0 AND length(notification_id)>0) */"),
    _ddl(guard=False, extra=', "CHECK" TEXT'),
])
def test_native_guard_name_text_does_not_prove_a_constraint(ddl):
    with closing(_database(ddl)) as connection:
        with pytest.raises(SQLiteInboxCheckError, match="^notification_inbox_sqlite_check_guard_missing$"):
            validate_sqlite_notification_identity_check(connection)


def test_actual_disabled_check_constraints_refuses_without_reset():
    with closing(_database()) as connection:
        connection.execute("PRAGMA ignore_check_constraints=ON")
        with pytest.raises(SQLiteInboxCheckError, match="^notification_inbox_sqlite_check_disabled$"):
            validate_sqlite_notification_identity_check(connection)
        assert connection.execute("PRAGMA ignore_check_constraints").fetchone()[0] == 1


@pytest.mark.parametrize("name,arity", [("length", 1), ("length", -1), ("substr", 3), ("substr", -1)])
def test_native_scalar_overrides_refuse_before_any_callback(name, arity):
    with closing(_database()) as connection:
        calls = []
        connection.create_function(name, arity, lambda *args: calls.append(args) or 1,
                                   deterministic=True)
        with pytest.raises(SQLiteInboxCheckError, match="^notification_inbox_sqlite_check_function_invalid$"):
            validate_sqlite_notification_identity_check(connection)
        assert calls == []


def test_native_aggregate_override_refuses_without_evaluation():
    calls = []

    class Aggregate:
        def step(self, *args):
            calls.append(args)

        def finalize(self):
            return 1

    with closing(_database()) as connection:
        connection.create_aggregate("length", 1, Aggregate)
        with pytest.raises(SQLiteInboxCheckError, match="^notification_inbox_sqlite_check_function_invalid$"):
            validate_sqlite_notification_identity_check(connection)
        assert calls == []


def test_native_different_fixed_arity_does_not_bind_one_argument_check():
    with closing(_database()) as connection:
        calls = []
        connection.create_function("length", 2, lambda *args: calls.append(args) or 1)
        assert validate_sqlite_notification_identity_check(connection) is True
        assert calls == []


@pytest.mark.parametrize("encoding", ["UTF-8", "UTF-16le", "UTF-16be"])
def test_native_database_encoding_uses_bounded_blob_ddl(encoding):
    with closing(_database(encoding=encoding)) as connection:
        assert validate_sqlite_notification_identity_check(connection) is True


def test_native_temp_shadow_and_view_and_case_alias_refuse():
    with closing(_database()) as connection:
        connection.execute("CREATE TEMP TABLE notification_read_states(dummy TEXT)")
        with pytest.raises(SQLiteInboxCheckError, match="^notification_inbox_sqlite_check_catalog_invalid$"):
            validate_sqlite_notification_identity_check(connection)
    with closing(sqlite3.connect(":memory:")) as connection:
        connection.execute("CREATE VIEW notification_read_states AS SELECT 1 AS dummy")
        with pytest.raises(SQLiteInboxCheckError, match="^notification_inbox_sqlite_check_catalog_invalid$"):
            validate_sqlite_notification_identity_check(connection)
    with closing(_database(_ddl().replace("notification_read_states", "Notification_Read_States"))) as connection:
        with pytest.raises(SQLiteInboxCheckError, match="^notification_inbox_sqlite_check_catalog_invalid$"):
            validate_sqlite_notification_identity_check(connection)


def test_native_absent_family_is_only_an_observation():
    with closing(sqlite3.connect(":memory:")) as connection:
        assert validate_sqlite_notification_identity_check(connection) is False


def test_native_actual_columns_prevent_double_quoted_literal_fallback():
    ddl = _ddl('length("actor_id")>0 AND length(notification_id)>0').replace(
        "actor_id VARCHAR NOT NULL", "different_id VARCHAR NOT NULL"
    ).replace("PRIMARY KEY(actor_id,notification_id)", "PRIMARY KEY(different_id,notification_id)")
    with closing(_database(ddl)) as connection:
        with pytest.raises(SQLiteInboxCheckError, match="^notification_inbox_sqlite_check_guard_invalid$"):
            validate_sqlite_notification_identity_check(connection)


@pytest.mark.parametrize("limits", [
    SQLiteInboxCheckLimits(ddl_bytes=32),
    SQLiteInboxCheckLimits(tokens=8),
    SQLiteInboxCheckLimits(depth=1),
])
def test_actual_native_metadata_or_parser_budgets_refuse(limits):
    with closing(_database()) as connection:
        with pytest.raises(SQLiteInboxCheckError, match="^notification_inbox_sqlite_check_budget_exceeded$"):
            validate_sqlite_notification_identity_check(connection, limits=limits)


@pytest.mark.parametrize("stock", ["indexes", "functions"])
def test_native_unrelated_catalog_stock_has_no_total_limit(stock):
    with closing(_database()) as connection:
        calls = []
        for index in range(513):
            if stock == "indexes":
                connection.execute(f"CREATE INDEX unrelated_{index} ON notification_read_states(read_at)")
            else:
                connection.create_function(f"unrelated_{index}", 1, lambda *args: calls.append(args) or 1)
        assert validate_sqlite_notification_identity_check(
            connection, limits=SQLiteInboxCheckLimits(batch_rows=1),
            deadline=monotonic() + 10,
        ) is True
        assert calls == []


def test_native_readonly_transaction_and_data_are_preserved():
    with closing(_database()) as connection:
        connection.execute("INSERT INTO notification_read_states VALUES ('a','n','2026-10-04 12:00:00')")
        assert connection.in_transaction
        original = list(connection.iterdump())
        deny = {sqlite3.SQLITE_INSERT, sqlite3.SQLITE_UPDATE, sqlite3.SQLITE_DELETE,
                sqlite3.SQLITE_CREATE_TABLE, sqlite3.SQLITE_DROP_TABLE, sqlite3.SQLITE_ALTER_TABLE,
                sqlite3.SQLITE_TRANSACTION}
        statements = []
        connection.set_authorizer(lambda operation, *_: sqlite3.SQLITE_DENY if operation in deny else sqlite3.SQLITE_OK)
        connection.set_trace_callback(statements.append)
        try:
            assert validate_sqlite_notification_identity_check(connection) is True
        finally:
            connection.set_authorizer(None)
            connection.set_trace_callback(None)
        assert connection.in_transaction
        assert list(connection.iterdump()) == original
        assert all(sql.lstrip().upper().startswith(("SELECT", "PRAGMA")) for sql in statements)


def test_sqlalchemy_real_sqlite_connection_keeps_caller_transaction():
    engine = create_engine("sqlite+pysqlite://", poolclass=StaticPool)
    try:
        with engine.connect() as connection:
            connection.exec_driver_sql(_ddl())
            assert connection.in_transaction()
            assert validate_sqlite_notification_identity_check(connection) is True
            assert connection.in_transaction()
    finally:
        engine.dispose()


@pytest.mark.parametrize("ddl", [
    "CREATE TABLE notification_read_states(",
    _ddl() + " /* unclosed",
    _ddl().replace("actor_id VARCHAR", '"actor_id VARCHAR'),
    _ddl() + " WITHOUT ROWID",
    _ddl(CANONICAL + ") OR 1 /*"),
])
def test_pure_malformed_or_unsupported_ddl_refuses(ddl):
    with pytest.raises(SQLiteInboxCheckError):
        parse_sqlite_notification_identity_ddl(ddl)


def test_expired_actual_deadline_refuses_before_native_call():
    with closing(_database()) as connection:
        statements = []
        connection.set_trace_callback(statements.append)
        with pytest.raises(SQLiteInboxCheckError, match="^notification_inbox_sqlite_check_timeout$"):
            validate_sqlite_notification_identity_check(connection, deadline=monotonic() - 1)
        assert statements == []


@pytest.mark.parametrize("value", [True, 0, -1, 1.5])
def test_invalid_limit_is_fixed_value_free_refusal(value):
    with pytest.raises(SQLiteInboxCheckError, match="^notification_inbox_sqlite_check_limits_invalid$"):
        SQLiteInboxCheckLimits(ddl_bytes=value)
