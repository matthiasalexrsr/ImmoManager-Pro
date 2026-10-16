"""Every retained PRO family blocks destructive rollback before any DDL."""

from importlib import import_module

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations


@pytest.mark.parametrize('revision,table', [
    ('e160a1b2c301_bank_imports', 'bank_imports'),
    ('e160a1b2c302_financial_sources', 'receivable_settlements'),
    ('e160a1b2c304_communication', 'communication_items'),
    ('e160a1b2c305_daily_receipts_settings', 'daily_user_state'),
    ('e180a1b2c307_daily_sessions_numbers', 'daily_number_reservations'),
    ('e160a1b2c306_document_work', 'document_work_events'),
    ('e160a1b2c307_teha_receive', 'teha_receive_items'),
    ('e160a1b2c308_channels', 'channel_cases'),
    ('e160a1b2c314_platform', 'storage_bindings'),
])
def test_retained_rows_are_rejected_before_any_schema_or_bytes_are_removed(revision, table):
    migration = import_module('backend.db.migrations.versions.' + revision)
    engine = sa.create_engine('sqlite:///:memory:')
    original = b'UNCHANGED ORIGINAL\x00\xff'
    with engine.begin() as connection:
        # Minimal independent storage oracle, unrelated to runtime serialization.
        connection.exec_driver_sql(f'CREATE TABLE {table}(id TEXT PRIMARY KEY, original BLOB)')
        connection.exec_driver_sql(f'INSERT INTO {table} VALUES (?,?)', ('retained', original))
        with pytest.raises(RuntimeError), Operations.context(MigrationContext.configure(connection)):
            migration.downgrade()
        assert connection.exec_driver_sql(f'SELECT original FROM {table}').scalar_one() == original
        assert table in sa.inspect(connection).get_table_names()
    engine.dispose()
