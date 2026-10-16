"""Offline session state machine: no test may construct a real bank connection."""
import base64
from datetime import date, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
import test_bank_imports_controlled as bank_tests
from fastapi import HTTPException
from pydantic import SecretStr

from backend import auth
from backend.db.bank_models import FinTSSessionORM
from backend.models import AccountCreate
from backend.services.bank_fints import CancelFinTS, FinTS, FinTSStep, StartFinTS
from backend.services.integrations import connection_storage as records

IBAN = 'DE02120300000000202051'
PIN = 'SYNTHETIC-PIN-NEVER-IN-JOURNAL'


bank = bank_tests.bank


class OfflineBank:
    def __init__(self):
        self.calls = []
        self.callback = None

    def step(self, config, state, *, tan=None, selected=None):
        self.calls.append((state['phase'], tan, selected))
        if self.callback:
            self.callback()
        if state['phase'] == 'init':
            return {'state': 'tan_required', 'phase': 'accounts', 'challenge_text': 'Freigabe Testbank',
                    'challenge': 'opaque-library-data', 'client': 'opaque', 'dialog': 'opaque'}
        if state['phase'] == 'accounts':
            assert tan == '654321'
            return {'state': 'select_account', 'phase': 'select', 'accounts': [[IBAN, 'TESTDEFF', '1', '', '12030000']]}
        assert state['phase'] == 'select' and selected == 0
        raw = (Path(__file__).parent / 'fixtures/bank/camt053.xml').read_bytes()
        return {'state': 'received', 'phase': 'done', 'originals': [base64.b64encode(raw).decode()]}


def setup(bank):
    imports, actor, account = bank
    current = imports.store.get_account(account)
    imports.store.update_account(account, AccountCreate(**{**current.model_dump(), 'iban': IBAN}))
    adapter = OfflineBank()
    service = FinTS(imports.store, imports.box, adapter_factory=lambda: adapter)
    command = StartFinTS(idempotency_key=str(uuid4()), account_id=account, bank_code='12030000', user_id='synthetic',
        pin=SecretStr(PIN), server='https://bank.example.test/fints', product_id='SYNTHETIC', date_from=date(2026, 10, 1), date_to=date(2026, 10, 16))
    return service, adapter, actor, command


def advance(service, actor, session, **kwargs):
    command = FinTSStep(idempotency_key=str(uuid4()), base_revision=session['revision'], **kwargs)
    return service.advance(session['id'], command, actor), command


def test_encrypted_tan_account_selection_resume_and_original_staging(bank):
    service, adapter, actor, command = setup(bank)
    session = service.start(command, actor)
    assert adapter.calls == []
    assert PIN not in str(session)
    session, first = advance(service, actor, session)
    assert session['state'] == 'tan_required'
    assert service.advance(session['id'], first, actor)['replayed']
    assert len(adapter.calls) == 1
    from backend.services import business_qol as commands
    with service.work(actor) as unit:
        receipt = commands.get_record(unit, 'business_qol_commands', commands.command_id(actor, first.idempotency_key))
        assert 'Freigabe Testbank' not in str(receipt.response)
        assert not {'challenge', 'accounts', 'pin', 'tan'}.intersection(receipt.response)
    session, _ = advance(service, actor, session, tan='654321')
    assert session['state'] == 'select_account'
    # New service instance uses only persisted encrypted state, not a live client object.
    resumed = FinTS(service.store, service.box, adapter_factory=lambda: adapter)
    session, _ = advance(resumed, actor, session, selected_account=0)
    assert session['state'] == 'received'
    with service.work(actor) as unit:
        row = service.session(unit, session['id'])
        assert PIN not in row.private_token and '654321' not in row.private_token
        assert 'config' not in service.private(row)
    staged = service.stage_received(session['id'], CancelFinTS(idempotency_key=str(uuid4()), base_revision=session['revision']), actor)
    assert staged['imports'][0]['total_cents'] == 9999
    assert service.store.list_bookings() == []
    assert service.original(staged['imports'][0]['id'], actor) == (Path(__file__).parent / 'fixtures/bank/camt053.xml').read_bytes()


def test_expired_and_cancelled_session_never_calls_adapter(bank):
    service, adapter, actor, command = setup(bank)
    session = service.start(command, actor)
    with service.work(actor, True) as unit:
        row = service.session(unit, session['id'])
        data = records.values(row)
        data['expires_at'] = records.now() - timedelta(seconds=1)
        records.put(unit, FinTSSessionORM, data)
    assert service.get(session['id'], actor)['state'] == 'expired'
    with pytest.raises(HTTPException):
        advance(service, actor, session)
    cancelled = service.cancel(session['id'], CancelFinTS(idempotency_key=str(uuid4()), base_revision=session['revision']), actor)
    assert cancelled['state'] == 'cancelled'
    with service.work(actor) as unit:
        assert 'config' not in service.private(service.session(unit, session['id']))
    assert adapter.calls == []


def test_network_failure_is_sanitized_and_cannot_retry_same_dialog(bank):
    service, adapter, actor, command = setup(bank)
    session = service.start(command, actor)
    def fail():
        raise TimeoutError(PIN)
    adapter.callback = fail
    result, retry = advance(service, actor, session)
    assert result['state'] == 'failed' and PIN not in str(result)
    assert service.advance(session['id'], retry, actor)['replayed']
    assert len(adapter.calls) == 1


def test_crash_after_claim_does_not_allow_second_network_call(bank):
    service, adapter, actor, command = setup(bank)
    session = service.start(command, actor)
    def crash():
        raise KeyboardInterrupt('simulated worker termination')
    adapter.callback = crash
    with pytest.raises(KeyboardInterrupt):
        advance(service, actor, session)
    current = service.get(session['id'], actor)
    assert current['state'] == 'running'
    with pytest.raises(HTTPException):
        advance(service, actor, current)
    assert len(adapter.calls) == 1


def test_other_actor_cannot_read_session_and_changed_pin_key_conflicts(bank):
    service, adapter, actor, command = setup(bank)
    session = service.start(command, actor)
    with pytest.raises(HTTPException):
        service.start(command.model_copy(update={'pin': type(command.pin)('other')}), actor)
    other = auth.register_user('bank-other', 'other@example.test', 'Andere Person', 'Secret123', 'eigentuemer')
    with pytest.raises(HTTPException) as exc:
        service.get(session['id'], other.id)
    assert exc.value.status_code == 404


def test_permission_revocation_discards_late_bank_response(bank):
    service, adapter, actor, command = setup(bank)
    session = service.start(command, actor)
    adapter.callback = lambda: auth.update_user(actor, {'role': 'readonly'})
    with pytest.raises(HTTPException) as exc:
        advance(service, actor, session)
    assert exc.value.status_code == 403
    assert len(adapter.calls) == 1
    assert service.get(session['id'], actor)['state'] == 'running'
