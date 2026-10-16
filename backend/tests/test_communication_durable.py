"""Independent protocol/evidence oracles for durable communication. No external accounts."""
from datetime import timedelta
from email import policy
from email.parser import BytesParser
from typing import TypedDict
from uuid import uuid4

import pytest
from fastapi import HTTPException

from backend import auth
from backend.db.communication_models import CommunicationItemORM as Item
from backend.dependencies import store
from backend.models import DocumentCreate, MessageThreadCreate, PortfolioCreate, PropertyCreate
from backend.services import document_versions as archive
from backend.services.communication import Assignment, Communication, Confirmation, Draft, RevisionCommand
from backend.services.integrations import connection_storage as dbs
from backend.services.integrations.connection_types import ConnectionCreate, ConnectionUpdate
from backend.services.integrations.connections import Connections
from backend.services.integrations.manager import IntegrationManager


@pytest.fixture
def setup(tmp_path, monkeypatch):
    import sys

    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session, sessionmaker

    from backend.db import schema_state
    from backend.repositories.sql_store import SQLAlchemyStore
    from backend.storage import InMemoryStore
    source: SQLAlchemyStore | InMemoryStore
    engine = None
    session = None
    if hasattr(store, 'db'):
        engine = create_engine(f"sqlite:///{(tmp_path / 'communication.db').as_posix()}")
        schema_state.initialise_empty(engine)
        session = Session(engine)
        source = SQLAlchemyStore(session)
        monkeypatch.setattr(auth, '_user_store', auth.SQLUserStore(sessionmaker(bind=engine)))
    else:
        source = InMemoryStore()
        auth.clear_users()
    monkeypatch.setattr(sys.modules[__name__], 'store', source)
    owner = auth.register_user('mail-' + uuid4().hex[:8], 'fixture@example.test', 'Prüfkonto', 'Secret123', 'eigentuemer')
    portfolio = store.create_portfolio(PortfolioCreate(name='Kommunikation'))
    prop = store.create_property(PropertyCreate(portfolio_id=portfolio.id, name='Haus', property_type='residential'))
    thread = store.create_message_thread(MessageThreadCreate(subject='Gleicher Betreff', property_id=prop.id))
    other = store.create_message_thread(MessageThreadCreate(subject='Gleicher Betreff', property_id=prop.id))
    manager = IntegrationManager()
    manager.seed_defaults()
    from backend.services.secret_box import SecretBox
    box = SecretBox(tmp_path / 'keyring.json')
    connection = Connections(store, manager, box).create(ConnectionCreate(idempotency_key=str(uuid4()),
        provider_id='email', name='Lokale Protokoll-Fixture', enabled=True,
        config=dict(sender_email='verwaltung@example.test', smtp_host='smtp.invalid', smtp_use_tls=True,
                    imap_host='imap.invalid', imap_user='fixture', imap_password='synthetic')), owner.id)
    service = Communication(store, manager, box)
    yield service, owner, thread, other, connection, prop
    if session is not None:
        session.close()
        assert engine is not None
        engine.dispose()
    else:
        auth.clear_users()


def draft(setup, **changes):
    service, owner, thread, _, connection, _ = setup
    values = dict(idempotency_key=str(uuid4()), thread_id=thread.id, source_revision=thread.updated_at.isoformat(),
                  connection_id=connection['id'], config_revision=connection['revision'],
                  to=['to@example.test'], cc=['cc@example.test'], bcc=['blind@example.test'],
                  subject='Vertrag äöü €', body='Prüfinhalt mit Umlauten.\nZweite Zeile.')
    values.update(changes)
    return service.save_draft(Draft(**values), owner.id)


def preview(setup, **changes):
    row = draft(setup, **changes)
    return setup[0].preview(row['id'], RevisionCommand(idempotency_key=str(uuid4()), base_revision=row['revision']), setup[1].id)


def ready(setup, **changes):
    row = preview(setup, **changes)
    return setup[0].confirm(row['id'], Confirmation(idempotency_key=str(uuid4()), base_revision=row['revision'],
        confirmed=True, mime_sha256=row['mime_sha256']), setup[1].id)


class Transport:
    def __init__(self, failure=None):
        self.failure = failure
        self.raw = None
        self.recipients = None
        self.closed = False
    def prepare(self, config, sender, recipients):
        self.sender, self.recipients = sender, recipients
        if self.failure == 'before':
            raise OSError('synthetic pre-DATA disconnect')
    def data(self, raw):
        self.raw = raw
        if self.failure == 'lost':
            raise OSError('synthetic lost DATA ack')
        if self.failure == 'crash':
            raise SystemExit('synthetic process loss')
        return 'rejected' if self.failure == 'reject' else 'accepted'
    def close(self):
        self.closed = True


def expire(service, owner, identifier):
    with service.work(owner.id, True) as unit:
        row = dbs.row(unit, Item, identifier)
        service.put(unit, row, service.data(row), lease_until=dbs.now() - timedelta(seconds=1))


