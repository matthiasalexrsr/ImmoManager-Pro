"""Actual consumers, token families and interleaved audit rollback; synthetic data only."""
from datetime import datetime, timedelta, timezone
from threading import Event, Thread
from uuid import uuid4

import jwt
import pytest
from fastapi import HTTPException
from sqlalchemy.exc import SQLAlchemyError

from backend import auth
from backend.audit import InMemoryAuditStore
from backend.dependencies import store
from backend.models import AuditLogEntry
from backend.services import daily_state
from backend.services.document_versions import Unit
from backend.storage import InMemoryStore
from backend.tests.test_daily_workflows import clean, client  # noqa: F401

SETTINGS = '/api/v1/auth/users/me/settings'


def login(browser, name):
    response = browser.post('/api/v1/auth/login', json={'username': name, 'password': 'Secret123'})
    assert response.status_code == 200, 'Synthetic login failed'
    return response.json()


def bearer(token):
    return {'Authorization': 'Bearer ' + token}


def test_family_inventory_is_private_and_revoke_blocks_access_and_refresh_but_not_other_family():
    actor, browser = client('session-consumer', 'readonly', portfolio_access='selected', portfolio_ids=[])
    legacy = auth.create_access_token(actor.id)
    first = login(browser, actor.username)
    second = login(browser, actor.username)
    family = auth.decode_token(first['access_token']).sid
    assert family and family == auth.decode_token(first['refresh_token']).sid
    assert family != auth.decode_token(second['access_token']).sid
    current_headers = bearer(second['access_token'])
    listing = browser.get(SETTINGS + '/sessions', headers=current_headers)
    assert listing.status_code == 200
    rows = listing.json()['items']
    assert len(rows) == 2 and sum(row['current'] for row in rows) == 1
    assert all(set(row) == {'id', 'revision', 'created_at', 'expires_at', 'revoked_at', 'current'} for row in rows)
    command = {'base_revision': 1, 'idempotency_key': str(uuid4())}
    _, foreign = client('other-session-consumer', 'readonly', portfolio_access='selected', portfolio_ids=[])
    assert foreign.post(f'{SETTINGS}/sessions/{family}/revoke', json=command).status_code == 404
    result = browser.post(f'{SETTINGS}/sessions/{family}/revoke', json=command, headers=current_headers)
    assert result.status_code == 200 and result.json()['revoked']
    assert browser.post(f'{SETTINGS}/sessions/{family}/revoke', json=command, headers=current_headers).json() == result.json()
    for token in (first['access_token'], first['refresh_token']):
        with pytest.raises(HTTPException) as error:
            auth.decode_token(token)
        assert error.value.status_code == 401
    assert auth.decode_token(second['access_token']).sub == actor.id
    assert auth.decode_token(legacy).sub == actor.id and auth.decode_token(legacy).sid is None
    denied_refresh = browser.post('/api/v1/auth/refresh', json={'refresh_token': first['refresh_token']})
    assert denied_refresh.status_code == 401
    assert not denied_refresh.headers.get('set-cookie')


def test_session_revoke_commit_failure_retains_session_and_audit_then_same_command_succeeds(monkeypatch):
    actor, browser = client('session-rollback')
    issued = login(browser, actor.username)
    family = auth.decode_token(issued['access_token']).sid
    key = str(uuid4())
    command = {'base_revision': 1, 'idempotency_key': key}
    original = daily_state.remember
    def fail(*args, **kwargs):
        raise SQLAlchemyError('synthetic private transaction failure')
    monkeypatch.setattr(daily_state, 'remember', fail)
    response = browser.post(f'{SETTINGS}/sessions/{family}/revoke', json=command)
    assert response.status_code == 503
    assert 'synthetic private' not in response.text
    assert auth.decode_token(issued['access_token']).sub == actor.id
    row = next(item for item in browser.get(SETTINGS + '/sessions').json()['items'] if item['id'] == family)
    assert row['revision'] == 1 and row['revoked_at'] is None
    monkeypatch.setattr(daily_state, 'remember', original)
    assert browser.post(f'{SETTINGS}/sessions/{family}/revoke', json=command).status_code == 200
    with pytest.raises(HTTPException) as error:
        auth.decode_token(issued['refresh_token'])
    assert error.value.status_code == 401


