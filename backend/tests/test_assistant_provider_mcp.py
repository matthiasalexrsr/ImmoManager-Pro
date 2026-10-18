"""Scoped application tool protocols; synthetic account streams, never inference."""
import json
import tomllib
from collections import deque
from types import SimpleNamespace

import pytest

from backend.services import assistant_provider_claude as claude
from backend.services import assistant_provider_codex as codex
from backend.services import assistant_providers as hub
from backend.services.assistant_provider_prompt import user_payload
from backend.services.assistant_provider_protocol import APPLICATION_TOOLS, ProviderError, application_mcp
from backend.tests.test_assistant_provider_claude import transport as transport
from backend.tests.test_assistant_provider_security import ScenarioRpc
from backend.tests.test_assistant_providers import private_accounts as private_accounts


def broker():
    return {'url': 'http://127.0.0.1:49152/mcp', 'server_name': 'immomanager',
            'headers': {'Authorization': 'Bearer SYNTHETIC-EPHEMERAL-BROKER-TOKEN'}, 'tools': sorted(APPLICATION_TOOLS)}


class ApplicationRpc(ScenarioRpc):
    def call(self, method, params=None, **kwargs):
        if method == 'mcpServerStatus/list':
            return {'data': [{'name': 'immomanager', 'runtimeStatus': 'connected',
                             'httpOrigin': broker()['url'].removesuffix('/mcp'),
                             'tools': {name: {'name': name} for name in APPLICATION_TOOLS}}]}
        return super().call(method, params, **kwargs)


def frame(**event):
    return ('stdout', json.dumps(event) + '\n')


def claude_init(**extra):
    return frame(type='system', subtype='init', tools=['mcp__immomanager__' + name for name in sorted(APPLICATION_TOOLS)],
                 mcp_servers=[{'name': 'immomanager', 'status': 'connected'}], plugins=[], **extra)


@pytest.mark.parametrize('url', ['https://127.0.0.1/mcp', 'http://localhost:2/mcp', 'http://evil.test:80/mcp',
    'http://127.0.0.1:2/mcp?q=x', 'http://user:pass@127.0.0.1:2/mcp', 'http://127.0.0.1:2/mcp#x',
    'file:///secret', 'http://127.0.0.1:99999/mcp', 'http://127.0.0.1:2/../secret', 'http://127.0.0.1:2/api/users'])
def test_application_connection_cannot_become_a_remote_or_file_capability(url):
    value = broker()
    value['url'] = url
    with pytest.raises(ProviderError, match='geschützte Verbindung'):
        application_mcp({'_application_mcp': value})


@pytest.mark.parametrize('change', [{'tools': ['immo_search', 'Bash']}, {'tools': ['immo_search', 'immo_search']},
    {'server_name': 'other'}, {'headers': {'Authorization': 'Bearer short'}},
    {'headers': {'Authorization': 'Bearer synthetic\nInjected: x'}}, {'command': 'powershell'}])
def test_application_configuration_has_no_implicit_tools_headers_or_commands(change):
    with pytest.raises(ProviderError):
        application_mcp({'_application_mcp': {**broker(), **change}})


def test_private_mcp_token_never_enters_model_payload_and_finance_pages_are_explicit():
    request = {'_application_mcp': broker(), 'local_analysis': {'finance': {'definition': {'kind': 'cash-v2'},
               'sources': [{'id': str(index)} for index in range(251)], 'totals': {'income': '0.30'}}}}
    raw = user_payload(request)
    result = json.loads(raw)['local_analysis']['finance']
    assert 'SYNTHETIC-EPHEMERAL' not in raw and '49152' not in raw and '_application_mcp' not in raw
    assert result['totals'] == {'income': '0.30'} and len(result['sources']) == 200
    assert result['coverage']['has_more'] and result['coverage']['total'] == 251
    assert result['coverage']['continuation_tool'] == 'immo_report' and result['coverage']['next_cursor'] is None
    assert len(request['local_analysis']['finance']['sources']) == 251


def test_codex_private_native_configuration_has_exact_application_server(monkeypatch, tmp_path):
    writes: list[str] = []
    lines = deque([frame(id=1, result={})])
    transport = SimpleNamespace(write_line=writes.append, next_line=lambda timeout: lines.popleft() if lines else None,
                                process=SimpleNamespace(poll=lambda: None), close=lambda: None)
    monkeypatch.setattr(codex, 'CliProcess', lambda *args, **kwargs: transport)
    with codex.CodexRpc(SimpleNamespace(path=tmp_path), ['synthetic'], mcp=broker()):
        config = tomllib.loads((tmp_path / 'config.toml').read_text())
    assert set(config['mcp_servers']) == {'immomanager'}
    server = config['mcp_servers']['immomanager']
    assert server['url'] == broker()['url'] and server['http_headers'] == broker()['headers']
    assert server['enabled'] and server['required'] and set(server['enabled_tools']) == APPLICATION_TOOLS
    assert config['features']['shell_tool'] is False and config['features']['plugins'] is False
    assert json.loads(writes[0])['params']['capabilities']['experimentalApi'] is False
    assert 'SYNTHETIC-EPHEMERAL' not in str(writes)