def test_preview_stable_mime_envelope_bcc_and_original_attachment_bytes(setup):
    service, owner, _, _, _, prop = setup
    original = b'%PDF-1.7\r\n\x00\xff original bytes\n%%EOF'
    document = store.create_document(DocumentCreate(title='Original', document_type='other', property_id=prop.id, file_url='/uploads/original.pdf'))
    with archive.work(store, owner.id, write_areas=('/documents',)) as unit:
        doc, binding = archive.bind_document(unit, document.id)
        version = archive.publish_generated_original(unit, doc, binding, original, 'a' * 64, version_id=str(uuid4()))
    row = preview(setup, attachments=[dict(document_id=document.id, version_id=version.id, sha256=version.sha256)])
    raw = service.download(row['id'], owner.id)[0]
    parsed = BytesParser(policy=policy.default).parsebytes(raw)
    assert parsed['Bcc'] is None
    assert 'blind@example.test' not in raw.decode('ascii', errors='ignore')
    assert parsed['To'] == 'to@example.test' and parsed['Cc'] == 'cc@example.test'
    assert str(parsed['Subject']) == 'Vertrag äöü €'
    assert list(parsed.iter_attachments())[0].get_payload(decode=True) == original
    command = Confirmation(idempotency_key=str(uuid4()), base_revision=row['revision'], confirmed=True, mime_sha256=row['mime_sha256'])
    confirmed = service.confirm(row['id'], command, owner.id)
    assert service.confirm(row['id'], command, owner.id)['id'] == confirmed['id']
    transport = Transport()
    assert service.dispatch(row['id'], owner.id, transport) == 'accepted'
    assert transport.raw == raw
    assert transport.sender == 'verwaltung@example.test'
    assert transport.recipients == ['to@example.test', 'cc@example.test', 'blind@example.test']
    assert service.dispatch(row['id'], owner.id, Transport()) == 'accepted'
    assert 'Zustellung nicht nachgewiesen' in service.get(row['id'], owner.id)['history'][-1]['detail']


@pytest.mark.parametrize('failure,expected', [('before', 'failed'), ('reject', 'failed'), ('lost', 'unknown')])
def test_disconnect_semantics_and_no_automatic_duplicate(setup, failure, expected):
    service, owner, *_ = setup
    row = ready(setup)
    transport = Transport(failure)
    assert service.dispatch(row['id'], owner.id, transport) == expected
    second = Transport()
    assert service.dispatch(row['id'], owner.id, second) == expected
    assert second.raw is None
    assert transport.closed
    if expected == 'unknown':
        with pytest.raises(HTTPException) as error:
            service.confirm(row['id'], Confirmation(idempotency_key=str(uuid4()), base_revision=service.get(row['id'], owner.id)['revision'],
                confirmed=True, mime_sha256=row['mime_sha256']), owner.id, retry=True)
        assert error.value.status_code == 409


def test_crash_after_checkpoint_restart_becomes_unknown_and_stale_worker_fenced(setup):
    service, owner, *_ = setup
    row = ready(setup)
    with pytest.raises(SystemExit):
        service.dispatch(row['id'], owner.id, Transport('crash'))
    assert service.get(row['id'], owner.id)['state'] == 'data_pending'
    with service.work(owner.id) as unit:
        token = dbs.row(unit, Item, row['id']).lease_token
    expire(service, owner, row['id'])
    restarted = Communication(service.store, service.connections.manager, service.box)
    assert restarted.dispatch(row['id'], owner.id, Transport()) == 'unknown'
    with pytest.raises(HTTPException):
        restarted.finish(row['id'], owner.id, token, 'accepted', 'stale worker')


def test_crash_before_data_is_resumable_after_lease_expiry(setup):
    service, owner, *_ = setup
    row = ready(setup)
    first = service.claim(row['id'], owner.id)
    assert first
    assert service.claim(row['id'], owner.id) is None
    expire(service, owner, row['id'])
    transport = Transport()
    assert service.dispatch(row['id'], owner.id, transport) == 'accepted'
    assert transport.raw
    with pytest.raises(HTTPException):
        service.checkpoint(row['id'], owner.id, first)


def test_permission_revoked_during_smtp_prepare_stops_before_data(setup, monkeypatch):
    service, owner, *_ = setup
    row = ready(setup)
    original = auth.get_user_by_id
    revoked = False
    class Revoking(Transport):
        def prepare(self, *args):
            nonlocal revoked
            revoked = True
    def account(identifier):
        value = original(identifier)
        return {**value, 'role': 'readonly'} if value is not None and revoked and identifier == owner.id else value
    # locked_account is the authoritative permission read for each write transaction.
    from contextlib import contextmanager
    original_lock = auth.locked_account
    @contextmanager
    def locked(identifier, *args):
        with original_lock(identifier, *args) as value:
            yield {**value, 'role': 'readonly'} if value is not None and revoked else value
    monkeypatch.setattr(auth, 'get_user_by_id', account)
    monkeypatch.setattr(auth, 'locked_account', locked)
    transport = Revoking()
    with pytest.raises(HTTPException):
        service.dispatch(row['id'], owner.id, transport)
    assert transport.raw is None


def test_changed_config_and_changed_draft_reject_confirmation(setup):
    service, owner, thread, _, connection, _ = setup
    row = preview(setup)
    Connections(store, service.connections.manager, service.box).update(connection['id'], ConnectionUpdate(
        idempotency_key=str(uuid4()), base_revision=connection['revision'], name='Neue Revision'), owner.id)
    with pytest.raises(HTTPException) as error:
        service.confirm(row['id'], Confirmation(idempotency_key=str(uuid4()), base_revision=row['revision'], confirmed=True, mime_sha256=row['mime_sha256']), owner.id)
    assert error.value.status_code == 409


