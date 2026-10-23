"""Personal email/outbox integration with synthetic local transports only."""
from uuid import uuid4

import pytest
from fastapi import HTTPException

from backend import auth
from backend.models import NotificationCreate, TaskCreate, TaskPatch
from backend.services import notification_inbox, settings_catalogue
from backend.services.communication import Confirmation
from backend.services.notification_email import Preview, preview
from backend.tests.test_communication_durable import Transport
from backend.tests.test_communication_durable import setup as _mail_setup

setup = _mail_setup


def make_preview(fixture):
    service, owner, _, _, connection, prop = fixture
    task = service.store.create_task(TaskCreate(title='Persönlicher Vorgang', property_id=prop.id))
    notice = service.store.create_notification(NotificationCreate(notification_type='task_due', title='Frist prüfen',
        content='Synthetischer persönlicher Hinweis', severity='warning', entity_type='task', entity_id=task.id))
    source = notification_inbox.open_source(service.store, owner.id, notice.id)['source']
    command = Preview(idempotency_key=str(uuid4()), connection_id=connection['id'],
                      config_revision=connection['revision'], source_revision=source['revision'])
    row = preview(service, notice.id, command, owner.id)
    return notice, task, command, row


def confirm(service, owner, row):
    return service.confirm(row['id'], Confirmation(idempotency_key=str(uuid4()), base_revision=row['revision'],
        mime_sha256=row['mime_sha256'], confirmed=True), owner.id)


def change(service, owner, **values):
    revision = settings_catalogue.prefs(service.store, owner.id)['_revision']
    return settings_catalogue.update(service.store, owner.id, values, revision, str(uuid4()))


def test_preview_uses_existing_evidence_is_private_and_never_releases_or_reads_notice(setup):
    service, owner, *_ = setup
    notice, _, command, row = make_preview(setup)
    assert row['state'] == 'preview' and row['kind'] == 'notification'
    assert row['to'] == [owner.email] and row['envelope'] == [owner.email]
    assert service.dispatch(row['id'], owner.id, Transport()) == 'preview'
    assert notification_inbox.inbox(service.store, owner.id)['unread_count'] == 1
    assert preview(service, notice.id, command, owner.id)['id'] == row['id']
    assert preview(service, notice.id, command.model_copy(update={'idempotency_key': str(uuid4())}), owner.id)['id'] == row['id']
    raw = service.download(row['id'], owner.id)[0]
    assert b'Message-ID:' in raw and b'Content-Type: text/plain' in raw
    other = auth.register_user('other-' + uuid4().hex[:8], 'other@example.test', 'Andere Person', 'Secret123', 'eigentuemer')
    with pytest.raises(HTTPException) as error:
        service.get(row['id'], other.id)
    assert error.value.status_code == 404
    assert service.page(other.id, kind='notification')['items'] == []
    assert service.page(owner.id, kind='outbound')['items'] == []
    assert service.page(owner.id, kind='notification')['items'][0]['id'] == row['id']
    ready = confirm(service, owner, row)
    assert ready['state'] == 'ready'
    transport = Transport()
    assert service.dispatch(row['id'], owner.id, transport) == 'accepted'
    assert transport.recipients == [owner.email] and transport.raw == raw
    assert service.dispatch(row['id'], owner.id, Transport()) == 'accepted'


@pytest.mark.parametrize('stage', ['release', 'claim', 'before_data'])
def test_policy_is_checked_at_release_claim_and_immediately_before_data(setup, stage):
    service, owner, *_ = setup
    _, _, _, row = make_preview(setup)
    if stage == 'release':
        change(service, owner, email_notifications='none')
        with pytest.raises(HTTPException) as error:
            confirm(service, owner, row)
        assert error.value.status_code == 409
        assert service.get(row['id'], owner.id)['state'] == 'preview'
        return
    confirm(service, owner, row)
    if stage == 'claim':
        change(service, owner, email_notifications='none')
        with pytest.raises(HTTPException) as error:
            service.dispatch(row['id'], owner.id, Transport())
        assert error.value.status_code == 409
        return
    class ChangeBeforeData(Transport):
        def prepare(self, config, sender, recipients):
            super().prepare(config, sender, recipients)
            change(service, owner, email_notifications='none')
    transport = ChangeBeforeData()
    assert service.dispatch(row['id'], owner.id, transport) == 'failed'
    assert transport.raw is None and transport.closed


