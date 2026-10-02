"""Recover actual wizard journals after removing the owned source installation."""

import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from backend.services.full_recovery import create_full_backup, restore_full_backup
from backend.services.recovery_archive import RecoveryError
from backend.services.recovery_validation import rebase_file_references, validate_file_references
from backend.tests.test_full_recovery import PASSPHRASE, plan, runtime_template  # noqa: F401

ROOT = Path(__file__).resolve().parents[2]

SEED = r'''
import hashlib, json
from pathlib import Path
from backend.dependencies import store
from backend.auth import authenticate_user
from backend.config import settings
from backend.models import DocumentCreate
from backend.services import contract_wizard as wizard
from backend.services.contract_wizard_types import DraftCreate, DraftData, DraftCommit, RevisionCommand, SignatureCreate, TemplateCreate
actor = authenticate_user('recovery-owner', 'SyntheticPassword123!')['id']
contract = store.list_contracts()[0]
property = store.get_property(contract.property_id)
content = b'original-wizard-attachment\x00\xff' * 9000
(Path(settings.uploads_dir)/'wizard-original.bin').write_bytes(content)
attachment = store.create_document(DocumentCreate(title='Recovery attachment', property_id=property.id,
    file_url='uploads/wizard-original.bin'))
template = wizard.create_template(store, TemplateCreate(idempotency_key='recovery-template', portfolio_id=property.portfolio_id,
    title='Own recovery terms', body='Own reviewed terms <escaped>'), actor)
data = DraftData(property_id=property.id, unit_id=contract.unit_id, tenant_id=contract.tenant_id,
    contract_number='WIZARD-RECOVERY', start_date='2047-01-01', landlord_name='Synthetic recovery owner',
    landlord_address='Synthetic street 1', deposit_amount='1500.00', template_id=template['id'], attachment_ids=[attachment.id])
row = wizard.create_draft(store, DraftCreate(idempotency_key='recovery-create', data=data), actor)
row = wizard.review_draft(store, row['id'], RevisionCommand(idempotency_key='recovery-review', expected_revision=row['revision']), actor)
pdf = wizard.read_review_pdf(store, row['id'], actor)
commit = DraftCommit(idempotency_key='recovery-publish', expected_revision=row['revision'], reviewed_hash=row['review_hash'], confirmed=True)
row = wizard.publish_draft(store, row['id'], commit, actor)
signature = SignatureCreate(idempotency_key='recovery-signature', expected_revision=row['revision'], confirmed=True,
    signed_date='2026-10-01', tenant_signer='Synthetic tenant', landlord_signer='Synthetic owner', reference='Actual synthetic paper record')
row = wizard.record_signature(store, row['id'], signature, actor)
evidence = wizard.attachment_evidence(store, row['id'], actor)['items'][0]
editable = wizard.create_draft(store, DraftCreate(idempotency_key='recovery-editable',
    data=data.model_copy(update={'contract_number':'WIZARD-EDITABLE', 'attachment_ids':[]})), actor)
print('WIZARD_READY:'+json.dumps(dict(draft=row, editable=editable, commit=commit.model_dump(mode='json'),
    signature=signature.model_dump(mode='json'), attachment_id=evidence['id'], original_sha256=hashlib.sha256(content).hexdigest(),
    original_size=len(content), pdf_sha256=hashlib.sha256(pdf).hexdigest(), cash_counts=[len(store.list_bookings()),len(store.list_payments())])))
'''

PROBE = r'''
import hashlib, json, sys
from pathlib import Path
from backend.services.full_recovery import load_recovered_environment
load_recovered_environment(Path(sys.argv[1]))
from backend.app import app
from fastapi.testclient import TestClient
from backend.dependencies import store
from backend.services import contract_wizard as wizard
from backend.services.contract_wizard_types import DraftCommit, SignatureCreate
expected = json.loads(sys.stdin.read())
with TestClient(app) as client:
    response = client.post('/api/v1/auth/login', json={'username':'recovery-owner','password':'SyntheticPassword123!'})
    assert response.status_code == 200, response.status_code
    headers = {'Authorization':'Bearer '+response.json()['access_token']}
    actor = client.get('/api/v1/auth/me', headers=headers).json()['id']
    row = expected['draft']
    assert wizard.get_draft(store, row['id'], actor) == row
    assert wizard.get_draft(store, expected['editable']['id'], actor) == expected['editable']
    # Earlier publication/signature commands replay their original receipts;
    # they do not insert another contract or mark another payment as received.
    assert wizard.publish_draft(store, row['id'], DraftCommit.model_validate(expected['commit']), actor)['state'] == 'committed'
    assert wizard.record_signature(store, row['id'], SignatureCreate.model_validate(expected['signature']), actor) == row
    pdf = client.get('/api/v1/contract-wizard/drafts/'+row['id']+'/pdf', headers=headers)
    assert pdf.status_code == 200, pdf.status_code
    assert hashlib.sha256(pdf.content).hexdigest() == expected['pdf_sha256']
    url = '/api/v1/contract-wizard/drafts/'+row['id']+'/attachments/'+expected['attachment_id']+'/download'
    original = client.get(url, headers=headers)
    assert original.status_code == 200, original.status_code
    assert len(original.content) == expected['original_size']
    assert hashlib.sha256(original.content).hexdigest() == expected['original_sha256']
    assert len(wizard.signature_evidence(store,row['id'],actor)['items']) == 1
    assert store.get_contract(row['contract_id']).status == 'draft'
    assert [len(store.list_bookings()),len(store.list_payments())] == expected['cash_counts']
print('SOURCE_GONE_WIZARD_RECOVERY_OK')
'''