def test_draft_replay_conflict_and_durable_reload(setup):
    service, owner, thread, _, connection, _ = setup
    payload = Draft(idempotency_key=str(uuid4()), thread_id=thread.id, source_revision=thread.updated_at.isoformat(),
                    connection_id=connection['id'], config_revision=connection['revision'], to=['a@example.test'], subject='A', body='B')
    row = service.save_draft(payload, owner.id)
    assert service.save_draft(payload, owner.id)['id'] == row['id']
    with pytest.raises(HTTPException):
        service.save_draft(payload.model_copy(update={'body': 'different'}), owner.id)
    assert Communication(store, service.connections.manager, service.box).get(row['id'], owner.id)['body'] == 'B'


class Inbox:
    raw_messages: dict[int, bytes] = {}
    validity = 100
    def __init__(self, config): pass
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def uidvalidity(self): return self.validity
    def next_uids(self, after, limit):
        ids = sorted(uid for uid in self.raw_messages if uid > after)[:limit]
        return ids, max(ids, default=after), False
    def raw(self, uid, maximum): return self.raw_messages[uid]


def incoming(message_id, references='', subject='Gleicher Betreff', content=b'Original\x00\xff'):
    from email.message import EmailMessage
    message = EmailMessage(policy=policy.SMTP)
    message['Message-ID'] = message_id
    message['Subject'] = subject
    message['From'] = 'to@example.test'
    if references:
        message['In-Reply-To'] = references
    message.set_content('Antwort')
    message.add_attachment(content, maintype='application', subtype='octet-stream', filename='../../evil.html')
    return message.as_bytes()


def test_inbox_exact_references_ambiguous_queue_raw_and_uid_dedupe(setup):
    service, owner, thread, other, connection, _ = setup
    first = ready(setup)
    second = ready(setup, thread_id=other.id, source_revision=other.updated_at.isoformat())
    service.dispatch(first['id'], owner.id, Transport())
    service.dispatch(second['id'], owner.id, Transport())
    raws = {1: incoming('<reply1@example.test>', first['message_id']),
            2: incoming('<reply2@example.test>', first['message_id'] + ' ' + second['message_id']),
            3: incoming('<reply3@example.test>')}
    class Adapter(Inbox):
        raw_messages = raws
    assert service.receive(connection['id'], owner.id, Adapter)['received'] == 3
    assert service.receive(connection['id'], owner.id, Adapter)['received'] == 0
    rows = service.page(owner.id, kind='inbound')['items']
    by_uid = {row['uid']: row for row in rows}
    assert by_uid[1]['thread_id'] == thread.id
    assert by_uid[2]['state'] == 'review' and by_uid[2]['review_reason'] == 'ambiguous'
    assert by_uid[3]['state'] == 'review' and by_uid[3]['review_reason'] == 'unmatched'
    for uid, row in by_uid.items():
        assert service.download(row['id'], owner.id)[0] == raws[uid]
        raw, filename, media = service.download(row['id'], owner.id, 0)
        assert raw == b'Original\x00\xff' and '/' not in filename and '\\' not in filename
        assert media == 'application/octet-stream'
    selected = by_uid[2]
    assigned = service.assign(selected['id'], Assignment(idempotency_key=str(uuid4()), base_revision=selected['revision'],
        thread_id=other.id, source_revision=other.updated_at.isoformat(), reason='Manuell geprüft'), owner.id)
    assert assigned['thread_id'] == other.id
    class NewValidity(Adapter):
        validity = 101
    assert service.receive(connection['id'], owner.id, NewValidity)['received'] == 3
    assert service.page(owner.id, kind='inbound')['total'] == 6


def test_receive_disconnect_commits_only_completed_uid_and_resumes(setup):
    service, owner, _, _, connection, _ = setup
    class Interrupted(Inbox):
        raw_messages = {1: incoming('<first@example.test>'), 2: incoming('<second@example.test>')}
        def raw(self, uid, maximum):
            if uid == 2:
                raise OSError('disconnect')
            return super().raw(uid, maximum)
    with pytest.raises(HTTPException):
        service.receive(connection['id'], owner.id, Interrupted)
    assert service.page(owner.id, kind='inbound')['total'] == 1
    class Restart(Inbox):
        raw_messages = Interrupted.raw_messages
    assert service.receive(connection['id'], owner.id, Restart)['received'] == 1
    assert service.page(owner.id, kind='inbound')['total'] == 2

