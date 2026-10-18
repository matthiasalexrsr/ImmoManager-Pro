"""Local output and account-hub acceptance without external login/inference."""
import json
import queue
import threading
from types import SimpleNamespace
from typing import Any

import pytest

from backend.services import assistant_provider_vault as vault
from backend.services import assistant_providers as hub
from backend.services.assistant_provider_prompt import finish_answer, user_payload
from backend.services.assistant_provider_protocol import ProviderError
from backend.services.secret_box import SecretBox, write_private_file


@pytest.fixture
def private_accounts(monkeypatch, tmp_path):
    data = tmp_path / 'data'
    uploads = tmp_path / 'uploads'
    data.mkdir()
    uploads.mkdir()
    box = SecretBox(tmp_path / 'keys.json')
    monkeypatch.setattr(vault, 'get_data_dir', lambda: data)
    monkeypatch.setattr(vault, 'get_uploads_dir', lambda: uploads)
    monkeypatch.setattr(vault, 'default_secret_box', lambda: box)
    monkeypatch.setattr(hub, 'get_data_dir', lambda: data)
    return SimpleNamespace(data=data, uploads=uploads)


def test_local_mode_works_without_client_credentials_or_network(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail('Local mode must not inspect provider credentials or call the CLI')
    monkeypatch.setattr(hub, 'executable', forbidden)
    monkeypatch.setattr(vault, 'load', forbidden)
    events: list[dict] = []
    result = hub.execute('local-actor', 'local', {'local_analysis': {'findings': [], 'documents': [{
        'source': {'id': 'doc-test'}, 'document_type': 'invoice', 'summary': 'Originalrechnung',
        'supplier': 'Beispielbetrieb', 'total_amount': '0.30', 'text': 'Prüftext aus lokalem Original',
    }] }}, events.append, lambda: False)
    assert result['usage'] == {'mode': 'local', 'model_used': False}
    assert 'Prüftext aus lokalem Original' in result['text']
    assert 'Beispielbetrieb' in result['text']
    assert result['proposals'] == [] and events[0]['text'] == result['text']


def test_local_finance_is_readable_exact_and_includes_zero_months():
    finance = {'basis': 'cash-v2', 'currency': 'CHF', 'filters': {'date_from': '2026-01-01', 'date_to': '2026-02-28'},
        'totals': {'income': '0.30', 'expense': '0.10', 'net': '0.20'}, 'sources': [], 'result_hash': 'known-hash',
        'monthly': [{'month': '2026-01', 'income': '0.30', 'expense': '0.10', 'net': '0.20'},
                    {'month': '2026-02', 'income': '0.00', 'expense': '0.00', 'net': '0.00'}]}
    result = hub.execute('local-actor', 'local', {'local_analysis': {'finance': finance}}, lambda e: None, lambda: False)
    text = result['text']
    assert '0,30 CHF' in text and '0,20 CHF' in text and '2026-02' in text and '0,00 CHF' in text
    assert '| Kennzahl | Betrag |' in text and '```json' not in text
    assert '2026-01-01 bis 2026-02-28' in text and 'known-hash' in text


def test_provider_prompt_bounds_sources_explicitly_without_mutating_financial_result():
    original: dict[str, Any] = {'local_analysis': {'finance': {'sources': [{'id': str(i)} for i in range(205)],
        'totals': {'income': '1234567890.30'}, 'monthly': [{'month': '2026-01', 'income': '1234567890.30'}]}},
        'attachments': [{'name': 'image.png', 'data_base64': 'private-image', 'sha256': 'image-hash'}]}
    result = json.loads(user_payload(original))
    assert len(result['local_analysis']['finance']['sources']) == 200
    assert result['local_analysis']['finance']['sources_omitted'] == 5
    assert result['local_analysis']['finance']['totals']['income'] == '1234567890.30'
    assert '205 Quellen' in result['omissions'][0]
    assert len(original['local_analysis']['finance']['sources']) == 205
    assert 'private-image' not in user_payload(original) and 'image-hash' in user_payload(original)


@pytest.mark.parametrize('invalid', ['{bad json', '{}', '[2]'])
def test_invalid_proposal_is_visible_and_never_created(invalid):
    result = finish_answer('Antwort\n```immomanager-proposals\n' + invalid + '\n```')
    assert not result['proposals'] and 'kein Entwurf erzeugt' in result['text']
    assert 'Antwort' in result['text']


def test_valid_proposal_is_separate_from_visible_answer():
    result = finish_answer('Vorschlag prüfen.\n```immomanager-proposals\n[{"kind":"task","values":{"title":"Prüfen"}}]\n```')
    assert result['text'] == 'Vorschlag prüfen.'
    assert result['proposals'][0]['values']['title'] == 'Prüfen'


def test_login_is_idempotent_private_and_codes_never_persist(private_accounts, monkeypatch):
    ready, release = threading.Event(), threading.Event()
    received = []
    def login(profile, executable, emit_state, cancelled, codes):
        emit_state({'status': 'awaiting_authorization', 'auth_url': 'https://claude.ai/oauth/authorize?state=test',
                    'can_submit_code': True, 'access_token': 'DO-NOT-PUBLISH'})
        ready.set()
        assert release.wait(5)
        while not codes.empty():
            received.append(codes.get_nowait())
        write_private_file(profile.path / '.credentials.json', b'{"token":"SYNTHETIC-ACCOUNT-TOKEN"}')
        return {'connected': True, 'auth_method': 'claude.ai'}
    monkeypatch.setattr(hub, 'executable', lambda provider: ['synthetic-claude'])
    monkeypatch.setattr(hub, '_adapter', lambda provider: SimpleNamespace(login=login))
    try:
        first = hub.start_login('login-owner-a', 'claude')
        assert ready.wait(5)
        current = hub.connection_status('login-owner-a', 'claude')
        identifier = current['pending_login']['id']
        assert first['pending_login']['id'] == identifier
        assert hub.start_login('login-owner-a', 'claude')['pending_login']['id'] == identifier
        assert 'DO-NOT-PUBLISH' not in str(current)
        assert hub.connection_status('login-owner-b', 'claude')['pending_login'] is None
        with pytest.raises(ProviderError):
            hub.complete_login('login-owner-b', 'claude', identifier, 'SYNTHETIC-ONE-TIME-CODE')
        hub.complete_login('login-owner-a', 'claude', identifier, 'SYNTHETIC-ONE-TIME-CODE')
        hub.complete_login('login-owner-a', 'claude', identifier, 'SYNTHETIC-ONE-TIME-CODE')
    finally:
        release.set()
        job = hub._logins[hub._identity('login-owner-a', 'claude')]
        job['thread'].join(5)
    assert not job['thread'].is_alive() and received == ['SYNTHETIC-ONE-TIME-CODE']
    state = hub.connection_status('login-owner-a', 'claude')
    assert state['connected'] and not state['account_access_verified_by_inference']
    assert 'SYNTHETIC-ACCOUNT-TOKEN' not in str(state)
    assert 'SYNTHETIC-ONE-TIME-CODE' not in str(job['public'])
    assert job['codes'].empty()
    assert not list((private_accounts.data / 'assistant-runtime').glob('*-claude-*'))
    raw = vault._vault_path('login-owner-a', 'claude').read_text()
    assert 'SYNTHETIC-ACCOUNT-TOKEN' not in raw


def test_cancelled_local_request_has_no_output():
    events: list[dict] = []
    with pytest.raises(ProviderError) as error:
        hub.execute('actor-cancelled', 'local', {}, events.append, lambda: True)
    assert error.value.code == 'cancelled' and not events


def test_crash_profile_cleanup_is_exactly_account_and_provider_scoped(private_accounts):
    root = private_accounts.data / 'assistant-runtime'
    root.mkdir()
    stale = root / (vault.actor_key('actor-a') + '-codex-crash')
    other_actor = root / (vault.actor_key('actor-b') + '-codex-active')
    other_provider = root / (vault.actor_key('actor-a') + '-claude-active')
    for path in (stale, other_actor, other_provider):
        path.mkdir()
        (path / 'marker').write_text('synthetic')
    with vault.ProfileLease('actor-a', 'codex'):
        assert not stale.exists() and other_actor.exists() and other_provider.exists()


def test_account_lease_is_nonblocking(private_accounts):
    with vault.ProfileLease('actor-a', 'codex'):
        with pytest.raises(ProviderError) as busy:
            vault.ProfileLease('actor-a', 'codex')
        assert busy.value.code == 'provider_busy'


def test_queue_has_no_one_time_code_after_cancelled_login(private_accounts, monkeypatch):
    def login(profile, executable, emit_state, cancelled, codes):
        emit_state({'status': 'awaiting_authorization', 'can_submit_code': True})
        codes.put('SYNTHETIC-UNUSED-CODE')
        raise ProviderError('Cancelled', 'cancelled')
    monkeypatch.setattr(hub, 'executable', lambda provider: ['synthetic'])
    monkeypatch.setattr(hub, '_adapter', lambda provider: SimpleNamespace(login=login))
    hub.start_login('cancel-login', 'claude')
    job = hub._logins[hub._identity('cancel-login', 'claude')]
    job['thread'].join(5)
    assert job['public']['status'] == 'cancelled'
    with pytest.raises(queue.Empty):
        job['codes'].get_nowait()
