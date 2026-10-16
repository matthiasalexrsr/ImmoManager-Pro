"""Upgrade a private connection without rewriting pre-existing evidence or configuration."""

from datetime import datetime
from typing import cast

import pytest
from alembic import command
from sqlalchemy import Table, create_engine, inspect, select

from backend.db import schema_state
from backend.db.integration_attempt_models import IntegrationActionAttemptORM
from backend.db.integration_connection_models import IntegrationActionRunORM, IntegrationConnectionORM

PREVIOUS = "d73f2b9a041c"
NEW_HEAD = "e160a1b2c300"


def test_private_connection_upgrade_preserves_exact_existing_state_and_refuses_lossy_rollback(tmp_path):
    url = f"sqlite:///{(tmp_path / 'only-synthetic-upgrade.sqlite3').as_posix()}"
    command.upgrade(schema_state.alembic_config(url), PREVIOUS)
    engine = create_engine(url)
    try:
        before = {"id": "synthetic-connection", "provider_id": "proof", "name": "Inventur Alt",
                  "enabled": False, "is_default": False, "archived": False, "revision": 3,
                  "config_token": "synthetic-encrypted-config-preserve-exactly",
                  "secret_refs": {"future_secret": "synthetic-secret-id"}, "legacy_source_hash": "a" * 64,
                  "created_by": "synthetic-actor", "created_at": datetime(2026, 10, 15),
                  "updated_at": datetime(2026, 10, 15)}
        with engine.begin() as db:
            db.execute(cast(Table, IntegrationConnectionORM.__table__).insert(), before)
        prior = schema_state.inspect_url(url)
        assert prior.revision == PREVIOUS and prior.needs_upgrade
        previous_bytes = engine.connect()
        try:
            original = dict(previous_bytes.execute(select(IntegrationConnectionORM.__table__)).mappings().one())
        finally:
            previous_bytes.close()
        _old, new = schema_state.run_migrations(url)
        assert new.revision == NEW_HEAD and new.can_start
        tables = set(inspect(engine).get_table_names())
        assert {"integration_action_attempts", "integration_run_cursors"} <= tables
        with engine.connect() as db:
            assert dict(db.execute(select(IntegrationConnectionORM.__table__)).mappings().one()) == original
        # Explicitly retained attempt evidence makes a destructive downgrade illegal.
        run = {"id": "synthetic-run", "connection_id": before["id"], "actor_id": "synthetic-actor",
               "command_key": "synthetic-once", "fingerprint": "b" * 64, "action": "check",
               "effect": "read", "state": "prepared", "config_revision": 3,
               "source_kind": None, "source_id": None, "source_revision": None,
               "config_snapshot_token": "synthetic-snapshot", "action_manifest_token": "synthetic-contract",
               "request_token": "synthetic-request", "request_sha256": "c" * 64,
               "checkpoint_token": None, "result_token": None, "result_sha256": None,
               "result_bytes": 0, "result_blocks": 0, "lease_token": None, "lease_until": None,
               "attempts": 1, "revision": 2, "safe_summary": "Nur lokale Migrationsprüfung",
               "created_at": datetime(2026, 10, 16), "updated_at": datetime(2026, 10, 16)}
        attempt = {"id": "synthetic-attempt", "run_id": run["id"], "number": 1,
                   "actor_id": "synthetic-actor", "lease_sha256": "d" * 64,
                   "request_sha256": "c" * 64, "input_token": "synthetic-protected-input",
                   "state": "started", "success": None, "manifest_token": None,
                   "result_sha256": None, "result_bytes": 0, "result_blocks": 0,
                   "detached": False, "reviewed_by": None, "reviewed_at": None,
                   "created_at": datetime(2026, 10, 16), "finished_at": None}
        with engine.begin() as db:
            db.execute(cast(Table, IntegrationActionRunORM.__table__).insert(), run)
            db.execute(cast(Table, IntegrationActionAttemptORM.__table__).insert(), attempt)
        with pytest.raises(RuntimeError, match="Retained provider-attempt evidence"):
            command.downgrade(schema_state.alembic_config(url), PREVIOUS)
        with engine.connect() as db:
            assert db.scalar(select(IntegrationActionAttemptORM.id)) == "synthetic-attempt"
            assert dict(db.execute(select(IntegrationConnectionORM.__table__)).mappings().one()) == original
        assert schema_state.inspect_url(url).revision == NEW_HEAD
    finally:
        engine.dispose()