@pytest.mark.parametrize('lost_ack,quit_disconnect,reject_rcpt', [(False, False, False), (True, False, False), (False, True, False), (False, False, True)])
def test_real_loopback_smtp_protocol_mime_and_disconnect(setup, lost_ack, quit_disconnect, reject_rcpt):
    import socketserver
    import threading

    from backend.services.communication_transport import SMTPTransport
    service, owner, *_ = setup
    row = ready(setup)
    class Observation(TypedDict):
        commands: list[str]
        data: bytes | None
    seen: Observation = {'commands': [], 'data': None}
    class Server(socketserver.StreamRequestHandler):
        def handle(self):
            self.wfile.write(b'220 fixture ESMTP\r\n')
            while line := self.rfile.readline():
                seen['commands'].append(line.decode('ascii').strip())
                verb = line.split()[0].upper()
                if verb == b'EHLO':
                    self.wfile.write(b'250-fixture\r\n250 SIZE 52428800\r\n')
                elif verb in (b'MAIL', b'RCPT'):
                    self.wfile.write(b'550 rejected\r\n' if reject_rcpt and b'cc@example.test' in line else b'250 OK\r\n')
                elif verb == b'DATA':
                    self.wfile.write(b'354 End with dot\r\n')
                    data = bytearray()
                    while (part := self.rfile.readline()) != b'.\r\n':
                        if not part:
                            return
                        data.extend(part[1:] if part.startswith(b'..') else part)
                    seen['data'] = bytes(data)
                    if lost_ack:
                        return
                    self.wfile.write(b'250 queued fixture-123\r\n')
                elif verb == b'QUIT':
                    if not quit_disconnect:
                        self.wfile.write(b'221 bye\r\n')
                    return
                else:
                    self.wfile.write(b'500 unsupported\r\n')
    with socketserver.TCPServer(('127.0.0.1', 0), Server) as server:
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        class LocalTransport(SMTPTransport):
            def prepare(self, config, sender, recipients):
                super().prepare({**config, 'smtp_host': '127.0.0.1', 'smtp_port': server.server_address[1], 'smtp_use_tls': False}, sender, recipients)
        try:
            assert service.dispatch(row['id'], owner.id, LocalTransport()) == ('failed' if reject_rcpt else 'unknown' if lost_ack else 'accepted')
        finally:
            server.shutdown()
            worker.join(timeout=3)
    if reject_rcpt:
        assert seen['data'] is None and 'data' not in seen['commands']
    else:
        assert seen['data'] == service.download(row['id'], owner.id)[0]
    assert [line for line in seen['commands'] if line.startswith('rcpt TO:')] == [
        'rcpt TO:<to@example.test>', 'rcpt TO:<cc@example.test>', 'rcpt TO:<blind@example.test>'][:2 if reject_rcpt else 3]
    if seen['data']:
        assert b'Bcc:' not in seen['data']
    if not lost_ack and not reject_rcpt:
        import base64
        receipt = service.get(row['id'], owner.id)['transport_receipts'][-1]['response']
        assert receipt['code'] == 250
        assert base64.b64decode(receipt['response_b64']) == b'queued fixture-123'


def test_real_loopback_imap_uses_examine_uid_and_peek_only(setup, monkeypatch):
    import imaplib
    import re
    import socketserver
    import threading
    service, owner, _, _, connection, _ = setup
    original = incoming('<local-imap@example.test>')
    commands_seen = []
    class Server(socketserver.StreamRequestHandler):
        def handle(self):
            self.wfile.write(b'* OK local fixture ready\r\n')
            while line := self.rfile.readline():
                text = line.decode('ascii').strip()
                commands_seen.append(text)
                tag, command, *args = text.split()
                if command == 'CAPABILITY':
                    self.wfile.write(b'* CAPABILITY IMAP4rev1\r\n')
                elif command == 'LOGIN':
                    pass
                elif command == 'EXAMINE':
                    self.wfile.write(b'* 1 EXISTS\r\n* OK [UIDVALIDITY 991] valid\r\n* OK [UIDNEXT 7] next\r\n')
                elif command == 'UID' and args[0] == 'FETCH':
                    if 'BODY.PEEK[]' in text:
                        self.wfile.write(f'* 1 FETCH (UID 6 BODY[] {{{len(original)}}}\r\n'.encode() + original + b')\r\n')
                    elif 'RFC822.SIZE' in text:
                        self.wfile.write(f'* 1 FETCH (UID 6 RFC822.SIZE {len(original)})\r\n'.encode())
                    elif re.search(r'FETCH \d+:\d+', text):
                        self.wfile.write(b'* 1 FETCH (UID 6)\r\n')
                elif command == 'LOGOUT':
                    self.wfile.write(b'* BYE local fixture\r\n' + tag.encode() + b' OK logout\r\n')
                    return
                else:
                    self.wfile.write(tag.encode() + b' BAD write forbidden\r\n')
                    continue
                self.wfile.write(tag.encode() + b' OK done\r\n')
    with socketserver.TCPServer(('127.0.0.1', 0), Server) as server:
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        # Real local IMAP protocol; TLS construction is separately covered by transport configuration tests.
        monkeypatch.setattr(imaplib, 'IMAP4_SSL', lambda *a, **kw: imaplib.IMAP4('127.0.0.1', server.server_address[1], timeout=5))
        try:
            result = service.receive(connection['id'], owner.id)
            assert result['received'] == 1 and result['uidvalidity'] == 991 and result['uid'] == 6
        finally:
            server.shutdown()
            worker.join(timeout=3)
    assert any(' EXAMINE ' in text for text in commands_seen)
    assert any('BODY.PEEK[]' in text for text in commands_seen)
    assert not any(re.search(r'\b(STORE|EXPUNGE|CLOSE|SELECT|APPEND)\b', text) for text in commands_seen)
    row = service.page(owner.id, kind='inbound')['items'][0]
    assert service.download(row['id'], owner.id)[0] == original


