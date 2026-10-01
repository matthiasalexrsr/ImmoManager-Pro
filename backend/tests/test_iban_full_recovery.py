"""Integrated encrypted IBAN recovery after the original installation is gone."""

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from backend.services.full_recovery import RecoveryPlan, create_full_backup, restore_full_backup
from backend.services.recovery_archive import RecoveryError
from backend.tests.test_account_encryption import IBAN, INDEX, KEY, LEGACY, OTHER

ROOT = Path(__file__).resolve().parents[2]
PASSWORD = "SyntheticRecoveryPassword123!"
PASSPHRASE = "synthetic-complete-backup-passphrase"

SEED = r"""
import hashlib, json, os, sys
from pathlib import Path
root = Path(sys.argv[1])
os.environ.update(DATA_DIR=str(root), UPLOADS_DIR=str(root/'uploads'), BACKUP_DIR=str(root/'backups'),
    DATABASE_URL='sqlite:///'+(root/'runtime.db').as_posix(), SQLITE_PERSISTENT_STORE='true',
    ALLOW_INMEMORY_FALLBACK='false', ENVIRONMENT='development', AUTO_SEED_DEMO_DATA='false',
    CONTRACT_WIZARD_REQUIRED='false', AI_ENABLED='false', INTEGRATION_STATE_FILE=str(root/'integrations.json'))
from backend.dependencies import store
from backend.auth import register_user, prepare_totp, update_user
from backend.config import settings
from backend.models import AccountPatch, DocumentCreate
from backend.tests.test_payments import seed
from backend.tests.test_bank_payments import bank_booking, linked_payload, reversal
from scripts.private_server_backup import protected_new_file
item = seed(store, 'rent_charge')
bank = bank_booking(store, item)
first = store.record_payment('rent_charge', item.id, linked_payload(bank))
store.reverse_payment('rent_charge', item.id, first.id, reversal())
receipt = store.record_payment('rent_charge', item.id, linked_payload(bank, '20.10'))
store._patch_entity('account', bank.account_id, AccountPatch(iban='DE89370400440532013000'))
store.create_document(DocumentCreate(title='Source-gone encrypted recovery', file_url='uploads/proof.bin'))
user = register_user('crypto-owner', 'crypto-owner@example.test', 'Synthetic Owner', 'SyntheticRecoveryPassword123!', 'eigentuemer')
totp = prepare_totp(user.id)['totp_secret']
update_user(user.id, {'totp_enabled': True})
values = {key.upper(): value if isinstance(value,str) else json.dumps(value)
          for key,value in settings.model_dump(mode='json').items() if value is not None}
with protected_new_file(root/'.env') as target:
    target.write(''.join(key+'='+value+'\n' for key,value in values.items()).encode())
with protected_new_file(root/'configuration.json') as target:
    target.write(json.dumps(values).encode())
print('SOURCE_READY:'+json.dumps(dict(account_id=bank.account_id, charge_id=item.id, receipt_id=receipt.id,
    totp_hash=hashlib.sha256(totp.encode()).hexdigest(), jwt_hash=hashlib.sha256(settings.jwt_secret_key.encode()).hexdigest())))
"""

PROBE = r"""
import base64, hashlib, hmac, json, os, struct, sys, time
from pathlib import Path
root = Path(sys.argv[1])
from backend.services.full_recovery import load_recovered_environment
load_recovered_environment(root)
from backend.auth import authenticate_user
from backend.config import settings
from backend.dependencies import store
from backend.app import app
from backend.db.session import engine
from fastapi.testclient import TestClient
from sqlalchemy import text
user = authenticate_user('crypto-owner', 'SyntheticRecoveryPassword123!')
assert user['totp_enabled'] is True
secret = user['totp_secret']
assert hashlib.sha256(secret.encode()).hexdigest() == os.environ['EXPECTED_TOTP_HASH']
assert hashlib.sha256(settings.jwt_secret_key.encode()).hexdigest() == os.environ['EXPECTED_JWT_HASH']
assert hashlib.sha256(settings.jwt_secret_key.encode()).hexdigest() != os.environ['ORIGINAL_JWT_HASH']
assert hashlib.sha256(settings.encryption_keyring.encode()).hexdigest() == os.environ['EXPECTED_RING_HASH']
assert hashlib.sha256(settings.encryption_index_key.encode()).hexdigest() == os.environ['EXPECTED_INDEX_HASH']
digest = hmac.new(base64.b32decode(secret), struct.pack('>Q', int(time.time())//30), 'sha1').digest()
offset = digest[-1] & 15
code = str((struct.unpack('>I', digest[offset:offset+4])[0] & 0x7fffffff)%1000000).zfill(6)
with TestClient(app) as client:
    assert client.post('/api/v1/auth/login', json=dict(username='crypto-owner', password='SyntheticRecoveryPassword123!')).status_code == 401
    response = client.post('/api/v1/auth/login', json=dict(username='crypto-owner', password='SyntheticRecoveryPassword123!', totp_code=code))
    assert response.status_code == 200, response.status_code
    headers = {'Authorization':'Bearer '+response.json()['access_token']}
    account = client.get('/api/v1/accounts/'+os.environ['EXPECTED_ACCOUNT_ID'], headers=headers)
    assert account.status_code == 200 and account.json()['iban'] == 'DE89370400440532013000'
    assert client.get('/api/v1/auth/2fa/status', headers=headers).json()['enabled'] is True
assert store.get_rent_charge(os.environ['EXPECTED_CHARGE_ID']).amount_paid == 20.10
assert any(receipt.id == os.environ['EXPECTED_RECEIPT_ID'] for receipt in store.list_payments())
assert len([receipt for receipt in store.list_payments() if receipt.reversal]) == 1
with engine.connect() as connection:
    raw, fingerprint = connection.execute(text('SELECT iban, iban_fingerprint FROM accounts WHERE id=:id'), dict(id=os.environ['EXPECTED_ACCOUNT_ID'])).one()
assert raw.startswith('enc:v1:current:') and 'DE89370400440532013000' not in raw and len(fingerprint) == 64
assert (root/'uploads'/'proof.bin').read_bytes() == b'synthetic-encrypted-recovery-proof'
print('SOURCE_GONE_CRYPTO_RECOVERY_OK')
"""


