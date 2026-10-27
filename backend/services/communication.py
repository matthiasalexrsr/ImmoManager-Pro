"""Immutable previews, explicit release, fenced SMTP and exact reply correlation.

Never retries DATA ambiguity. The job runner may restart this module freely:
claimed-before-DATA can resume after expiry; data_pending becomes unknown.
"""
from __future__ import annotations

import base64
import hashlib
import re
from contextlib import contextmanager
from datetime import timedelta
from email import policy
from email.message import EmailMessage
from email.parser import BytesParser
from email.utils import format_datetime
from typing import Literal
from uuid import uuid4

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select

from ..db.communication_models import CommunicationAttachmentORM as AttachmentReference
from ..db.communication_models import CommunicationBlockORM as Block
from ..db.communication_models import CommunicationEvidenceORM as Evidence
from ..db.communication_models import CommunicationItemORM as Item
from ..db.integration_connection_models import IntegrationConnectionORM
from . import business_qol as commands
from . import document_versions as archive
from .integrations import connection_storage as dbs
from .integrations.connections import Connections
from .portfolio_scope import scope_context, scope_from_user
from .workspace_contexts import bound_actor, resolve_context

MAX_BYTES = 25 * 1024 * 1024
MESSAGE_ID = re.compile(r'<[^<>\s\x00-\x20\x7f-\U0010ffff]+@[^<>\s\x00-\x20\x7f-\U0010ffff]+>')
ADDRESS = re.compile(r"[^\s<>@,;\x00-\x1f\x7f]+@[^\s<>@,;\x00-\x1f\x7f]+\.[^\s<>@,;\x00-\x1f\x7f]+")


class Command(BaseModel):
    model_config = ConfigDict(extra="forbid")
    idempotency_key: str = Field(min_length=1, max_length=128)


class RevisionCommand(Command):
    base_revision: int = Field(ge=1)


class Attachment(BaseModel):
    model_config = ConfigDict(extra="forbid")
    document_id: str = Field(min_length=1, max_length=120)
    version_id: str = Field(min_length=1, max_length=120)
    document_revision: str | None = Field(default=None, max_length=200)
    sha256: str = Field(pattern=r'^[a-f0-9]{64}$')


class Draft(Command):
    thread_id: str = Field(min_length=1, max_length=120)
    source_revision: str = Field(min_length=1, max_length=200)
    connection_id: str = Field(min_length=1, max_length=36)
    config_revision: int = Field(ge=1)
    to: list[str] = Field(default_factory=list, max_length=100)
    cc: list[str] = Field(default_factory=list, max_length=100)
    bcc: list[str] = Field(default_factory=list, max_length=100)
    subject: str = Field(max_length=998)
    body: str = Field(max_length=200000)
    attachments: list[Attachment] = Field(default_factory=list, max_length=50)
    template_id: str | None = Field(default=None, max_length=36)
    template_revision: int | None = Field(default=None, ge=1)
    snippet_ids: list[str] = Field(default_factory=list, max_length=50)
    snippet_revisions: dict[str, int] = Field(default_factory=dict, max_length=50)
    reply_to_item_id: str | None = Field(default=None, max_length=36)
    base_revision: int | None = Field(default=None, ge=1)

    @field_validator('to', 'cc', 'bcc')
    @classmethod
    def recipients(cls, values):
        if any(not value.isascii() or not ADDRESS.fullmatch(value) or len(value) > 254 for value in values):
            raise ValueError('Bitte einzelne gültige E-Mail-Adressen ohne Anzeigenamen eingeben.')
        return list(dict.fromkeys(values))

    @field_validator('subject')
    @classmethod
    def header(cls, value):
        if any(ord(char) < 32 or ord(char) == 127 for char in value):
            raise ValueError('Der Betreff darf keine Steuerzeichen enthalten.')
        return value

    @field_validator('snippet_ids')
    @classmethod
    def snippets(cls, values):
        if any(not value or len(value) > 36 for value in values):
            raise ValueError('Ungültige Textbausteinkennung.')
        return list(dict.fromkeys(values))


class Confirmation(RevisionCommand):
    mime_sha256: str = Field(pattern=r'^[a-f0-9]{64}$')
    confirmed: Literal[True]


class Decision(RevisionCommand):
    decision: Literal['accepted', 'rejected']
    evidence: str = Field(min_length=10, max_length=4000)


class Assignment(RevisionCommand):
    thread_id: str = Field(min_length=1, max_length=120)
    source_revision: str = Field(min_length=1, max_length=200)
    reason: str = Field(min_length=5, max_length=2000)


class SkipIncoming(RevisionCommand):
    reason: str = Field(min_length=10, max_length=2000)


class ReceiveCommand(Command):
    config_revision: int = Field(ge=1)


class Template(Command):
    usage: Literal['template', 'snippet'] = 'template'
    name: str = Field(min_length=1, max_length=200)
    subject: str = Field(max_length=998)
    body: str = Field(max_length=200000)
    predecessor_id: str | None = Field(default=None, max_length=36)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


