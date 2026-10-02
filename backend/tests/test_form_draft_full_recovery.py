"""Private drafts survive real full recovery; unknown keys never publish a target."""

import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
from dataclasses import replace
from pathlib import Path
from zipfile import ZipFile

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from backend import auth
from backend.form_draft_models import DraftWrite
from backend.repositories.sql_store import SQLAlchemyStore
from backend.services import form_draft_crypto, form_drafts
from backend.services import full_recovery as recovery
from backend.services.data_transfer import TransferError, export_store_data, import_store_data
from backend.services.iban_encryption import IBANKeyring, generate_key, keyring_from_configuration
from backend.services.portfolio_scope import scope_from_user
from backend.services.recovery_archive import RecoveryError, decrypt_zip, encrypted_zip
from backend.tests import test_form_drafts as draft_fixtures
from backend.tests import test_full_recovery as recovery_fixtures
from backend.tests import test_restore_session_security as session_fixtures

workspace = draft_fixtures.workspace
plan = recovery_fixtures.plan
runtime_template = recovery_fixtures.runtime_template
PASSPHRASE = recovery_fixtures.PASSPHRASE
ROOT = Path(__file__).resolve().parents[2]


def saved_draft(plan, monkeypatch):
    original = keyring_from_configuration(plan.configuration)
    keys = dict(original.keys) | {"draft-test": generate_key()}
    ring = IBANKeyring("draft-test", keys, original.legacy_jwt_keys, original.index_key)
    values = plan.configuration | {"ENCRYPTION_KEY": "", "ENCRYPTION_KEYRING": json.dumps(keys),
        "ENCRYPTION_ACTIVE_KEY_ID": "draft-test", "FORM_DRAFT_TTL_DAYS": "14", "FORM_DRAFT_MAX_BYTES": "65536"}
    plan = replace(plan, configuration=values)
    plan.runtime_env.write_text("".join(k + "=" + v + "\n" for k, v in values.items()), encoding="utf-8")
    engine = create_engine("sqlite:///" + plan.database.as_posix())
    factory = sessionmaker(bind=engine, autoflush=False)
    monkeypatch.setattr(auth, "_user_store", auth.SQLUserStore(factory))
    monkeypatch.setattr(auth, "_auth_session_factory", factory)
    monkeypatch.setattr(form_draft_crypto, "current_keyring", lambda: ring)
    try:
        owner = auth.authenticate_user("recovery-owner", "SyntheticPassword123!")
        assert owner is not None
        with Session(engine) as db:
            store = SQLAlchemyStore(db)
            row = store.list_properties()[0]
            command = DraftWrite(collection="properties", entity_id=row.id, owner_id=owner["id"],
                schema="synthetic:private-name", values={"name": "Synthetic private unsaved €"},
                original_values={"name": row.name, "portfolio_id": row.portfolio_id},
                edit_revision={"collection": "properties", "id": row.id, "updatedAt": row.updated_at.isoformat()})
            form_drafts.form_draft(store, command, scope_from_user(owner), write=command)
            return plan, row.id, row.updated_at.isoformat(), keys
    finally:
        engine.dispose()


PROBE = r'''
import json, sys
from pathlib import Path
from backend.services.full_recovery import load_recovered_environment
load_recovered_environment(Path(sys.argv[1]))
from backend.app import app
from backend.config import settings
from fastapi.testclient import TestClient
assert settings.form_draft_ttl_days == 14 and settings.form_draft_max_bytes == 65536
with TestClient(app) as client:
    logged = client.post('/api/v1/auth/login', json={'username':'recovery-owner','password':'SyntheticPassword123!'})
    assert logged.status_code == 200, logged.status_code
    headers = {'Authorization':'Bearer '+logged.json()['access_token']}
    user = client.get('/api/v1/auth/me', headers=headers).json()
    response = client.get('/api/v1/auth/users/me/form-drafts', headers=headers,
        params={'owner_id':user['id'], 'collection':'properties', 'entity_id':sys.argv[2]})
    assert response.status_code == 200, response.status_code
    draft = response.json()['draft']
    assert draft['values']['name'] == 'Synthetic private unsaved €'
    assert draft['edit_revision']['updatedAt'] == sys.argv[3]
    record = client.get('/api/v1/properties/'+sys.argv[2], headers=headers)
    assert record.status_code == 200 and record.json()['name'] == draft['original_values']['name']
print('PRIVATE_DRAFT_SOURCE_GONE_FULL_RECOVERY_OK')
'''