def test_uploaded_non_pdf_original_transmitted_and_changed_bytes_refuse_confirmation(setup, tmp_path, monkeypatch):
    from backend.services import file_storage
    from backend.services.file_storage import LocalStorage
    service, owner, _, _, _, prop = setup
    storage = LocalStorage(tmp_path / 'fixture-uploads')
    monkeypatch.setattr(file_storage, 'get_file_storage', lambda: storage)
    path = storage.base_dir / 'original.txt'
    original = b'\xff\x00\r\n unveraenderte Originaldatei'
    path.write_bytes(original)
    document = store.create_document(DocumentCreate(title='Dateioriginal', document_type='other', property_id=prop.id, file_url='/uploads/original.txt'))
    choice = service.attachment_choices(document.id, owner.id)['items'][0]
    attachment = dict(document_id=document.id, version_id='upload', sha256=choice['sha256'], document_revision=choice['document_revision'])
    row = ready(setup, attachments=[attachment])
    transport = Transport()
    assert service.dispatch(row['id'], owner.id, transport) == 'accepted'
    assert transport.raw is not None
    assert list(BytesParser(policy=policy.default).parsebytes(transport.raw).iter_attachments())[0].get_payload(decode=True) == original
    other = preview(setup, attachments=[attachment])
    path.write_bytes(b'Changed after preview')
    with pytest.raises(HTTPException) as error:
        service.confirm(other['id'], Confirmation(idempotency_key=str(uuid4()), base_revision=other['revision'], confirmed=True, mime_sha256=other['mime_sha256']), owner.id)
    assert error.value.status_code == 409
    assert service.download(other['id'], owner.id)[0] != b'Changed after preview'


def test_one_frozen_preview_per_draft_revision_and_consumed_draft_cannot_send_twice(setup):
    service, owner, *_ = setup
    row = draft(setup)
    first = service.preview(row['id'], RevisionCommand(idempotency_key=str(uuid4()), base_revision=row['revision']), owner.id)
    second = service.preview(row['id'], RevisionCommand(idempotency_key=str(uuid4()), base_revision=row['revision']), owner.id)
    assert first['id'] == second['id'] and first['message_id'] == second['message_id']
    service.confirm(first['id'], Confirmation(idempotency_key=str(uuid4()), base_revision=first['revision'], confirmed=True, mime_sha256=first['mime_sha256']), owner.id)
    current = service.get(row['id'], owner.id)
    values = {key: value for key, value in current.items() if key in Draft.model_fields and key != 'base_revision'}
    with pytest.raises(HTTPException):
        service.save_draft(Draft(**values, base_revision=current['revision'], idempotency_key=str(uuid4())), owner.id, row['id'])


def test_unknown_requires_documented_reconciliation_no_retry_even_after_rejected(setup):
    from backend.services.communication import Decision
    service, owner, *_ = setup
    row = ready(setup)
    service.dispatch(row['id'], owner.id, Transport('lost'))
    current = service.get(row['id'], owner.id)
    command = Decision(base_revision=current['revision'], idempotency_key=str(uuid4()), decision='rejected', evidence='Serverprotokoll bestätigt keine Annahme.')
    assert service.reconcile(row['id'], command, owner.id)['state'] == 'rejected'
    assert service.reconcile(row['id'], command, owner.id)['state'] == 'rejected'
    assert service.dispatch(row['id'], owner.id, Transport()) == 'rejected'


def test_job_restart_recovers_release_without_http_enqueue_and_does_not_duplicate(setup, monkeypatch):
    from backend import dependencies
    from backend.services.integrations import manager as managers
    from backend.services.jobs import communication as bridge
    from backend.services.jobs.communication import KIND, recover
    from backend.services.jobs.core import JobRunner, MemoryJobStore, SqlJobStore
    service, owner, *_ = setup
    row = ready(setup)
    monkeypatch.setattr(dependencies, 'store', store)
    monkeypatch.setattr(managers, 'integration_manager', service.connections.manager)
    # Use this fixture's keyring on worker restart, as the real default keyring is installation owned.
    monkeypatch.setattr(bridge, 'Communication', lambda source, manager: service)
    import backend.services.communication_transport as protocol
    calls = []
    class Recording(Transport):
        def data(self, raw):
            calls.append(raw)
            return super().data(raw)
    monkeypatch.setattr(protocol, 'SMTPTransport', Recording)
    jobs = SqlJobStore(store.db.get_bind()) if hasattr(store, 'db') else MemoryJobStore(store_factory=lambda: store)
    recover(jobs)
    recover(jobs)
    assert len(jobs.list_runs()) == 1
    runner = JobRunner(jobs, {KIND: bridge.handler})
    runner.run_until_idle(max_jobs=1)
    assert service.get(row['id'], owner.id)['state'] == 'accepted'
    recover(jobs)
    runner.run_until_idle(max_jobs=1)
    assert len(calls) == 1

@pytest.mark.parametrize('checkpoint_failure', [True, False])
def test_persistence_failure_never_sends_without_checkpoint_or_repeats_unknown(setup, monkeypatch, checkpoint_failure):
    service, owner, *_ = setup
    row = ready(setup)
    original_transition = service.transition
    def failing(unit, current, state, *args, **kwargs):
        if (checkpoint_failure and state == 'data_pending') or (not checkpoint_failure and state in ('accepted', 'unknown')):
            raise OSError('synthetic durable write failure')
        return original_transition(unit, current, state, *args, **kwargs)
    monkeypatch.setattr(service, 'transition', failing)
    transport = Transport()
    if checkpoint_failure:
        assert service.dispatch(row['id'], owner.id, transport) == 'failed'
        assert transport.raw is None
    else:
        with pytest.raises(OSError):
            service.dispatch(row['id'], owner.id, transport)
        assert transport.raw and service.get(row['id'], owner.id)['state'] == 'data_pending'
        monkeypatch.setattr(service, 'transition', original_transition)
        expire(service, owner, row['id'])
        second = Transport()
        assert service.dispatch(row['id'], owner.id, second) == 'unknown'
        assert second.raw is None


