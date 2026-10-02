"""Real encrypted source-gone recovery preserves confirmed private disclosure."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from backend.services.full_recovery import create_full_backup, restore_full_backup
from backend.tests.test_full_recovery import PASSPHRASE, plan, runtime_template  # noqa: F401

ROOT = Path(__file__).resolve().parents[2]
SEED = r'''
import json
from datetime import datetime, timedelta, timezone
from backend.app import app
from backend.dependencies import store
from backend.models import ContractCreate, ReceivableCreate, TenantCreate, UnitCreate
from fastapi.testclient import TestClient

with TestClient(app) as client:
    def request(method, url, headers, payload=None, expected=200):
        response = client.request(method, '/api/v1'+url, headers=headers, json=payload)
        assert response.status_code == expected, (response.status_code, response.text)
        return response.json()
    login = request('POST', '/auth/login', {},
        {'username':'recovery-owner','password':'SyntheticPassword123!'})
    headers = {'Authorization':'Bearer '+login['access_token']}
    actor = request('GET', '/auth/me', headers)['id']
    prop = store.list_properties()[0]
    unit = store.create_unit(UnitCreate(property_id=prop.id, label='Own lifecycle recovery unit', unit_type='apartment'))
    tenant = store.create_tenant(TenantCreate(full_name='Lifecycle recovery tenant Ä €'))
    today = datetime.now(timezone.utc).date()
    contract = store.create_contract(ContractCreate(contract_number='OWN-LIFECYCLE-RECOVERY',
        property_id=prop.id, unit_id=unit.id, tenant_id=tenant.id, start_date=today-timedelta(days=120)))
    cash_counts = [len(store.list_bookings()),len(store.list_payments())]
    # Due dates after the end do not assert a future monthly service period.
    receivable = store.create_receivable(ReceivableCreate(contract_id=contract.id,
        due_date=today+timedelta(days=5), amount_due=37.15, description='Explicit retained post-end claim'))
    other = request('POST','/auth/users',headers,{'username':'lifecycle-private-manager',
        'email':'lifecycle-private@example.test','full_name':'Own private author',
        'password':'SyntheticPrivatePassword123!','role':'verwalter',
        'portfolio_access':'selected','portfolio_ids':[prop.portfolio_id]},expected=201)
    private_login = request('POST','/auth/login',{},
        {'username':'lifecycle-private-manager','password':'SyntheticPrivatePassword123!'})
    other_headers = {'Authorization':'Bearer '+private_login['access_token']}
    base = '/contracts/'+contract.id+'/lifecycle'
    def fresh_etag():
        response = client.get('/api/v1/contracts/'+contract.id,headers=headers)
        assert response.status_code == 200
        return response.headers['etag']
    def create(key, end, reason, auth=headers):
        return request('POST',base+'/drafts',auth,{'idempotency_key':key,
            'expected_contract_etag':fresh_etag(),'data':{'operation':'termination',
            'termination_end_date':end.isoformat(),'reason':reason}},expected=201)
    def confirm(row, key):
        payload = {'idempotency_key':key+'-review','expected_revision':row['revision'],
            'expected_contract_etag':row['source_contract_etag']}
        reviewed = request('POST',base+'/drafts/'+row['id']+'/review',headers,payload)
        payload.update(idempotency_key=key+'-confirm',expected_revision=reviewed['revision'],
            reviewed_hash=reviewed['review_hash'],confirmed=True)
        result = request('POST',base+'/drafts/'+row['id']+'/confirm',headers,payload)
        return result,payload
    old,old_command = confirm(create('recovery-old',today+timedelta(days=60),
        'ORIGINAL_ACCEPTED_REASON_601'), 'old')
    assert old['state'] == 'pending_effective'
    new,new_command = confirm(create('recovery-new',today-timedelta(days=1),
        'CURRENT_ACCEPTED_REASON_602'), 'new')
    assert new['state'] == 'completed'
    private = create('recovery-private',today-timedelta(days=2),'PRIVATE_OTHER_REASON_603',other_headers)
    graph = request('GET','/admin/dsgvo/tenant/'+tenant.id+'/export',headers)
    assert graph['scope']['private_lifecycle_drafts']['count'] == 1
    assert 'PRIVATE_OTHER_REASON_603' not in json.dumps(graph)
    print('LIFECYCLE_PRIVACY_READY:'+json.dumps({'tenant_id':tenant.id,'contract_id':contract.id,
        'old':old,'new':new,'old_command':old_command,'new_command':new_command,
        'private_id':private['id'],'private_actor':other['id'],'actor':actor,
        'access_token':login['access_token'],'cash_counts':cash_counts,
        'receivable':store.get_receivable(receivable.id).model_dump(mode='json'),
        'drafts':graph['contract_lifecycle_drafts'],'commands':graph['contract_lifecycle_commands'],
        'source_sha256':graph['scope']['contract_lifecycle']['source_sha256']}))
'''

PROBE = r'''
import hashlib, json, sys
from pathlib import Path
from backend.services.full_recovery import load_recovered_environment
load_recovered_environment(Path(sys.argv[1]))
from backend.app import app
from backend.dependencies import store
from fastapi.testclient import TestClient
expected = json.loads(sys.stdin.read())
with TestClient(app) as client:
    login = client.post('/api/v1/auth/login',json={'username':'recovery-owner','password':'SyntheticPassword123!'})
    assert login.status_code == 200, login.text
    headers = {'Authorization':'Bearer '+login.json()['access_token']}
    assert client.get('/api/v1/auth/me',headers={'Authorization':'Bearer '+expected['access_token']}).status_code == 401
    base = '/api/v1/contracts/'+expected['contract_id']+'/lifecycle'
    # Replay still returns each original result, including the earlier accepted
    # pending state; it must not rewrite the present supersession chain.
    for key in ('old','new'):
        response = client.post(base+'/drafts/'+expected[key]['id']+'/confirm',
            headers=headers,json=expected[key+'_command'])
        assert response.status_code == 200, response.text
        assert response.json() == expected[key]
    url = '/api/v1/admin/dsgvo/tenant/'+expected['tenant_id']
    response = client.get(url+'/export',headers=headers)
    assert response.status_code == 200, response.text
    assert hashlib.sha256(response.content).hexdigest() == response.headers['x-content-sha256']
    graph = response.json()
    assert graph['contract_lifecycle_drafts'] == expected['drafts']
    assert graph['contract_lifecycle_commands'] == expected['commands']
    assert graph['scope']['contract_lifecycle']['source_sha256'] == expected['source_sha256']
    assert graph['scope']['private_lifecycle_drafts']['count'] == 1
    encoded = json.dumps(graph)
    assert 'PRIVATE_OTHER_REASON_603' not in encoded and expected['private_id'] not in encoded
    assert expected['private_actor'] not in encoded
    commands = {row['draft_id']:row for row in graph['contract_lifecycle_commands']}
    assert commands[expected['old']['id']]['result'] == expected['old']
    assert {row['actor_id'] for row in commands.values()} == {expected['actor']}
    preview = client.get(url+'/anonymization-preview',headers=headers)
    assert preview.status_code == 200,preview.text
    plan = preview.json()
    assert plan['can_anonymize'] and plan['retained_personal_evidence']['contract_lifecycle_drafts']['count'] == 2
    saved = client.post(url+'/anonymize',headers=headers,json={
        'plan_hash':plan['plan_hash'],'confirm_tenant_id':expected['tenant_id']})
    assert saved.status_code == 200,saved.text
    after = client.get(url+'/export',headers=headers)
    assert after.status_code == 200,after.text
    assert after.json()['contract_lifecycle_drafts'] == expected['drafts']
    assert after.json()['contract_lifecycle_commands'] == expected['commands']
    assert after.json()['scope']['contract_lifecycle']['source_sha256'] == expected['source_sha256']
    assert [len(store.list_bookings()),len(store.list_payments())] == expected['cash_counts']
    assert store.get_receivable(expected['receivable']['id']).model_dump(mode='json') == expected['receivable']
    assert store.get_tenant(expected['tenant_id']).archived
print('SOURCE_GONE_LIFECYCLE_PRIVACY_OK')
'''


def test_source_gone_encrypted_full_restore_replays_retains_and_discloses_lifecycle(plan, tmp_path):  # noqa: F811
    environment = {**os.environ, **plan.configuration, "PYTHONUTF8": "1", "AI_ENABLED": "false",
                   "OPERATIONAL_SCHEDULER_ENABLED": "false", "BACKUP_SCHEDULER_ENABLED": "false"}
    seeded = subprocess.run([sys.executable, "-c", SEED], cwd=ROOT, env=environment,
        capture_output=True, encoding="utf-8", timeout=90)
    assert seeded.returncode == 0, seeded.stderr
    metadata = json.loads(next(line.removeprefix("LIFECYCLE_PRIVACY_READY:") for line in seeded.stdout.splitlines()
                              if line.startswith("LIFECYCLE_PRIVACY_READY:")))
    archive = tmp_path / "lifecycle-privacy.immobak"
    create_full_backup(plan, archive, PASSPHRASE, offline=True)
    assert b"ORIGINAL_ACCEPTED_REASON_601" not in archive.read_bytes()
    assert metadata["access_token"].encode() not in archive.read_bytes()
    source = plan.database.parent.resolve()
    assert source.is_relative_to(tmp_path.resolve()) and source.name == "source"
    shutil.rmtree(source)
    assert not source.exists()
    target = tmp_path / "recovered"
    result = restore_full_backup(archive, target, PASSPHRASE)
    assert result["signing_key_rotated"]
    environment.update(DATABASE_URL="sqlite:///:memory:", DATA_DIR=str(tmp_path / "wrong-ambient-data"),
        JWT_SECRET_KEY="deliberately-wrong-ambient-signing-key", SQLITE_PERSISTENT_STORE="false")
    recovered = subprocess.run([sys.executable, "-c", PROBE, str(target)], cwd=ROOT, env=environment,
        input=json.dumps(metadata), capture_output=True, encoding="utf-8", timeout=90)
    assert recovered.returncode == 0, recovered.stderr
    assert "SOURCE_GONE_LIFECYCLE_PRIVACY_OK" in recovered.stdout
    assert not (tmp_path / "wrong-ambient-data").exists()
