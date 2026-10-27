"""Authenticated public contracts and the controlled legacy compatibility route."""
import test_bank_imports_controlled as bank_tests
from fastapi.testclient import TestClient

from backend import auth
from backend.app import app
from backend.routers import bank_imports, reports

bank = bank_tests.bank


def test_legacy_route_stages_only_and_original_requires_authentication(bank, monkeypatch):
    service, actor, account = bank
    monkeypatch.setattr(bank_imports, 'store', service.store)
    monkeypatch.setattr(bank_imports, 'BankImports', lambda target: service)
    monkeypatch.setattr(reports, 'store', service.store)
    monkeypatch.setattr(reports, 'BankImports', lambda target: service)
    client = TestClient(app)
    headers = {'Authorization': f'Bearer {auth.create_access_token(actor)}'}
    raw = 'date;amount;text\r\n2026-10-01;1.23;Miete\r\n'
    response = client.post('/api/v1/reports/bookings/import', headers=headers, json={
        'account_id': account, 'csv_content': raw, 'idempotency_key': 'legacy-http-fixture'})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body['requires_confirmation'] and body['imported'] == 0
    assert body['preview']['source_provenance'] == 'submitted_text_utf8'
    assert service.store.list_bookings() == []
    identifier = body['preview']['id']
    assert client.get(f'/api/v1/bank-imports/{identifier}/original').status_code == 401
    original = client.get(f'/api/v1/bank-imports/{identifier}/original', headers=headers)
    assert original.status_code == 200 and original.content == raw.encode()
    assert original.headers['cache-control'] == 'private, no-store'


def test_internal_reader_can_read_but_cannot_confirm(bank, monkeypatch):
    service, actor, _ = bank
    preview, _ = bank_tests.stage(bank)
    monkeypatch.setattr(bank_imports, 'store', service.store)
    monkeypatch.setattr(bank_imports, 'BankImports', lambda target: service)
    reader = auth.register_user('bank-reader', 'reader@example.test', 'Lesekonto', 'Secret123', 'readonly')
    headers = {'Authorization': f'Bearer {auth.create_access_token(reader.id)}'}
    client = TestClient(app)
    response = client.get(f"/api/v1/bank-imports/{preview['id']}", headers=headers)
    assert response.status_code == 200, response.text
    assert response.json()['row_count'] == 2
    confirmation = bank_tests.confirm(bank, preview)
    denied = client.post(f"/api/v1/bank-imports/{preview['id']}/confirm", headers=headers,
                         json=confirmation.model_dump(mode='json'))
    assert denied.status_code == 403
    assert service.store.list_bookings() == []