@pytest.mark.parametrize('tool', sorted(APPLICATION_TOOLS))
def test_codex_accepts_only_exact_scoped_application_tool(monkeypatch, tmp_path, tool):
    rpc = ApplicationRpc(events=[{'method': 'item/started', 'params': {'threadId': 'thread-current', 'turnId': 'turn-current',
          'item': {'type': 'mcpToolCall', 'server': 'immomanager', 'tool': tool}}},
        {'method': 'item/completed', 'params': {'item': {'type': 'agentMessage', 'id': 'answer', 'text': 'Geprüfte Antwort'}}},
        {'method': 'turn/completed', 'params': {'turn': {'id': 'turn-current', 'status': 'completed'}}}])
    monkeypatch.setattr(codex, 'CodexRpc', lambda *args, **kwargs: rpc)
    result = codex.execute(SimpleNamespace(path=tmp_path), ['synthetic'], {'_application_mcp': broker()}, lambda event: None, lambda: False)
    assert result['text'] == 'Geprüfte Antwort' and rpc.closed


@pytest.mark.parametrize('item', [{'type': 'mcpToolCall', 'server': 'other', 'tool': 'immo_read'},
    {'type': 'mcpToolCall', 'server': 'immomanager', 'tool': 'write'}, {'type': 'commandExecution'},
    {'type': 'fileChange'}, {'type': 'dynamicToolCall'}, {'type': 'collabAgentToolCall'}])
def test_codex_rejects_other_server_tools_and_side_effect_paths(monkeypatch, tmp_path, item):
    rpc = ApplicationRpc(events=[{'method': 'item/started', 'params': {'item': item}}])
    monkeypatch.setattr(codex, 'CodexRpc', lambda *args, **kwargs: rpc)
    with pytest.raises(ProviderError) as rejected:
        codex.execute(SimpleNamespace(path=tmp_path), ['synthetic'], {'_application_mcp': broker()}, lambda event: None, lambda: False)
    assert rejected.value.code == 'unexpected_tool' and rpc.closed


@pytest.mark.parametrize('tool', sorted(APPLICATION_TOOLS))
def test_claude_all_application_tools_and_only_private_mcp_config_are_accepted(transport, tool):
    transport.scripts.append({'events': [claude_init(), frame(type='assistant', message={'content': [
        {'type': 'tool_use', 'id': 'tool-current', 'name': 'mcp__immomanager__' + tool, 'input': {}}]}),
        frame(type='result', subtype='success', is_error=False, result='Geprüfte Antwort')]})
    result = claude.execute(transport.profile, transport.executable, {'_application_mcp': broker()}, lambda event: None, lambda: False)
    child = transport.children[0]
    config = json.loads((transport.profile.path / 'application-mcp.json').read_text())
    assert set(config['mcpServers']) == {'immomanager'} and config['mcpServers']['immomanager']['headers'] == broker()['headers']
    assert '--safe-mode' not in child.argv and '--restricted' in child.argv and '--strict-mcp-config' in child.argv
    assert set(child.argv[child.argv.index('--allowedTools') + 1].split(',')) == {'mcp__immomanager__' + name for name in APPLICATION_TOOLS}
    assert child.argv[child.argv.index('--tools') + 1] == ''
    assert 'SYNTHETIC-EPHEMERAL' not in str(child.argv) + str(child.writes)
    assert result['text'] == 'Geprüfte Antwort'


@pytest.mark.parametrize('server', [{'name': 'other', 'status': 'connected'}, {'name': 'immomanager', 'status': 'failed'}])
def test_claude_never_answers_without_its_exact_connected_broker(transport, server):
    transport.scripts.append({'events': [frame(type='system', subtype='init', tools=['mcp__immomanager__' + name for name in APPLICATION_TOOLS],
        mcp_servers=[server], plugins=[])]})
    with pytest.raises(ProviderError) as rejected:
        claude.execute(transport.profile, transport.executable, {'_application_mcp': broker()}, lambda event: None, lambda: False)
    assert rejected.value.code == 'provider_isolation_failed'


