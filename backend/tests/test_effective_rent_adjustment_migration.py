"""Run the frozen pricing migration on actual historical Alembic schemas."""

import sqlite3
from contextlib import closing
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory

ROOT = Path(__file__).resolve().parents[2]
BEFORE = "j1a2b3c4d5e6"
HEAD = "k1a2b3c4d5e6"
INDEX = "uq_applied_rent_adjustment_contract_date"


@pytest.fixture
def migrated_database(tmp_path, monkeypatch):
    database = tmp_path / "synthetic-price-migration.db"
    monkeypatch.setenv("DATABASE_URL", "sqlite:///" + database.as_posix())
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "backend/db/migrations"))
    return config, database


def insert_rules(database, *, duplicate=False):
    with closing(sqlite3.connect(database)) as db:
        # A historical schema migration must operate on referentially valid
        # data, including when a later migration audits all foreign keys.
        stamp = "2025-01-01"
        db.execute("INSERT INTO portfolios (id,name,currency,timezone,status,created_at,updated_at) "
                   "VALUES ('p','Synthetic','EUR','Europe/Berlin','active',?,?)", (stamp, stamp))
        db.execute("INSERT INTO properties (id,portfolio_id,name,property_type,status,created_at,updated_at) "
                   "VALUES ('h','p','Synthetic','residential','active',?,?)", (stamp, stamp))
        db.execute("INSERT INTO units (id,property_id,label,unit_type,status,created_at,updated_at) "
                   "VALUES ('u','h','Synthetic','apartment','occupied',?,?)", (stamp, stamp))
        db.execute("INSERT INTO tenants (id,full_name,created_at,updated_at,archived) "
                   "VALUES ('t','Synthetic',?,?,0)", (stamp, stamp))
        db.execute("INSERT INTO contracts (id,contract_number,property_id,unit_id,tenant_id,start_date,status,created_at,updated_at) "
                   "VALUES ('synthetic','Synthetic','h','u','t','2025-01-01','active',?,?)", (stamp, stamp))
        for row_id, status in (("a", "applied"), ("b", "applied" if duplicate else "pending")):
            db.execute("INSERT INTO rent_adjustments (id,contract_id,adjustment_type,effective_date,previous_rent,"
                       "new_rent,status,created_at,updated_at) VALUES (?, 'synthetic', 'stepped', '2025-02-01',"
                       "500, 600, ?, '2025-01-01', '2025-01-01')", (row_id, status))
        db.commit()


def test_fresh_chain_has_one_head_and_repeat_upgrade_preserves_rules(migrated_database):
    config, database = migrated_database
    scripts = ScriptDirectory.from_config(config)
    heads = scripts.get_heads()
    assert len(heads) == 1
    assert HEAD in {revision.revision for revision in scripts.iterate_revisions(heads[0], "base")}
    command.upgrade(config, "head")
    insert_rules(database)
    with closing(sqlite3.connect(database)) as db:
        expected = db.execute("SELECT * FROM rent_adjustments ORDER BY id").fetchall()
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("UPDATE rent_adjustments SET status='applied' WHERE id='b'")
    command.downgrade(config, BEFORE)
    command.upgrade(config, "head")
    with closing(sqlite3.connect(database)) as db:
        assert db.execute("SELECT * FROM rent_adjustments ORDER BY id").fetchall() == expected
        assert db.execute("SELECT name FROM sqlite_master WHERE type='index' AND name=?", (INDEX,)).fetchone()


def test_conflicting_historical_rules_fail_before_schema_marker_or_data_changes(migrated_database):
    config, database = migrated_database
    command.upgrade(config, BEFORE)
    insert_rules(database, duplicate=True)
    with closing(sqlite3.connect(database)) as db:
        expected = db.execute("SELECT * FROM rent_adjustments ORDER BY id").fetchall()
    with pytest.raises(RuntimeError, match="Ambiguous applied rent adjustments.*No rows are deleted"):
        command.upgrade(config, "head")
    with closing(sqlite3.connect(database)) as db:
        assert db.execute("SELECT * FROM rent_adjustments ORDER BY id").fetchall() == expected
        assert db.execute("SELECT version_num FROM alembic_version").fetchone() == (BEFORE,)
        assert not db.execute("SELECT name FROM sqlite_master WHERE type='index' AND name=?", (INDEX,)).fetchone()
