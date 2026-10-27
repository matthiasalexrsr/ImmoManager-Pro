"""The additive migration preserves independently seeded old rows and its graph."""
from importlib import import_module
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory


def test_revision_is_the_assigned_child_and_not_a_new_root():
    root = Path(__file__).resolve().parents[2]
    config = Config(str(root / "alembic.ini"))
    config.set_main_option("script_location", str(root / "backend/db/migrations"))
    scripts = ScriptDirectory.from_config(config)
    revision = scripts.get_revision("e160a1b2c306")
    assert revision.down_revision == "d73f2b9a041c"
    assert scripts.get_revision("d73f2b9a041c") is not None


def test_additive_upgrade_preserves_legacy_values_and_installs_history_guards():
    engine = sa.create_engine("sqlite:///:memory:")
    migration = import_module("backend.db.migrations.versions.e160a1b2c306_document_work")
    with engine.begin() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        connection.exec_driver_sql("CREATE TABLE portfolios (id TEXT PRIMARY KEY, name TEXT)")
        connection.exec_driver_sql("CREATE TABLE documents (id TEXT PRIMARY KEY, title TEXT)")
        connection.exec_driver_sql("CREATE TABLE handover_protocols (id TEXT PRIMARY KEY, contract_id TEXT, unit_id TEXT)")
        connection.exec_driver_sql("INSERT INTO portfolios VALUES ('p1','Altbestand ÄÖÜ')")
        connection.exec_driver_sql("INSERT INTO documents VALUES ('d1','Original § 14')")
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
        assert connection.exec_driver_sql("SELECT * FROM portfolios").all() == [('p1', 'Altbestand ÄÖÜ')]
        assert connection.exec_driver_sql("SELECT * FROM documents").all() == [('d1', 'Original § 14')]
        assert connection.exec_driver_sql("SELECT count(*) FROM document_work_events").scalar_one() == 0
        connection.exec_driver_sql("INSERT INTO document_work_events "
            "(id,document_id,portfolio_id,actor_id,kind,resource_id,revision,command_key,fingerprint,payload,created_at) "
            "VALUES ('e1','d1','p1','u1','archive','r1',1,'k1','hash','{}','2026-10-16')")
        with pytest.raises(sa.exc.IntegrityError, match="immutable"):
            connection.exec_driver_sql("UPDATE document_work_events SET payload='{}' WHERE id='e1'")
        with pytest.raises(sa.exc.IntegrityError, match="immutable"):
            connection.exec_driver_sql("DELETE FROM document_work_events")
    engine.dispose()
