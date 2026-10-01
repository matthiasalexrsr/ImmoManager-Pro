"""Full Alembic chain and pre-DDL evidence preservation, never a user database."""

import sqlite3
from contextlib import closing

import pytest
from alembic import command
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect

from backend.db.tax_models import AnnualTaxProfileORM, AnnualTaxProjectionORM, AnnualTaxSourceORM
from backend.tests.test_billing_migration_guards import _state, _structure
from backend.tests.test_billing_migration_guards import migration_database as migration_database  # noqa: F401 fixture


def test_real_full_chain_has_single_tax_head_and_empty_roundtrip(migration_database):
    config, path = migration_database
    directory = ScriptDirectory.from_config(config)
    assert len(directory.get_heads()) == 1
    assert directory.get_revision("s1a2b3c4d5e6").down_revision == "r1a2b3c4d5e6"
    command.upgrade(config, "s1a2b3c4d5e6")
    engine = create_engine("sqlite:///" + path.as_posix())
    try:
        schema = inspect(engine)
        for model in (AnnualTaxProfileORM, AnnualTaxProjectionORM, AnnualTaxSourceORM):
            assert {column["name"] for column in schema.get_columns(model.__tablename__)} == set(model.__table__.c.keys())
            assert schema.get_foreign_keys(model.__tablename__)
        before = _structure(path)
        command.downgrade(config, "r1a2b3c4d5e6")
        assert "annual_tax_profiles" not in inspect(engine).get_table_names()
        command.upgrade(config, "s1a2b3c4d5e6")
        assert _structure(path) == before
    finally:
        engine.dispose()


@pytest.mark.parametrize("table", ["annual_tax_profiles", "annual_tax_projections", "annual_tax_sources"])
def test_each_tax_evidence_table_blocks_downgrade_before_any_schema_or_data_change(migration_database, table):
    config, path = migration_database
    command.upgrade(config, "s1a2b3c4d5e6")
    # Even pre-existing orphan/corrupt evidence must not silently disappear.
    # sqlite3's separate connection leaves FKs disabled only for this fixture.
    with closing(sqlite3.connect(path)) as db:
        if table == "annual_tax_profiles":
            db.execute("INSERT INTO annual_tax_profiles VALUES ('version','portfolio',2024,NULL,'actor:key','actor','{}',?, '2025-01-01')", ("a" * 64,))
        elif table == "annual_tax_projections":
            db.execute("INSERT INTO annual_tax_projections VALUES ('snapshot','portfolio',2024,'version',NULL,'portfolio:2024','actor:key','actor','{}','{}',?, '2025-01-01')", ("a" * 64,))
        else:
            db.execute("INSERT INTO annual_tax_sources VALUES ('source','portfolio','snapshot','bank-evidence',1,'{}',?)", ("a" * 64,))
        db.commit()
    before = _state(path)
    with pytest.raises(RuntimeError, match="downgrade would erase review/source evidence"):
        command.downgrade(config, "r1a2b3c4d5e6")
    assert _state(path) == before
