"""Actual Alembic chain and offline validation, not a mocked table list."""

import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend import auth
from backend.repositories.sql_store import SQLAlchemyStore
from backend.services import operational_jobs as service
from backend.services.operational_job_types import JobCommand, JobCreate
from backend.services.operational_job_validation import (
    JobIntegrityError,
    reset_restored_job_claims,
    validate_job_journal,
)

ROOT = Path(__file__).resolve().parents[2]


def test_actual_migration_and_nonempty_downgrade_guard(tmp_path, monkeypatch):
    database = tmp_path / "own-jobs.db"
    environment = dict(os.environ, DATABASE_URL="sqlite:///" + database.as_posix(), PYTHONUTF8="1")
    upgraded = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=ROOT, env=environment,
                              capture_output=True, text=True, timeout=90)
    assert upgraded.returncode == 0, upgraded.stderr
    monkeypatch.setattr(auth, "get_user_by_id", lambda identifier: dict(id="actor", role="verwalter", is_active=True, portfolio_access="all"))
    engine = create_engine("sqlite:///" + database.as_posix())
    try:
        with Session(engine) as db:
            store = SQLAlchemyStore(db)
            created = service.create_job(store, JobCreate(idempotency_key="migration", as_of="2026-11-05"), "actor")
            service.cancel_job(store, created["id"], JobCommand(idempotency_key="retained-cancel", expected_revision=created["revision"]), "actor")
        with engine.connect() as connection:
            assert validate_job_journal(connection)
        with sqlite3.connect(database) as connection:
            with pytest.raises(sqlite3.IntegrityError):
                connection.execute("UPDATE operational_work_items SET result='{}' WHERE kind='command'")
            connection.rollback()
            assert validate_job_journal(connection)
    finally:
        engine.dispose()
    downgraded = subprocess.run([sys.executable, "-m", "alembic", "downgrade", "a2a2b3c4d5e6"], cwd=ROOT, env=environment,
                                capture_output=True, text=True, timeout=90)
    assert downgraded.returncode != 0 and "erase retained operational work" in downgraded.stderr


def test_completely_absent_legacy_schema_is_accepted_and_partial_is_rejected():
    with sqlite3.connect(":memory:") as connection:
        assert validate_job_journal(connection) is False
        assert reset_restored_job_claims(connection) == 0
        connection.execute("CREATE TABLE operational_jobs (id TEXT)")
        with pytest.raises(JobIntegrityError, match="schema_incomplete"):
            reset_restored_job_claims(connection)
