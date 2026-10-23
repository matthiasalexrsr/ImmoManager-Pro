"""The assigned additive revision preserves every preexisting SQLite table value."""
from alembic import command
from sqlalchemy import create_engine, inspect

from backend.db.schema_state import alembic_config


def test_bank_revision_is_additive_and_originals_are_guarded(tmp_path):
    url = f"sqlite:///{(tmp_path / 'migration.db').as_posix()}"
    config = alembic_config(url)
    command.upgrade(config, 'd73f2b9a041c')
    engine = create_engine(url)
    with engine.begin() as connection:
        connection.exec_driver_sql("INSERT INTO portfolios (id,name,currency,timezone,status,created_at,updated_at) VALUES ('bank-pf','Umlaut ä','EUR','Europe/Berlin','active','2026-01-01','2026-01-01')")
        old = {name: connection.exec_driver_sql(f'SELECT * FROM "{name}"').fetchall()
               for name in inspect(connection).get_table_names() if name != 'alembic_version'}
    command.upgrade(config, 'e160a1b2c301')
    with engine.connect() as connection:
        for name, values in old.items():
            assert connection.exec_driver_sql(f'SELECT * FROM "{name}"').fetchall() == values
        assert {'bank_imports', 'bank_source_links', 'bank_fints_sessions'}.issubset(inspect(connection).get_table_names())
        assert connection.exec_driver_sql('SELECT version_num FROM alembic_version').scalar_one() == 'e160a1b2c301'
        triggers = {row[0] for row in connection.exec_driver_sql("SELECT name FROM sqlite_master WHERE type='trigger'")}
        assert {'bank_original_update', 'bank_original_delete', 'bank_link_update', 'bank_link_delete'} <= triggers
    # Simulate the DDL being present while the revision stamp was not committed.
    command.stamp(config, 'd73f2b9a041c')
    command.upgrade(config, 'e160a1b2c301')
    with engine.connect() as connection:
        for name, values in old.items():
            assert connection.exec_driver_sql(f'SELECT * FROM "{name}"').fetchall() == values
    engine.dispose()