def test_family_read_failure_is_temporary_not_an_authorized_or_unknown_session(monkeypatch):
    actor, browser = client('session-db-failure')
    issued = login(browser, actor.username)
    original = auth._auth_session_factory
    def unavailable():
        raise SQLAlchemyError('synthetic private database parameters')
    monkeypatch.setattr(auth, '_auth_session_factory', unavailable)
    with pytest.raises(HTTPException) as error:
        auth.decode_token(issued['access_token'])
    assert error.value.status_code == 503
    assert 'synthetic private' not in str(error.value.detail)
    monkeypatch.setattr(auth, '_auth_session_factory', original)
    assert auth.decode_token(issued['access_token']).sub == actor.id


def test_memory_token_checks_wait_for_revoke_rollback_before_deciding(monkeypatch):
    if hasattr(store, 'db'):
        pytest.skip('Memory interleaving oracle; SQL transactions provide isolation')
    from backend.services import daily_sessions
    actor, browser = client('session-interleaving')
    issued = login(browser, actor.username)
    family = auth.decode_token(issued['access_token']).sid
    changed, finish, checked = Event(), Event(), Event()
    outcomes: list[int | str] = []
    def fail_after_mutation(*args, **kwargs):
        changed.set()
        assert finish.wait(timeout=5)
        raise SQLAlchemyError('synthetic rollback after visible mutation')
    monkeypatch.setattr(daily_state, 'remember', fail_after_mutation)
    def revoke():
        try:
            daily_sessions.revoke(store, actor.id, family, {'base_revision': 1, 'idempotency_key': str(uuid4())})
        except HTTPException as exc:
            outcomes.append(exc.status_code)
    def check():
        try:
            daily_sessions.check(family, actor.id)
            outcomes.append('valid')
        finally:
            checked.set()
    writer = Thread(target=revoke)
    writer.start()
    assert changed.wait(timeout=5)
    reader = Thread(target=check)
    reader.start()
    try:
        assert not checked.wait(timeout=0.1), 'Reader observed an uncommitted revoke'
    finally:
        finish.set()
        writer.join(timeout=5)
        reader.join(timeout=5)
    assert not writer.is_alive() and not reader.is_alive()
    assert len(outcomes) == 2 and 503 in outcomes and 'valid' in outcomes


def test_memory_settings_read_does_not_expose_a_value_that_later_rolls_back(monkeypatch):
    if hasattr(store, 'db'):
        pytest.skip('Memory interleaving oracle; SQL transactions provide isolation')
    from backend.services import settings_catalogue
    actor, _ = client('setting-interleaving')
    changed, finish, checked = Event(), Event(), Event()
    outcomes: list[int | str] = []
    def fail_after_mutation(*args, **kwargs):
        changed.set()
        assert finish.wait(timeout=5)
        raise SQLAlchemyError('synthetic settings rollback after mutation')
    monkeypatch.setattr(daily_state, 'remember', fail_after_mutation)
    def write():
        try:
            settings_catalogue.update(store, actor.id, {'reminder_days': '30'}, 0, str(uuid4()))
        except HTTPException as exc:
            outcomes.append(exc.status_code)
    def read():
        try:
            outcomes.append(settings_catalogue.prefs(store, actor.id)['reminder_days'])
        finally:
            checked.set()
    writer = Thread(target=write)
    writer.start()
    assert changed.wait(timeout=5)
    reader = Thread(target=read)
    reader.start()
    try:
        assert not checked.wait(timeout=0.1), 'Read observed an uncommitted setting'
    finally:
        finish.set()
        writer.join(timeout=5)
        reader.join(timeout=5)
    assert not writer.is_alive() and not reader.is_alive()
    assert len(outcomes) == 2 and 503 in outcomes and '7' in outcomes


@pytest.mark.parametrize('claims', [{}, {'sub': 'synthetic', 'sid': []}, {'sub': None}, {'sub': 'synthetic', 'type': None}])
def test_validly_signed_but_invalid_claims_are_neutral_authentication_failures(claims):
    value = {'exp': datetime.now(timezone.utc) + timedelta(minutes=2), 'type': 'access', **claims}
    token = jwt.encode(value, auth.SECRET_KEY, algorithm=auth.ALGORITHM)
    with pytest.raises(HTTPException) as error:
        auth.decode_token(token)
    assert error.value.status_code == 401
    assert error.value.detail == 'Ungültiger Token'


