"""The installed adapter executes observed request shapes through real HTTPX parsing."""
import base64
import hashlib
import json

import httpx

from backend.services.providers.teha_provider import TehaProvider
from backend.services.providers.teha_transport import TehaTransport

PDF = b"%PDF-1.7\n\x00\xffprovider original\n%%EOF"


def provider(handler):
    return TehaProvider(lambda **kwargs: TehaTransport(transport=httpx.MockTransport(handler), **kwargs))


def test_provider_document_output_has_actual_bytes_metadata_and_full_exchange():
    calls = []
    def handle(request):
        calls.append((request.method, request.url.path))
        if request.url.path == '/api/user':
            payload = {"id": 7, "mandantId": 1, "accessToken": "synthetic-access-token", "refreshToken": "synthetic-refresh-token", "error": None}
        elif request.url.path.endswith('/documents'):
            assert json.loads(request.content) == {"LiegNr": "00017"}
            payload = {"documents": [{"reference": "ref-a", "fileName": "Datei.pdf", "properties": {"unknown": {"future": True}}, "attachments": []}], "future_envelope": 42}
        else:
            assert request.url.path == '/api/Liegenschaften/document-content'
            assert json.loads(request.content) == {"LiegNr": "00017", "Ref": "ref-a"}
            payload = {"content": base64.b64encode(PDF).decode(), "unknown": [1, None]}
        return httpx.Response(200, json=payload)
    result = provider(handle).run({"action": "document", "lieg_nr": "00017", "reference": "ref-a"}, {"username": "test", "password": "synthetic-private-password"})
    assert result.success is True
    record = result.details['records'][0]
    assert base64.b64decode(record['content_base64']) == PDF
    assert record['content_sha256'] == hashlib.sha256(PDF).hexdigest()
    assert record['raw']['properties'] == {"unknown": {"future": True}}
    assert len(result.details['exchanges']) == 2
    assert 'synthetic-access-token' not in json.dumps(result.details)
    assert calls == [('POST', '/api/user'), ('POST', '/api/Liegenschaften/documents'), ('POST', '/api/Liegenschaften/document-content')]


def test_unknown_outbound_actions_never_enter_transport():
    def forbidden(**kwargs):
        raise AssertionError('No transport can be constructed for an unknown write')
    adapter = TehaProvider(forbidden)
    for action in ('send_costs', 'send_users', 'maintenance_order', 'POST', 'https://other.test'):
        result = adapter.run({"action": action}, {})
        assert not result.success
        assert result.details['code'] == 'teha_write_contract_missing'
    assert all(action['effect'] == 'read' for action in adapter.manifest.actions)


def test_expired_auth_produces_safe_explicit_retry_not_automatic_login_loop():
    calls = []
    def handle(request):
        calls.append(request.url.path)
        return httpx.Response(200, json={"id": 7, "mandantId": 1, "accessToken": "synthetic-token", "error": None}) if request.url.path == '/api/user' else httpx.Response(401, json={"error": "private-error"})
    result = provider(handle).run({"action": "inventory"}, {"username": "test", "password": "synthetic-pass"})
    assert not result.success
    assert calls == ['/api/user', '/api/liegenschaften']
    assert 'private-error' not in result.message
    assert result.details['code'] == 'authentication_expired'
