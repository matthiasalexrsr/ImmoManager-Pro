"""Native encrypted containers authenticate their own private connection file."""

import hashlib
import json
import os
import subprocess
import sys
from zipfile import ZipFile

import pytest

from backend.services import full_recovery as recovery
from backend.services.iban_encryption import IBANKeyring, generate_key, keyring_from_configuration
from backend.services.integrations.encrypted_config_store import EncryptedJsonIntegrationConfigStore
from backend.services.integrations.runtime_factory import configured_runtime_store
from backend.services.recovery_archive import RecoveryError, decrypt_zip, encrypted_zip
from backend.services.recovery_integration_state import verify_archived_integration_state
from backend.tests.test_full_recovery import (
    PASSPHRASE,
    PROBE,
    ROOT,
)
from backend.tests.test_full_recovery import (
    plan as plan,
)
from backend.tests.test_full_recovery import (
    runtime_template as runtime_template,
)


def encrypted_source(plan, *, ring=None):
    path = plan.integration_state
    assert path is not None
    state = json.loads(path.read_bytes())
    state["future_private_extension"] = {"nested": [None, {"preserve": "SYNTHETIC_UNKNOWN"}]}
    path.unlink()  # The explicitly owned, temporary fixture file only.
    store = EncryptedJsonIntegrationConfigStore(
        str(path), keyring=ring or keyring_from_configuration(plan.configuration),
    )
    store.initialize(state)
    return state, path.read_bytes()


def test_actual_encrypted_full_roundtrip_uses_archived_keys_after_signer_rotation(plan, tmp_path):
    state, before = encrypted_source(plan)
    archive, target = tmp_path / "encrypted.immobak", tmp_path / "encrypted-restored"
    source_db = plan.database.read_bytes()
    recovery.create_full_backup(plan, archive, PASSPHRASE, offline=True)
    result = recovery.restore_full_backup(archive, target, PASSPHRASE)
    values = json.loads((target / "configuration.json").read_bytes())
    assert values["JWT_SECRET_KEY"] != plan.configuration["JWT_SECRET_KEY"]
    assert (target / "integrations.json").read_bytes() == before
    assert plan.integration_state.read_bytes() == before
    assert plan.database.read_bytes() == source_db
    assert result["signing_key_rotated"] is True
    restored = configured_runtime_store(values)
    assert restored.load() == state
    assert b"synthetic-integration-secret" not in archive.read_bytes()
    assert b"SYNTHETIC_UNKNOWN" not in before
    # Actual normal global factory and login in a fresh recovered app process;
    # no init permission, fake security, mocked API response or provider action.
    native_probe = PROBE.replace("print('RECOVERY_OK')", """
with TestClient(app) as client:
    login = client.post('/api/v1/auth/login', json={'username':'recovery-owner','password':'SyntheticPassword123!'})
    assert login.status_code == 200
    response = client.get('/api/v1/integrations/email/connection-state',
        headers={'Authorization':'Bearer '+login.json()['access_token']})
    assert response.status_code == 200
    assert response.json()['config']['smtp_password'] == '***'
    assert 'synthetic-integration-secret' not in response.text
assert integration_manager._store.load()['future_private_extension'] == {'nested':[None,{'preserve':'SYNTHETIC_UNKNOWN'}]}
print('ENCRYPTED_FACTORY_RECOVERY_OK')
""")
    env = os.environ.copy()
    wrong = tmp_path / "wrong-ambient-data"
    env.update(JWT_SECRET_KEY="deliberately-wrong-ambient-key", DATABASE_URL="sqlite:///:memory:",
               DATA_DIR=str(wrong), SQLITE_PERSISTENT_STORE="false")
    probe = subprocess.run([sys.executable, "-c", native_probe, str(target)], cwd=ROOT,
        env=env, capture_output=True, text=True, timeout=30)
    assert probe.returncode == 0, "Recovered native app failed; private child output withheld"
    assert "ENCRYPTED_FACTORY_RECOVERY_OK" in probe.stdout
    assert not wrong.exists()
    assert (target / "integrations.json").read_bytes() == before
    assert plan.integration_state.read_bytes() == before
    assert plan.database.read_bytes() == source_db


@pytest.mark.parametrize("fault", ["missing_key", "tampered", "malformed_envelope"])
def test_invalid_encrypted_source_is_refused_without_publishing_backup(plan, tmp_path, fault):
    wrong = IBANKeyring("not_archived", {"not_archived": generate_key()}) if fault == "missing_key" else None
    encrypted_source(plan, ring=wrong)
    path = plan.integration_state
    if fault != "missing_key":
        envelope = json.loads(path.read_bytes())
        if fault == "tampered":
            envelope["ciphertext"] = envelope["ciphertext"][:-7] + "AAAAAAA"
        else:
            envelope["format"] = "unexpected_encrypted_format"
        path.write_text(json.dumps(envelope), encoding="utf-8")
    before, database = path.read_bytes(), plan.database.read_bytes()
    archive = tmp_path / (fault + ".immobak")
    with pytest.raises(RecoveryError, match="Integrationszugänge"):
        recovery.create_full_backup(plan, archive, PASSPHRASE, offline=True)
    assert not archive.exists()
    assert path.read_bytes() == before
    assert plan.database.read_bytes() == database
    assert not list(tmp_path.glob(".immo-backup-*"))