def test_full_restore_retains_editable_draft_signed_pdf_originals_and_command_replays(plan, tmp_path):  # noqa: F811
    environment = {**os.environ, **plan.configuration, "PYTHONUTF8": "1", "AI_ENABLED": "false",
        "OPERATIONAL_SCHEDULER_ENABLED": "false", "BACKUP_SCHEDULER_ENABLED": "false"}
    seeded = subprocess.run([sys.executable, "-c", SEED], cwd=ROOT, env=environment,
        capture_output=True, encoding="utf-8", timeout=90)
    assert seeded.returncode == 0, seeded.stderr
    metadata = json.loads(next(line.removeprefix("WIZARD_READY:") for line in seeded.stdout.splitlines()
        if line.startswith("WIZARD_READY:")))
    archive = tmp_path / "wizard-complete.immobak"
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
    assert "SOURCE_GONE_WIZARD_RECOVERY_OK" in recovered.stdout
    assert not (tmp_path / "wrong-ambient-data").exists()


@pytest.fixture
def embedded_image(tmp_path):
    image = tmp_path / "embedded.sqlite"
    identifier = "11111111-2222-3333-4444-555555555555"
    url = "/uploads/contract-wizard/" + identifier + ".pdf"
    pdf = b"%PDF-synthetic-checksummed-recovery-bytes" * 3000
    with sqlite3.connect(image) as db:
        db.executescript("""
            CREATE TABLE properties(id TEXT, portfolio_id TEXT);
            CREATE TABLE contracts(id TEXT, property_id TEXT, unit_id TEXT, tenant_id TEXT);
            CREATE TABLE documents(id TEXT, file_url TEXT, contract_id TEXT, property_id TEXT, unit_id TEXT);
            CREATE TABLE contract_wizard_drafts(id TEXT, pdf BLOB, pdf_sha256 TEXT, data TEXT, state TEXT,
                contract_id TEXT, document_id TEXT, portfolio_id TEXT, published_tenant_id TEXT);
            INSERT INTO properties VALUES ('property','portfolio');
            INSERT INTO contracts VALUES ('contract','property','unit','tenant');
            """)
        db.execute("INSERT INTO documents VALUES ('document',?,'contract','property','unit')", (url,))
        db.execute("INSERT INTO contract_wizard_drafts VALUES (?,?,?,?, 'committed','contract','document','portfolio','tenant')",
            (identifier, pdf, hashlib.sha256(pdf).hexdigest(), json.dumps({"property_id":"property","unit_id":"unit"})))
    return image


def test_virtual_pdf_is_proved_in_database_and_keeps_exact_url_during_rebase(embedded_image, tmp_path):
    report = validate_file_references(embedded_image, str(tmp_path), expected_upload_files=set())
    assert report.local_references == 1 and report.local_files == frozenset()
    assert rebase_file_references(embedded_image, str(tmp_path), tmp_path / "new-uploads", expected_upload_files=set()) == 0


@pytest.mark.parametrize("mutation", [
    "UPDATE contract_wizard_drafts SET pdf_sha256='" + "0" * 64 + "'",
    "UPDATE contract_wizard_drafts SET pdf=X'626164'",
    "UPDATE contract_wizard_drafts SET state='reviewed'",
    "UPDATE contract_wizard_drafts SET published_tenant_id='foreign-tenant'",
    "UPDATE contract_wizard_drafts SET data='{}'",
    "UPDATE documents SET contract_id='foreign-contract'",
    "UPDATE properties SET portfolio_id='foreign-portfolio'",
    "DROP TABLE contract_wizard_drafts",
    "UPDATE documents SET file_url='/uploads/contract-wizard/unowned.pdf'",
])
def test_virtual_pdf_never_bypasses_missing_bytes_or_wrong_publication_links(embedded_image, tmp_path, mutation):
    with sqlite3.connect(embedded_image) as db:
        db.execute(mutation)
    with pytest.raises(RecoveryError):
        validate_file_references(embedded_image, str(tmp_path), expected_upload_files=set())
