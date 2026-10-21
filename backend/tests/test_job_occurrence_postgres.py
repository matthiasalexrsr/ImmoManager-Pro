"""Real PostgreSQL upgrade, stable occurrence keys and guarded rollback."""
import pytest
import sqlalchemy as sa
from alembic import command
from sqlalchemy.orm import Session
from test_document_versions_postgres import postgres  # noqa: F401

from backend.services.jobs.core import SqlLedger


def test_occurrence_upgrade_preserves_short_keys_and_accepts_full_dunning_identity(postgres):  # noqa: F811
    engine, config = postgres
    command.downgrade(config, 'a5c7e9b1d3f5')
    with Session(engine) as session, session.begin():
        assert SqlLedger(session).record('dunning:test', 'v1', 'already-processed', 'proposed')
    command.upgrade(config, 'head')
    long_key = '12345678-1234-1234-1234-123456789012:2:12345678-1234-1234-1234-123456789013'
    with Session(engine) as session, session.begin():
        ledger = SqlLedger(session)
        assert not ledger.record('dunning:test', 'v1', 'already-processed', 'proposed')
        assert ledger.record('dunning:test', 'v1', long_key, 'proposed')
        assert not ledger.record('dunning:test', 'v1', long_key, 'proposed')
    with pytest.raises(RuntimeError, match='longer than 64'):
        command.downgrade(config, 'a5c7e9b1d3f5')
    with engine.connect() as connection:
        assert connection.execute(sa.text('SELECT version_num FROM alembic_version')).scalar() == 'c7e9a1b3d5f7'
        assert connection.execute(sa.text('SELECT count(*) FROM job_occurrences')).scalar() == 2
