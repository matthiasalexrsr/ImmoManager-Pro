"""Frozen additive migration from d73, checked independently of runtime table creation."""
from importlib import import_module
from typing import cast

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import Table, create_engine, inspect, select

from backend.db.orm_models import Base, PortfolioORM


def test_teha_migration_preserves_predecessor_values_and_enforces_immutability(tmp_path):
    migration = import_module('backend.db.migrations.versions.e160a1b2c307_teha_receive')
    assert migration.revision == 'e160a1b2c307'
    assert migration.down_revision == 'd73f2b9a041c'
    engine = create_engine('sqlite:///' + (tmp_path / 'migration.sqlite').as_posix())
    old_tables = [table for table in Base.metadata.sorted_tables if not table.name.startswith('teha_')]
    Base.metadata.create_all(engine, tables=old_tables)
    with engine.begin() as connection:
        connection.execute(cast(Table, PortfolioORM.__table__).insert().values(id='old-portfolio', name='Altbestand ä', currency='EUR', timezone='Europe/Berlin', status='active'))
        before = dict(connection.execute(select(PortfolioORM.__table__)).mappings().one())
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
        assert dict(connection.execute(select(PortfolioORM.__table__)).mappings().one()) == before
        assert {'teha_receive_batches', 'teha_receive_items', 'teha_mappings', 'teha_publication_receipts'} <= set(inspect(connection).get_table_names())
        triggers = {row[0] for row in connection.exec_driver_sql("SELECT name FROM sqlite_master WHERE type='trigger'")}
        assert {'teha_receive_items_update', 'teha_publication_receipts_update', 'teha_receive_items_delete', 'teha_publication_receipts_delete'} <= triggers
        with pytest.raises(Exception):
            with Operations.context(MigrationContext.configure(connection)):
                migration.upgrade()  # no silent adoption/repair of an unknown TEHA layout
    engine.dispose()
