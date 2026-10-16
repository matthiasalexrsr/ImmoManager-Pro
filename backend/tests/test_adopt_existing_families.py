"""No permissive stamps or silent weakening of existing table constraints.

Only isolated SQLite memory engines and synthetic schemas are involved.
"""
from typing import cast

import pytest
from sqlalchemy import Table, create_engine, text

from backend.db.daily_models import (
    DailyCommandORM,
    DailySessionORM,
    DailyStateORM,
    NumberReservationORM,
    SettingRuleORM,
)
from backend.db.migrations.adopt_existing import adopt_exact_family
from backend.db.orm_models import Base

SETTINGS = (DailyStateORM, DailyCommandORM, SettingRuleORM)
SESSIONS = (DailySessionORM, NumberReservationORM)


def test_exact_current_create_all_family_can_be_adopted_without_writing_any_rows():
    engine = create_engine("sqlite:///:memory:")
    try:
        Base.metadata.create_all(engine)
        with engine.connect() as connection:
            assert adopt_exact_family(connection, SETTINGS)
            assert adopt_exact_family(connection, SESSIONS)
            assert connection.execute(text("SELECT COUNT(*) FROM daily_commands")).scalar() == 0
    finally:
        engine.dispose()


def test_partial_family_is_rejected_instead_of_creating_missing_tables():
    engine = create_engine("sqlite:///:memory:")
    try:
        cast(Table, DailyStateORM.__table__).create(engine)
        with engine.connect() as connection:
            with pytest.raises(RuntimeError, match="Partial private table family"):
                adopt_exact_family(connection, SETTINGS)
            assert connection.execute(text("SELECT COUNT(*) FROM daily_user_state")).scalar() == 0
    finally:
        engine.dispose()


def test_unexpected_column_is_not_mistaken_for_current_schema():
    engine = create_engine("sqlite:///:memory:")
    try:
        Base.metadata.create_all(engine)
        with engine.begin() as connection:
            connection.execute(text("ALTER TABLE daily_user_state ADD COLUMN unreviewed_payload TEXT"))
            with pytest.raises(RuntimeError, match="columns differ"):
                adopt_exact_family(connection, SETTINGS)
            assert "unreviewed_payload" in {
                row[1] for row in connection.exec_driver_sql("PRAGMA table_info(daily_user_state)")
            }
    finally:
        engine.dispose()


def test_missing_required_index_is_rejected_before_mutation():
    engine = create_engine("sqlite:///:memory:")
    try:
        Base.metadata.create_all(engine)
        with engine.begin() as connection:
            connection.execute(text("DROP INDEX ix_daily_auth_sessions_owner_id"))
            with pytest.raises(RuntimeError, match="indexes differ"):
                adopt_exact_family(connection, SESSIONS)
            assert connection.execute(text("SELECT COUNT(*) FROM daily_auth_sessions")).scalar() == 0
    finally:
        engine.dispose()
