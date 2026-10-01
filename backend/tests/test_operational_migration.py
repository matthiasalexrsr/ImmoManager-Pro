"""Real SQLite downgrade guards on the actual j1 Alembic operations."""
from datetime import date
from importlib import import_module

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, select

from backend.db.operational_models import (
    OperationalDispatchORM,
    OperationalLockORM,
    OperationalOccurrenceORM,
    OperationalScheduleORM,
    OperationalTickORM,
)

migration = import_module("backend.db.migrations.versions.j1a2b3c4d5e6_operational_schedule")
tables = (OperationalLockORM, OperationalScheduleORM, OperationalOccurrenceORM,
          OperationalDispatchORM, OperationalTickORM)


@pytest.mark.parametrize("model,values", [
    (OperationalScheduleORM, dict(id="task:sentinel", source_kind="task", source_id="sentinel",
        anchor_date=date(2026, 1, 31), recurrence_rule="FREQ=MONTHLY")),
    (OperationalOccurrenceORM, dict(key="a" * 64, schedule_id="task:sentinel",
        occurrence_date=date(2026, 2, 28), target_kind="task", target_id="sentinel")),
    (OperationalDispatchORM, dict(key="b" * 64, notification_id="sentinel",
        family="escalation", entity_type="task", entity_id="sentinel")),
    (OperationalTickORM, dict(id="sentinel", as_of=date(2026, 2, 28), result={"tasks_created": 1})),
])
def test_each_history_table_blocks_downgrade_without_dropping_tables(tmp_path, model, values):
    engine = create_engine(f"sqlite:///{tmp_path / 'history.db'}")
    try:
        with engine.begin() as connection:
            with Operations.context(MigrationContext.configure(connection)):
                migration.upgrade()
            connection.execute(model.__table__.insert().values(**values))
        with engine.begin() as connection:
            with Operations.context(MigrationContext.configure(connection)):
                with pytest.raises(RuntimeError, match="history exists"):
                    migration.downgrade()
            assert {model.__tablename__ for model in tables} <= set(inspect(connection).get_table_names())
            assert len(connection.execute(select(model)).all()) == 1
    finally:
        engine.dispose()


def test_empty_operational_migration_can_downgrade_and_upgrade_again(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'empty.db'}")
    try:
        with engine.begin() as connection:
            with Operations.context(MigrationContext.configure(connection)):
                migration.upgrade()
                migration.downgrade()
                assert not set(inspect(connection).get_table_names())
                migration.upgrade()
            assert connection.execute(select(OperationalLockORM.id)).scalars().all() == [1]
    finally:
        engine.dispose()
