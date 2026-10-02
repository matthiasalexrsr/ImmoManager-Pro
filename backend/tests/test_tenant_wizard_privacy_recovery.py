"""Actual encrypted full recovery followed by complete authenticated privacy export."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from backend.services.full_recovery import create_full_backup, restore_full_backup
from backend.tests.test_contract_wizard_recovery import SEED
from backend.tests.test_full_recovery import PASSPHRASE, plan, runtime_template  # noqa: F401

ROOT = Path(__file__).resolve().parents[2]
PROBE = r'''
import base64, hashlib, json, sys
from pathlib import Path
from backend.services.full_recovery import load_recovered_environment
load_recovered_environment(Path(sys.argv[1]))
from backend.app import app
from backend.config import settings
from backend.dependencies import store
from fastapi.testclient import TestClient
expected = json.loads(sys.stdin.read())
with TestClient(app) as client:
    login = client.post('/api/v1/auth/login', json={'username':'recovery-owner','password':'SyntheticPassword123!'})
    assert login.status_code == 200, login.status_code
    headers = {'Authorization':'Bearer '+login.json()['access_token']}
    tenant_id = store.get_contract(expected['draft']['contract_id']).tenant_id
    # The archive has restored all tables. The disclosure itself needs only the
    # immutable stored originals, even if an independently managed source is gone.
    (Path(settings.uploads_dir)/'wizard-original.bin').unlink()
    response = client.get('/api/v1/admin/dsgvo/tenant/'+tenant_id+'/export', headers=headers)
    assert response.status_code == 200, response.status_code
    graph = response.json()
    assert graph['tenant']['id'] == tenant_id
    assert {row['id'] for row in graph['contract_wizard_drafts']} == {expected['draft']['id'],expected['editable']['id']}
    assert graph['contract_signature_evidence'][0]['reference'] == 'Actual synthetic paper record'
    files = {row['id']:row for row in graph['contract_wizard_files']}
    kinds = {}
    for record in graph['wizard_file_contents']:
        contents = b''.join(base64.b64decode(row['data_base64'],validate=True) for row in record['blocks'])
        meta = files[record['id']]
        assert len(contents) == meta['size_bytes']
        assert hashlib.sha256(contents).hexdigest() == meta['sha256']
        kinds[meta['kind']] = meta['sha256']
    assert kinds['reviewed_pdf'] == expected['pdf_sha256']
    assert kinds['frozen_attachment'] == expected['original_sha256']
    preview = client.get('/api/v1/admin/dsgvo/tenant/'+tenant_id+'/anonymization-preview',headers=headers)
    assert preview.status_code == 200, preview.status_code
    assert preview.json()['retained_personal_evidence']['contract_wizard_drafts']['count'] == 2
    assert [len(store.list_bookings()),len(store.list_payments())] == expected['cash_counts']
print('SOURCE_GONE_WIZARD_PRIVACY_OK')
'''


def test_restored_journals_export_every_stored_original_without_the_source_installation(plan, tmp_path):  # noqa: F811
    environment = {**os.environ, **plan.configuration, "PYTHONUTF8": "1", "AI_ENABLED": "false",
                   "OPERATIONAL_SCHEDULER_ENABLED": "false", "BACKUP_SCHEDULER_ENABLED": "false"}
    seeded = subprocess.run([sys.executable, "-c", SEED], cwd=ROOT, env=environment,
        capture_output=True, encoding="utf-8", timeout=90)
    assert seeded.returncode == 0, seeded.stderr
    metadata = json.loads(next(line.removeprefix("WIZARD_READY:") for line in seeded.stdout.splitlines()
                              if line.startswith("WIZARD_READY:")))
    archive = tmp_path / "wizard-privacy.immobak"
    create_full_backup(plan, archive, PASSPHRASE, offline=True)
    source = plan.database.parent.resolve()
    assert source.is_relative_to(tmp_path.resolve()) and source.name == "source"
    shutil.rmtree(source)
    assert not source.exists()
    target = tmp_path / "recovered"
    restore_full_backup(archive, target, PASSPHRASE)
    environment.update(DATABASE_URL="sqlite:///:memory:", DATA_DIR=str(tmp_path / "wrong-ambient-data"),
        JWT_SECRET_KEY="deliberately-wrong-ambient-signing-key", SQLITE_PERSISTENT_STORE="false")
    recovered = subprocess.run([sys.executable, "-c", PROBE, str(target)], cwd=ROOT, env=environment,
        input=json.dumps(metadata), capture_output=True, encoding="utf-8", timeout=90)
    assert recovered.returncode == 0, recovered.stderr
    assert "SOURCE_GONE_WIZARD_PRIVACY_OK" in recovered.stdout
    assert not (tmp_path / "wrong-ambient-data").exists()