def test_rehashed_authenticated_container_with_bad_inner_envelope_refuses_before_session_dml(plan, tmp_path, monkeypatch):
    encrypted_source(plan)
    archive = tmp_path / "valid.immobak"
    recovery.create_full_backup(plan, archive, PASSPHRASE, offline=True)
    decoded = tmp_path / "decoded.zip"
    decrypt_zip(archive, decoded, PASSPHRASE, recovery.RecoveryLimits().total_bytes)
    with ZipFile(decoded) as original:
        entries = {item.filename: original.read(item) for item in original.infolist()}
    envelope = json.loads(entries["integrations.json"])
    envelope["ciphertext"] = envelope["ciphertext"][:-7] + "AAAAAAA"
    entries["integrations.json"] = json.dumps(envelope).encode()
    manifest = json.loads(entries["manifest.json"])
    manifest["files"]["integrations.json"] = {
        "sha256": hashlib.sha256(entries["integrations.json"]).hexdigest(),
        "size": len(entries["integrations.json"]),
    }
    entries["manifest.json"] = json.dumps(manifest).encode()
    bad = tmp_path / "authenticated-but-invalid.immobak"
    with encrypted_zip(bad, PASSPHRASE) as container:
        for name, data in entries.items():
            container.writestr(name, data)
    from backend.services import recovery_sessions

    def no_session_dml(*args, **kwargs):
        raise AssertionError("invalid private state reached session mutation")

    monkeypatch.setattr(recovery_sessions, "secure_sqlite_restore", no_session_dml)
    target = tmp_path / "must-not-publish"
    before_db, before_state = plan.database.read_bytes(), plan.integration_state.read_bytes()
    with pytest.raises(RecoveryError, match="Integrationszugänge"):
        recovery.restore_full_backup(bad, target, PASSPHRASE)
    assert not target.exists()
    assert plan.database.read_bytes() == before_db
    assert plan.integration_state.read_bytes() == before_state
    assert not list(tmp_path.glob(".immo-restore-*"))


def test_verified_state_sha_must_match_actual_archived_bytes(plan, tmp_path, monkeypatch):
    encrypted_source(plan)
    original = recovery._add_file

    def mutate_before_read(*args, **kwargs):
        if args[1] == "integrations.json":
            # A cooperating offline source is expected. A valid replacement
            # still cannot substitute for the exact verified state revision.
            store = EncryptedJsonIntegrationConfigStore(
                str(plan.integration_state), keyring=keyring_from_configuration(plan.configuration),
            )
            store.update(lambda value: {**value, "later_field": "SYNTHETIC_CHANGED"})
            args = (*args[:3], recovery._fingerprint(plan.integration_state), *args[4:])
        return original(*args, **kwargs)

    monkeypatch.setattr(recovery, "_add_file", mutate_before_read)
    archive = tmp_path / "changed-source.immobak"
    with pytest.raises(RecoveryError, match="Integrationszustand wurde"):
        recovery.create_full_backup(plan, archive, PASSPHRASE, offline=True)
    assert not archive.exists()


PURE = '''
import importlib.abc, json, sys
from pathlib import Path
class Reject(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        blocked = ("backend.auth", "backend.config", "backend.settings", "backend.dependencies",
                   "backend.app", "backend.storage", "backend.repositories",
                   "backend.services.integrations.manager", "backend.services.providers")
        if any(fullname == name or fullname.startswith(name + ".") for name in blocked):
            raise AssertionError("archive state proof reached ambient runtime")
sys.meta_path.insert(0, Reject())
from backend.services.recovery_integration_state import verify_archived_integration_state
before = Path(sys.argv[1]).read_bytes()
report = verify_archived_integration_state(Path(sys.argv[1]), json.loads(Path(sys.argv[2]).read_bytes()),
    max_plaintext_bytes=32*1024*1024, max_json_depth=96)
assert report["verified"] is True and report["legacy_requires_migration"] is False
assert Path(sys.argv[1]).read_bytes() == before
print("PURE_ARCHIVED_CONNECTION_STATE")
'''


def test_fresh_process_archive_adapter_has_no_ambient_runtime_and_no_lock_sidecar(plan, tmp_path):
    encrypted_source(plan)
    config = tmp_path / "explicit-archive-configuration.json"
    config.write_text(json.dumps(plan.configuration), encoding="utf-8")
    before = plan.integration_state.read_bytes()
    names = {item.name for item in plan.integration_state.parent.iterdir()}
    result = subprocess.run([sys.executable, "-c", PURE, str(plan.integration_state), str(config)],
        cwd=ROOT, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
    assert "PURE_ARCHIVED_CONNECTION_STATE" in result.stdout
    assert "synthetic-integration-secret" not in result.stdout + result.stderr
    assert plan.integration_state.read_bytes() == before
    assert {item.name for item in plan.integration_state.parent.iterdir()} == names


def test_legacy_state_is_explicitly_identified_and_never_converted(plan):
    before = plan.integration_state.read_bytes()
    report = verify_archived_integration_state(
        plan.integration_state, plan.configuration, max_plaintext_bytes=1024*1024,
        max_json_depth=64,
    )
    assert report["legacy_requires_migration"] is True
    assert report["state_revision"] == hashlib.sha256(before).hexdigest()
    assert plan.integration_state.read_bytes() == before