def test_source_gone_full_restore_with_foreign_ambient_key_retains_private_work_and_original_revision(plan, tmp_path, monkeypatch):
    plan, row_id, revision, _ = saved_draft(plan, monkeypatch)
    with sqlite3.connect(plan.database) as db:
        ciphertext = db.execute("SELECT id,payload FROM form_drafts").fetchall()
        assert len(ciphertext) == 1 and "Synthetic private" not in ciphertext[0][1]
    db.close()
    archive, target = tmp_path / "private.immobak", tmp_path / "restored-private-work"
    recovery.create_full_backup(plan, archive, PASSPHRASE, offline=True)
    original = plan.database.parent.resolve()
    assert original.is_relative_to(tmp_path.resolve()) and original.name == "source"
    shutil.rmtree(original)
    recovery.restore_full_backup(archive, target, PASSPHRASE)
    with sqlite3.connect(target / "database.sqlite3") as db:
        assert db.execute("SELECT id,payload FROM form_drafts").fetchall() == ciphertext
    env = os.environ | {"ENCRYPTION_KEY": generate_key(), "ENCRYPTION_KEYRING": "", "FORM_DRAFT_TTL_DAYS": "1"}
    process = subprocess.run([sys.executable, "-c", PROBE, str(target), row_id, revision], cwd=ROOT,
        env=env, capture_output=True, text=True, timeout=90)
    assert process.returncode == 0, process.stderr
    assert "PRIVATE_DRAFT_SOURCE_GONE_FULL_RECOVERY_OK" in process.stdout


@pytest.mark.parametrize("problem", ["missing", "wrong"])
def test_backup_refuses_unreadable_private_draft_without_ambient_key_fallback_or_source_change(plan, tmp_path, monkeypatch, problem):
    plan, _, _, keys = saved_draft(plan, monkeypatch)
    altered = dict(keys)
    if problem == "missing":
        del altered["draft-test"]
    else:
        altered["draft-test"] = generate_key()
    values = plan.configuration | {"ENCRYPTION_KEYRING": json.dumps(altered), "ENCRYPTION_ACTIVE_KEY_ID": next(iter(altered))}
    before = recovery._database_info(plan.database)
    target = tmp_path / "unreadable.immobak"
    with pytest.raises(RecoveryError, match="Formularentwürfe"):
        recovery.create_full_backup(replace(plan, configuration=values), target, PASSPHRASE, offline=True)
    assert not target.exists() and recovery._database_info(plan.database) == before


def test_pre_draft_archive_is_compatible_but_partial_existing_draft_schema_is_refused(plan, tmp_path):
    with sqlite3.connect(plan.database) as db:
        db.execute("DROP TABLE form_drafts")
    archive, target = tmp_path / "pre-drafts.immobak", tmp_path / "pre-drafts-restored"
    recovery.create_full_backup(plan, archive, PASSPHRASE, offline=True)
    recovery.restore_full_backup(archive, target, PASSPHRASE)
    with sqlite3.connect(target / "database.sqlite3") as db:
        assert db.execute("SELECT name FROM sqlite_master WHERE name='form_drafts'").fetchone() is None
    with sqlite3.connect(plan.database) as db:
        db.execute("CREATE TABLE form_drafts(id TEXT, payload TEXT)")
    with pytest.raises(RecoveryError, match="Datenbankschema"):
        recovery.create_full_backup(plan, tmp_path / "partial.immobak", PASSPHRASE, offline=True)


