"""Back up the supported receipt schema before the required offline upgrade."""
import hashlib
import sqlite3

import pytest

from backend.services.full_recovery import _database_info, create_full_backup, restore_full_backup
from backend.services.recovery_archive import RecoveryError
from backend.tests import test_full_recovery as recovery_fixtures
from backend.tests.test_bank_matching_schema_recovery import migrate

PASSPHRASE = recovery_fixtures.PASSPHRASE
plan = recovery_fixtures.plan
runtime_template = recovery_fixtures.runtime_template


def legacy(plan):
    url = "sqlite:///" + plan.database.as_posix()
    # The owned fixture is created from current ORM metadata. Apply the real
    # downgrade to its supported predecessor, retaining existing rent receipts.
    stamped = migrate(url, "stamp", "w1a2b3c4d5e6")
    assert stamped.returncode == 0, stamped.stderr
    downgraded = migrate(url, "downgrade", "v1a2b3c4d5e6")
    assert downgraded.returncode == 0, downgraded.stderr


def test_actual_pre_w1_schema_backups_and_restores_before_upgrade(plan, tmp_path):
    legacy(plan)
    before = _database_info(plan.database)
    assert before["rows"]["payments"] > 0 and before["rows"]["payment_reversals"] > 0
    archive = tmp_path / "legacy.immobak"
    create_full_backup(plan, archive, PASSPHRASE, offline=True)
    restored = tmp_path / "restored"
    restore_full_backup(archive, restored, PASSPHRASE)
    with sqlite3.connect(restored / "database.sqlite3") as db:
        assert "invoice_id" not in {row[1] for row in db.execute("PRAGMA table_info(payments)")}
        assert "amount_paid" not in {row[1] for row in db.execute("PRAGMA table_info(invoices)")}
        for table in ("payments", "payment_reversals", "bookings", "receivables", "invoices"):
            assert db.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == before["rows"][table]
        assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert not db.execute("PRAGMA foreign_key_check").fetchall()
    original = plan.uploads / "proof.bin"
    copied = restored / "uploads" / "proof.bin"
    assert hashlib.sha256(original.read_bytes()).digest() == hashlib.sha256(copied.read_bytes()).digest()


def test_unrelated_missing_invoice_column_is_not_accepted_as_legacy(plan):
    legacy(plan)
    with sqlite3.connect(plan.database) as db:
        db.execute("ALTER TABLE invoices DROP COLUMN payment_terms")
    with pytest.raises(RecoveryError, match="Datenbankschema"):
        _database_info(plan.database)


def test_missing_invoice_table_is_not_accepted_as_missing_additive_columns(plan):
    legacy(plan)
    with sqlite3.connect(plan.database) as db:
        db.execute("DROP TABLE invoices")
    with pytest.raises(RecoveryError, match="Datenbankschema"):
        _database_info(plan.database)
