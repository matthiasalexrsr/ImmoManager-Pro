"""Independent source-preservation and live account-revocation counterexamples."""
from uuid import uuid4

import pytest
from fastapi import HTTPException

from backend import auth
from backend.models import MessageThreadCreate, PortfolioCreate, PropertyCreate
from backend.services.communication import Communication
from backend.tests import test_communication_durable as fixtures
from backend.tests.test_communication_durable import Transport, expire, preview, ready

setup = fixtures.setup


def test_moved_thread_does_not_disclose_historical_body_to_new_portfolio(setup):
    service, owner, thread, _, _, prop = setup
    source = service.store
    frozen = preview(setup)
    raw = service.download(frozen['id'], owner.id)[0]
    other = source.create_portfolio(PortfolioCreate(name='Neuer Bestand'))
    location = source.create_property(PropertyCreate(portfolio_id=other.id, name='Neues Haus', property_type='residential'))
    reader = auth.register_user('reader-' + uuid4().hex[:8], 'reader@example.test', 'Neuer Bestand', 'Secret123', 'verwalter',
                                portfolio_access='selected', portfolio_ids=[other.id])
    source.update_message_thread(thread.id, MessageThreadCreate(subject=thread.subject, property_id=location.id))
    with pytest.raises(HTTPException) as error:
        service.download(frozen['id'], reader.id)
    assert error.value.status_code == 404
    auth.update_user(reader.id, {'portfolio_access': 'selected', 'portfolio_ids': [other.id, prop.portfolio_id]})
    assert service.download(frozen['id'], reader.id)[0] == raw
    with pytest.raises(HTTPException) as error:
        source.delete_message_thread(thread.id)
    assert error.value.status_code == 409
    assert source.get_message_thread(thread.id).id == thread.id
    assert service.download(frozen['id'], owner.id)[0] == raw


def test_actual_role_revocation_before_data_yields_blocked_job_without_transmission(setup, monkeypatch):
    from backend import dependencies
    from backend.services import communication_transport
    from backend.services.integrations import manager as managers
    from backend.services.jobs import communication as bridge
    from backend.services.jobs.core import JobRunner, MemoryJobStore, SqlJobStore
    service, owner, *_ = setup
    frozen = ready(setup)
    called = []
    class Revoking(Transport):
        def prepare(self, *args):
            auth.update_user(owner.id, {'role': 'readonly'})
        def data(self, raw):
            called.append(raw)
            return 'accepted'
    monkeypatch.setattr(communication_transport, 'SMTPTransport', Revoking)
    monkeypatch.setattr(dependencies, 'store', service.store)
    monkeypatch.setattr(managers, 'integration_manager', service.connections.manager)
    monkeypatch.setattr(bridge, 'Communication', lambda store, manager: service)
    jobs = SqlJobStore(service.store.db.get_bind()) if hasattr(service.store, 'db') else MemoryJobStore(store_factory=lambda: service.store)
    bridge.recover(jobs)
    JobRunner(jobs, {bridge.KIND: bridge.handler}).run_until_idle(max_jobs=1)
    assert called == []
    assert service.get(frozen['id'], owner.id)['state'] == 'blocked'
    assert jobs.list_runs()[0].status == 'succeeded'


def test_expired_data_checkpoint_reaped_after_actual_account_deactivation(setup):
    from backend.services.jobs.communication import reap
    service, owner, *_ = setup
    frozen = ready(setup)
    with pytest.raises(SystemExit):
        service.dispatch(frozen['id'], owner.id, Transport('crash'))
    expire(service, owner, frozen['id'])
    reviewer = auth.register_user('review-' + uuid4().hex[:8], 'review@example.test', 'Prüfung', 'Secret123', 'eigentuemer')
    auth.update_user(owner.id, {'is_active': False})
    reap(service.store)
    restarted = Communication(service.store, service.connections.manager, service.box)
    assert restarted.get(frozen['id'], reviewer.id)['state'] == 'unknown'
    with pytest.raises(HTTPException):
        restarted.dispatch(frozen['id'], owner.id, Transport())


