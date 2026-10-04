"""Whole-installation adoption; fixtures, keys and every byte are synthetic."""

import hashlib
import json
import os
import sqlite3
import subprocess
import sys
from contextlib import closing
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.backup_operations.plan import BackupOperationError
from backend.legacy_sqlite_upgrade import service
from backend.legacy_sqlite_upgrade.schema import catalog, inspect_legacy_sqlite, profiles
from backend.services.full_recovery import RecoveryLimits
from backend.tests.test_full_recovery import PASSPHRASE, runtime_template  # noqa: F401 — shared synthetic seed fixture

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(params=tuple(profiles()))
def legacy_installation(request, runtime_template, tmp_path):  # noqa: F811 — shared pytest fixture
    root = tmp_path / "synthetic-installation"
    root.mkdir()
    uploads = root / "uploads"
    uploads.mkdir()
    (uploads / "empty").mkdir()
    (uploads / "proof.bin").write_bytes((runtime_template / "uploads/proof.bin").read_bytes())
    (root / "integrations.json").write_bytes((runtime_template / "integrations.json").read_bytes())
    database = root / "runtime.sqlite"
    reference = profiles()[request.param]
    with closing(sqlite3.connect(database)) as target:
        for sql in reference["ddl"]:
            if service.normalized_kind(sql) in {"table", "index", "unique"}:
                target.execute(sql)
        with closing(sqlite3.connect((runtime_template / "runtime.db").as_uri() + "?mode=ro", uri=True)) as source:
            for name in reference["catalog"]["tables"]:
                columns = [row[1] for row in target.execute(f'PRAGMA table_info("{name}")')]
                fields = ",".join('"' + field + '"' for field in columns)
                rows = source.execute(f'SELECT {fields} FROM "{name}"').fetchall()
                if rows:
                    target.executemany(f'INSERT INTO "{name}"({fields}) VALUES ({",".join("?" for _ in columns)})', rows)
        now, expiry = "2026-10-03 08:30:00.000000", "2027-10-03 08:30:00.000000"
        target.execute("INSERT INTO auth_sessions(id,user_id,device_label,created_at,last_used_at,expires_at,generation,current_refresh_hash) VALUES (?,?,?,?,?,?,?,?)",
                       ("synthetic-session", "synthetic-user", "Synthetic original device", now, now, expiry, 1, "a" * 64))
        target.execute("INSERT INTO auth_refresh_tokens(token_hash,session_id,generation,expires_at) VALUES (?,?,?,?)",
                       ("a" * 64, "synthetic-session", 1, expiry))
        document = target.execute("SELECT id FROM documents LIMIT 1").fetchone()[0]
        prop, portfolio = target.execute("SELECT id,portfolio_id FROM properties LIMIT 1").fetchone()
        target.execute("INSERT INTO invoices(id,property_id,supplier,invoice_date,net_amount,vat_rate,vat_amount,gross_amount,status,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                       ("synthetic-legacy-paid", prop, "Synthetic historical supplier", "2026-09-01", 50.20, 0, 0, 50.20, "paid", now, now))
        target.execute("UPDATE documents SET property_id=? WHERE id=?", (prop, document))
        manifest_cursor = target.execute("SELECT * FROM documents WHERE id=?", (document,))
        metadata = dict(zip([column[0] for column in manifest_cursor.description], manifest_cursor.fetchone()))
        payload = b"%PDF-1.7\nSynthetic immutable original\x00\xff\n%%EOF"
        target.execute("INSERT INTO document_versions(id,document_id,portfolio_id,property_id,number,actor_id,idempotency_key,request_sha256,operation,comment,filename,media_type,sha256,size_bytes,metadata_snapshot,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            ("synthetic-original", document, portfolio, prop, 1, "synthetic-user", "original-command", "b" * 64,
             "archive_original", "Synthetic retained original", "original.pdf", "application/pdf", hashlib.sha256(payload).hexdigest(), len(payload), json.dumps(metadata), now))
        target.execute("INSERT INTO document_version_chunks(version_id,position,portfolio_id,data) VALUES (?,?,?,?)",
                       ("synthetic-original", 0, portfolio, payload))
        for sql in reference["ddl"]:
            if service.normalized_kind(sql) not in {"table", "index", "unique"}:
                target.execute(sql)
        target.commit()
    values = json.loads((runtime_template / "configuration-for-test.json").read_text(encoding="utf-8"))
    values.update(DATA_DIR=str(root), DATABASE_URL="sqlite:///" + database.as_posix(), UPLOADS_DIR=str(uploads),
                  INTEGRATION_STATE_FILE=str(root / "integrations.json"))
    (root / ".env").write_text("".join(key + "=" + value + "\n" for key, value in values.items()), encoding="utf-8")
    assert inspect_legacy_sqlite(database).profile_id == request.param
    args = SimpleNamespace(data_dir=root, database=None, uploads=None, integrations=None, offline=True,
                           output=tmp_path / "original-full.immobak", capacity_file=None, timeout_seconds=None)
    return args, database