def test_authenticated_restore_with_wrong_draft_key_cannot_publish_or_use_runtime_key(plan, tmp_path, monkeypatch):
    plan, _, _, keys = saved_draft(plan, monkeypatch)
    original, decoded, modified = tmp_path / "original.immobak", tmp_path / "decoded-test.zip", tmp_path / "modified.immobak"
    recovery.create_full_backup(plan, original, PASSPHRASE, offline=True)
    decrypt_zip(original, decoded, PASSPHRASE, 64 * 1024**2)
    with ZipFile(decoded) as archive:
        entries = {entry.filename: archive.read(entry.filename) for entry in archive.infolist()}
    configuration = json.loads(entries["configuration.json"])
    configuration["ENCRYPTION_KEYRING"] = json.dumps(keys | {"draft-test": generate_key()})
    entries["configuration.json"] = json.dumps(configuration).encode()
    manifest = json.loads(entries["manifest.json"])
    manifest["files"]["configuration.json"] = {"size": len(entries["configuration.json"]),
        "sha256": hashlib.sha256(entries["configuration.json"]).hexdigest()}
    entries["manifest.json"] = json.dumps(manifest).encode()
    with encrypted_zip(modified, PASSPHRASE) as archive:
        for name, content in entries.items():
            archive.writestr(name, content)
    before = recovery._database_info(plan.database)
    target = tmp_path / "unpublished-draft-target"
    with pytest.raises(RecoveryError, match="Formularentwürfe"):
        recovery.restore_full_backup(modified, target, PASSPHRASE)
    assert not target.exists() and recovery._database_info(plan.database) == before


def test_actual_clear_and_replace_refuse_private_work_before_any_business_mutation(workspace):
    store, _, properties, owner, *_ = workspace
    draft_fixtures.write(store, owner, properties[0])
    snapshot = export_store_data(store, "synthetic")
    with pytest.raises(ValueError, match="Formularentwürfe"):
        store.clear_all()
    with pytest.raises(TransferError, match="Formularentwürfe"):
        import_store_data(store, snapshot, replace_existing=True)
    assert draft_fixtures.read(store, owner, properties[0])["values"]["name"] == "Not yet saved"
    assert store.get_property(properties[0].id).name == properties[0].name


@pytest.mark.parametrize("problem", [None, "wrong-key", "corrupted"])
def test_actual_offline_restore_cli_checks_draft_before_revoking_any_family(tmp_path, monkeypatch, problem):
    from backend.db.form_draft_models import ensure_form_draft_schema
    key = generate_key()
    ring = IBANKeyring("default", {"default": key})
    monkeypatch.setattr(form_draft_crypto, "current_keyring", lambda: ring)
    database = tmp_path / "draft-cli%40.sqlite"
    session_fixtures.session_database(database)
    engine = create_engine("sqlite:///" + database.as_posix())
    try:
        with engine.begin() as db:
            ensure_form_draft_schema(db)
            payload = form_draft_crypto.encrypt(b'{"values":{"name":"Synthetic private CLI work"}}', b"a" * 64)
            db.exec_driver_sql("INSERT INTO form_drafts(id,user_id,collection,entity_id,form_key,scope_hash,revision,payload,updated_at,expires_at) "
                "VALUES (?, 'synthetic-user', 'properties', 'synthetic-property', 'crud', ?, ?, ?, CURRENT_TIMESTAMP, '2099-01-01')",
                ("a" * 64, "b" * 64, "c" * 36, "invalid" if problem == "corrupted" else payload))
    finally:
        engine.dispose()
    configuration = {"JWT_SECRET_KEY": "synthetic-old-signing-key", "ENCRYPTION_KEY": generate_key() if problem == "wrong-key" else key}
    process = subprocess.run([sys.executable, "-m", "scripts.restore_session_security", "--configuration-stdin"], cwd=ROOT,
        env=os.environ | {"DATABASE_URL": "sqlite:///" + database.as_posix(), "ENCRYPTION_KEY": generate_key()},
        input=json.dumps(configuration), capture_output=True, text=True, timeout=30)
    assert key not in process.stdout + process.stderr and "Synthetic private CLI work" not in process.stdout + process.stderr
    with sqlite3.connect(database) as db:
        assert db.execute("SELECT count(*) FROM auth_refresh_tokens WHERE consumed_at IS NOT NULL").fetchone()[0] == 1
        assert db.execute("SELECT payload FROM form_drafts").fetchone()[0] == ("invalid" if problem == "corrupted" else payload)
        if problem is None:
            assert process.returncode == 0, process.stderr
            assert json.loads(process.stdout) == {"revoked_session_count": 1, "legacy_iban_present": False}
            assert db.execute("SELECT revoke_reason FROM auth_sessions").fetchone()[0] == "database_restore"
        else:
            assert process.returncode == 1 and "restore_session_security_failed" in process.stderr
            assert db.execute("SELECT revoked_at FROM auth_sessions").fetchone()[0] is None
