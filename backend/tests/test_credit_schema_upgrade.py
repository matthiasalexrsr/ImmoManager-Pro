"""Real stopped SQLite upgrades and rollback, with a protected pre-DDL snapshot."""

import sqlite3
from contextlib import contextmanager
from pathlib import Path

import pytest
from alembic import command
from sqlalchemy import event, inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from backend import credit_schema_upgrade as tool
from backend.repositories.sql_store import SQLAlchemyStore
from backend.services import credit_ledger as credit
from backend.tests.test_bank_payments import bank_booking
from backend.tests.test_credit_ledger import credit_scenario, payout
from backend.tests.test_credit_migration import current_orm_read_compatibility, migrate


def legacy(tmp_path, monkeypatch):
    _, engine = migrate(tmp_path, monkeypatch)
    with engine.begin() as db:
        db.execute(text("DROP TABLE alembic_version"))
        db.execute(text("CREATE TRIGGER retained_booking_trigger BEFORE DELETE ON bookings BEGIN SELECT 1; END"))
    return Path(engine.url.database), engine


def state(engine):
    with engine.connect() as db:
        return db.execute(text("SELECT name, sql FROM sqlite_master ORDER BY name")).all()


def test_stopped_upgrade_preserves_rows_trigger_links_and_private_previous_database(tmp_path, monkeypatch):
    path, engine = legacy(tmp_path, monkeypatch)
    current_orm_read_compatibility(engine)
    with Session(engine) as db:
        active = SQLAlchemyStore(db)
        source, contract, _, charge = credit_scenario(active, monkeypatch)
        bank = bank_booking(active, charge, -100)
    before = state(engine)
    backup = tmp_path / "before-credit.sqlite"
    assert tool.upgrade_legacy_sqlite(path, backup, offline=True)["backup_created"]
    with sqlite3.connect(backup.as_uri() + "?mode=ro", uri=True) as db:
        assert db.execute("SELECT name, sql FROM sqlite_master ORDER BY name").fetchall() == before
        assert db.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        assert db.execute("SELECT rent_charge_id, amount, invoice_id FROM payments").fetchall() == [(charge.id, 700, None)]
    with Session(engine) as db:
        active = SQLAlchemyStore(db)
        receipt = credit.create_receipt(active, payout(source, "60", method="bank", booking_id=bank.id))
        assert receipt.contract_id == contract.id and active.get_booking(bank.id).allocated_amount == 60
        assert db.execute(text("PRAGMA foreign_key_check")).first() is None
        assert db.execute(text("SELECT 1 FROM sqlite_master WHERE name='retained_booking_trigger'")).scalar() == 1
    # Running again preserves a populated immutable journal.
    tool.upgrade_legacy_sqlite(path, tmp_path / "second.sqlite", offline=True)
    with engine.connect() as db:
        assert db.execute(text("SELECT id FROM credit_receipts")).scalar() == receipt.id
        assert {row["name"] for row in inspect(db).get_indexes("bookings")}
    engine.dispose()


def test_explicit_stop_existing_output_and_versioned_database_fail_before_any_ddl(tmp_path, monkeypatch):
    path, engine = legacy(tmp_path, monkeypatch)
    before = state(engine)
    backup = tmp_path / "before.sqlite"
    with pytest.raises(tool.CreditUpgradeError, match="offline_required"):
        tool.upgrade_legacy_sqlite(path, backup)
    assert not backup.exists() and state(engine) == before
    backup.write_bytes(b"NEVER OVERWRITE")
    with pytest.raises(tool.CreditUpgradeError, match="snapshot_exists"):
        tool.upgrade_legacy_sqlite(path, backup, offline=True)
    assert backup.read_bytes() == b"NEVER OVERWRITE"
    with engine.begin() as db:
        db.execute(text("CREATE TABLE alembic_version(version_num TEXT PRIMARY KEY)"))
        db.execute(text("INSERT INTO alembic_version VALUES ('m1a2b3c4d5e6')"))
    with pytest.raises(tool.CreditUpgradeError, match="database_versioned"):
        tool.upgrade_legacy_sqlite(path, tmp_path / "versioned.sqlite", offline=True)
    assert not (tmp_path / "versioned.sqlite").exists()
    engine.dispose()


def test_actual_partial_ddl_failure_rolls_back_everything_and_keeps_previous_snapshot(tmp_path, monkeypatch):
    path, engine = legacy(tmp_path, monkeypatch)
    before = state(engine)
    migration = tool.import_module("backend.db.migrations.versions.n1a2b3c4d5e6_credit_receipt_journal")
    original = migration._allocation_check
    def fail_after_rebuild(expression):
        original(expression)
        raise RuntimeError("DO NOT LEAK PRIVATE DATABASE DETAILS")
    monkeypatch.setattr(migration, "_allocation_check", fail_after_rebuild)
    backup = tmp_path / "failure.sqlite"
    with pytest.raises(tool.CreditUpgradeError, match="upgrade_failed") as error:
        tool.upgrade_legacy_sqlite(path, backup, offline=True)
    assert "PRIVATE" not in str(error.value) and state(engine) == before
    with sqlite3.connect(backup) as db:
        assert db.execute("SELECT name, sql FROM sqlite_master ORDER BY name").fetchall() == before
    engine.dispose()


def test_other_writer_after_completed_snapshot_aborts_without_ddl(tmp_path, monkeypatch):
    path, engine = legacy(tmp_path, monkeypatch)
    before = state(engine)
    original = tool.protected_new_file
    @contextmanager
    def interleave(destination):
        with original(destination) as output:
            yield output
        with sqlite3.connect(path) as db:
            db.execute("CREATE TABLE other_writer(value TEXT)")
    monkeypatch.setattr(tool, "protected_new_file", interleave)
    with pytest.raises(tool.CreditUpgradeError, match="database_changed"):
        tool.upgrade_legacy_sqlite(path, tmp_path / "raced.sqlite", offline=True)
    after = state(engine)
    assert [row for row in after if row[0] != "other_writer"] == before
    assert not any(row[0].startswith("_alembic") for row in after)
    engine.dispose()


def test_cli_actionable_error_does_not_expose_exception_data(tmp_path, monkeypatch, capsys):
    path, engine = legacy(tmp_path, monkeypatch)
    def fail(*_, **__):
        raise tool.CreditUpgradeError("database_busy")
    monkeypatch.setattr(tool, "upgrade_legacy_sqlite", fail)
    assert tool.main(["--database", str(path), "--backup-output", str(tmp_path / "cli.sqlite"), "--offline"]) == 2
    assert "Schreiber stoppen" in capsys.readouterr().err
    engine.dispose()


def test_versioned_alembic_failure_after_real_ddl_restores_schema_and_version(tmp_path, monkeypatch):
    config, engine = migrate(tmp_path, monkeypatch)
    before = state(engine)
    def fail_after_real_ddl(_, __, statement, ___, ____, _____):
        if "create table credit_reversals" in " ".join(statement.lower().replace('"', "").split()):
            raise RuntimeError("synthetic post-DDL failure")
    event.listen(Engine, "after_cursor_execute", fail_after_real_ddl)
    try:
        with pytest.raises(RuntimeError, match="post-DDL"):
            command.upgrade(config, "n1a2b3c4d5e6")
    finally:
        event.remove(Engine, "after_cursor_execute", fail_after_real_ddl)
    assert state(engine) == before
    with engine.connect() as db:
        assert db.execute(text("SELECT version_num FROM alembic_version")).scalar() == "m1a2b3c4d5e6"
        assert db.execute(text("PRAGMA foreign_key_check")).first() is None
    engine.dispose()
