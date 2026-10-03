"""Real h2 DDL and native query plans; complete g2->h2 chain is composition-owned."""
# ruff: noqa: F811

from datetime import date, datetime
from importlib import import_module

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, insert, inspect, text

from backend.db.operational_scheduler_models import OperationalSchedulerORM  # noqa: F401
from backend.db.orm_models import Base, TaskORM
from backend.tests.test_private_server_concurrency import postgres_database as postgres_database

migration = import_module("backend.db.migrations.versions.h2a2b3c4d5e6_scheduler_progress_indices")


def exercise(connection):
    connection.execute(insert(TaskORM).values(id="retained-index-source", title="Synthetic preserved source",
        due_date=date(2026, 1, 1), priority="medium", status="open", created_at=datetime(2026, 1, 1), updated_at=datetime(2026, 1, 1)))
    with Operations.context(MigrationContext.configure(connection)):
        # Explicit test installation starts with registered model indices.
        migration.downgrade()
        for name, table, _ in migration.INDICES:
            assert name not in {value["name"] for value in inspect(connection).get_indexes(table)}
        migration.upgrade()
        migration.upgrade()  # Older create-table migrations use current metadata.
        for name, table, columns in migration.INDICES:
            index = next(value for value in inspect(connection).get_indexes(table) if value["name"] == name)
            assert index["column_names"] == columns
    assert connection.execute(text("SELECT title FROM tasks WHERE id='retained-index-source'")).scalar_one() == "Synthetic preserved source"


def test_sqlite_real_h2_preserves_sources_and_uses_bounded_indices(tmp_path):
    engine = create_engine("sqlite:///" + str(tmp_path / "scheduler-index.sqlite"))
    try:
        Base.metadata.create_all(engine)
        with engine.begin() as connection:
            exercise(connection)
            series = connection.exec_driver_sql("EXPLAIN QUERY PLAN SELECT id FROM operational_work_items "
                "WHERE action_key='recurring_task:source' AND planned_revision='revision' AND state='done' ORDER BY created_at DESC,id DESC LIMIT 1").all()
            children = connection.exec_driver_sql("EXPLAIN QUERY PLAN SELECT id FROM tasks "
                "WHERE parent_task_id='source' AND due_date='2026-01-01' ORDER BY id LIMIT 1").all()
            assert "ix_scheduler_completed_source" in str(series) and "ix_scheduler_task_due" in str(children)
    finally:
        engine.dispose()


def test_postgres_real_h2_preserves_sources_and_creates_both_indices(postgres_database):
    engine, _, _, _ = postgres_database
    with engine.begin() as connection:
        exercise(connection)


def test_sqlite_h2_refuses_same_name_with_wrong_index_shape(tmp_path):
    engine = create_engine("sqlite:///" + str(tmp_path / "wrong-index.sqlite"))
    try:
        Base.metadata.create_all(engine)
        with engine.begin() as connection, Operations.context(MigrationContext.configure(connection)):
            name, table, _ = migration.INDICES[0]
            connection.exec_driver_sql('DROP INDEX "' + name + '"')
            connection.exec_driver_sql('CREATE INDEX "' + name + '" ON "' + table + '" (source_id)')
            with pytest.raises(RuntimeError, match="unexpected definition"):
                migration.upgrade()
    finally:
        engine.dispose()
