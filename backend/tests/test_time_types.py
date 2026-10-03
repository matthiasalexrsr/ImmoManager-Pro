"""Pure UTC bind and DDL compatibility; no application or database connection."""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import Column, DateTime, MetaData, Table
from sqlalchemy.dialects import postgresql, sqlite
from sqlalchemy.schema import CreateTable

from backend.db.time_types import UTCNaiveDateTime


@pytest.mark.parametrize("offset", [-5, 0, 2])
def test_aware_bind_keeps_instant_and_microseconds(offset):
    value = datetime(2026, 1, 1, 12, 0, 0, 123456, tzinfo=timezone(timedelta(hours=offset)))
    result = UTCNaiveDateTime().process_bind_param(value, None)
    assert result == value.astimezone(timezone.utc).replace(tzinfo=None)
    assert result.tzinfo is None and result.microsecond == 123456


def test_naive_and_absent_binds_are_not_reinterpreted():
    value = datetime(2026, 1, 1, 12, 0, 0, 123456)
    assert UTCNaiveDateTime().process_bind_param(value, None) is value
    assert UTCNaiveDateTime().process_bind_param(None, None) is None


@pytest.mark.parametrize("dialect", [sqlite.dialect(), postgresql.dialect()])
def test_physical_type_compilation_is_identical(dialect):
    def ddl(kind):
        return str(CreateTable(Table("change_history", MetaData(), Column("changed_at", kind, nullable=False))).compile(dialect=dialect))
    assert ddl(DateTime()) == ddl(UTCNaiveDateTime())


@pytest.mark.parametrize("value", [datetime.min.replace(tzinfo=timezone(timedelta(hours=2))),
                                   datetime.max.replace(tzinfo=timezone(timedelta(hours=-2)))])
def test_utc_overflow_is_not_capped(value):
    with pytest.raises(ValueError, match="UTC-Zeitpunkt"):
        UTCNaiveDateTime().process_bind_param(value, None)
