"""Prepared native M2 Operations proofs; no active head/chain acceptance claim."""

import importlib.util
import os
from datetime import datetime
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import Column, DateTime, MetaData, String, Table, create_engine, event, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError

from backend.db.notification_inbox_models import NotificationReadStateORM
from backend.services.notification_inbox_validation import validate_notification_inbox_database

PROPOSAL = (Path(__file__).resolve().parents[1] / "db/migrations/proposals"
            / "m2a2b3c4d5e6_personal_notification_reads.py")


def _proposal():
    specification = importlib.util.spec_from_file_location("prepared_personal_inbox_m2", PROPOSAL)
    assert specification is not None and specification.loader is not None
    module = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(module)
    return module


@pytest.fixture(params=["sqlite", "postgresql"], ids=["sqlite", "postgresql"])
def proposal_database(request, tmp_path):
    admin = None
    schema = None
    if request.param == "postgresql":
        source = os.getenv("TEST_SERVER_DATABASE_URL")
        if not source:
            pytest.fail("M2 PostgreSQL proof requires explicit disposable TEST_SERVER_DATABASE_URL")
        url = make_url(source)
        if url.get_backend_name() != "postgresql":
            pytest.fail("M2 PostgreSQL proof requires a PostgreSQL URL")
        schema = "notification_inbox_m2_" + uuid4().hex
        admin = create_engine(url, hide_parameters=True)
        with admin.begin() as connection:
            connection.exec_driver_sql(f'CREATE SCHEMA "{schema}"')
        engine = create_engine(url.update_query_dict({"options": "-csearch_path=" + schema}),
                               hide_parameters=True)
    else:
        engine = create_engine("sqlite:///" + (tmp_path / "native-m2.sqlite").as_posix(),
                               hide_parameters=True)

        @event.listens_for(engine, "connect")
        def foreign_keys(connection, record):
            connection.execute("PRAGMA foreign_keys=ON")

    try:
        metadata = MetaData()
        users = Table("users", metadata, Column("id", String(), primary_key=True))
        notices = Table("notifications", metadata, Column("id", String(), primary_key=True),
                        Column("status", String(), nullable=False), Column("read_at", DateTime()))
        with engine.begin() as connection:
            if schema is not None:
                assert connection.scalar(text("SELECT current_schema()")) == schema
            metadata.create_all(connection)
            connection.execute(users.insert(), [{"id": "reader-a"}, {"id": "reader-b"}])
            connection.execute(notices.insert(), [
                {"id": "global-read", "status": "read", "read_at": datetime(2026, 10, 2, 12)},
                {"id": "global-unread", "status": "unread", "read_at": None},
            ])
        yield engine
    finally:
        engine.dispose()
        if admin is not None:
            try:
                with admin.begin() as connection:
                    connection.exec_driver_sql(f'DROP SCHEMA "{schema}" CASCADE')
            finally:
                admin.dispose()


def _run(engine, name):
    with engine.begin() as connection:
        with Operations.context(MigrationContext.configure(connection)):
            getattr(_proposal(), name)()


def _shape(connection):
    schema = inspect(connection)
    return {
        "columns": [(column["name"], str(column["type"].compile(dialect=connection.dialect)),
                     column["nullable"], column["default"])
                    for column in schema.get_columns("notification_read_states")],
        "pk": schema.get_pk_constraint("notification_read_states")["constrained_columns"],
        "fks": sorted((item["constrained_columns"][0], item["referred_table"],
                       item["referred_columns"][0], item["options"]["ondelete"])
                      for item in schema.get_foreign_keys("notification_read_states")),
        "checks": [(item["name"], item["sqltext"])
                   for item in schema.get_check_constraints("notification_read_states")],
    }


def test_native_proposal_exact_shape_and_empty_down_up(proposal_database):
    engine = proposal_database
    module = _proposal()
    assert module.revision == "m2a2b3c4d5e6" and module.down_revision == "l2a2b3c4d5e6"
    assert PROPOSAL.parent.name == "proposals"
    _run(engine, "upgrade")
    with engine.connect() as connection:
        before = _shape(connection)
        model = NotificationReadStateORM.__table__
        assert [(item[0], item[1], item[2]) for item in before["columns"]] == [
            (column.name, str(column.type.compile(dialect=connection.dialect)), column.nullable)
            for column in model.columns
        ]
        assert all(item[3] is None for item in before["columns"])
        assert before["pk"] == ["actor_id", "notification_id"]
        assert before["fks"] == [("actor_id", "users", "id", "CASCADE"),
                                  ("notification_id", "notifications", "id", "CASCADE")]
        # PG reflects casts/parentheses into the SQL expression. Verify the
        # actual named constraint here and native behavior separately below.
        assert [item[0] for item in before["checks"]] == ["ck_notification_read_identity"]
        assert validate_notification_inbox_database(connection)
    _run(engine, "downgrade")
    assert "notification_read_states" not in inspect(engine).get_table_names()
    _run(engine, "upgrade")
    with engine.connect() as connection:
        assert _shape(connection) == before


