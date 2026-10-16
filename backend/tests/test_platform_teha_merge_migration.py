"""Real Alembic merge of two independent additive interface histories.

No old revision is modified and populated SQLite evidence cannot be partially
downgraded. Only a new synthetic QA database is used.
"""
from typing import cast

import pytest
from alembic import command
from sqlalchemy import Table, create_engine, inspect, select, text

from backend.db import schema_state
from backend.db.access_models import PluginInstallationORM
from backend.db.orm_models import LoginAttemptORM

HEAD = "e1f0a1b2c315"


def test_real_merge_upgrade_preserves_old_rows_and_blocks_partial_downgrade(tmp_path):
    url = f"sqlite:///{(tmp_path / 'synthetic-merge.sqlite').as_posix()}"
    command.upgrade(schema_state.alembic_config(url), "d73f2b9a041c")
    engine = create_engine(url)
    try:
        with engine.begin() as connection:
            connection.execute(
                text("INSERT INTO login_attempts(id,username,attempted_at,success) "
                     "VALUES ('test-preserved','fixture','2026-10-15',0)")
            )
        with engine.connect() as connection:
            assert connection.scalar(select(LoginAttemptORM.username).where(
                LoginAttemptORM.id == "test-preserved")) == "fixture"
        command.upgrade(schema_state.alembic_config(url), "head")
        assert schema_state.head_revision() == HEAD
        status = schema_state.inspect_url(url)
        assert status.revision == HEAD and status.can_start
        with engine.connect() as connection:
            tables = set(inspect(connection).get_table_names())
            assert {"teha_receive_batches", "teha_receive_items", "teha_publication_receipts",
                    "plugin_installations", "storage_bindings", "integration_action_attempts"} <= tables
            assert connection.scalar(select(LoginAttemptORM.username).where(
                LoginAttemptORM.id == "test-preserved")) == "fixture"
        with engine.begin() as connection:
            connection.execute(cast(Table, PluginInstallationORM.__table__).insert(), {
                "name": "synthetic",
                "revision": 1,
                "enabled": False,
                "manifest": {"test": True},
                "payload": {"retained": "original"},
                "backups": [],
                "commands": {},
            })
        with pytest.raises(RuntimeError, match="partial downgrade"):
            command.downgrade(schema_state.alembic_config(url), "e1f0a1b2c314")
        with engine.connect() as connection:
            assert connection.scalar(select(PluginInstallationORM.revision)
                                     .where(PluginInstallationORM.name == "synthetic")) == 1
            assert connection.scalar(select(LoginAttemptORM.username).where(
                LoginAttemptORM.id == "test-preserved")) == "fixture"
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == HEAD
    finally:
        engine.dispose()