def test_two_workers_cannot_transmit_the_same_message(setup):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    service, owner, *_ = setup
    row = ready(setup)
    prepared = Event()
    release = Event()
    class Paused(Transport):
        def prepare(self, *args):
            super().prepare(*args)
            prepared.set()
            assert release.wait(10)
    first, second = Paused(), Transport()
    with ThreadPoolExecutor(max_workers=1) as worker:
        future = worker.submit(service.dispatch, row['id'], owner.id, first)
        assert prepared.wait(10)
        assert service.dispatch(row['id'], owner.id, second) == 'claimed'
        release.set()
        assert future.result(timeout=10) == 'accepted'
    assert first.raw and second.raw is None


def test_private_drafts_hidden_from_other_account_and_readonly_cannot_release(setup):
    service, owner, *_ = setup
    row = draft(setup)
    other = auth.register_user('other-' + uuid4().hex[:8], 'other@example.test', 'Andere Person', 'Secret123', 'readonly')
    with pytest.raises(HTTPException) as error:
        service.get(row['id'], other.id)
    assert error.value.status_code == 404
    outgoing = preview(setup)
    assert service.get(outgoing['id'], other.id)['state'] == 'preview'
    with pytest.raises(HTTPException) as error:
        service.confirm(outgoing['id'], Confirmation(base_revision=outgoing['revision'], idempotency_key=str(uuid4()),
            confirmed=True, mime_sha256=outgoing['mime_sha256']), other.id)
    assert error.value.status_code == 403


def test_additive_migration_preserves_existing_rows_and_guards_new_evidence(tmp_path):
    from alembic import command
    from sqlalchemy import create_engine, inspect
    from sqlalchemy.exc import IntegrityError

    from backend.db.schema_state import alembic_config
    url = f"sqlite:///{(tmp_path / 'migration-fixture.db').as_posix()}"
    config = alembic_config(url)
    command.upgrade(config, 'd73f2b9a041c')
    engine = create_engine(url)
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql('CREATE TABLE fixture_existing_originals (id TEXT PRIMARY KEY, content BLOB)')
            connection.exec_driver_sql("INSERT INTO fixture_existing_originals VALUES ('retained', X'0001FF0D0A')")
            tables = inspect(connection).get_table_names()
            before = {name: connection.exec_driver_sql(f'SELECT * FROM "{name}"').all() for name in tables if name != 'alembic_version'}
        command.upgrade(config, 'e160a1b2c304')
        with engine.begin() as connection:
            for name, values in before.items():
                assert connection.exec_driver_sql(f'SELECT * FROM "{name}"').all() == values
            assert connection.exec_driver_sql('SELECT version_num FROM alembic_version').scalar_one() == 'e160a1b2c304'
            connection.exec_driver_sql("INSERT INTO communication_evidence VALUES ('e','i',?,3,'2026-10-16')", ('a' * 64,))
        with pytest.raises(IntegrityError), engine.begin() as connection:
            connection.exec_driver_sql("UPDATE communication_evidence SET sha256='changed' WHERE id='e'")
        with pytest.raises(IntegrityError), engine.begin() as connection:
            connection.exec_driver_sql("DELETE FROM communication_evidence WHERE id='e'")
    finally:
        engine.dispose()


