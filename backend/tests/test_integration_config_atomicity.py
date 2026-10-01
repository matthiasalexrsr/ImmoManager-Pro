"""Real file/process persistence and rollback for independently managed configs."""
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

import pytest
from fastapi.testclient import TestClient

from backend import auth
from backend.app import app
from backend.services.integrations.config_store import ConfigStoreError, JsonFileIntegrationConfigStore
from backend.services.integrations.manager import IntegrationManager
from backend.services.integrations.providers import EmailIntegrationProvider, WhatsAppIntegrationProvider


def manager(path):
    store = JsonFileIntegrationConfigStore(str(path))
    store.initialize()
    selected = IntegrationManager(store)
    selected.register(EmailIntegrationProvider())
    selected.register(WhatsAppIntegrationProvider())
    return selected


def test_independent_managers_merge_without_lost_configuration_or_masked_secret(tmp_path):
    path = tmp_path / 'integrations.json'
    first, second = manager(path), manager(path)
    first.update_config('email', {'smtp_password': 'synthetic-secret', 'smtp_host': 'smtp.invalid'})
    second.update_config('whatsapp', {'api_token': 'synthetic-token'})
    second.update_config('email', {'smtp_password': '***', 'sender_email': 'sender@example.invalid'})
    first.set_enabled('whatsapp', True)
    raw = json.loads(path.read_text(encoding='utf-8'))
    assert raw['config']['email'] == {'smtp_password': 'synthetic-secret', 'smtp_host': 'smtp.invalid', 'sender_email': 'sender@example.invalid'}
    assert raw['config']['whatsapp']['api_token'] == 'synthetic-token'
    assert second.get_integration('whatsapp')['enabled'] is True
    assert 'synthetic-secret' not in json.dumps(first.list_integrations())


def test_parallel_partial_settings_updates_keep_every_field(tmp_path):
    path = tmp_path / 'parallel.json'
    first, second = manager(path), manager(path)
    barrier = Barrier(2)
    def save(item):
        selected, fields = item
        barrier.wait(timeout=5)
        selected.update_config('email', fields)
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(save, [(first, {'smtp_host': 'smtp.invalid'}), (second, {'sender_email': 'sender@example.invalid'})]))
    assert set(json.loads(path.read_text())['config']['email']) == {'smtp_host', 'sender_email'}


def test_independent_process_updates_share_a_stable_file_lock(tmp_path):
    path = tmp_path / 'processes.json'
    manager(path)
    root = Path(__file__).resolve().parents[2]
    code = ('import sys; from backend.services.integrations.config_store import JsonFileIntegrationConfigStore; '
            's=JsonFileIntegrationConfigStore(sys.argv[1]); '
            's.update(lambda d: {**d, "config": {**d.get("config", {}), sys.argv[2]: {"field": sys.argv[2]}}})')
    def save(index):
        return subprocess.run([sys.executable, '-c', code, str(path), str(index)], cwd=root,
                              env={**os.environ, 'PYTHONUTF8': '1'}, capture_output=True, timeout=20)
    with ThreadPoolExecutor(max_workers=4) as pool:
        assert all(result.returncode == 0 for result in pool.map(save, range(4)))
    assert set(json.loads(path.read_text())['config']) == {'0', '1', '2', '3'}


@pytest.mark.parametrize('raw', [b'{broken', b'{"config":{},"config":{}}', b'{"enabled":{"email":"true"}}', b'{"config":[]}'])
def test_corrupt_configuration_is_never_replaced_with_empty_success(tmp_path, raw):
    path = tmp_path / 'damaged.json'
    path.write_bytes(raw)
    store = JsonFileIntegrationConfigStore(str(path))
    for operation in (store.initialize, store.load, lambda: store.save({}), lambda: store.update(lambda state: {})):
        with pytest.raises(ConfigStoreError):
            operation()
        assert path.read_bytes() == raw


def test_failed_replace_preserves_old_values_and_manager_reports_failure(tmp_path, monkeypatch):
    path = tmp_path / 'failed.json'
    selected = manager(path)
    selected.update_config('email', {'sender_email': 'old@example.invalid'})
    previous = path.read_bytes()
    def fail(*args):
        raise OSError('synthetic secret must not be printed')
    monkeypatch.setattr('backend.services.integrations.config_store.os.replace', fail)
    with pytest.raises(ConfigStoreError) as error:
        selected.update_config('email', {'sender_email': 'new@example.invalid'})
    assert error.value.published is False
    assert 'synthetic secret' not in str(error.value)
    assert path.read_bytes() == previous
    assert selected.get_integration('email')['config']['sender_email'] == 'old@example.invalid'
    assert not list(tmp_path.glob('*.tmp-*'))


def test_missing_config_is_a_truthful_service_error_without_overwriting_it(tmp_path, monkeypatch):
    path = tmp_path / 'missing.json'
    selected = manager(path)
    path.unlink()
    monkeypatch.setattr('backend.routers.integrations.integration_manager', selected)
    monkeypatch.setattr(auth, '_user_store', auth.InMemoryUserStore())
    monkeypatch.setattr(auth, '_auth_session_factory', None)
    owner = auth.register_user('config-owner', 'owner@example.invalid', 'Owner', 'Strong123', 'eigentuemer')
    with TestClient(app) as client:
        response = client.put('/api/v1/integrations/email/config', json={'config': {'smtp_host': 'new.invalid'}},
                              headers={'Authorization': 'Bearer ' + auth.create_access_token(owner.id)})
    assert response.status_code == 503
    assert not path.exists()
