"""Full SQLite recovery acceptance tests; all data and credentials are synthetic."""

import json
import os
import shutil
import sqlite3
import subprocess
import sys
from dataclasses import replace
from pathlib import Path
from zipfile import ZipFile, ZipInfo

import pytest

from backend.services import full_recovery as recovery
from backend.services.recovery_archive import RecoveryError, decrypt_zip, encrypted_zip

ROOT = Path(__file__).resolve().parents[2]
PASSPHRASE = "synthetic-backup-passphrase-2026"
SEED = r'''
import json, os, sys
from pathlib import Path
root = Path(sys.argv[1])
os.environ.update(DATA_DIR=str(root), UPLOADS_DIR=str(root/'uploads'),
    DATABASE_URL='sqlite:///'+(root/'runtime.db').as_posix(),
    SQLITE_PERSISTENT_STORE='true', ALLOW_INMEMORY_FALLBACK='false',
    ENVIRONMENT='development', JWT_SECRET_KEY='synthetic-recovery-jwt-key-'+'a'*40,
    INTEGRATION_STATE_FILE=str(root/'integrations.json'), AUTO_SEED_DEMO_DATA='false')
from backend.dependencies import store
from backend.auth import register_user
from backend.config import settings
from backend.models import AccountPatch, BillingPeriodCreate, DocumentCreate
from backend.services.iban_encryption import encrypt_iban
from backend.tests.test_payments import seed
from backend.tests.test_bank_payments import bank_booking, linked_payload, reversal
from datetime import date
item = seed(store, 'receivable')
bank = bank_booking(store, item)
first = store.record_payment('receivable', item.id, linked_payload(bank))
store.reverse_payment('receivable', item.id, first.id, reversal())
store.record_payment('receivable', item.id, linked_payload(bank, '20.10'))
store._patch_entity('account', bank.account_id, AccountPatch(iban=encrypt_iban('DE89370400440532013000')))
contract = store.get_contract(item.contract_id)
store.create_billing_period(BillingPeriodCreate(property_id=contract.property_id,
    label='Complete backup evidence', start_date=date(2026,1,1), end_date=date(2026,12,31)))
store.create_document(DocumentCreate(title='Full backup upload', file_url='uploads/proof.bin'))
register_user('recovery-owner', 'recovery@example.test', 'Recovery Owner', 'SyntheticPassword123!', 'eigentuemer')
values = {k.upper(): v if isinstance(v,str) else json.dumps(v)
    for k,v in settings.model_dump(mode='json').items() if v is not None}
(root/'configuration-for-test.json').write_text(json.dumps(values), encoding='utf-8')
(root/'.env').write_text(''.join(k+'='+v+'\n' for k,v in values.items()), encoding='utf-8')
'''


@pytest.fixture(scope="module")
def runtime_template(tmp_path_factory):
    root = tmp_path_factory.mktemp("synthetic-full-recovery")
    (root / "uploads" / "empty").mkdir(parents=True)
    (root / "uploads" / "proof.bin").write_bytes(b"recovery-proof\x00\xff" * 37)
    (root / "integrations.json").write_text(json.dumps({"enabled": {"email": False},
        "config": {"email": {"smtp_password": "synthetic-integration-secret"}}}), encoding="utf-8")
    env = os.environ.copy()
    env.update(CONTRACT_WIZARD_REQUIRED="false", AI_ENABLED="false")
    result = subprocess.run([sys.executable, "-c", SEED, str(root)], cwd=ROOT,
                            env=env, capture_output=True, text=True, timeout=90)
    assert result.returncode == 0, result.stderr
    return root


@pytest.fixture
def plan(runtime_template, tmp_path):
    root = tmp_path / "source"
    shutil.copytree(runtime_template, root)
    values = json.loads((root / "configuration-for-test.json").read_text(encoding="utf-8"))
    values.update(DATA_DIR=str(root), UPLOADS_DIR=str(root / "uploads"),
                  DATABASE_URL="sqlite:///" + (root / "runtime.db").as_posix(),
                  INTEGRATION_STATE_FILE=str(root / "integrations.json"))
    (root / ".env").write_text("".join(k + "=" + v + "\n" for k, v in values.items()), encoding="utf-8")
    return recovery.RecoveryPlan(root / "runtime.db", root / "uploads", values,
                                 root / ".env", root / "integrations.json")


