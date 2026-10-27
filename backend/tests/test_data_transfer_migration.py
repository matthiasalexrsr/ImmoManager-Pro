from importlib import import_module

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, insert, text

from backend.db.orm_models import Base
from backend.services.data_transfer.backup import verify


def test_existing_complete_schema_adopted_but_missing_unique_constraint_rejected(tmp_path):
    migration = import_module("backend.db.migrations.versions.b4c6d8e0f2a5_data_transfer")
    engine = create_engine(f"sqlite:///{tmp_path / 'migration.db'}")
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
        connection.execute(text("DROP TABLE data_external_references"))
        table = next(table for table in migration.tables() if table.name == "data_external_references")
        from sqlalchemy import UniqueConstraint
        for constraint in tuple(table.constraints):
            if isinstance(constraint, UniqueConstraint):
                table.constraints.remove(constraint)
        table.create(connection)
        with Operations.context(MigrationContext.configure(connection)), pytest.raises(RuntimeError, match="uniqueness"):
            migration.upgrade()
    engine.dispose()


def test_corrupt_retained_import_source_refuses_backup_verification(tmp_path):
    from datetime import datetime

    from backend.db.data_transfer_models import ImportBatchORM, ImportFileORM
    engine = create_engine(f"sqlite:///{tmp_path / 'source.db'}")
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(insert(ImportBatchORM), dict(id="batch", portfolio_id=None, source_system="test", format="snapshot", created_by="owner",
            idempotency_key="x" * 16, request_sha256="0" * 64, state="ready", revision=1, mappings={}, preview={}, target_sha256="0" * 64,
            plan_sha256="0" * 64, created_at=datetime.now(), updated_at=datetime.now()))
        connection.execute(insert(ImportFileORM), dict(id="file", batch_id="batch", filename="test.json", entity="snapshot", sha256="0" * 64, content=b"modified"))
        with pytest.raises(ValueError, match="checksum"):
            verify(connection)
    engine.dispose()
