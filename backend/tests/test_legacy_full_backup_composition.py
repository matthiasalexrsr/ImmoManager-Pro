"""The real unchanged full container must carry exactly proven old schemas."""

import sqlite3
from contextlib import closing
from dataclasses import replace

import pytest

from backend.legacy_sqlite_upgrade.schema import catalog, catalog_hash, inspect_legacy_sqlite
from backend.services.full_recovery import _database_info, create_full_backup, restore_full_backup
from backend.services.recovery_archive import RecoveryError
from backend.tests.test_full_recovery import PASSPHRASE
from backend.tests.test_full_recovery import plan as plan
from backend.tests.test_full_recovery import runtime_template as runtime_template
from backend.tests.test_legacy_sqlite_schema_proof import legacy as legacy


def _copy_original_columns(source, target):
    with closing(sqlite3.connect(source)) as original, closing(sqlite3.connect(target)) as old:
        # Reconstruct synthetic old rows only, then validate real native FKs.
        # This new empty fixture must reproduce a snapshot, not replay live
        # source-revision triggers while loading its historical parent rows.
        triggers = old.execute("SELECT name,sql FROM sqlite_master WHERE type='trigger'").fetchall()
        for name, _ in triggers:
            old.execute('DROP TRIGGER "' + name.replace('"', '""') + '"')
        names = [row[0] for row in old.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        for name in names:
            quoted = '"' + name.replace('"', '""') + '"'
            columns = [row[1] for row in old.execute(f"PRAGMA table_info({quoted})")]
            fields = ",".join('"' + column.replace('"', '""') + '"' for column in columns)
            rows = original.execute(f"SELECT {fields} FROM {quoted}").fetchall()
            old.executemany(f"INSERT INTO {quoted} ({fields}) VALUES ({','.join('?' for _ in columns)})", rows)
        for _, sql in triggers:
            old.execute(sql)
        old.commit()
        assert old.execute("PRAGMA foreign_key_check").fetchall() == []


def test_actual_full_backup_restore_preserves_exact_proven_legacy_catalog_and_rows(legacy, plan, tmp_path):
    database, profile_id, reference = legacy
    _copy_original_columns(plan.database, database)
    original = database.read_bytes()
    values = dict(plan.configuration, DATABASE_URL="sqlite:///" + database.as_posix())
    selected = replace(plan, database=database, configuration=values)
    proof = inspect_legacy_sqlite(database)
    assert proof.profile_id == profile_id
    before = _database_info(database)
    archive, target = tmp_path / "old-complete.immobak", tmp_path / "restored-old"
    create_full_backup(selected, archive, PASSPHRASE, offline=True)
    result = restore_full_backup(archive, target, PASSPHRASE)
    assert result["signing_key_rotated"] is True
    restored = target / "database.sqlite3"
    assert _database_info(restored) == before
    assert inspect_legacy_sqlite(restored) == proof
    with closing(sqlite3.connect(restored)) as connection:
        assert catalog_hash(catalog(connection)) == reference["schema_sha256"]
        assert connection.execute("SELECT COUNT(*) FROM payment_reversals").fetchone()[0] == 1
    assert (target / "uploads" / "proof.bin").read_bytes() == (plan.uploads / "proof.bin").read_bytes()
    assert (target / "integrations.json").read_bytes() == plan.integration_state.read_bytes()
    assert database.read_bytes() == original


@pytest.mark.parametrize("damage", ["guard", "index"])
def test_changed_legacy_catalog_cannot_use_missing_column_exception(legacy, plan, tmp_path, damage):
    database, _, _ = legacy
    _copy_original_columns(plan.database, database)
    with closing(sqlite3.connect(database)) as connection:
        if damage == "index":
            connection.execute("DROP INDEX idx_payments_booking")
            connection.execute("CREATE INDEX idx_payments_booking ON payments(id DESC)")
        else:
            trigger = connection.execute("SELECT name FROM sqlite_master WHERE type='trigger' AND name LIKE '%lifecycle%' LIMIT 1").fetchone()[0]
            connection.execute('DROP TRIGGER "' + trigger + '"')
            connection.execute('CREATE TRIGGER "' + trigger + '" BEFORE DELETE ON contract_lifecycle_commands BEGIN SELECT 1; END')
        connection.commit()
    original = database.read_bytes()
    selected = replace(plan, database=database)
    archive = tmp_path / "not-published.immobak"
    with pytest.raises(RecoveryError):
        create_full_backup(selected, archive, PASSPHRASE, offline=True)
    assert not archive.exists()
    assert database.read_bytes() == original