@pytest.fixture
def encrypted_installation(tmp_path):
    source = tmp_path / "source-owned-by-this-test"
    (source / "uploads").mkdir(parents=True)
    (source / "uploads" / "proof.bin").write_bytes(b"synthetic-encrypted-recovery-proof")
    (source / "integrations.json").write_text("{}", encoding="utf-8")
    ring = json.dumps({"old": KEY, "current": OTHER})
    environment = {
        **os.environ,
        "PYTHONUTF8": "1",
        "JWT_SECRET_KEY": LEGACY,
        "ENCRYPTION_KEY": "",
        "ENCRYPTION_KEYRING": ring,
        "ENCRYPTION_ACTIVE_KEY_ID": "current",
        "ENCRYPTION_INDEX_KEY": INDEX,
        "ENCRYPTION_LEGACY_JWT_KEYS": "[]",
    }
    process = subprocess.run(
        [sys.executable, "-c", SEED, str(source)],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        encoding="utf-8",
        timeout=90,
    )
    assert process.returncode == 0, process.stderr
    metadata = json.loads(
        next(
            line.removeprefix("SOURCE_READY:")
            for line in process.stdout.splitlines()
            if line.startswith("SOURCE_READY:")
        )
    )
    values = json.loads((source / "configuration.json").read_text())
    return source, values, metadata


def test_full_encrypted_recovery_keeps_keys_totp_receipts_and_login_after_source_deleted(
    encrypted_installation, tmp_path
):
    source, values, metadata = encrypted_installation
    archive = tmp_path / "private-complete.immobak"
    create_full_backup(
        RecoveryPlan(source / "runtime.db", source / "uploads", values, source / ".env", source / "integrations.json"),
        archive,
        PASSPHRASE,
        offline=True,
    )
    original_env = (source / ".env").read_bytes()
    for value in (KEY, OTHER, INDEX, LEGACY, IBAN):
        assert value.encode() not in archive.read_bytes()
    # Exact owned generated target, verified before recursive removal. This is
    # the explicit source-gone test; no application/user database is targeted.
    assert source.resolve().parent == tmp_path.resolve() and source.name == "source-owned-by-this-test"
    shutil.rmtree(source)
    assert not source.exists()
    restored = tmp_path / "restored-owned-by-this-test"
    restore_full_backup(archive, restored, PASSPHRASE)
    restored_values = json.loads((restored / "configuration.json").read_text(encoding="utf-8"))
    assert (restored / "original-runtime.env").read_bytes() == original_env
    environment = {
        **os.environ,
        "PYTHONUTF8": "1",
        "JWT_SECRET_KEY": "foreign-jwt-must-not-be-used",
        "ENCRYPTION_KEY": "foreign-encryption-key",
        "ENCRYPTION_INDEX_KEY": "foreign-index-key",
        "ENCRYPTION_KEYRING": '{"foreign":"invalid"}',
        "ENCRYPTION_ACTIVE_KEY_ID": "foreign",
        "DATABASE_URL": "sqlite:///" + (tmp_path / "foreign-never-created.db").as_posix(),
        "EXPECTED_TOTP_HASH": metadata["totp_hash"],
        "EXPECTED_JWT_HASH": hashlib.sha256(restored_values["JWT_SECRET_KEY"].encode()).hexdigest(),
        "ORIGINAL_JWT_HASH": metadata["jwt_hash"],
        "EXPECTED_RING_HASH": hashlib.sha256(values["ENCRYPTION_KEYRING"].encode()).hexdigest(),
        "EXPECTED_INDEX_HASH": hashlib.sha256(values["ENCRYPTION_INDEX_KEY"].encode()).hexdigest(),
        "EXPECTED_ACCOUNT_ID": metadata["account_id"],
        "EXPECTED_CHARGE_ID": metadata["charge_id"],
        "EXPECTED_RECEIPT_ID": metadata["receipt_id"],
    }
    result = subprocess.run(
        [sys.executable, "-c", PROBE, str(restored)],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        encoding="utf-8",
        timeout=90,
    )
    assert result.returncode == 0, result.stderr
    assert "SOURCE_GONE_CRYPTO_RECOVERY_OK" in result.stdout
    assert not (tmp_path / "foreign-never-created.db").exists()


def test_full_backup_wrong_encryption_configuration_never_creates_an_archive(encrypted_installation, tmp_path):
    source, values, _ = encrypted_installation
    archive = tmp_path / "must-not-exist.immobak"
    wrong = {**values, "ENCRYPTION_KEYRING": json.dumps({"old": KEY, "current": KEY})}
    with pytest.raises(RecoveryError, match="AUTHENTICATION_FAILED"):
        create_full_backup(
            RecoveryPlan(
                source / "runtime.db", source / "uploads", wrong, source / ".env", source / "integrations.json"
            ),
            archive,
            PASSPHRASE,
            offline=True,
        )
    assert not archive.exists()
