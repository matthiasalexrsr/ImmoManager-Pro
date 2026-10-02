"""Actual Alembic downgrades preserve unposted billing evidence and revisions."""

import sqlite3
from contextlib import closing
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory

ROOT = Path(__file__).resolve().parents[2]
BEFORE_BILLING = "f0a1b2c3d4e5"
BILLING_HEAD = "h1a2b3c4d5e6"


@pytest.fixture
def migration_database(tmp_path, monkeypatch):
    database = tmp_path / "isolated-migration.db"
    monkeypatch.setenv("DATABASE_URL", "sqlite:///" + database.as_posix())
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "backend" / "db" / "migrations"))
    return config, database


def _state(database):
    """Include every schema object and row, including the revision marker."""
    with closing(sqlite3.connect(database)) as db:
        schema = tuple(db.execute("SELECT type, name, tbl_name, sql FROM sqlite_master ORDER BY type, name"))
        tables = [row[1] for row in schema if row[0] == "table"]
        rows = {}
        for name in tables:
            quoted = '"' + name.replace('"', '""') + '"'
            rows[name] = tuple(sorted(db.execute("SELECT * FROM " + quoted).fetchall(), key=repr))
        return schema, rows


def _structure(database):
    """Batch ALTER may reformat CREATE SQL while preserving the actual schema."""
    with closing(sqlite3.connect(database)) as db:
        result = {}
        for (name,) in db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name").fetchall():
            quoted = '"' + name.replace('"', '""') + '"'
            columns = tuple(sorted(row[1:] for row in db.execute("PRAGMA table_info(" + quoted + ")")))
            foreign_keys = tuple(sorted(row[2:] for row in db.execute("PRAGMA foreign_key_list(" + quoted + ")")))
            indices = []
            for row in db.execute("PRAGMA index_list(" + quoted + ")").fetchall():
                index = '"' + row[1].replace('"', '""') + '"'
                indices.append((row[1:], tuple(db.execute("PRAGMA index_info(" + index + ")"))))
            result[name] = columns, foreign_keys, tuple(sorted(indices))
        return result


def _seed(database, *, statement_updates=None, period_updates=None):
    with closing(sqlite3.connect(database)) as db:
        db.execute(
            "INSERT INTO billing_periods "
            "(id, property_id, label, start_date, end_date, status, created_at, updated_at, revision_number) "
            "VALUES ('period', 'property', 'Historical proof', '2025-01-01', '2025-12-31', "
            "'draft', '2026-01-01', '2026-01-01', 1)"
        )
        db.execute(
            "INSERT INTO utility_statements "
            "(id, billing_period_id, contract_id, unit_id, total_cost, advance_paid, balance, "
            "status, created_at, updated_at) "
            "VALUES ('statement', 'period', 'contract', 'unit', 10, 4, 6, 'draft', '2026-01-01', '2026-01-01')"
        )
        for table, updates in (("utility_statements", statement_updates), ("billing_periods", period_updates)):
            for column, value in (updates or {}).items():
                # Column names come only from fixed test cases below.
                db.execute(f'UPDATE "{table}" SET "{column}" = ? WHERE id = ?',
                           (value, "statement" if table == "utility_statements" else "period"))
        db.commit()


def test_complete_empty_upgrade_downgrade_upgrade_has_one_head(migration_database):
    config, database = migration_database
    assert len(ScriptDirectory.from_config(config).get_heads()) == 1
    # This gate verifies the frozen billing migration's own rollback contract.
    # Later feature revisions intentionally require full-backup recovery.
    command.upgrade(config, BILLING_HEAD)
    before_rows, before_structure = _state(database)[1], _structure(database)
    command.downgrade(config, BEFORE_BILLING)
    command.upgrade(config, BILLING_HEAD)
    assert _state(database)[1] == before_rows
    assert _structure(database) == before_structure


@pytest.mark.parametrize("statement_updates,period_updates", [
    ({"advance_details": '[{"rent_charge_id":"month", "receipt_ids":["receipt-proof"]}]'}, None),
    ({"advance_details": "[]"}, None),
    ({"calculation_hash": "saved-calculation-hash"}, None),
    ({"source_statement_id": "original-statement"}, None),
    ({"status": "finalized"}, None),
    ({"status": "delivered"}, None),
    ({"status": "disputed"}, None),
    (None, {"source_period_id": "original-period"}),
    (None, {"revision_number": 2}),
    (None, {"revision_notes": "Invoice correction"}),
    (None, {"status": "finalized"}),
    (None, {"status": "delivered"}),
    (None, {"status": "disputed"}),
    (None, {"status": "corrected"}),
    (None, {"owner_cost_share": '{"total_amount":20}'}),
])
def test_unposted_evidence_refuses_downgrade_before_any_mutation(
    migration_database, statement_updates, period_updates,
):
    config, database = migration_database
    command.upgrade(config, BILLING_HEAD)
    _seed(database, statement_updates=statement_updates, period_updates=period_updates)
    before = _state(database)
    with pytest.raises(RuntimeError, match="history exists|evidence exists|snapshots exist"):
        command.downgrade(config, BEFORE_BILLING)
    assert _state(database) == before


def test_posted_settlement_refuses_before_owner_or_evidence_columns_change(migration_database):
    config, database = migration_database
    command.upgrade(config, BILLING_HEAD)
    _seed(database)
    with closing(sqlite3.connect(database)) as db:
        db.execute(
            "INSERT INTO billing_settlements "
            "(id,billing_period_id,statement_id,root_statement_id,contract_id,signed_amount,kind,status,created_at) "
            "VALUES ('settlement','period','statement','statement','contract',-6,'credit','credit_available','2026-01-01')"
        )
        db.commit()
    before = _state(database)
    with pytest.raises(RuntimeError, match="settlement history exists"):
        command.downgrade(config, BEFORE_BILLING)
    assert _state(database) == before


def test_finalized_statement_without_settlement_keeps_actual_receipt_evidence(migration_database):
    config, database = migration_database
    command.upgrade(config, BILLING_HEAD)
    _seed(database, statement_updates={
        "status": "finalized",
        "advance_details": '[{"receipt_ids":["real-payment-id"], "legacy_undated_paid":0}]',
        "calculation_hash": "immutable-financial-snapshot",
    }, period_updates={"status": "finalized"})
    before = _state(database)
    assert before[1]["billing_settlements"] == ()
    with pytest.raises(RuntimeError, match="statement evidence exists"):
        command.downgrade(config, BEFORE_BILLING)
    assert _state(database) == before


def test_feature_completion_revision_refuses_schema_loss_before_any_mutation(migration_database):
    config, database = migration_database
    command.upgrade(config, "i2a2b3c4d5e6")
    before = _state(database)
    with pytest.raises(RuntimeError, match="preserved|history exists|evidence exists|snapshots exist"):
        command.downgrade(config, BEFORE_BILLING)
    assert _state(database) == before
