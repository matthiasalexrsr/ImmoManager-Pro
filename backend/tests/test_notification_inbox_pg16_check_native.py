"""Prepared genuine PG16 cases; Root runs with central support >= 1fce39f.

Only the dedicated central fixture owns connections/UUID schema/cleanup. This
file creates no engines or parallel alternative fixture and imports no runtime.
"""

import importlib.util
import os
from pathlib import Path
from time import monotonic

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import event, text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import IntegrityError

from backend.services.notification_inbox_pg16_check import (
    PG16InboxCheckError,
    validate_pg16_notification_identity_check,
)
from backend.tests.notification_inbox_pg_proposal_support import postgres_proposal_database

GUARD = "ck_notification_read_identity"
CANONICAL = "pg_catalog.length(actor_id)>0 AND pg_catalog.length(notification_id)>0"
PROPOSAL = (Path(__file__).resolve().parents[1] / "db/migrations/proposals"
            / "m2a2b3c4d5e6_personal_notification_reads.py")


def _sql(connection, sql, parameters=None):
    result = connection.execute(text(sql), {} if parameters is None else parameters)
    try:
        return [tuple(row) for row in result] if result.returns_rows else []
    finally:
        result.close()


def _proposal():
    specification = importlib.util.spec_from_file_location("native_pg_guard_m2", PROPOSAL)
    assert specification is not None and specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    assert module.revision == "m2a2b3c4d5e6"
    assert module.down_revision == "l2a2b3c4d5e6"
    assert PROPOSAL.parent.name == "proposals"
    return module


@pytest.fixture
def native_m2_database():
    # No skip/fallback: the central helper rejects missing/non-dedicated URLs.
    with postgres_proposal_database(os.getenv("TEST_SERVER_DATABASE_URL")) as engine:
        with engine.begin() as connection:
            assert isinstance(connection, Connection)
            schema, version = _sql(connection, """
                SELECT pg_catalog.current_schema(), pg_catalog.current_setting('server_version_num')
            """)[0]
            assert schema.startswith("notification_inbox_m2_")
            assert len(schema) == len("notification_inbox_m2_") + 32
            assert int(version) // 10000 == 16, "This native gate requires actual PG16; no version stub"
            _sql(connection, "CREATE TABLE users(id VARCHAR PRIMARY KEY)")
            _sql(connection, """CREATE TABLE notifications(
                id VARCHAR PRIMARY KEY, status VARCHAR NOT NULL, read_at TIMESTAMP WITHOUT TIME ZONE)
            """)
            _sql(connection, "INSERT INTO users(id) VALUES (:id)", [{"id": "reader-a"}, {"id": ""}])
            _sql(connection, "INSERT INTO notifications(id,status) VALUES (:id,'unread')",
                 [{"id": "notice-a"}, {"id": ""}])
            with Operations.context(MigrationContext.configure(connection)):
                _proposal().upgrade()
            _sql(connection, """INSERT INTO notification_read_states(actor_id,notification_id,read_at)
                VALUES ('reader-a','notice-a','2026-10-04 12:15:00')
            """)
        yield engine, schema


def _quoted(connection, schema):
    # Schema came from the central helper's actual random owned namespace.
    return connection.dialect.identifier_preparer.quote_schema(schema)


def _fingerprint(connection, schema):
    context = _sql(connection, """
        SELECT pg_catalog.current_schema(),
               pg_catalog.to_regnamespace(pg_catalog.current_schema())::oid,
               pg_catalog.to_regclass('notification_read_states')::oid
    """)
    objects = _sql(connection, """
        SELECT c.relname,c.oid,c.relkind,n.nspname
        FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace
        WHERE (n.nspname=:schema OR c.oid=pg_catalog.to_regclass('notification_read_states'))
          AND c.relname IN ('notification_read_states','original_notification_read_states')
        ORDER BY n.nspname,c.relname
    """, {"schema": schema})
    constraints = _sql(connection, """
        SELECT c.oid,c.conrelid,c.conname,c.convalidated,c.conkey,
               pg_catalog.octet_length(c.conbin::text),pg_catalog.substr(c.conbin::text,1,8192)
        FROM pg_catalog.pg_constraint c JOIN pg_catalog.pg_class r ON r.oid=c.conrelid
        JOIN pg_catalog.pg_namespace n ON n.oid=r.relnamespace
        WHERE n.nspname=:schema
          AND r.relname IN ('notification_read_states','original_notification_read_states')
        ORDER BY c.oid
    """, {"schema": schema})
    data_table = ("original_notification_read_states"
                  if any(row[0] == "original_notification_read_states" and row[3] == schema for row in objects)
                  else "notification_read_states")
    data = _sql(connection, f"""
        SELECT actor_id,notification_id,read_at FROM {_quoted(connection, schema)}.{data_table}
        ORDER BY actor_id,notification_id
    """)
    return context, objects, constraints, data


