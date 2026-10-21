"""Communication records keep their context, history and useful validation errors."""
import os
from datetime import date

import pytest
from fastapi.testclient import TestClient

from backend import auth
from backend.app import app
from backend.dependencies import store
from backend.models import (
    ContractCreate,
    MessageCreate,
    MessageThreadCreate,
    PortfolioCreate,
    PropertyCreate,
    TenantCreate,
    UnitCreate,
)


@pytest.fixture
def context():
    if os.environ.get('IMMO_EXPECT_POSTGRES') == 'true':
        assert hasattr(store, 'db') and store.db.get_bind().dialect.name == 'postgresql'
    auth.clear_users()
    store.clear_all()
    owner = auth.register_user('office-records', 'office@example.test', 'Prüfung', 'Secret123', 'eigentuemer')
    client = TestClient(app, headers={'Authorization': 'Bearer ' + auth.create_access_token(owner.id)})
    portfolio = store.create_portfolio(PortfolioCreate(name='Prüfbestand'))
    a, b = [store.create_property(PropertyCreate(portfolio_id=portfolio.id, name=name, property_type='residential'))
            for name in ('Haus A', 'Haus B')]
    ua, ub = [store.create_unit(UnitCreate(property_id=prop.id, label='Wohnung', unit_type='residential')) for prop in (a, b)]
    tenant = store.create_tenant(TenantCreate(full_name='Prüfpartei'))
    lease = store.create_contract(ContractCreate(contract_number='PR-1', property_id=a.id, unit_id=ua.id,
                                                tenant_id=tenant.id, start_date=date(2026, 1, 1)))
    yield client, a, b, ua, ub, lease
    store.clear_all()
    auth.clear_users()


@pytest.mark.parametrize('field', ['property_id', 'unit_id', 'contract_id', 'participant_ids'])
def test_unavailable_thread_reference_is_rejected_without_creating_a_record(context, field):
    client, *_ = context
    response = client.post('/api/v1/messages/threads', json={'subject': 'Prüfung', field: 'not-present'})
    assert response.status_code in (400, 404, 422), response.text
    assert store.list_message_threads() == []


def test_thread_location_and_contract_must_describe_the_same_dossier(context):
    client, a, b, ua, ub, lease = context
    for values in ({'property_id': a.id, 'unit_id': ub.id}, {'unit_id': ub.id, 'contract_id': lease.id},
                   {'property_id': b.id, 'contract_id': lease.id}):
        response = client.post('/api/v1/messages/threads', json={'subject': 'Widersprüchlicher Bezug', **values})
        assert response.status_code in (400, 422), response.text
    good = client.post('/api/v1/messages/threads', json={'subject': 'Passender Bezug', 'property_id': a.id,
                                                       'unit_id': ua.id, 'contract_id': lease.id})
    assert good.status_code == 201, good.text
    thread = good.json()
    rejected = client.patch('/api/v1/messages/threads/' + thread['id'], json={'unit_id': ub.id})
    assert rejected.status_code in (400, 422), rejected.text
    assert store.get_message_thread(thread['id']).unit_id == ua.id


def test_empty_subject_is_refused_on_create_and_edit(context):
    client, *_ = context
    rejected = client.post('/api/v1/messages/threads', json={'subject': '  '})
    assert rejected.status_code in (400, 422), rejected.text
    thread = store.create_message_thread(MessageThreadCreate(subject='Erhalten'))
    rejected = client.patch('/api/v1/messages/threads/' + thread.id, json={'subject': '  '})
    assert rejected.status_code in (400, 422), rejected.text
    assert store.get_message_thread(thread.id).subject == 'Erhalten'


def test_renaming_a_conversation_preserves_existing_message_statistics(context):
    client, *_ = context
    thread = store.create_message_thread(MessageThreadCreate(subject='Original'))
    store.create_message(MessageCreate(thread_id=thread.id, body='Bleibende Nachricht'))
    before = store.get_message_thread(thread.id)
    assert before.message_count == 1 and before.last_message_at is not None
    store.update_message_thread(thread.id, MessageThreadCreate(subject='Zwischenstand'))
    assert store.get_message_thread(thread.id).message_count == 1
    edited = client.patch('/api/v1/messages/threads/' + thread.id, json={'subject': 'Neuer Betreff'})
    assert edited.status_code == 200, edited.text
    after = store.get_message_thread(thread.id)
    assert after.message_count == 1
    assert after.last_message_at == before.last_message_at
    assert len(store.list_messages(thread_id=thread.id)) == 1