def test_number_reservation_has_actual_consumer_replay_and_no_financial_side_effects():
    _, browser = client('number-consumer')
    for key, value in {'contract_number_prefix': 'QA-', 'contract_number_start': 100, 'contract_number_width': 4}.items():
        response = browser.put(SETTINGS, json={'values': {key: value}, 'scope': 'global', 'base_revision': 0, 'idempotency_key': str(uuid4())})
        assert response.status_code == 200, response.text
    preview = browser.get(SETTINGS + '/draft-defaults?context=contracts').json()
    assert preview['numbering_enabled'] and preview['values'] == {}
    command = {'context': 'contracts', 'expected_revision': preview['revision'], 'idempotency_key': str(uuid4())}
    allocated = browser.post(SETTINGS + '/draft-defaults', json=command)
    assert allocated.status_code == 200, allocated.text
    assert allocated.json()['values'] == {'contract_number': 'QA-0100'}
    assert browser.post(SETTINGS + '/draft-defaults', json=command).json() == allocated.json()
    _, another = client('second-number-consumer')
    next_preview = another.get(SETTINGS + '/draft-defaults?context=contracts').json()
    next_command = {'context': 'contracts', 'expected_revision': next_preview['revision'], 'idempotency_key': str(uuid4())}
    assert another.post(SETTINGS + '/draft-defaults', json=next_command).json()['values'] == {'contract_number': 'QA-0101'}
    assert browser.post(SETTINGS + '/draft-defaults', json={**command, 'idempotency_key': str(uuid4())}).status_code == 409
    assert store.list_contracts() == [] and store.list_bookings() == []
    _, reader = client('readonly-number-consumer', 'readonly', portfolio_access='selected', portfolio_ids=[])
    assert reader.get(SETTINGS + '/draft-defaults?context=contracts').status_code == 403


def test_bank_profile_and_housing_defaults_return_exact_saved_values_without_business_writes():
    _, browser = client('source-defaults')
    values = {'bank_csv_decimal': ',', 'bank_csv_encoding': 'cp1252', 'bank_csv_amount_column': 'Umsatz',
              'document_sender': 'Synthetischer Wohnungsgeber', 'document_signature': 'Ausstellerin',
              'document_address': 'Prüfstraße 1\n12345 Prüfort', 'document_profile': 'authorized_person'}
    changed = browser.put(SETTINGS, json={'values': values, 'base_revision': 0, 'idempotency_key': str(uuid4())})
    assert changed.status_code == 200, changed.text
    profile = browser.get(SETTINGS + '/bank-import-profile').json()
    assert profile['options']['encoding'] == 'cp1252' and profile['options']['decimal'] == ','
    assert profile['options']['columns']['amount'] == 'Umsatz'
    draft = browser.get(SETTINGS + '/draft-defaults?context=housing-confirmation').json()
    assert draft['values'] == {'housing_provider_name': values['document_sender'], 'housing_provider_address': values['document_address'],
                               'issuer_name': values['document_signature'], 'issuer_role': 'authorized_person'}
    assert store.list_bookings() == [] and store.list_documents() == []


def test_memory_audit_rollback_preserves_a_later_concurrent_event():
    journal = InMemoryAuditStore()
    unit = Unit(InMemoryStore(), None, {'id': 'synthetic-actor'}, None)
    own = AuditLogEntry(id='own', user_id='synthetic-actor', action='settings_change', entity_type='setting', entity_id='one')
    other = AuditLogEntry(id='other', user_id='another-actor', action='update', entity_type='task', entity_id='two')
    unit.append(journal._logs, own, lock=journal._lock)
    writer = Thread(target=journal.add, args=(other,))
    writer.start()
    writer.join(timeout=5)
    assert not writer.is_alive()
    unit.rollback()
    assert [item.id for item in journal.list_all()] == ['other']
    assert journal.list_all()[0] is other