@pytest.mark.parametrize('name', ['Bash', 'Read', 'mcp__other__immo_read', 'mcp__immomanager__write', 'EndConversation'])
def test_claude_rejects_foreign_or_builtin_tools_even_after_valid_initialization(transport, name):
    transport.scripts.append({'events': [claude_init(), frame(type='assistant', message={'content': [{'type': 'tool_use', 'name': name}]})]})
    with pytest.raises(ProviderError) as rejected:
        claude.execute(transport.profile, transport.executable, {'_application_mcp': broker()}, lambda event: None, lambda: False)
    assert rejected.value.code == 'provider_isolation_failed' and transport.children[0].closed


def test_explicit_auth_probe_does_not_infer_or_promote_an_unverified_model_list(private_accounts, monkeypatch):
    monkeypatch.setattr(hub, 'executable', lambda provider: ['synthetic'])
    calls = []
    def status(*args):
        calls.append('native-auth-only')
        return {'connected': False, 'auth_mode': 'none'}
    monkeypatch.setattr(hub, '_adapter', lambda provider: SimpleNamespace(status=status))
    result = hub.probe_connection('probe-owner', 'codex')
    assert calls == ['native-auth-only'] and result['client_available']
    assert result['auth_probe_status'] == 'disconnected' and not result['connected']
    assert not result['account_access_verified_by_inference'] and result['model_catalog_source'] == 'unverified_defaults'


def test_codex_catalog_pages_preserve_actual_effort_and_image_capabilities():
    pages = deque([{'data': [{'id': 'model-one', 'supportedReasoningEfforts': [{'reasoningEffort': 'high'}], 'inputModalities': ['text', 'image']}], 'nextCursor': 'page-two'},
                   {'data': [{'id': 'model-two'}], 'nextCursor': None}])
    calls = []
    def call(method, params):
        calls.append(params)
        return pages.popleft()
    result = codex._models(SimpleNamespace(call=call))
    assert [item['id'] for item in result] == ['model-one', 'model-two']
    assert result[0]['supported_efforts'] == ['high'] and result[0]['input_modalities'] == ['text', 'image']
    assert calls[1]['cursor'] == 'page-two'


@pytest.mark.parametrize('inventory', [{}, {'data': []}, {'data': [{'name': 'immomanager', 'runtimeStatus': 'failed', 'tools': {}}]},
    {'data': [{'name': 'other', 'runtimeStatus': 'connected', 'tools': {}}]},
    {'data': [{'name': 'immomanager', 'runtimeStatus': 'connected', 'tools': {'immo_read': {}}}]},
    {'data': [{'name': 'immomanager', 'runtimeStatus': 'connected', 'httpOrigin': 'https://foreign.test', 'tools': {name: {} for name in APPLICATION_TOOLS}}]},
    {'data': [{'name': 'immomanager', 'runtimeStatus': 'connected', 'pluginId': 'foreign-plugin', 'tools': {name: {} for name in APPLICATION_TOOLS}}]}])
def test_codex_inventory_mismatch_fails_before_model_submission(monkeypatch, tmp_path, inventory):
    class BadInventory(ApplicationRpc):
        def call(self, method, params=None, **kwargs):
            if method == 'mcpServerStatus/list':
                return inventory
            return super().call(method, params, **kwargs)
    rpc = BadInventory()
    monkeypatch.setattr(codex, 'CodexRpc', lambda *args, **kwargs: rpc)
    with pytest.raises(ProviderError) as rejected:
        codex.execute(SimpleNamespace(path=tmp_path), ['synthetic'], {'_application_mcp': broker()}, lambda event: None, lambda: False)
    assert rejected.value.code == 'provider_isolation_failed' and not rejected.value.uncertain
    assert not any(method == 'turn/start' for method, _ in rpc.calls)


def test_auth_probe_is_explicit_and_does_not_relabel_stored_catalog_on_get(private_accounts, monkeypatch):
    calls = []
    monkeypatch.setattr(hub, 'executable', lambda provider: ['synthetic'])
    def status(profile, executable, cancelled):
        calls.append('probe')
        from backend.services.secret_box import write_private_file
        write_private_file(profile.path / 'auth.json', b'{"token":"SYNTHETIC"}')
        return {'connected': True, 'auth_mode': 'chatgpt', 'models': [{'id': 'actual-model', 'label': 'Actual Model'}],
                'model_discovery_status': 'verified'}
    monkeypatch.setattr(hub, '_adapter', lambda provider: SimpleNamespace(status=status))
    assert hub.connection_status('probe-actual', 'codex')['auth_probe_status'] == 'unknown'
    result = hub.probe_connection('probe-actual', 'codex')
    assert result['connected'] and result['auth_probe_status'] == 'verified'
    assert result['models'] == [{'id': 'actual-model', 'label': 'Actual Model'}]
    assert result['model_catalog_source'] == 'account_client' and not result['account_access_verified_by_inference']
    hub.connection_status('probe-actual', 'codex')
    assert calls == ['probe']