def test_source_recipient_and_read_receipt_changes_block_release(setup):
    service, owner, *_ = setup
    notice, task, _, row = make_preview(setup)
    service.store._patch_entity('task', task.id, TaskPatch(title='Geänderte Quelle'))
    with pytest.raises(HTTPException) as error:
        confirm(service, owner, row)
    assert error.value.status_code == 409
    _, _, _, second = make_preview(setup)
    auth.update_user(owner.id, {'email': 'new@example.test'})
    with pytest.raises(HTTPException) as error:
        confirm(service, owner, second)
    assert error.value.status_code == 409
    notice, _, _, third = make_preview(setup)
    source = notification_inbox.open_source(service.store, owner.id, notice.id)['source']
    notification_inbox.mutate(service.store, owner.id, notice.id, dict(action='landed', base_revision=0,
        idempotency_key=str(uuid4()), source_kind=source['kind'], source_id=source['entity_id'], source_revision=source['revision']))
    with pytest.raises(HTTPException) as error:
        confirm(service, owner, third)
    assert error.value.status_code == 409


def test_preview_failure_rolls_back_item_evidence_and_retries_same_command(setup, monkeypatch):
    from sqlalchemy.exc import SQLAlchemyError
    service, owner, *_ = setup
    original = service.command
    def failure(*args, **kwargs):
        raise SQLAlchemyError('synthetic command write failure')
    monkeypatch.setattr(service, 'command', failure)
    with pytest.raises(SQLAlchemyError):
        make_preview(setup)
    assert service.page(owner.id, kind='notification')['items'] == []
    monkeypatch.setattr(service, 'command', original)
    assert make_preview(setup)[3]['state'] == 'preview'


def test_existing_scheduler_recovers_only_explicitly_released_personal_previews(setup, monkeypatch):
    from backend import dependencies
    from backend.services.jobs import communication as jobs
    service, owner, *_ = setup
    _, _, _, first = make_preview(setup)
    _, _, _, second = make_preview(setup)
    confirm(service, owner, second)
    monkeypatch.setattr(dependencies, 'store', service.store)
    class Queue:
        calls = []
        def find(self, key):
            return None
        def enqueue(self, kind, key, payload, **kwargs):
            self.calls.append(payload)
    queue = Queue()
    jobs.recover(queue)
    assert queue.calls == [{'item_id': second['id'], 'actor_id': owner.id}]
    assert service.get(first['id'], owner.id)['state'] == 'preview'


def test_current_quiet_hours_and_revoked_portfolio_rights_are_checked_before_release(setup, monkeypatch):
    from datetime import datetime, timezone
    service, owner, *_ = setup
    _, _, _, row = make_preview(setup)
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            value = datetime(2026, 10, 16, 20, 30, tzinfo=timezone.utc)
            return value.astimezone(tz) if tz else value.replace(tzinfo=None)
    monkeypatch.setattr(settings_catalogue, 'datetime', Clock)
    change(service, owner, quiet_start='22:00', quiet_end='07:00')
    with pytest.raises(HTTPException) as error:
        confirm(service, owner, row)
    assert error.value.status_code == 409
    change(service, owner, quiet_start='', quiet_end='')
    auth.update_user(owner.id, {'role': 'verwalter', 'portfolio_access': 'selected', 'portfolio_ids': []})
    with pytest.raises(HTTPException) as error:
        confirm(service, owner, row)
    assert error.value.status_code in (403, 404)


def test_personal_email_opt_out_does_not_suppress_explicit_business_correspondence(setup):
    from backend.tests.test_communication_durable import preview as business_preview
    service, owner, *_ = setup
    change(service, owner, email_notifications='none')
    row = business_preview(setup)
    confirm(service, owner, row)
    transport = Transport()
    assert service.dispatch(row['id'], owner.id, transport) == 'accepted'
    assert transport.recipients == ['to@example.test', 'cc@example.test', 'blind@example.test']