def _observe(connection, schema, error=None):
    assert isinstance(connection, Connection)
    transaction = connection.get_transaction()
    assert transaction is not None
    before = _fingerprint(connection, schema)
    statements = []

    def capture(connection, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(connection, "before_cursor_execute", capture)
    try:
        if error is None:
            assert validate_pg16_notification_identity_check(connection, deadline=monotonic() + 10) is True
        else:
            with pytest.raises(PG16InboxCheckError, match=f"^notification_inbox_pg16_check_{error}$"):
                validate_pg16_notification_identity_check(connection, deadline=monotonic() + 10)
    finally:
        event.remove(connection, "before_cursor_execute", capture)
    assert statements and all(statement.lstrip().upper().startswith("SELECT") for statement in statements)
    assert connection.get_transaction() is transaction
    assert connection.in_transaction()
    assert _fingerprint(connection, schema) == before


def _replace_check(connection, expression, *, not_valid=False):
    _sql(connection, f'ALTER TABLE notification_read_states DROP CONSTRAINT "{GUARD}"')
    suffix = " NOT VALID" if not_valid else ""
    # Expressions are fixed test-source literals, never request or private data.
    _sql(connection, f'ALTER TABLE notification_read_states ADD CONSTRAINT "{GUARD}" CHECK ({expression}){suffix}')


def test_native_m2_operations_guard_is_active_and_readonly_proof_passes(native_m2_database):
    engine, schema = native_m2_database
    with engine.begin() as connection:
        _sql(connection, "SET TRANSACTION READ ONLY")
        _observe(connection, schema)
        assert _sql(connection, "SHOW transaction_read_only") == [("on",)]
    with engine.begin() as connection:
        before = _fingerprint(connection, schema)
        for actor, notice in (("", "notice-a"), ("reader-a", "")):
            with pytest.raises(IntegrityError) as failure:
                with connection.begin_nested():
                    _sql(connection, """INSERT INTO notification_read_states(actor_id,notification_id,read_at)
                        VALUES (:actor,:notice,'2026-10-04 12:16:00')
                    """, {"actor": actor, "notice": notice})
            assert failure.value.orig.pgcode == "23514"
            assert failure.value.orig.diag.constraint_name == GUARD
        assert _fingerprint(connection, schema) == before
        _observe(connection, schema)


def test_native_missing_identity_check_refuses_without_repair(native_m2_database):
    engine, schema = native_m2_database
    with engine.begin() as connection:
        _sql(connection, f'ALTER TABLE notification_read_states DROP CONSTRAINT "{GUARD}"')
        assert _sql(connection, """SELECT count(*) FROM pg_catalog.pg_constraint
            WHERE conrelid='notification_read_states'::pg_catalog.regclass AND contype='c'
        """) == [(0,)]
        _observe(connection, schema, "guard_missing")


@pytest.mark.parametrize("expression", [
    "pg_catalog.length(actor_id)>0 OR pg_catalog.length(notification_id)>0",
    "pg_catalog.length(actor_id)>0 AND pg_catalog.length(read_at::text)>0",
], ids=["or", "other-field"])
def test_native_changed_check_semantics_refuse(native_m2_database, expression):
    engine, schema = native_m2_database
    with engine.begin() as connection:
        _replace_check(connection, expression)
        _observe(connection, schema, "guard_invalid")


def test_native_not_valid_identity_check_refuses(native_m2_database):
    engine, schema = native_m2_database
    with engine.begin() as connection:
        _replace_check(connection, CANONICAL, not_valid=True)
        assert _sql(connection, """SELECT convalidated FROM pg_catalog.pg_constraint
            WHERE conrelid='notification_read_states'::pg_catalog.regclass AND conname=:guard
        """, {"guard": GUARD}) == [(False,)]
        _observe(connection, schema, "guard_invalid")


def test_native_own_schema_same_named_length_cannot_replace_builtin_proof(native_m2_database):
    engine, schema = native_m2_database
    with engine.begin() as connection:
        own = _quoted(connection, schema)
        _sql(connection, f"""CREATE FUNCTION {own}.length(text) RETURNS integer
            LANGUAGE SQL IMMUTABLE STRICT AS 'SELECT 1'
        """)
        own_oid = _sql(connection, """SELECT p.oid FROM pg_catalog.pg_proc p
            JOIN pg_catalog.pg_namespace n ON n.oid=p.pronamespace
            WHERE n.nspname=:schema AND p.proname='length' AND p.proargtypes::text='25'
        """, {"schema": schema})[0][0]
        assert own_oid != 1317
        _replace_check(connection, f"{own}.length(actor_id::text)>0 AND pg_catalog.length(notification_id)>0")
        tree = _sql(connection, """SELECT pg_catalog.substr(conbin::text,1,8192)
            FROM pg_catalog.pg_constraint
            WHERE conrelid='notification_read_states'::pg_catalog.regclass AND conname=:guard
        """, {"guard": GUARD})[0][0]
        # Native OID occurrence is only fixture setup evidence; acceptance must
        # use the actual adapter's complete AST plus real catalog semantics.
        assert f":funcid {own_oid} " in tree
        _sql(connection, """INSERT INTO notification_read_states(actor_id,notification_id,read_at)
            VALUES ('','notice-a','2026-10-04 12:17:00')
        """)
        assert _sql(connection, "SELECT actor_id FROM notification_read_states WHERE actor_id=''") == [("",)]
        _observe(connection, schema, "guard_invalid")


def test_native_same_named_view_is_not_the_selected_base_relation(native_m2_database):
    engine, schema = native_m2_database
    with engine.begin() as connection:
        _sql(connection, "ALTER TABLE notification_read_states RENAME TO original_notification_read_states")
        _sql(connection, "CREATE VIEW notification_read_states AS SELECT * FROM original_notification_read_states")
        assert _sql(connection, """SELECT relkind FROM pg_catalog.pg_class
            WHERE oid=pg_catalog.to_regclass('notification_read_states')
        """) == [("v",)]
        _observe(connection, schema, "catalog_invalid")


def test_native_wrong_selected_schema_cannot_borrow_visible_business_table(native_m2_database):
    engine, schema = native_m2_database
    with engine.begin() as connection:
        own_oid = _sql(connection, "SELECT pg_catalog.to_regclass('notification_read_states')::oid")[0][0]
        _sql(connection, f"SET LOCAL search_path=pg_catalog,{_quoted(connection, schema)}")
        assert _sql(connection, "SELECT pg_catalog.current_schema()") == [("pg_catalog",)]
        assert _sql(connection, "SELECT pg_catalog.to_regclass('notification_read_states')::oid") == [(own_oid,)]
        _observe(connection, schema, "catalog_invalid")


def test_native_connection_temp_shadow_cannot_borrow_main_guard(native_m2_database):
    engine, schema = native_m2_database
    with engine.begin() as connection:
        own_oid = _sql(connection, "SELECT pg_catalog.to_regclass('notification_read_states')::oid")[0][0]
        _sql(connection, "CREATE TEMP TABLE notification_read_states(dummy TEXT) ON COMMIT DROP")
        context = _sql(connection, """SELECT pg_catalog.current_schema(),
            pg_catalog.to_regclass('notification_read_states')::oid
        """)[0]
        assert context[0] == schema
        assert context[1] != own_oid
        _observe(connection, schema, "catalog_invalid")