def test_full_backup_restores_mime_keyring_receipts_and_uncertain_restart(tmp_path, monkeypatch):
    import json

    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session, sessionmaker

    from backend.db import schema_state
    from backend.repositories.sql_store import SQLAlchemyStore
    from backend.services import full_backup
    from backend.services.full_backup import Sources
    from backend.services.secret_box import SecretBox
    data = tmp_path / 'original'
    data.mkdir()
    uploads = data / 'uploads'
    uploads.mkdir()
    database = data / 'immo_manager.db'
    engine = create_engine(f'sqlite:///{database.as_posix()}')
    restored_engine = None
    try:
        schema_state.initialise_empty(engine)
        monkeypatch.setattr(auth, '_user_store', auth.SQLUserStore(sessionmaker(bind=engine)))
        owner = auth.register_user('restore-mail', 'restore@example.test', 'Wiederherstellung', 'Secret123', 'eigentuemer')
        box = SecretBox(data / 'secrets' / 'keyring.json')
        manager = IntegrationManager()
        manager.seed_defaults()
        with Session(engine) as session:
            source = SQLAlchemyStore(session)
            portfolio = source.create_portfolio(PortfolioCreate(name='Restore'))
            prop = source.create_property(PropertyCreate(portfolio_id=portfolio.id, name='Restore-Haus', property_type='residential'))
            thread = source.create_message_thread(MessageThreadCreate(subject='Wiederanlauf', property_id=prop.id))
            connection = Connections(source, manager, box).create(ConnectionCreate(idempotency_key=str(uuid4()), provider_id='email',
                name='Restore SMTP', enabled=True, config=dict(sender_email='restore@example.test', smtp_host='smtp.invalid')), owner.id)
            service = Communication(source, manager, box)
            draft_row = service.save_draft(Draft(idempotency_key=str(uuid4()), thread_id=thread.id, source_revision=thread.updated_at.isoformat(),
                connection_id=connection['id'], config_revision=connection['revision'], to=['target@example.test'], subject='Original', body='Originalinhalt'), owner.id)
            frozen = service.preview(draft_row['id'], RevisionCommand(idempotency_key=str(uuid4()), base_revision=1), owner.id)
            confirmation = Confirmation(idempotency_key=str(uuid4()), base_revision=1, mime_sha256=frozen['mime_sha256'], confirmed=True)
            service.confirm(frozen['id'], confirmation, owner.id)
            with pytest.raises(SystemExit):
                service.dispatch(frozen['id'], owner.id, Transport('crash'))
            expire(service, owner, frozen['id'])
            original_raw = service.download(frozen['id'], owner.id)[0]
        state = data / 'integrations.json'
        state.write_text(json.dumps({'enabled': {}, 'config': {}}), encoding='utf-8')
        env = data / '.env'
        env.write_text('JOB_SCHEDULER_ENABLED=false\nBACKUP_SCHEDULE_ENABLED=false\n', encoding='utf-8')
        sources = Sources(database_url=f'sqlite:///{database.as_posix()}', data_dir=data, uploads_dir=uploads,
                          root=data / 'backups', integration_state=state, key_file=box.key_file, env_file=env)
        backup = full_backup.create_full_backup('manual', sources)
        assert backup['ok'] and backup['missing_key_ids'] == []
        import sqlite3
        from contextlib import closing

        from backend.services.communication_backup import needed_key_ids, verify
        from backend.services.secret_box import SecretKeyMissing
        with closing(sqlite3.connect(database)) as sql_connection:
            tables = {item[0] for item in sql_connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            assert needed_key_ids(sql_connection, tables) == sorted(key.id for key in box.keys())
            assert verify(sql_connection, box.keys(), tables)['originals'] == 1
            with pytest.raises(SecretKeyMissing):
                verify(sql_connection, [], tables)
        probe = full_backup.restore_probe(sources.root / backup['archive'], sources)
        assert probe['ok']
        target = tmp_path / 'restored'
        assert full_backup.restore_archive(sources.root / backup['archive'], target)['revision'] == schema_state.head_revision()
        engine.dispose()
        data.rename(tmp_path / 'source-unavailable')
        assert not database.exists()
        restored_engine = create_engine(f"sqlite:///{(target / 'immo_manager.db').as_posix()}")
        monkeypatch.setattr(auth, '_user_store', auth.SQLUserStore(sessionmaker(bind=restored_engine)))
        with Session(restored_engine) as session:
            restored = Communication(SQLAlchemyStore(session), manager, SecretBox(target / 'secrets' / 'keyring.json'))
            assert restored.download(frozen['id'], owner.id)[0] == original_raw
            assert restored.confirm(frozen['id'], confirmation, owner.id)['id'] == frozen['id']
            transport = Transport()
            assert restored.dispatch(frozen['id'], owner.id, transport) == 'unknown'
            assert transport.raw is None
    finally:
        engine.dispose()
        if restored_engine:
            restored_engine.dispose()


def test_receive_error_explicit_defer_and_later_original_recovery(setup):
    from backend.services.communication import SkipIncoming
    service, owner, _, _, connection, _ = setup
    originals = {1: incoming('<one@example.test>'), 2: incoming('<two@example.test>'), 3: incoming('<three@example.test>')}
    class Interrupted(Inbox):
        raw_messages = originals
        def raw(self, uid, maximum):
            if uid == 2:
                raise ValueError('synthetic oversized original')
            return super().raw(uid, maximum)
    with pytest.raises(HTTPException):
        service.receive(connection['id'], owner.id, Interrupted)
    mailbox = service.page(owner.id, kind='mailbox')['items'][0]
    assert mailbox['uid'] == 1 and mailbox['last_error']['uid'] == 2
    payload = SkipIncoming(base_revision=mailbox['revision'], idempotency_key=str(uuid4()), reason='Das Original wird separat auf dem Server geprüft.')
    deferred = service.skip_incoming(mailbox['id'], payload, owner.id)
    assert deferred['state'] == 'deferred' and deferred['raw_available'] is False
    assert service.skip_incoming(mailbox['id'], payload, owner.id)['id'] == deferred['id']
    class Normal(Inbox):
        raw_messages = originals
    assert service.receive(connection['id'], owner.id, Normal)['received'] == 1
    result = service.receive_again(deferred['id'], RevisionCommand(base_revision=deferred['revision'], idempotency_key=str(uuid4())), owner.id, Normal)
    assert result['id'] == deferred['id'] and result['raw_available'] is True and result['state'] == 'review'
    assert service.download(result['id'], owner.id)[0] == originals[2]
    assert service.page(owner.id, kind='inbound')['total'] == 3


def test_receive_command_replay_does_not_access_account_again(setup):
    from backend.services.communication import ReceiveCommand
    service, owner, _, _, connection, _ = setup
    class Adapter(Inbox):
        raw_messages = {1: incoming('<one@example.test>')}
    payload = ReceiveCommand(idempotency_key=str(uuid4()), config_revision=connection['revision'])
    assert service.receive(connection['id'], owner.id, Adapter, command=payload)['received'] == 1
    class MustNotConnect:
        def __init__(self, config):
            raise AssertionError('Replayed command must not contact IMAP')
    assert service.receive(connection['id'], owner.id, MustNotConnect, command=payload)['received'] == 1


def test_restart_reaps_data_pending_independently_of_revoked_sender_account(setup):
    from backend.services.jobs.communication import reap
    service, owner, *_ = setup
    row = ready(setup)
    with pytest.raises(SystemExit):
        service.dispatch(row['id'], owner.id, Transport('crash'))
    expire(service, owner, row['id'])
    # Reaping is a conservative scheduler metadata transition; no authorizing account or MIME read.
    reap(store)
    assert service.get(row['id'], owner.id)['state'] == 'unknown'
    assert service.claim(row['id'], owner.id) is None


def test_internal_reply_private_workspace_draft_persists_with_revisions(setup):
    from backend.services import workspace
    service, owner, thread, *_ = setup
    identifier = str(uuid4())
    payload = dict(base_revision=0, idempotency_key=str(uuid4()), context='message-reply', mode='edit',
                   source=dict(kind='message_thread', id=thread.id, revision=thread.updated_at.isoformat()),
                   anchor=dict(kind='message_thread', id=thread.id), field_keys=['body'], form_key='reply-body',
                   values=dict(body='Nicht verlorener Antwortentwurf'))
    saved = workspace.mutate(store, owner.id, 'drafts', identifier, payload)
    assert saved['values']['body'] == 'Nicht verlorener Antwortentwurf'
    assert workspace.mutate(store, owner.id, 'drafts', identifier, payload)['revision'] == saved['revision']
    assert workspace.get_record(store, owner.id, 'drafts', identifier)['values'] == payload['values']
    another = auth.register_user('draft-' + uuid4().hex[:8], 'draft@example.test', 'Fremdes Konto', 'Secret123', 'eigentuemer')
    with pytest.raises(HTTPException):
        workspace.get_record(store, another.id, 'drafts', identifier)
    assert service.store.list_messages(thread_id=thread.id) == []


def test_current_portfolio_revocation_hides_mime_and_receipt_replays(setup):
    service, owner, thread, _, _, prop = setup
    row = preview(setup)
    user = auth.register_user('scope-' + uuid4().hex[:8], 'scope@example.test', 'Sachbearbeitung', 'Secret123', 'verwalter',
                              portfolio_access='selected', portfolio_ids=[prop.portfolio_id])
    assert service.download(row['id'], user.id)[0]
    command = Confirmation(base_revision=row['revision'], idempotency_key=str(uuid4()), confirmed=True, mime_sha256=row['mime_sha256'])
    service.confirm(row['id'], command, user.id)
    auth.update_user(user.id, {'portfolio_access': 'selected', 'portfolio_ids': []})
    with pytest.raises(HTTPException) as error:
        service.download(row['id'], user.id)
    assert error.value.status_code == 404
    with pytest.raises(HTTPException):
        service.confirm(row['id'], command, user.id)
    with pytest.raises(HTTPException):
        service.page(user.id, thread_id=thread.id)


def test_manual_dunning_bridge_reads_existing_outbox_without_copy_or_smtp(setup, monkeypatch):
    from fastapi.testclient import TestClient

    from backend.app import app
    from backend.routers import dunning as router
    from backend.services import dunning
    from backend.tests import test_dunning as helpers
    service, owner, *_ = setup
    monkeypatch.setattr(helpers, 'store', store)
    monkeypatch.setattr(router, 'store', store)
    headers = {'Authorization': f'Bearer {auth.create_access_token(owner.id)}'}
    client = TestClient(app)
    lease = helpers._lease(email='fixture-recipient@example.test')
    [letter] = helpers._run(client, headers, lease['contract'].id, '2026-07-10')['letters']
    result = helpers._finalize(client, headers, letter['id'], channel='email')
    assert result.status_code == 200, result.text
    entry = result.json()['outbox']
    rows = service.page(owner.id, kind='manual_dunning')
    assert rows['total'] == 1 and rows['items'][0]['id'] == entry['id']
    assert rows['items'][0]['state'] == 'manual_ready'
    assert service.page(owner.id, kind='outbound')['total'] == 0
    first_eml, _ = dunning.email_draft(store, entry['id'], owner.id)
    parsed = BytesParser(policy=policy.default).parsebytes(first_eml)
    attachment = list(parsed.iter_attachments())[0].get_payload(decode=True)
    document_id = result.json()['document_id']
    with archive.work(store, owner.id) as unit:
        original_version = archive.head(unit, document_id)
        assert original_version is not None
        assert attachment == archive.original_bytes(unit, original_version)
    with pytest.raises(HTTPException):
        service.claim(entry['id'], owner.id)
    marked = client.post(f"/api/v1/dunning/outbox/{entry['id']}/mark-sent", headers=headers, json={'sent_on': '2026-07-11', 'via': 'Lokales Mailprogramm'})
    assert marked.status_code == 200
    assert service.page(owner.id, kind='manual_dunning')['items'][0]['state'] == 'manual_sent'
    assert service.page(owner.id, kind='outbound')['total'] == 0
