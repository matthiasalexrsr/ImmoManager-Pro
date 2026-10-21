"""Widen occurrence identities without losing idempotency or prior SQLite rows."""
from datetime import datetime

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session
from test_migrations import migrate  # noqa: F401

from backend.db.job_models import JobOccurrenceORM
from backend.services.jobs.core import SqlLedger

PREVIOUS = 'a5c7e9b1d3f5'
LONG_KEY = '12345678-1234-1234-1234-123456789012:2:12345678-1234-1234-1234-123456789013'


def test_sqlite_upgrade_preserves_existing_long_keys_and_refuses_lossy_downgrade(migrate):  # noqa: F811
    path = migrate(PREVIOUS)
    engine = sa.create_engine(f'sqlite:///{path}')
    try:
        with Session(engine) as session, session.begin():
            session.add(JobOccurrenceORM(rule_key='dunning:test', rule_version='v1', occurrence_key=LONG_KEY,
                                         status='proposed', created_at=datetime(2026, 10, 21)))
        migrate()
        with Session(engine) as session, session.begin():
            ledger = SqlLedger(session)
            assert not ledger.record('dunning:test', 'v1', LONG_KEY, 'proposed')
            assert ledger.record('dunning:test', 'v1', 'next:' + 'x' * 200, 'proposed')
            assert not ledger.record('dunning:test', 'v1', 'next:' + 'x' * 200, 'proposed')
        with pytest.raises(RuntimeError, match='longer than 64'):
            migrate.downgrade(PREVIOUS)
        with engine.connect() as connection:
            assert connection.execute(sa.text('SELECT version_num FROM alembic_version')).scalar() == migrate.head
            assert connection.execute(sa.text('SELECT count(*) FROM job_occurrences')).scalar() == 2
        assert isinstance(sa.inspect(engine).get_columns('job_occurrences')[2]['type'], sa.Text)
    finally:
        engine.dispose()


def test_empty_occurrence_ledger_can_be_downgraded_and_upgraded(migrate):  # noqa: F811
    path = migrate()
    migrate.downgrade(PREVIOUS)
    migrate()
    with sa.create_engine(f'sqlite:///{path}').connect() as connection:
        assert connection.execute(sa.text('SELECT count(*) FROM job_occurrences')).scalar() == 0