def state(database):
    with closing(sqlite3.connect(database)) as connection:
        tables = connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name").fetchall()
        rows = {name: connection.execute(f'SELECT * FROM "{name}" ORDER BY rowid').fetchall() for (name,) in tables}
        return catalog(connection), rows


def test_real_archive_probe_adoption_and_checked_rollback_preserve_every_original(legacy_installation):
    args, database = legacy_installation
    if inspect_legacy_sqlite(database).profile_id == "release126-fresh-create-all":
        with closing(sqlite3.connect(database)) as connection:
            connection.execute("CREATE TABLE alembic_version(version_num VARCHAR(32) NOT NULL PRIMARY KEY)")
            connection.commit()
    original = state(database)
    files = {name: (args.data_dir / name).read_bytes() for name in (".env", "integrations.json", "uploads/proof.bin")}
    try:
        result = service.upgrade(args, PASSPHRASE, limits=RecoveryLimits(timeout_seconds=600))
    except service.LegacyUpgradeError as error:
        # These inputs are explicitly synthetic. Preserve the internal cause in
        # test diagnostics while the public maintenance command stays redacted.
        raise AssertionError("Synthetic adoption failed") from error.__context__
    assert result["backup_restore_verified"]
    assert result["review_status"] == "legacy_business_states_preserved_require_source_review"
    args.operation_id = result["operation_id"]
    assert service.status(args)["database_state"] == "upgraded"
    from sqlalchemy import create_engine, event
    from sqlalchemy.pool import NullPool

    from backend.db.runtime_schema import validate_runtime_schema
    readonly = create_engine("sqlite:///" + database.as_posix(), poolclass=NullPool)
    @event.listens_for(readonly, "connect")
    def enforce_readonly(connection, _record):
        connection.execute("PRAGMA query_only=ON")
    try:
        validate_runtime_schema(readonly)
    finally:
        readonly.dispose()
    with closing(sqlite3.connect(database)) as connection:
        assert connection.execute("SELECT revoked_at,revoke_reason FROM auth_sessions WHERE id='synthetic-session'").fetchone() == (None, None)
        assert connection.execute("SELECT COUNT(*) FROM payment_reversals").fetchone()[0] == 1
        assert connection.execute("SELECT status FROM invoices WHERE id='synthetic-legacy-paid'").fetchone() == ("paid",)
        assert connection.execute("SELECT COUNT(*) FROM payments WHERE invoice_id='synthetic-legacy-paid'").fetchone() == (0,)
        assert connection.execute("SELECT consumption_medium,consumption_unit FROM allocation_keys").fetchall() == []
        assert connection.execute("SELECT COUNT(*) FROM measurement_facts").fetchone() == (0,)
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    assert all((args.data_dir / name).read_bytes() == value for name, value in files.items())
    assert service.rollback(args)["status"] == "rolled_back"
    assert state(database) == original
    assert all((args.data_dir / name).read_bytes() == value for name, value in files.items())
    assert service.status(args)["database_state"] == "original"


