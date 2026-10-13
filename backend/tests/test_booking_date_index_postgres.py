"""Real PostgreSQL date-index checks, discovered by the mandatory no-skip gate."""

from test_booking_date_index import _exercise_migration
from test_postgres_money_migration import postgres_money_db  # noqa: F401


def test_date_index_upgrade_downgrade_and_actual_finance_plan(postgres_money_db):  # noqa: F811
    engine, config = postgres_money_db
    _exercise_migration(engine, config)