@pytest.fixture
def bundle(plan, tmp_path):
    archive = tmp_path / "complete.immobak"
    result = recovery.create_full_backup(plan, archive, PASSPHRASE, offline=True)
    assert result["encrypted"] is True
    assert b"synthetic-integration-secret" not in archive.read_bytes()
    assert plan.configuration["JWT_SECRET_KEY"].encode() not in archive.read_bytes()
    return archive


def test_full_roundtrip_preserves_every_table_uploads_and_configuration(plan, bundle, tmp_path):
    target = tmp_path / "restored"
    before = recovery._database_info(plan.database)
    result = recovery.restore_full_backup(bundle, target, PASSPHRASE)
    assert result["existing_installation_changed"] is False
    assert recovery._database_info(target / "database.sqlite3") == before
    assert recovery._database_info(plan.database) == before
    assert (target / "uploads" / "proof.bin").read_bytes() == (plan.uploads / "proof.bin").read_bytes()
    assert (target / "uploads" / "empty").is_dir()
    assert (target / "integrations.json").read_bytes() == plan.integration_state.read_bytes()
    assert (target / "original-runtime.env").read_bytes() == plan.runtime_env.read_bytes()
    config = json.loads((target / "configuration.json").read_text(encoding="utf-8"))
    assert config["JWT_SECRET_KEY"] != plan.configuration["JWT_SECRET_KEY"]
    assert len(config["JWT_SECRET_KEY"]) == 96
    assert config["ENCRYPTION_KEY"] == plan.configuration["ENCRYPTION_KEY"]
    assert config["ENCRYPTION_INDEX_KEY"] == plan.configuration["ENCRYPTION_INDEX_KEY"]
    assert result["signing_key_rotated"] is True
    assert config["UPLOADS_DIR"] == str(target / "uploads")
    assert before["rows"]["users"] == 1
    assert before["rows"]["payment_reversals"] == 1
    assert before["rows"]["billing_periods"] == 1