def test_failure_after_native_ddl_rolls_back_without_losing_original(legacy_installation):
    args, database = legacy_installation
    before = state(database)
    def fail(phase):
        if phase == "transaction_prepared":
            raise RuntimeError("synthetic injected transaction abort")
    with pytest.raises(service.LegacyUpgradeError, match="legacy_upgrade_aborted"):
        service.upgrade(args, PASSPHRASE, limits=RecoveryLimits(timeout_seconds=600), _checkpoint=fail)
    assert args.output.is_file()
    assert state(database) == before
    operation = next((args.data_dir / ".legacy-sqlite-upgrade").iterdir()).name
    args.operation_id = operation
    assert service.status(args)["database_state"] == "original"


def test_active_native_installation_lease_blocks_before_configuration(legacy_installation, monkeypatch):
    args, database = legacy_installation
    with service.installation_lease(args.data_dir):
        monkeypatch.setattr(service, "_selected", lambda *_: pytest.fail("selection crossed a live lifetime fence"))
        with pytest.raises(BackupOperationError, match="installation_busy"):
            service.upgrade(args, PASSPHRASE)
    assert not args.output.exists()
    assert inspect_legacy_sqlite(database)


def test_unmanaged_native_writer_blocks_before_archive(legacy_installation):
    args, database = legacy_installation
    with closing(sqlite3.connect(database)) as writer:
        writer.execute("BEGIN IMMEDIATE")
        with pytest.raises(service.LegacyUpgradeError, match="legacy_database_busy"):
            service.upgrade(args, PASSPHRASE)
    assert not args.output.exists()
    assert inspect_legacy_sqlite(database)


@pytest.mark.parametrize("changed", ["business", "upload", "snapshot", "database"])
def test_checked_rollback_refuses_newer_data_or_replaced_return_resources(legacy_installation, changed):
    args, database = legacy_installation
    result = service.upgrade(args, PASSPHRASE, limits=RecoveryLimits(timeout_seconds=600))
    args.operation_id = result["operation_id"]
    if changed == "business":
        with closing(sqlite3.connect(database)) as connection:
            connection.execute("UPDATE portfolios SET name='Synthetic new business write'")
            connection.commit()
    elif changed == "upload":
        (args.data_dir / "uploads/proof.bin").write_bytes(b"Synthetic newer original")
    elif changed == "database":
        clone = database.with_name("synthetic-cloned-database.sqlite")
        with closing(sqlite3.connect(database)) as source, closing(sqlite3.connect(clone)) as destination:
            source.backup(destination)
        os.replace(clone, database)
    else:
        snapshot = args.data_dir / ".legacy-sqlite-upgrade" / args.operation_id / "original.sqlite"
        snapshot.write_bytes(b"Synthetic replaced return snapshot")
    before = state(database)
    with pytest.raises(service.LegacyUpgradeError):
        service.rollback(args)
    assert state(database) == before


def test_process_death_after_commit_has_checked_return_path(legacy_installation):
    args, database = legacy_installation
    before = state(database)
    worker = """
import os,sys
from pathlib import Path
from types import SimpleNamespace
from backend.legacy_sqlite_upgrade.service import upgrade
from backend.services.full_recovery import RecoveryLimits
args=SimpleNamespace(data_dir=Path(sys.argv[1]),database=None,uploads=None,integrations=None,offline=True,output=Path(sys.argv[2]))
def checkpoint(phase):
    if phase=='committed': os._exit(23)
upgrade(args,'synthetic-backup-passphrase-2026',limits=RecoveryLimits(timeout_seconds=600),_checkpoint=checkpoint)
"""
    worker_result = subprocess.run([sys.executable, "-c", worker, str(args.data_dir), str(args.output)], cwd=ROOT,
                                   env=os.environ.copy(), capture_output=True, timeout=600)
    assert worker_result.returncode == 23, worker_result.stderr.decode(errors="replace")
    args.operation_id = next((args.data_dir / ".legacy-sqlite-upgrade").iterdir()).name
    report = service.status(args)
    assert report["recorded_phase"] == "transaction_prepared"
    assert report["database_state"] == "upgraded"
    assert service.rollback(args)["status"] == "rolled_back"
    assert state(database) == before
