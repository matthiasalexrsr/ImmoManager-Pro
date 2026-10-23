"""Real PG coverage of the complete ORM adoption path and precise drift checks."""

import pytest
import sqlalchemy as sa
from alembic import command

from backend.db.orm_models import Base, PortfolioORM
from backend.tests.test_orm_adoption_head import exercise_complete_adoption
from backend.tests.test_postgres_money_migration import postgres_money_db as postgres_money_db


def test_complete_unversioned_postgres_orm_preserves_families_backfills_and_guards(postgres_money_db):
    engine, config = postgres_money_db
    exercise_complete_adoption(engine, config)


@pytest.mark.parametrize('mutation', [
    'ALTER TABLE daily_auth_sessions ALTER COLUMN id TYPE VARCHAR(120)',
    'ALTER TABLE document_work_events DROP CONSTRAINT document_work_events_pkey',
])
def test_postgres_unversioned_type_and_primary_key_drift_are_rejected_before_stamp(postgres_money_db, mutation):
    engine, config = postgres_money_db
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(sa.insert(PortfolioORM), {'id': 'preserved', 'name': 'Preserved original'})
        connection.exec_driver_sql(mutation)
    with pytest.raises(RuntimeError, match='Partial or altered current ORM adoption schema'):
        command.upgrade(config, 'head')
    with engine.connect() as connection:
        assert not sa.inspect(connection).has_table('alembic_version')
        assert connection.scalar(sa.text("SELECT name FROM portfolios WHERE id='preserved'")) == 'Preserved original'