def test_exhausted_job_before_claim_is_restarted_without_repeating_data(setup, monkeypatch):
    from backend import dependencies
    from backend.services import communication_transport
    from backend.services.integrations import manager as managers
    from backend.services.jobs import communication as bridge
    from backend.services.jobs.core import JobRunner, MemoryJobStore, SqlJobStore
    service, owner, *_ = setup
    row = ready(setup)
    monkeypatch.setattr(dependencies, 'store', service.store)
    monkeypatch.setattr(managers, 'integration_manager', service.connections.manager)
    monkeypatch.setattr(bridge, 'Communication', lambda store, manager: service)
    calls = []
    class Recording(Transport):
        def data(self, raw):
            calls.append(raw)
            return 'accepted'
    monkeypatch.setattr(communication_transport, 'SMTPTransport', Recording)
    jobs = SqlJobStore(service.store.db.get_bind()) if hasattr(service.store, 'db') else MemoryJobStore(store_factory=lambda: service.store)
    bridge.recover(jobs)
    claimed = jobs.claim('crashed-before-outbox-claim', (bridge.KIND,))
    jobs.fail(claimed, 'Synthetic infrastructure failure before outbox claim', permanent=True)
    assert service.get(row['id'], owner.id)['state'] == 'ready'
    bridge.recover(jobs)
    assert len(jobs.list_runs()) == 2
    JobRunner(jobs, {bridge.KIND: bridge.handler}).run_until_idle(max_jobs=1)
    bridge.recover(jobs)
    JobRunner(jobs, {bridge.KIND: bridge.handler}).run_until_idle(max_jobs=1)
    assert service.get(row['id'], owner.id)['state'] == 'accepted' and len(calls) == 1


def test_uploaded_attachment_keeps_original_portfolio_and_document_source(setup, tmp_path, monkeypatch):
    from backend.models import DocumentCreate
    from backend.services import file_storage
    from backend.services.file_storage import LocalStorage
    service, owner, _, _, _, prop = setup
    source = service.store
    original_portfolio = source.create_portfolio(PortfolioCreate(name='Originalanlage'))
    original_property = source.create_property(PropertyCreate(portfolio_id=original_portfolio.id, name='Anlagenquelle', property_type='residential'))
    new_portfolio = source.create_portfolio(PortfolioCreate(name='Spätere Anlagenzuordnung'))
    new_property = source.create_property(PropertyCreate(portfolio_id=new_portfolio.id, name='Neues Anlagenhaus', property_type='residential'))
    storage = LocalStorage(tmp_path / 'uploads')
    monkeypatch.setattr(file_storage, 'get_file_storage', lambda: storage)
    (storage.base_dir / 'attachment.txt').write_bytes(b'Original bytes from the earlier portfolio')
    document = source.create_document(DocumentCreate(title='Originalanlage', document_type='other', property_id=original_property.id, file_url='/uploads/attachment.txt'))
    choice = service.attachment_choices(document.id, owner.id)['items'][0]
    frozen = preview(setup, attachments=[dict(document_id=document.id, version_id='upload', document_revision=choice['document_revision'], sha256=choice['sha256'])])
    source.update_document(document.id, DocumentCreate(title='Originalanlage', document_type='other', property_id=new_property.id, file_url='/uploads/attachment.txt'))
    reader = auth.register_user('attachment-' + uuid4().hex[:8], 'attachment@example.test', 'Neue Akte', 'Secret123', 'verwalter',
                                portfolio_access='selected', portfolio_ids=[prop.portfolio_id, new_portfolio.id])
    with pytest.raises(HTTPException):
        service.download(frozen['id'], reader.id)
    with pytest.raises(HTTPException) as error:
        source.delete_document(document.id)
    assert error.value.status_code == 409
    auth.update_user(reader.id, {'portfolio_access': 'selected', 'portfolio_ids': [prop.portfolio_id, new_portfolio.id, original_portfolio.id]})
    assert service.download(frozen['id'], reader.id)[0] == service.download(frozen['id'], owner.id)[0]


def test_template_and_snippet_versions_are_retained_and_pinned_in_mime(setup):
    from email import policy
    from email.parser import BytesParser

    from backend.services.communication import Template
    service, owner, *_ = setup
    old = service.save_template(Template(idempotency_key=str(uuid4()), usage='snippet', name='Gruß', subject='', body='Mit freundlichen Grüßen'), owner.id)
    new = service.save_template(Template(idempotency_key=str(uuid4()), usage='snippet', name='Gruß', subject='', body='Beste Grüße', predecessor_id=old['id']), owner.id)
    assert old['id'] != new['id'] and new['predecessor_id'] == old['id']
    assert service.get(old['id'], owner.id)['body'] == 'Mit freundlichen Grüßen'
    message = preview(setup, body='Guten Tag,\nMit freundlichen Grüßen', snippet_ids=[old['id']])
    assert message['snippet_revisions'] == {old['id']: 1}
    raw = service.download(message['id'], owner.id)[0]
    parsed = BytesParser(policy=policy.default).parsebytes(raw)
    body = parsed.get_body()
    assert body is not None
    assert body.get_content().strip() == 'Guten Tag,\r\nMit freundlichen Grüßen'
    assert raw.isascii()