class Communication:
    def __init__(self, store, manager, box=None):
        self.store = store
        self.connections = Connections(store, manager, box)
        self.box = box

    @contextmanager
    def work(self, actor_id, write=False):
        with archive.work(self.store, actor_id, write_areas=('/messages',) if write else ()) as unit:
            with bound_actor(unit.user), scope_context(scope_from_user(unit.user)):
                yield unit

    def data(self, row):
        return dbs.unseal(row.payload_token, 'communication/' + row.id, self.box)

    def put(self, unit, row, payload, **changes):
        values = dbs.values(row)
        values.update(changes)
        values['payload_token'] = dbs.seal(payload, 'communication/' + row.id, self.box)
        values['updated_at'] = dbs.now()
        return dbs.put(unit, Item, values)

    def new(self, unit, kind, payload, **fields):
        identifier = str(uuid4())
        return dbs.put(unit, Item, dict(id=identifier, kind=kind, actor_id=unit.actor_id,
            thread_id=None, connection_id=None, state='draft', revision=1,
            payload_token=dbs.seal(payload, 'communication/' + identifier, self.box),
            message_id=None, dedupe_key=None, lease_token=None, lease_until=None,
            created_at=dbs.now(), updated_at=dbs.now(), **fields))

    def thread_context(self, unit, identifier, *, lock=False):
        context = resolve_context(unit.store, 'message_thread', identifier, unit.actor_id, lock=lock)
        portfolios = set(context['portfolio_ids'])
        # These current thread columns are text references, not ORM foreign keys.
        # Resolve the real parents explicitly rather than assuming the generic
        # context's FK traversal returned their portfolio bindings.
        for kind, field in (('property', 'property_id'), ('unit', 'unit_id'), ('contract', 'contract_id')):
            if context['values'].get(field):
                parent = resolve_context(unit.store, kind, context['values'][field], unit.actor_id, lock=lock)
                portfolios.update(parent['portfolio_ids'])
        if unit.db is not None:
            from ..db.access_models import ResourcePortfolioORM
            portfolios.update(unit.db.scalars(select(ResourcePortfolioORM.portfolio_id).where(
                ResourcePortfolioORM.resource_type == 'message_threads', ResourcePortfolioORM.resource_id == identifier)))
        else:
            portfolios.update(pid for table, key, pid in unit.store.__dict__.get('_resource_grants', ())
                              if table == 'message_threads' and key == identifier)
        return {**context, 'portfolio_ids': sorted(portfolios)}

    def access(self, unit, row, private=False):
        data = self.data(row)
        scope = scope_from_user(unit.user)
        original_portfolios = set(data.get('origin_portfolio_ids', data.get('source', {}).get('portfolio_ids', [])))
        if not scope.unrestricted and not original_portfolios.issubset(set(scope.portfolio_ids)):
            raise HTTPException(404, 'Nachricht nicht gefunden.')
        if data.get('notification_recipient_id'):
            from .notification_email import context as notification_context
            _, context = notification_context(unit, data)
        elif row.thread_id:
            context = self.thread_context(unit, row.thread_id)
        elif row.kind == 'template':
            context = dict(kind='integration_connection', entity_id=row.id, property_id=None)
        else:
            context = dict(kind='integration_connection', entity_id=row.connection_id or row.id, property_id=None)
            if not scope_from_user(unit.user).unrestricted:
                raise HTTPException(403, 'Für den ungeklärten Posteingang benötigen Sie Zugriff auf alle Portfolios.')
        if row.kind in ('outbound', 'draft'):
            for attachment in self.data(row).get('attachments', []):
                resolve_context(unit.store, 'document', attachment['document_id'], unit.actor_id)
        if (private or row.kind == 'draft') and row.actor_id != unit.actor_id:
            raise HTTPException(404, 'Entwurf nicht gefunden.')
        return context

    def public(self, unit, row):
        self.access(unit, row)
        payload = self.data(row)
        if row.state in ('unknown', 'blocked') and (not payload.get('history') or payload['history'][-1]['state'] != row.state):
            payload.setdefault('history', []).append(dict(state=row.state, at=dbs.stamp(row.updated_at), detail='Wiederanlauf nach Ablauf der Workerfreigabe' if row.state == 'unknown' else 'Versand wegen geänderter Rechte oder Quellen gesperrt'))
        return {**payload, 'id': row.id, 'kind': row.kind, 'state': row.state, 'revision': row.revision,
                'thread_id': row.thread_id, 'connection_id': row.connection_id, 'message_id': row.message_id,
                'created_at': dbs.stamp(row.created_at), 'updated_at': dbs.stamp(row.updated_at)}

    def get(self, identifier, actor_id):
        with self.work(actor_id) as unit:
            return self.public(unit, dbs.row(unit, Item, identifier))

    def page(self, actor_id, *, kind='outbound', thread_id=None, cursor=None, limit=50):
        if kind == 'manual_dunning':
            return self.manual_dunning_page(actor_id, thread_id=thread_id, cursor=cursor, limit=limit)
        if kind not in ('draft', 'outbound', 'inbound', 'template', 'mailbox', 'notification'):
            raise HTTPException(422, 'Unbekannte Nachrichtenart.')
        with self.work(actor_id) as unit:
            if thread_id:
                resolve_context(unit.store, 'message_thread', thread_id, actor_id)
            elif kind != 'notification' and not scope_from_user(unit.user).unrestricted:
                raise HTTPException(403, 'Bitte eine berechtigte Konversation öffnen.')
            filters = dict(kind=kind)
            if thread_id:
                filters['thread_id'] = thread_id
            if kind in ('draft', 'notification'):
                filters['actor_id'] = actor_id
            result = dbs.page(unit, Item, actor_id, cursor=cursor, limit=limit, **filters)
            result['items'] = [self.public(unit, row) for row in result['items']]
            return result

    def manual_dunning_page(self, actor_id, *, thread_id=None, cursor=None, limit=50):
        from ..db.dunning_models import DunningOutboxORM
        from . import dunning

        if not 1 <= limit <= 250:
            raise HTTPException(422, 'Bitte eine gültige Seitengröße wählen.')
        with self.work(actor_id) as unit:
            filters = {}
            if thread_id:
                source = resolve_context(unit.store, 'message_thread', thread_id, actor_id)
                contract_id = source['values'].get('contract_id')
                if not contract_id:
                    return dict(items=[], total=0, next_cursor=None, has_more=False)
                filters['contract_id'] = contract_id
            if unit.db is not None:
                result = dbs.page(unit, DunningOutboxORM, actor_id, cursor=cursor, limit=limit, **filters)
                entries = [dunning.DunningOutbox.model_validate(dbs.values(row)) for row in result['items']]
            else:
                namespace = ['communication-manual-dunning', actor_id, thread_id]
                anchor = commands.cursor_decode(cursor, namespace)
                entries = sorted(dunning._rows(unit, 'dunning_outbox', **filters), key=lambda row: (dbs.stamp(row.created_at), row.id), reverse=True)
                total = len(entries)
                if anchor:
                    if len(anchor) != 2 or not all(isinstance(value, str) for value in anchor):
                        raise HTTPException(422, 'Ungültige Fortsetzung.')
                    entries = [row for row in entries if (dbs.stamp(row.created_at), row.id) < tuple(anchor)]
                more = len(entries) > limit
                entries = entries[:limit]
                result = dict(total=total, has_more=more, next_cursor=commands.cursor_encode(namespace, [dbs.stamp(entries[-1].created_at), entries[-1].id]) if more else None)
            result['items'] = [dict(**dunning._outbox_public(row), kind='manual_dunning', direction='outbound',
                state='manual_' + row.status, to=[row.recipient_email] if row.recipient_email else [], cc=[], bcc=[],
                attachments=[], history=[], manual_eml_available=row.channel == 'email' and row.status in ('ready', 'sent'), source_href='/contracts?focus_id=' + row.contract_id) for row in entries]
            return result

    def command(self, unit, operation, payload, context, row):
        commands.save_command(unit, unit.actor_id, 'communication:' + operation, payload, context, {'item_id': row.id})

    def replay(self, unit, operation, payload):
        prior = commands.replay(unit, unit.actor_id, 'communication:' + operation, payload)
        if prior:
            return self.public(unit, dbs.row(unit, Item, prior['item_id']))
        return None

    def save_draft(self, payload, actor_id, identifier=None):
        with self.work(actor_id, True) as unit:
            context = self.thread_context(unit, payload.thread_id, lock=True)
            old = dbs.row(unit, Item, identifier, lock=True) if identifier else None
            if old:
                self.access(unit, old, True)
                if old.kind != 'draft' or old.state != 'draft' or old.thread_id != payload.thread_id:
                    raise HTTPException(409, 'Dieser Entwurf gehört zu einem anderen Vorgang.')
            prior = self.replay(unit, 'draft:' + str(identifier), payload)
            if prior:
                return prior
            if old:
                dbs.revision(old, payload.base_revision)
                values = payload.model_dump(exclude={'idempotency_key', 'base_revision'})
                values['origin_portfolio_ids'] = self.data(old).get('origin_portfolio_ids', context['portfolio_ids'])
                row = self.put(unit, old, values, revision=old.revision + 1)
            else:
                values = payload.model_dump(exclude={'idempotency_key', 'base_revision'})
                values['origin_portfolio_ids'] = context['portfolio_ids']
                row = self.new(unit, 'draft', values)
                row = self.put(unit, row, self.data(row), thread_id=payload.thread_id, connection_id=payload.connection_id)
            self.command(unit, 'draft:' + str(identifier), payload, context, row)
            return self.public(unit, row)

    def config(self, unit, connection_id, revision=None):
        connection = dbs.row(unit, IntegrationConnectionORM, connection_id, lock=True)
        if connection.provider_id != 'email' or not connection.enabled or connection.archived:
            raise HTTPException(409, 'Diese E-Mail-Verbindung ist nicht freigegeben.')
        if revision is not None:
            dbs.revision(connection, revision)
        config = self.connections.effective_config(unit, connection)
        if not self.connections.validation('email', config, complete=True)['valid']:
            raise HTTPException(409, 'Die E-Mail-Verbindung ist unvollständig.')
        return connection, config

    def upload_original(self, unit, document_id):
        from mimetypes import guess_type
        from types import SimpleNamespace

        from ..routers.files import _file_url_to_key
        from .file_storage import LocalStorage, get_file_storage
        from .filesystem_paths import filesystem_path
        from .upload_policy import ARCHIVED_PREFIXES, DOCUMENT_EXTENSIONS, require_allowed_extension

        context = resolve_context(unit.store, 'document', document_id, unit.actor_id, lock=True)
        document = unit.store.get_document(document_id)
        if archive.head(unit, document_id) is not None:
            raise HTTPException(409, 'Bitte die archivierte Originalfassung auswählen.')
        key = _file_url_to_key(document.file_url or '')
        if not key or key.startswith(ARCHIVED_PREFIXES):
            raise HTTPException(409, 'Das Dokument besitzt kein verfügbares Datei-Original.')
        require_allowed_extension(key, DOCUMENT_EXTENSIONS)
        storage = get_file_storage()
        if isinstance(storage, LocalStorage):
            path = filesystem_path(storage._path(key))
            if not path.is_file() or path.stat().st_size > MAX_BYTES:
                raise HTTPException(413, 'Das Datei-Original fehlt oder überschreitet 25 MiB.')
        raw = storage.get(key)
        if raw is None:
            raise HTTPException(404, 'Datei-Original nicht gefunden.')
        if len(raw) > MAX_BYTES:
            raise HTTPException(413, 'Das Datei-Original überschreitet 25 MiB.')
        row = SimpleNamespace(id='upload', filename=safe_filename(key.rsplit('/', 1)[-1]),
                              media_type=guess_type(key)[0] or 'application/octet-stream',
                              sha256=sha(raw), size_bytes=len(raw))
        return row, raw, context['revision']

    def attachment_choices(self, document_id, actor_id, before=None):
        with self.work(actor_id) as unit:
            resolve_context(unit.store, 'document', document_id, actor_id)
            if archive.head(unit, document_id) is None:
                row, _raw, revision = self.upload_original(unit, document_id)
                return dict(items=[dict(id='upload', document_id=document_id, document_revision=revision, number=1,
                                       filename=row.filename, sha256=row.sha256, size_bytes=row.size_bytes)], next_before=None)
        return archive.history(self.store, document_id, actor_id, before=before)

    def attachments(self, unit, payload):
        result = []
        total = 0
        for attachment in payload.attachments:
            resolve_context(unit.store, 'document', attachment.document_id, unit.actor_id, lock=True)
            if attachment.version_id == 'upload':
                row, raw, revision = self.upload_original(unit, attachment.document_id)
                if not attachment.document_revision:
                    raise HTTPException(422, 'Die Quellrevision des Datei-Originals fehlt.')
                commands.check_revision(attachment.document_revision, revision)
            else:
                _, binding = archive.bind_document(unit, attachment.document_id, lock=True)
                row = archive.authorized_version(unit, attachment.document_id, attachment.version_id, binding)
                raw = archive.original_bytes(unit, row)
            if row.sha256 != attachment.sha256:
                raise HTTPException(409, 'Ein Originalanhang wurde geändert. Bitte erneut auswählen.')
            total += row.size_bytes
            if total > MAX_BYTES:
                raise HTTPException(413, 'Die Anhänge überschreiten 25 MiB. Bitte auf mehrere Nachrichten verteilen.')
            result.append((row, raw))
        return result

    def check_source(self, unit, payload):
        context = self.thread_context(unit, payload.thread_id, lock=True)
        commands.check_revision(payload.source_revision, context['revision'])
        connection, config = self.config(unit, payload.connection_id, payload.config_revision)
        if payload.template_id:
            template = dbs.row(unit, Item, payload.template_id)
            self.access(unit, template)
            if template.kind != 'template':
                raise HTTPException(409, 'Die Vorlagenfassung wurde nicht gefunden.')
            if payload.template_revision is not None:
                dbs.revision(template, payload.template_revision)
        for identifier in payload.snippet_ids:
            snippet = dbs.row(unit, Item, identifier)
            self.access(unit, snippet)
            if snippet.kind != 'template' or self.data(snippet).get('usage') != 'snippet':
                raise HTTPException(409, 'Der Textbaustein wurde nicht gefunden.')
            if identifier in payload.snippet_revisions:
                dbs.revision(snippet, payload.snippet_revisions[identifier])
        return context, connection, config, self.attachments(unit, payload)

    def check_outbound(self, unit, data):
        if data.get('notification_recipient_id'):
            from .notification_email import check
            return check(self, unit, data)
        return self.check_source(unit, Draft(idempotency_key='worker', **{key: value for key, value in data.items() if key in Draft.model_fields}))

    def evidence(self, unit, row, raw):
        if len(raw) > MAX_BYTES * 2:
            raise HTTPException(413, 'Die Nachricht ist zu groß; das Original bleibt auf dem Server.')
        identifier = str(uuid4())
        dbs.put(unit, Evidence, dict(id=identifier, item_id=row.id, sha256=sha(raw), byte_length=len(raw), created_at=dbs.now()))
        for index, offset in enumerate(range(0, len(raw), 65536)):
            block_id = str(uuid4())
            token = dbs.seal(base64.b64encode(raw[offset:offset + 65536]).decode('ascii'), 'communication-block/' + block_id, self.box)
            dbs.put(unit, Block, dict(id=block_id, evidence_id=identifier, sequence=index, data_token=token, created_at=dbs.now()))

    def raw(self, unit, row):
        evidence = dbs.find_one(unit, Evidence, item_id=row.id)
        if evidence is None:
            raise HTTPException(409, 'Für diesen Entwurf gibt es noch kein eingefrorenes Original.')
        if unit.db is None:
            blocks = sorted((b for b in dbs.memory(unit, Block).values() if b.evidence_id == evidence.id), key=lambda b: b.sequence)
        else:
            blocks = list(unit.db.scalars(select(Block).where(Block.evidence_id == evidence.id).order_by(Block.sequence)))
        if [b.sequence for b in blocks] != list(range(len(blocks))):
            raise HTTPException(409, 'Das Nachrichtenoriginal ist unvollständig.')
        raw = b''.join(base64.b64decode(dbs.unseal(b.data_token, 'communication-block/' + b.id, self.box), validate=True) for b in blocks)
        if len(raw) != evidence.byte_length or sha(raw) != evidence.sha256:
            raise HTTPException(409, 'Das Nachrichtenoriginal besteht die Integritätsprüfung nicht.')
        return raw

    def download(self, identifier, actor_id, part=None):
        with self.work(actor_id) as unit:
            row = dbs.row(unit, Item, identifier)
            self.access(unit, row)
            raw = self.raw(unit, row)
            if part is None:
                return raw, 'nachricht.eml', 'message/rfc822'
            parts = list(BytesParser(policy=policy.default).parsebytes(raw).iter_attachments())
            if not 0 <= part < len(parts):
                raise HTTPException(404, 'Anhang nicht gefunden.')
            value = parts[part]
            decoded = value.get_payload(decode=True)
            if decoded is None:
                raise HTTPException(409, 'Dieser eingebettete Anhang ist nur im unveränderten E-Mail-Original verfügbar.')
            return decoded, safe_filename(value.get_filename()), 'application/octet-stream'

    def preview(self, identifier, payload, actor_id):
        with self.work(actor_id, True) as unit:
            draft = dbs.row(unit, Item, identifier, lock=True)
            context = self.access(unit, draft, True)
            prior = self.replay(unit, 'preview:' + identifier, payload)
            if prior:
                return prior
            dbs.revision(draft, payload.base_revision)
            if draft.kind != 'draft':
                raise HTTPException(409, 'Bitte einen gespeicherten Entwurf auswählen.')
            dedupe = dbs.digest(['outbound', identifier, draft.revision])
            existing = dbs.find_one(unit, Item, dedupe_key=dedupe)
            if existing:
                self.command(unit, 'preview:' + identifier, payload, context, existing)
                return self.public(unit, existing)
            data = Draft(idempotency_key=payload.idempotency_key, **{key: value for key, value in self.data(draft).items() if key in Draft.model_fields})
            context, connection, config, attachments = self.check_source(unit, data)
            envelope = list(dict.fromkeys(data.to + data.cc + data.bcc))
            if not envelope:
                raise HTTPException(422, 'Bitte mindestens einen Empfänger auswählen.')
            if data.template_id:
                template = dbs.row(unit, Item, data.template_id)
                self.access(unit, template)
                if template.kind != 'template':
                    raise HTTPException(422, 'Vorlagenfassung nicht gefunden.')
                data.template_revision = template.revision
            message = EmailMessage(policy=policy.SMTP)
            message_id = f'<{uuid4()}@immomanager.local>'
            message['Message-ID'] = message_id
            message['Date'] = format_datetime(commands.timestamp())
            message['From'] = config['sender_email']
            if data.to:
                message['To'] = ', '.join(data.to)
            if data.cc:
                message['Cc'] = ', '.join(data.cc)
            message['Subject'] = data.subject
            if data.reply_to_item_id:
                parent = dbs.row(unit, Item, data.reply_to_item_id)
                self.access(unit, parent)
                if parent.thread_id != data.thread_id or not parent.message_id:
                    raise HTTPException(409, 'Die Antwortquelle ist nicht eindeutig diesem Vorgang zugeordnet.')
                message['In-Reply-To'] = parent.message_id
                references = self.data(parent).get('references', [])
                message['References'] = ' '.join(list(dict.fromkeys(references + [parent.message_id]))[-50:])
            message.set_content(data.body, cte='quoted-printable')
            for attachment, raw in attachments:
                media = attachment.media_type.split('/', 1)
                message.add_attachment(raw, maintype=media[0], subtype=media[1], filename=attachment.filename)
            raw = message.as_bytes()
            data_value = data.model_dump(exclude={'idempotency_key', 'base_revision'})
            data_value['snippet_revisions'] = {identifier: dbs.row(unit, Item, identifier).revision for identifier in data.snippet_ids}
            original_portfolios = set(context['portfolio_ids'])
            for attachment in data.attachments:
                document_context = resolve_context(unit.store, 'document', attachment.document_id, actor_id)
                original_portfolios.update(document_context['portfolio_ids'])
            data_value.update(channel='email', direction='outbound', origin_portfolio_ids=sorted(original_portfolios), source=dict(kind='message_thread', id=data.thread_id, revision=data.source_revision, href=context['href'], portfolio_ids=context['portfolio_ids']), envelope=envelope, sender=config['sender_email'], mime_sha256=sha(raw),
                              draft_id=identifier, draft_revision=draft.revision, history=[{'state': 'preview', 'at': dbs.stamp(dbs.now())}])
            row = self.new(unit, 'outbound', data_value)
            row = self.put(unit, row, data_value, thread_id=data.thread_id, connection_id=connection.id,
                           message_id=message_id, dedupe_key=dedupe, state='preview')
            self.evidence(unit, row, raw)
            for attachment in data.attachments:
                dbs.put(unit, AttachmentReference, dict(id=str(uuid4()), item_id=row.id, document_id=attachment.document_id,
                    version_id=attachment.version_id, sha256=attachment.sha256, created_at=dbs.now()))
            self.command(unit, 'preview:' + identifier, payload, context, row)
            return self.public(unit, row)

    def transition(self, unit, row, state, detail='', **changes):
        data = self.data(row)
        data.setdefault('history', []).append(dict(state=state, detail=detail, at=dbs.stamp(dbs.now())))
        return self.put(unit, row, data, state=state, revision=row.revision + 1, **changes)

    def confirm(self, identifier, payload, actor_id, *, retry=False):
        operation = ('retry:' if retry else 'confirm:') + identifier
        with self.work(actor_id, True) as unit:
            row = dbs.row(unit, Item, identifier, lock=True)
            context = self.access(unit, row)
            prior = self.replay(unit, operation, payload)
            if prior:
                return prior
            dbs.revision(row, payload.base_revision)
            if row.kind not in ('outbound', 'notification') or row.state not in (('failed', 'blocked') if retry else ('preview',)):
                raise HTTPException(409, 'Dieser Zustand erlaubt keinen Versand. Unklare Ergebnisse zuerst abgleichen.')
            data = self.data(row)
            self.check_outbound(unit, data)
            draft = None
            if not data.get('notification_recipient_id'):
                draft = dbs.row(unit, Item, data['draft_id'])
                expected_draft_revision = data['draft_revision'] + (1 if retry else 0)
                if draft.revision != expected_draft_revision or draft.state != ('released' if retry else 'draft'):
                    raise HTTPException(409, 'Der Entwurf wurde geändert. Bitte eine neue Vorschau erstellen.')
            raw = self.raw(unit, row)
            if sha(raw) != payload.mime_sha256:
                raise HTTPException(409, 'Die Bestätigung gehört zu einer anderen Vorschau.')
            if not retry and draft is not None:
                self.transition(unit, draft, 'released', 'Versandfreigabe ist an diesen Entwurf gebunden')
            row = self.transition(unit, row, 'ready', 'Versand ausdrücklich bestätigt', lease_token=None, lease_until=None)
            self.command(unit, operation, payload, context, row)
            return self.public(unit, row)

    def reconcile(self, identifier, payload, actor_id):
        with self.work(actor_id, True) as unit:
            row = dbs.row(unit, Item, identifier, lock=True)
            context = self.access(unit, row)
            prior = self.replay(unit, 'reconcile:' + identifier, payload)
            if prior:
                return prior
            dbs.revision(row, payload.base_revision)
            if row.state != 'unknown':
                raise HTTPException(409, 'Nur ein unklarer Versand darf abgeglichen werden.')
            row = self.transition(unit, row, payload.decision, payload.evidence)
            self.command(unit, 'reconcile:' + identifier, payload, context, row)
            return self.public(unit, row)

    def save_template(self, payload, actor_id):
        with self.work(actor_id, True) as unit:
            if not scope_from_user(unit.user).unrestricted:
                raise HTTPException(403, 'Gemeinsame Vorlagen benötigen Zugriff auf alle Portfolios.')
            prior = self.replay(unit, 'template', payload)
            if prior:
                return prior
            if payload.predecessor_id:
                old = dbs.row(unit, Item, payload.predecessor_id)
                if old.kind != 'template':
                    raise HTTPException(422, 'Vorlagenvorgänger nicht gefunden.')
            row = self.new(unit, 'template', payload.model_dump(exclude={'idempotency_key'}))
            row = self.put(unit, row, self.data(row), state='published')
            self.command(unit, 'template', payload, {'kind': 'integration_connection', 'entity_id': row.id, 'property_id': None}, row)
            return self.public(unit, row)

    def claim(self, identifier, actor_id):
        with self.work(actor_id, True) as unit:
            row = dbs.row(unit, Item, identifier, lock=True)
            self.access(unit, row)
            if row.state in ('claimed', 'data_pending'):
                if row.lease_until and row.lease_until > dbs.now():
                    return None
                if row.state == 'data_pending':
                    self.transition(unit, row, 'unknown', 'Workerabbruch nach DATA-Checkpoint', lease_token=None, lease_until=None)
                    return None
            elif row.state != 'ready':
                return None
            data = self.data(row)
            self.check_outbound(unit, data)
            token = uuid4().hex
            self.transition(unit, row, 'claimed', lease_token=token, lease_until=dbs.now() + timedelta(seconds=180))
            return token

    def checkpoint(self, identifier, actor_id, token):
        with self.work(actor_id, True) as unit:
            row = self.fenced(unit, identifier, token)
            data = self.data(row)
            _, _, config, _ = self.check_outbound(unit, data)
            raw = self.raw(unit, row)
            self.transition(unit, row, 'data_pending', 'Dauerhafter Checkpoint unmittelbar vor DATA')
            return data, config, raw

    def fenced(self, unit, identifier, token):
        row = dbs.row(unit, Item, identifier, lock=True)
        self.access(unit, row)
        if row.lease_token != token or not row.lease_until or row.lease_until <= dbs.now():
            raise HTTPException(409, 'Die Versandfreigabe dieses Workers ist abgelaufen.')
        return row

    def finish(self, identifier, actor_id, token, state, detail, receipt=None):
        with self.work(actor_id, True) as unit:
            row = self.fenced(unit, identifier, token)
            if receipt is not None:
                data = self.data(row)
                data.setdefault('transport_receipts', []).append(dict(at=dbs.stamp(dbs.now()), state=state, **receipt))
                row = self.put(unit, row, data)
            return self.public(unit, self.transition(unit, row, state, detail, lease_token=None, lease_until=None))

    def dispatch(self, identifier, actor_id, transport=None):
        from .communication_transport import SMTPTransport
        token = self.claim(identifier, actor_id)
        if token is None:
            return self.get(identifier, actor_id)['state']
        transport = transport or SMTPTransport()
        pending = False
        try:
            # Connect/authenticate and RCPT are before the irreversible checkpoint.
            with self.work(actor_id) as unit:
                row = dbs.row(unit, Item, identifier)
                self.access(unit, row)
                data = self.data(row)
                _, config = self.config(unit, row.connection_id, data['config_revision'])
            transport.prepare(config, data['sender'], data['envelope'])
            data, _config, raw = self.checkpoint(identifier, actor_id, token)
            pending = True
            outcome = transport.data(raw)
            state = 'accepted' if outcome == 'accepted' else 'failed'
            self.finish(identifier, actor_id, token, state, 'SMTP-Annahme bestätigt; Zustellung nicht nachgewiesen' if state == 'accepted' else 'SMTP hat DATA endgültig abgelehnt',
                        receipt=dict(provider='smtp', response=getattr(transport, 'receipt', None), recipients=getattr(transport, 'recipient_results', [])))
            return state
        except Exception:
            state = 'unknown' if pending else 'failed'
            # If result persistence fails, data_pending itself protects against retry.
            self.finish(identifier, actor_id, token, state, 'DATA-Ausgang unbekannt; nicht erneut senden' if pending else 'Fehler vor DATA; nach Prüfung ausdrücklich wiederholbar',
                        receipt=dict(provider='smtp', response=getattr(transport, 'receipt', None), recipients=getattr(transport, 'recipient_results', [])))
            return state
        finally:
            transport.close()

    def ingest(self, unit, mailbox, validity, uid, raw):
        """Persist original, exact-correlation decision and UID checkpoint atomically."""
        key = dbs.digest([mailbox.connection_id, self.data(mailbox)['folder'], validity, uid])
        prior = dbs.find_one(unit, Item, dedupe_key=key)
        if prior and prior.state != 'deferred':
            return prior
        message = BytesParser(policy=policy.default).parsebytes(raw)
        identifiers = [str(value) for value in message.get_all('Message-ID', [])]
        message_ids = MESSAGE_ID.findall(identifiers[0]) if len(identifiers) == 1 else []
        message_id = message_ids[0] if len(message_ids) == 1 and identifiers[0].strip() == message_ids[0] else None
        references = []
        malformed = False
        for name in ('In-Reply-To', 'References'):
            for header in message.get_all(name, []):
                text = str(header)
                ids = MESSAGE_ID.findall(text)
                if MESSAGE_ID.sub('', text).strip():
                    malformed = True
                references.extend(ids)
        references = list(dict.fromkeys(references))
        candidates: set[str] = set()
        original_portfolios: set[str] = set()
        for reference in references:
            if unit.db is None:
                matches = [item for item in dbs.memory(unit, Item).values() if item.message_id == reference]
            else:
                matches = unit.db.scalars(select(Item).where(Item.message_id == reference)).all()
            candidates.update(item.thread_id for item in matches if item.thread_id and (item.kind == 'inbound' or (item.kind == 'outbound' and item.state in ('accepted', 'unknown'))))
            for item in matches:
                original_portfolios.update(self.data(item).get('origin_portfolio_ids', []))
        # Never select a case using sender display name, subject or quoted body.
        thread_id = next(iter(candidates)) if len(candidates) == 1 and not malformed else None
        if thread_id:
            context = self.thread_context(unit, thread_id, lock=True)
            original_portfolios.update(context['portfolio_ids'])
        body_part = message.get_body(preferencelist=('plain',))
        try:
            body = body_part.get_content() if body_part else ''
            if body_part is None and message.get_body(preferencelist=('html',)) is not None:
                body = 'Die Nachricht enthält HTML. Der vollständige Inhalt ist im unveränderten E-Mail-Original verfügbar.'
        except (LookupError, UnicodeError, ValueError):
            body = 'Der Nachrichtentext ist nicht lesbar. Das unveränderte Original ist erhalten.'
        attachments = [dict(part=index, filename=safe_filename(part.get_filename()),
                            media_type=part.get_content_type(),
                            sha256=sha(part.get_payload(decode=True)) if part.get_payload(decode=True) is not None else None,
                            downloadable=part.get_payload(decode=True) is not None,
                            size=len(part.get_payload(decode=True)) if part.get_payload(decode=True) is not None else None)
                       for index, part in enumerate(message.iter_attachments())]
        payload = dict(channel='email', direction='inbound', subject=str(message.get('Subject', '')), body=str(body), sender=str(message.get('From', '')),
                       to=[str(v) for v in message.get_all('To', [])], cc=[str(v) for v in message.get_all('Cc', [])],
                       references=references, attachments=attachments, raw_sha256=sha(raw),
                       uidvalidity=validity, uid=uid, folder=self.data(mailbox)['folder'],
                       review_reason='malformed_references' if malformed else 'ambiguous' if len(candidates) > 1 else 'unmatched' if not candidates else None,
                       history=[dict(state='assigned' if thread_id else 'review', at=dbs.stamp(dbs.now()))])
        payload['raw_available'] = True
        payload['origin_portfolio_ids'] = sorted(original_portfolios)
        if prior:
            payload['history'] = self.data(prior).get('history', []) + payload['history']
        row = prior or self.new(unit, 'inbound', payload)
        row = self.put(unit, row, payload, revision=row.revision + (1 if prior else 0), thread_id=thread_id, connection_id=mailbox.connection_id,
                       message_id=message_id, dedupe_key=key, state='assigned' if thread_id else 'review')
        self.evidence(unit, row, raw)
        return row

    def receive(self, connection_id, actor_id, adapter_factory=None, command=None):
        """One bounded receive step, explicitly invoked; no automatic account actions."""
        from .communication_transport import IMAPReadonly
        adapter_factory = adapter_factory or IMAPReadonly
        with self.work(actor_id, True) as unit:
            if not scope_from_user(unit.user).unrestricted:
                raise HTTPException(403, 'Der Eingang benötigt Zugriff auf alle Portfolios.')
            connection, config = self.config(unit, connection_id, command.config_revision if command else None)
            if command:
                prior = commands.replay(unit, actor_id, 'communication:receive:' + connection_id, command)
                if prior:
                    return prior
            if not all(config.get(k) for k in ('imap_host', 'imap_user', 'imap_password')):
                raise HTTPException(409, 'Die lesende IMAP-Verbindung ist noch nicht eingerichtet.')
            folder = config.get('imap_mailbox') or 'INBOX'
            key = dbs.digest(['mailbox', connection_id, folder])
            mailbox = dbs.find_one(unit, Item, dedupe_key=key, lock=True)
            if mailbox is None:
                mailbox = self.new(unit, 'mailbox', dict(folder=folder, uidvalidity=None, uid=0, config_revision=connection.revision))
                mailbox = self.put(unit, mailbox, self.data(mailbox), connection_id=connection_id, dedupe_key=key)
            if mailbox.lease_until and mailbox.lease_until > dbs.now():
                raise HTTPException(409, 'Der Posteingang wird bereits abgerufen.')
            token = uuid4().hex
            mailbox = self.put(unit, mailbox, self.data(mailbox), lease_token=token, lease_until=dbs.now() + timedelta(seconds=180))
            mailbox_id = mailbox.id
            config_revision = connection.revision
            checkpoint = self.data(mailbox)
        current_uid = None
        validity = None
        try:
            with adapter_factory(config) as adapter:
                validity = adapter.uidvalidity()
                # A validity change starts a new UID namespace; old evidence is retained.
                after = checkpoint['uid'] if checkpoint['uidvalidity'] == validity else 0
                uids, through, more = adapter.next_uids(after, 50)
                received = 0
                for uid in uids:
                    current_uid = uid
                    raw = adapter.raw(uid, MAX_BYTES * 2)
                    with self.work(actor_id, True) as unit:
                        self.config(unit, connection_id, config_revision)
                        mailbox = self.fenced(unit, mailbox_id, token)
                        self.ingest(unit, mailbox, validity, uid, raw)
                        self.put(unit, mailbox, dict(folder=folder, uidvalidity=validity, uid=uid, config_revision=config_revision))
                    received += 1
                result = dict(received=received, uidvalidity=validity, uid=through, has_more=more)
                with self.work(actor_id, True) as unit:
                    self.config(unit, connection_id, config_revision)
                    mailbox = self.fenced(unit, mailbox_id, token)
                    self.put(unit, mailbox, dict(folder=folder, uidvalidity=validity, uid=through, config_revision=config_revision),
                             state='idle', revision=mailbox.revision + 1, lease_token=None, lease_until=None)
                    if command:
                        commands.save_command(unit, actor_id, 'communication:receive:' + connection_id, command,
                            dict(kind='integration_connection', entity_id=connection_id, property_id=None), result)
                return result
        except Exception as exc:
            # The checkpoint stays at the last atomically archived UID. No secrets in errors.
            with self.work(actor_id, True) as unit:
                mailbox = self.fenced(unit, mailbox_id, token)
                data = self.data(mailbox)
                data['last_error'] = dict(uid=current_uid, uidvalidity=validity,
                    reason='oversize' if isinstance(exc, ValueError) else 'interrupted', at=dbs.stamp(dbs.now()))
                self.put(unit, mailbox, data, state='failed', revision=mailbox.revision + 1, lease_token=None, lease_until=None)
            raise HTTPException(503, 'Der Eingang wurde unterbrochen. Bereits archivierte Nachrichten bleiben erhalten; erneut abrufen.') from None

    def skip_incoming(self, identifier, payload, actor_id):
        with self.work(actor_id, True) as unit:
            mailbox = dbs.row(unit, Item, identifier, lock=True)
            context = self.access(unit, mailbox)
            prior = self.replay(unit, 'skip:' + identifier, payload)
            if prior:
                return prior
            dbs.revision(mailbox, payload.base_revision)
            data = self.data(mailbox)
            failure = data.get('last_error') or {}
            uid, validity = failure.get('uid'), failure.get('uidvalidity')
            if mailbox.kind != 'mailbox' or mailbox.state != 'failed' or not uid or not validity:
                raise HTTPException(409, 'Es liegt kein einzelner zurückstellbarer Eingang vor.')
            if mailbox.lease_token:
                raise HTTPException(409, 'Der Eingang wird bereits abgerufen.')
            if data['uidvalidity'] == validity and uid <= data['uid']:
                raise HTTPException(409, 'Dieser Eingang wurde bereits verarbeitet.')
            key = dbs.digest([mailbox.connection_id, data['folder'], validity, uid])
            if dbs.find_one(unit, Item, dedupe_key=key):
                raise HTTPException(409, 'Dieser Eingang ist bereits erfasst.')
            row = self.new(unit, 'inbound', dict(subject=f'Zurückgestellter Eingang UID {uid}', body='',
                uid=uid, uidvalidity=validity, folder=data['folder'], attachments=[], raw_available=False,
                history=[dict(state='deferred', at=dbs.stamp(dbs.now()), detail=payload.reason)]))
            row = self.put(unit, row, self.data(row), connection_id=mailbox.connection_id, state='deferred', dedupe_key=key)
            self.put(unit, mailbox, dict(folder=data['folder'], uidvalidity=validity, uid=uid,
                     config_revision=data['config_revision']), state='idle', revision=mailbox.revision + 1)
            self.command(unit, 'skip:' + identifier, payload, context, row)
            return self.public(unit, row)

    def receive_again(self, identifier, payload, actor_id, adapter_factory=None):
        from .communication_transport import IMAPReadonly
        with self.work(actor_id, True) as unit:
            row = dbs.row(unit, Item, identifier, lock=True)
            self.access(unit, row)
            prior = self.replay(unit, 'receive-again:' + identifier, payload)
            if prior:
                return prior
            dbs.revision(row, payload.base_revision)
            if row.kind != 'inbound' or row.state != 'deferred':
                raise HTTPException(409, 'Nur ein zurückgestellter Eingang darf nachgeholt werden.')
            connection, config = self.config(unit, row.connection_id)
            config_revision = connection.revision
            data = self.data(row)
            if data['folder'] != (config.get('imap_mailbox') or 'INBOX'):
                raise HTTPException(409, 'Der ursprüngliche IMAP-Ordner wurde geändert.')
        with (adapter_factory or IMAPReadonly)(config) as adapter:
            if adapter.uidvalidity() != data['uidvalidity']:
                raise HTTPException(409, 'Der IMAP-Server hat den UID-Namensraum geändert. Das alte Original kann nicht anhand einer neuen UID ersetzt werden.')
            raw = adapter.raw(data['uid'], MAX_BYTES * 2)
        with self.work(actor_id, True) as unit:
            row = dbs.row(unit, Item, identifier, lock=True)
            context = self.access(unit, row)
            self.config(unit, row.connection_id, config_revision)
            prior = self.replay(unit, 'receive-again:' + identifier, payload)
            if prior:
                return prior
            dbs.revision(row, payload.base_revision)
            mailbox = dbs.find_one(unit, Item, dedupe_key=dbs.digest(['mailbox', row.connection_id, data['folder']]))
            result = self.ingest(unit, mailbox, data['uidvalidity'], data['uid'], raw)
            self.command(unit, 'receive-again:' + identifier, payload, context, result)
            return self.public(unit, result)

    def assign(self, identifier, payload, actor_id):
        with self.work(actor_id, True) as unit:
            row = dbs.row(unit, Item, identifier, lock=True)
            self.access(unit, row)
            context = self.thread_context(unit, payload.thread_id, lock=True)
            prior = self.replay(unit, 'assign:' + identifier, payload)
            if prior:
                return prior
            dbs.revision(row, payload.base_revision)
            commands.check_revision(payload.source_revision, context['revision'])
            if row.kind != 'inbound' or row.state != 'review':
                raise HTTPException(409, 'Dieser Eingang ist bereits zugeordnet.')
            data = self.data(row)
            data['origin_portfolio_ids'] = sorted(set(data.get('origin_portfolio_ids', [])) | set(context['portfolio_ids']))
            row = self.put(unit, row, data)
            row = self.transition(unit, row, 'assigned', payload.reason, thread_id=payload.thread_id)
            self.command(unit, 'assign:' + identifier, payload, context, row)
            return self.public(unit, row)


def safe_filename(value):
    name = re.sub(r'[\\/:\x00-\x1f\x7f]', '_', value or 'Anhang.bin').strip('. ')[:180]
    return name or 'Anhang.bin'


def ensure_thread_can_delete(store, thread_id):
    if hasattr(store, 'db'):
        found = store.db.scalar(select(Item.id).where(Item.thread_id == thread_id).limit(1))
    else:
        rows = store.__dict__.get('_integration_connections', {}).get(Item.__tablename__, {})
        found = any(row.thread_id == thread_id for row in rows.values())
    if found:
        raise HTTPException(409, 'Die Konversation besitzt Kommunikationsbelege oder Entwürfe und bleibt als Quelle erhalten.')


def ensure_document_can_delete(store, document_id):
    if hasattr(store, 'db'):
        found = store.db.scalar(select(AttachmentReference.id).where(AttachmentReference.document_id == document_id).limit(1))
    else:
        rows = store.__dict__.get('_integration_connections', {}).get(AttachmentReference.__tablename__, {})
        found = any(row.document_id == document_id for row in rows.values())
    if found:
        raise HTTPException(409, 'Das Dokument ist Originalanhang eines Kommunikationsbelegs und bleibt als Quelle erhalten.')