def test_native_proposal_rejects_existing_family_without_repair(proposal_database):
    engine = proposal_database
    _run(engine, "upgrade")
    with engine.connect() as connection:
        before = _shape(connection)
    with pytest.raises(RuntimeError, match="already exists"):
        _run(engine, "upgrade")
    with engine.connect() as connection:
        assert _shape(connection) == before


def test_native_personal_evidence_is_not_global_read_backfill_and_blocks_downgrade(proposal_database):
    engine = proposal_database
    with engine.connect() as connection:
        original = connection.execute(text("SELECT id,status,read_at FROM notifications ORDER BY id")).all()
    _run(engine, "upgrade")
    with engine.begin() as connection:
        assert connection.scalar(text("SELECT count(*) FROM notification_read_states")) == 0
        connection.execute(text("INSERT INTO notification_read_states VALUES (:actor,:notice,:time)"),
                           {"actor": "reader-a", "notice": "global-read", "time": datetime(2026, 10, 3, 12, 15)})
    with pytest.raises(RuntimeError, match="erase personal notification read evidence"):
        _run(engine, "downgrade")
    with engine.connect() as connection:
        assert connection.execute(text("SELECT id,status,read_at FROM notifications ORDER BY id")).all() == original
        assert connection.scalar(text("SELECT count(*) FROM notification_read_states")) == 1
        assert validate_notification_inbox_database(connection)


def test_native_personal_pair_uniqueness_and_both_parent_cascades(proposal_database):
    engine = proposal_database
    _run(engine, "upgrade")
    statement = text("INSERT INTO notification_read_states VALUES (:actor,:notice,:time)")
    values = {"actor": "reader-a", "notice": "global-read", "time": datetime(2026, 10, 3, 12, 15)}
    with engine.begin() as connection:
        connection.execute(statement, values)
    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(statement, values)
    with engine.begin() as connection:
        connection.execute(statement, {**values, "actor": "reader-b"})
        connection.execute(text("DELETE FROM users WHERE id='reader-a'"))
        assert connection.scalar(text("SELECT count(*) FROM notification_read_states")) == 1
        connection.execute(text("DELETE FROM notifications WHERE id='global-read'"))
        assert connection.scalar(text("SELECT count(*) FROM notification_read_states")) == 0


def test_native_required_read_fields_and_identity_guard(proposal_database):
    engine = proposal_database
    _run(engine, "upgrade")
    with engine.begin() as connection:
        # Real parents make the blank-identity denial a CHECK proof, not a FK denial.
        connection.execute(text("INSERT INTO users(id) VALUES ('')"))
        connection.execute(text("INSERT INTO notifications(id,status) VALUES ('','unread')"))
    values = {"actor": "reader-a", "notice": "global-read", "time": datetime(2026, 10, 3, 12, 15)}
    for change in ({"actor": ""}, {"notice": ""}, {"time": None}, {"actor": "missing-actor"}):
        with pytest.raises(IntegrityError):
            with engine.begin() as connection:
                connection.execute(text("INSERT INTO notification_read_states VALUES (:actor,:notice,:time)"),
                                   {**values, **change})
    with engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM notification_read_states")) == 0


def test_sqlite_downgrade_preserves_even_orphan_read_evidence(tmp_path):
    engine = create_engine("sqlite:///" + (tmp_path / "orphan-evidence.sqlite").as_posix())
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql("CREATE TABLE users(id VARCHAR PRIMARY KEY)")
            connection.exec_driver_sql("CREATE TABLE notifications(id VARCHAR PRIMARY KEY)")
        _run(engine, "upgrade")
        with engine.begin() as connection:
            # Deliberately corrupt untrusted synthetic image; declared native FKs remain.
            connection.exec_driver_sql("INSERT INTO notification_read_states VALUES ('absent-actor','absent-notice','2026-10-03 12:15:00')")
        with pytest.raises(RuntimeError, match="erase personal notification read evidence"):
            _run(engine, "downgrade")
        with engine.connect() as connection:
            assert connection.scalar(text("SELECT count(*) FROM notification_read_states")) == 1
    finally:
        engine.dispose()