def test_wrong_password_and_corruption_never_publish_a_directory(bundle, tmp_path):
    for number, password in enumerate(["wrong-synthetic-passphrase", PASSPHRASE]):
        archive = bundle
        if number:
            raw = bytearray(bundle.read_bytes())
            raw[len(raw) // 2] ^= 1
            archive = tmp_path / "corrupted.immobak"
            archive.write_bytes(raw)
        target = tmp_path / f"rejected-{number}"
        with pytest.raises(RecoveryError):
            recovery.restore_full_backup(archive, target, password)
        assert not target.exists()
    assert not list(tmp_path.glob(".immo-restore-*"))


def test_existing_destinations_and_offline_requirement(plan, bundle, tmp_path):
    target = tmp_path / "existing"
    target.mkdir()
    (target / "sentinel").write_bytes(b"must remain")
    with pytest.raises(RecoveryError):
        recovery.restore_full_backup(bundle, target, PASSPHRASE)
    assert (target / "sentinel").read_bytes() == b"must remain"
    before = bundle.read_bytes()
    with pytest.raises(RecoveryError):
        recovery.create_full_backup(plan, bundle, PASSPHRASE, offline=True)
    assert bundle.read_bytes() == before
    with pytest.raises(RecoveryError):
        recovery.create_full_backup(plan, tmp_path / "not-offline.immobak", PASSPHRASE)
    assert not (tmp_path / "not-offline.immobak").exists()


def test_uncheckpointed_wal_commits_are_included(plan, tmp_path):
    archive, target = tmp_path / "wal.immobak", tmp_path / "wal-restored"
    with sqlite3.connect(plan.database) as writer:
        writer.execute("PRAGMA journal_mode=WAL")
        writer.execute("PRAGMA wal_autocheckpoint=0")
        writer.execute("UPDATE portfolios SET name='Committed in WAL'")
        writer.commit()
        assert Path(str(plan.database) + "-wal").stat().st_size > 0
        recovery.create_full_backup(plan, archive, PASSPHRASE, offline=True)
        recovery.restore_full_backup(archive, target, PASSPHRASE)
        with sqlite3.connect(target / "database.sqlite3") as restored:
            assert restored.execute("SELECT name FROM portfolios").fetchone()[0] == "Committed in WAL"


PROBE = r'''
import json, sys
from pathlib import Path
from backend.services.full_recovery import load_recovered_environment
root = Path(sys.argv[1])
load_recovered_environment(root)
from backend.app import app
from backend.dependencies import store
from backend.services.iban_encryption import decrypt_iban
from fastapi.testclient import TestClient
with TestClient(app) as client:
    response = client.post('/api/v1/auth/login', json={'username':'recovery-owner','password':'SyntheticPassword123!'})
    assert response.status_code == 200, response.status_code
    token = response.json()['access_token']
    assert client.get('/api/v1/portfolios', headers={'Authorization':'Bearer '+token}).status_code == 200
assert decrypt_iban(store.list_accounts()[0].iban) == 'DE89370400440532013000'
assert store.list_receivables()[0].amount_paid == 20.10
assert store.list_bookings()[0].allocated_amount == 20.10
assert len([p for p in store.list_payments() if p.reversal]) == 1
assert len(store.list_billing_periods()) == 1
assert (root/'uploads'/'proof.bin').read_bytes() == b'recovery-proof\x00\xff'*37
from backend.services.integrations.manager import integration_manager
assert integration_manager._config['email']['smtp_password'] == 'synthetic-integration-secret'
print('RECOVERY_OK')
'''


def test_fresh_process_login_and_secret_dependent_decryption(bundle, tmp_path):
    target = tmp_path / "fresh-process-restored"
    recovery.restore_full_backup(bundle, target, PASSPHRASE)
    env = os.environ.copy()
    env.update(JWT_SECRET_KEY="deliberately-wrong-ambient-key", DATABASE_URL="sqlite:///:memory:",
               DATA_DIR=str(tmp_path / "wrong-ambient-data"), SQLITE_PERSISTENT_STORE="false")
    result = subprocess.run([sys.executable, "-c", PROBE, str(target)], cwd=ROOT, env=env,
                            capture_output=True, text=True, timeout=90)
    assert result.returncode == 0, result.stderr
    assert "RECOVERY_OK" in result.stdout
    assert not (tmp_path / "wrong-ambient-data").exists()


def test_late_backup_failure_leaves_source_and_no_archive(plan, tmp_path, monkeypatch):
    before = recovery._database_info(plan.database)
    original = recovery._add_file

    def fail_after_write(*args, **kwargs):
        result = original(*args, **kwargs)
        if args[1].startswith("uploads/"):
            raise OSError("simulated disk full after upload write")
        return result
    monkeypatch.setattr(recovery, "_add_file", fail_after_write)
    with pytest.raises(OSError, match="disk full"):
        recovery.create_full_backup(plan, tmp_path / "failed.immobak", PASSPHRASE, offline=True)
    assert not (tmp_path / "failed.immobak").exists()
    assert not list(tmp_path.glob(".immo-backup-*"))
    assert recovery._database_info(plan.database) == before


def test_late_restore_publish_failure_never_replaces_existing_data(plan, bundle, tmp_path, monkeypatch):
    before = recovery._database_info(plan.database)
    target = tmp_path / "failed-restore"

    def blocked_publish(_source, destination):
        destination.mkdir()
        (destination / "racing-owner").write_bytes(b"preserve")
        raise FileExistsError("another process created the target")

    monkeypatch.setattr(recovery, "_publish_directory", blocked_publish)
    with pytest.raises(FileExistsError):
        recovery.restore_full_backup(bundle, target, PASSPHRASE)
    assert (target / "racing-owner").read_bytes() == b"preserve"
    assert list(target.iterdir()) == [target / "racing-owner"]
    assert recovery._database_info(plan.database) == before
    assert not list(tmp_path.glob(".immo-restore-*"))


@pytest.mark.parametrize("fault", ["traversal", "case_collision", "duplicate", "symlink",
                                     "missing_database", "wrong_hash", "unknown_format", "oversize"])
def test_authenticated_but_invalid_archives_are_rejected(bundle, tmp_path, fault):
    plain = tmp_path / "test-only.zip"
    decrypt_zip(bundle, plain, PASSPHRASE, 64 * 1024**2)
    with ZipFile(plain) as archive:
        entries = [(item.filename, archive.read(item.filename)) for item in archive.infolist()]
    manifest = json.loads(dict(entries)["manifest.json"])
    if fault == "traversal":
        entries.append(("../outside", b"untrusted"))
    elif fault == "case_collision":
        entries.append(("UPLOADS/PROOF.BIN", b"untrusted"))
    elif fault == "duplicate":
        entries.append(("configuration.json", b"{}"))
    elif fault == "symlink":
        link = ZipInfo("uploads/link")
        link.create_system = 3
        link.external_attr = 0o120777 << 16
        entries.append((link, b"../outside"))
    elif fault == "missing_database":
        entries = [(name, data) for name, data in entries if name != "database.sqlite3"]
    elif fault == "wrong_hash":
        manifest["files"]["uploads/proof.bin"]["sha256"] = "0" * 64
    elif fault == "unknown_format":
        manifest["version"] = 999
    entries = [(name, json.dumps(manifest).encode() if name == "manifest.json" else data)
               for name, data in entries]
    modified = tmp_path / "invalid.immobak"
    with encrypted_zip(modified, PASSPHRASE) as archive:
        for name, data in entries:
            if fault == "duplicate" and name == "configuration.json" and data == b"{}":
                with pytest.warns(UserWarning, match="Duplicate"):
                    archive.writestr(name, data)
            else:
                archive.writestr(name, data)
    limits = replace(recovery.RecoveryLimits(), file_bytes=100) if fault == "oversize" else recovery.RecoveryLimits()
    target = tmp_path / "invalid-output"
    with pytest.raises(RecoveryError):
        recovery.restore_full_backup(modified, target, PASSPHRASE, limits=limits)
    assert not target.exists()
    assert not (tmp_path / "outside").exists()


def test_upload_tree_mutation_aborts_backup(plan, tmp_path, monkeypatch):
    original = recovery._add_file

    def mutate_after_read(*args, **kwargs):
        result = original(*args, **kwargs)
        if args[1].startswith("uploads/"):
            (plan.uploads / "new-during-backup.bin").write_bytes(b"concurrent write")
        return result
    monkeypatch.setattr(recovery, "_add_file", mutate_after_read)
    with pytest.raises(RecoveryError):
        recovery.create_full_backup(plan, tmp_path / "mutated.immobak", PASSPHRASE, offline=True)
    assert not (tmp_path / "mutated.immobak").exists()


def test_wrong_encryption_secret_is_rejected_before_publication(plan, tmp_path):
    from backend.services.iban_encryption import generate_key

    wrong = replace(plan, configuration={**plan.configuration, "ENCRYPTION_KEY": generate_key(), "ENCRYPTION_KEYRING": ""})
    with pytest.raises(RecoveryError, match="IBAN"):
        recovery.create_full_backup(wrong, tmp_path / "wrong-key.immobak", PASSPHRASE, offline=True)
    assert not (tmp_path / "wrong-key.immobak").exists()


def test_session_key_change_does_not_invalidate_account_encryption(plan, tmp_path):
    changed = replace(plan, configuration={**plan.configuration, "JWT_SECRET_KEY": "changed-session-signing-key"})
    result = recovery.create_full_backup(changed, tmp_path / "new-session-key.immobak", PASSPHRASE, offline=True)
    assert result["encrypted"] is True


def test_capacity_profile_can_resume_rejected_backup_and_restore(plan, tmp_path):
    from backend.services.capacity_settings import load_capacity

    profile = tmp_path / "capacity.json"
    archive = tmp_path / "capacity.immobak"
    profile.write_text(json.dumps({"version": 1, "sqlite_recovery": {"file_bytes": 1}}), encoding="utf-8")
    with pytest.raises(RecoveryError):
        recovery.create_full_backup(plan, archive, PASSPHRASE, offline=True,
                                    limits=load_capacity(profile, "sqlite_recovery", recovery.RecoveryLimits))
    assert not archive.exists()
    profile.write_text(json.dumps({"version": 1, "sqlite_recovery": {"total_bytes": 64 * 1024**2,
        "file_bytes": 32 * 1024**2, "files": 1000, "timeout_seconds": 120}}), encoding="utf-8")
    limits = load_capacity(profile, "sqlite_recovery", recovery.RecoveryLimits)
    recovery.create_full_backup(plan, archive, PASSPHRASE, offline=True, limits=limits)
    target = tmp_path / "capacity-restored"
    recovery.restore_full_backup(archive, target, PASSPHRASE, limits=limits)
    assert recovery._database_info(target / "database.sqlite3") == recovery._database_info(plan.database)
    assert (target / "uploads" / "proof.bin").read_bytes() == (plan.uploads / "proof.bin").read_bytes()


def test_absolute_upload_references_are_rebased_only_in_restored_database(plan, tmp_path):
    original = str(plan.uploads / "proof.bin")
    with sqlite3.connect(plan.database) as db:
        db.execute("UPDATE documents SET file_url=?", (original,))
        db.commit()
    archive, target = tmp_path / "paths.immobak", tmp_path / "rebased"
    recovery.create_full_backup(plan, archive, PASSPHRASE, offline=True)
    recovery.restore_full_backup(archive, target, PASSPHRASE)
    with sqlite3.connect(plan.database) as db:
        assert db.execute("SELECT file_url FROM documents").fetchone()[0] == original
    with sqlite3.connect(target / "database.sqlite3") as db:
        restored = db.execute("SELECT file_url FROM documents").fetchone()[0]
        assert restored == str(target / "uploads" / "proof.bin")
        assert Path(restored).read_bytes() == (plan.uploads / "proof.bin").read_bytes()


def test_external_local_file_is_not_silently_omitted(plan, tmp_path):
    with sqlite3.connect(plan.database) as db:
        db.execute("UPDATE documents SET file_url=?", (str(tmp_path / "outside.pdf"),))
        db.commit()
    with pytest.raises(RecoveryError, match="Upload"):
        recovery.create_full_backup(plan, tmp_path / "external.immobak", PASSPHRASE, offline=True)
    assert not (tmp_path / "external.immobak").exists()


@pytest.mark.parametrize("name", ["../escape", "/absolute", "C:/escape", "uploads/a:stream",
                                 "uploads/NUL.txt", "uploads/trailing.", "uploads/a\\b"])
def test_unsafe_portable_names_are_rejected(name):
    with pytest.raises(RecoveryError):
        recovery._portable(name)


def test_cli_plan_and_help(plan, monkeypatch):
    from argparse import Namespace

    from backend.recovery import _plan
    # Explicit runtime configuration is used when no ambient override is supplied.
    for key in plan.configuration:
        monkeypatch.delenv(key, raising=False)
    configured = _plan(Namespace(data_dir=plan.database.parent, database=None, uploads=None, integrations=None))
    assert configured.database == plan.database
    assert configured.uploads == plan.uploads
    assert configured.configuration["JWT_SECRET_KEY"] == plan.configuration["JWT_SECRET_KEY"]
    result = subprocess.run([sys.executable, "-m", "backend.recovery", "--help"], cwd=ROOT,
                            capture_output=True, text=True, timeout=15)
    assert result.returncode == 0
    assert "backup" in result.stdout and "restore" in result.stdout


def test_future_tables_and_installation_marker_are_preserved(plan, tmp_path):
    with sqlite3.connect(plan.database) as db:
        assert db.execute("SELECT COUNT(*) FROM auth_setup").fetchone()[0] == 1
        db.execute("CREATE TABLE future_module_state (id TEXT PRIMARY KEY, payload BLOB)")
        db.execute("INSERT INTO future_module_state VALUES (?, ?)", ("future", b"future-data\x00\xff"))
        db.commit()
    archive, target = tmp_path / "future.immobak", tmp_path / "future-restored"
    recovery.create_full_backup(plan, archive, PASSPHRASE, offline=True)
    recovery.restore_full_backup(archive, target, PASSPHRASE)
    with sqlite3.connect(target / "database.sqlite3") as db:
        assert db.execute("SELECT payload FROM future_module_state").fetchone()[0] == b"future-data\x00\xff"
        assert db.execute("SELECT COUNT(*) FROM auth_setup").fetchone()[0] == 1
        db.execute("DELETE FROM users")
        db.commit()
    probe = "from pathlib import Path; import sys; from backend.services.full_recovery import load_recovered_environment; load_recovered_environment(Path(sys.argv[1])); from backend.app import app; from backend.auth import setup_required; assert not setup_required(); print('SETUP_REMAINS_CLOSED')"
    result = subprocess.run([sys.executable, "-c", probe, str(target)], cwd=ROOT,
                            capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    assert "SETUP_REMAINS_CLOSED" in result.stdout


def test_incompatible_database_columns_are_rejected(plan, tmp_path):
    with sqlite3.connect(plan.database) as db:
        db.execute("ALTER TABLE users RENAME COLUMN hashed_password TO unsupported_password_field")
    with pytest.raises(RecoveryError, match="schema"):
        recovery.create_full_backup(plan, tmp_path / "wrong-schema.immobak", PASSPHRASE, offline=True)


def test_totp_required_after_full_recovery(plan, tmp_path):
    secret = "JBSWY3DPEHPK3PXP"
    with sqlite3.connect(plan.database) as db:
        db.execute("UPDATE users SET totp_secret=?, totp_enabled=1 WHERE username='recovery-owner'", (secret,))
        db.commit()
    archive, target = tmp_path / "totp.immobak", tmp_path / "totp-restored"
    recovery.create_full_backup(plan, archive, PASSPHRASE, offline=True)
    recovery.restore_full_backup(archive, target, PASSPHRASE)
    probe = r'''
import sys
from pathlib import Path
from backend.services.full_recovery import load_recovered_environment
load_recovered_environment(Path(sys.argv[1]))
from backend.app import app
from backend.tests.test_auth_setup import totp
from fastapi.testclient import TestClient
with TestClient(app) as client:
    credentials = {'username':'recovery-owner','password':'SyntheticPassword123!'}
    missing = client.post('/api/v1/auth/login', json=credentials)
    assert missing.status_code == 401 and missing.headers['X-2FA-Required'] == 'true'
    accepted = client.post('/api/v1/auth/login', json={**credentials,'totp_code':totp('JBSWY3DPEHPK3PXP')})
    assert accepted.status_code == 200
print('TOTP_PRESERVED')
'''
    result = subprocess.run([sys.executable, "-c", probe, str(target)], cwd=ROOT,
                            capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
    assert "TOTP_PRESERVED" in result.stdout


def test_unreadable_upload_subtree_must_fail_closed(plan, tmp_path, monkeypatch):
    """Release gate: os.walk errors must not become an apparently empty tree."""
    original_walk = recovery.os.walk
    def inaccessible_tree(_root, **kwargs):
        if Path(_root).resolve() != plan.uploads.resolve():
            return original_walk(_root, **kwargs)
        callback = kwargs.get("onerror")
        if callback is not None:
            callback(PermissionError("simulated unreadable upload directory"))
        return iter(())
    monkeypatch.setattr(recovery.os, "walk", inaccessible_tree)
    archive = tmp_path / "unreadable.immobak"
    with pytest.raises(RecoveryError):
        recovery.create_full_backup(plan, archive, PASSPHRASE, offline=True)
    assert not archive.exists()


def test_selected_installation_ignores_foreign_terminal_settings(plan, monkeypatch):
    from argparse import Namespace

    from backend.recovery import _plan
    monkeypatch.setenv("JWT_SECRET_KEY", "foreign-terminal-key")
    monkeypatch.setenv("DATABASE_URL", "postgresql://foreign.invalid/foreign")
    monkeypatch.setenv("UPLOADS_DIR", "C:/foreign/empty-uploads")
    monkeypatch.setenv("MAX_UPLOAD_SIZE_BYTES", "invalid-number")
    selected = _plan(Namespace(data_dir=plan.database.parent, database=None, uploads=None, integrations=None))
    assert selected.configuration["JWT_SECRET_KEY"] == plan.configuration["JWT_SECRET_KEY"]
    assert selected.configuration["MAX_UPLOAD_SIZE_BYTES"] == plan.configuration["MAX_UPLOAD_SIZE_BYTES"]
    assert selected.database == plan.database and selected.uploads == plan.uploads


def test_recovered_process_ignores_invalid_foreign_environment_and_cwd(bundle, tmp_path):
    target, foreign_cwd = tmp_path / "isolated-restored", tmp_path / "foreign-working-directory"
    recovery.restore_full_backup(bundle, target, PASSPHRASE)
    foreign_cwd.mkdir()
    (foreign_cwd / ".env").write_text("MAX_UPLOAD_SIZE_BYTES=not-a-number\nENVIRONMENT=invalid\n", encoding="utf-8")
    env = {**os.environ, "PYTHONPATH": str(ROOT), "MAX_UPLOAD_SIZE_BYTES": "invalid",
           "ENVIRONMENT": "invalid", "JWT_SECRET_KEY": "foreign-key", "DATABASE_URL": "sqlite:///:memory:"}
    result = subprocess.run([sys.executable, "-c", PROBE, str(target)], cwd=foreign_cwd,
                            env=env, capture_output=True, text=True, timeout=90)
    assert result.returncode == 0, result.stderr
    assert "RECOVERY_OK" in result.stdout
    help_result = subprocess.run([sys.executable, "-m", "backend.recovery", "--help"], cwd=foreign_cwd,
                                 env=env, capture_output=True, text=True, timeout=15)
    assert help_result.returncode == 0


def test_invalid_configuration_is_rejected_before_backup_publication(plan, tmp_path):
    invalid = replace(plan, configuration={**plan.configuration, "MAX_UPLOAD_SIZE_BYTES": "not-numeric"})
    output = tmp_path / "invalid-settings.immobak"
    with pytest.raises(RecoveryError, match="Konfiguration"):
        recovery.create_full_backup(invalid, output, PASSPHRASE, offline=True)
    assert not output.exists()


def test_missing_explicit_integration_state_is_not_replaced_with_empty_data(plan, tmp_path):
    from argparse import Namespace

    from backend.recovery import _plan
    missing = tmp_path / "missing-integrations.json"
    with pytest.raises(RecoveryError, match="Integrationsdatei"):
        _plan(Namespace(data_dir=plan.database.parent, database=None, uploads=None, integrations=missing))
    with pytest.raises(FileNotFoundError):
        recovery.create_full_backup(replace(plan, integration_state=missing), tmp_path / "missing-state.immobak",
                                  PASSPHRASE, offline=True)
    assert not (tmp_path / "missing-state.immobak").exists()


def test_metadata_and_database_limits_fail_before_publication(plan, tmp_path):
    for name, limits in (("metadata", recovery.RecoveryLimits(metadata_bytes=20)),
                         ("database", recovery.RecoveryLimits(file_bytes=32_000)),
                         ("manifest", recovery.RecoveryLimits(manifest_bytes=20)),
                         ("directory", recovery.RecoveryLimits(central_directory_bytes=20))):
        output = tmp_path / (name + ".immobak")
        with pytest.raises(RecoveryError):
            recovery.create_full_backup(plan, output, PASSPHRASE, offline=True, limits=limits)
        assert not output.exists()
        assert not list(tmp_path.glob(".immo-backup-*"))


def test_real_exclusive_database_lock_aborts_with_bounded_wait(plan, tmp_path):
    import time
    output = tmp_path / "locked.immobak"
    with sqlite3.connect(plan.database) as writer:
        writer.execute("PRAGMA journal_mode=DELETE")
        writer.execute("BEGIN EXCLUSIVE")
        started = time.monotonic()
        with pytest.raises((RecoveryError, sqlite3.OperationalError)):
            recovery.create_full_backup(plan, output, PASSPHRASE, offline=True,
                                      limits=recovery.RecoveryLimits(timeout_seconds=0.15))
        assert time.monotonic() - started < 1
        writer.rollback()
    assert not output.exists()
    assert not list(tmp_path.glob(".immo-backup-*"))


def test_deep_metadata_and_paths_are_rejected_before_parsing():
    with pytest.raises(RecoveryError, match="verschachtelt"):
        recovery._json(b"[" * 2000 + b"0" + b"]" * 2000)
    with pytest.raises(RecoveryError, match="verschachtelt"):
        recovery._portable("uploads/" + "/".join("deep" for _ in range(60)))


def test_recovery_disables_external_plugin_paths_until_review(plan, tmp_path):
    configured = replace(plan, configuration={**plan.configuration, "PLUGIN_DIRS": '["C:/external/plugins"]'})
    output, target = tmp_path / "plugins.immobak", tmp_path / "plugins-restored"
    recovery.create_full_backup(configured, output, PASSPHRASE, offline=True)
    recovery.restore_full_backup(output, target, PASSPHRASE)
    restored = json.loads((target / "configuration.json").read_text(encoding="utf-8"))
    original = json.loads((target / "original-configuration.json").read_text(encoding="utf-8"))
    assert json.loads(restored["PLUGIN_DIRS"]) == []
    assert json.loads(original["PLUGIN_DIRS"]) == ["C:/external/plugins"]


def test_recovery_works_after_original_installation_is_gone(plan, bundle, tmp_path):
    # A disaster-recovery archive must not require its original disk/tree.
    assert plan.database.parent.resolve().is_relative_to(tmp_path.resolve())
    shutil.rmtree(plan.database.parent)
    target = tmp_path / "independent-recovery"
    recovery.restore_full_backup(bundle, target, PASSPHRASE)
    assert (target / "uploads" / "proof.bin").read_bytes() == b"recovery-proof\x00\xff" * 37
    result = subprocess.run([sys.executable, "-c", PROBE, str(target)], cwd=ROOT,
                            capture_output=True, text=True, timeout=90)
    assert result.returncode == 0, result.stderr
    assert "RECOVERY_OK" in result.stdout


def test_recovered_configuration_json_is_authoritative_for_next_backup(plan, tmp_path):
    from argparse import Namespace

    from backend.recovery import _plan
    archive, target = tmp_path / "next-backup.immobak", tmp_path / "next-backup-source"
    recovery.create_full_backup(plan, archive, PASSPHRASE, offline=True)
    recovery.restore_full_backup(archive, target, PASSPHRASE)
    # Convenience .env may be stale; restored exact JSON must keep the actual key.
    (target / ".env").write_text("JWT_SECRET_KEY=wrong-copy\nDATABASE_URL=sqlite:///:memory:\n", encoding="utf-8")
    next_plan = _plan(Namespace(data_dir=target, database=None, uploads=None, integrations=None))
    assert next_plan.database == target / "database.sqlite3"
    restored_config = json.loads((target / "configuration.json").read_text(encoding="utf-8"))
    assert next_plan.configuration["JWT_SECRET_KEY"] == restored_config["JWT_SECRET_KEY"]
    assert next_plan.configuration["JWT_SECRET_KEY"] != plan.configuration["JWT_SECRET_KEY"]
    recovery.create_full_backup(next_plan, tmp_path / "second-generation.immobak", PASSPHRASE, offline=True)
