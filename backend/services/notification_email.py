"""Explicit personal notification previews in the existing durable SMTP outbox.

No scheduler creates these rows. Only the authenticated recipient can prepare
and release one; the normal outbox worker rechecks consent and source at claim
and immediately before DATA. Business correspondence never enters this policy.
"""
from datetime import timezone
from email import policy
from email.message import EmailMessage
from email.utils import format_datetime
from uuid import uuid4

from fastapi import HTTPException
from pydantic import Field
from sqlalchemy import select

from ..db.communication_models import CommunicationItemORM as Item
from ..db.orm_models import NotificationORM
from . import daily_state as state
from . import notification_inbox as inbox
from . import settings_catalogue as settings
from .communication import ADDRESS, Command, sha
from .integrations import connection_storage as dbs


class Preview(Command):
    connection_id: str = Field(min_length=1, max_length=36)
    config_revision: int = Field(ge=1)
    source_revision: str = Field(min_length=1, max_length=200)


def context(unit, data, *, lock=False):
    if data['notification_recipient_id'] != unit.actor_id:
        raise HTTPException(404, 'Persönliche Hinweis-E-Mail nicht gefunden.')
    if lock and unit.db is not None:
        unit.db.scalar(select(NotificationORM.id).where(NotificationORM.id == data['notification_id']).with_for_update())
    notice = unit.store.get_notification(data['notification_id'])
    source = inbox.target(unit.store, notice, unit.actor_id, lock=lock)
    if source is None:
        raise HTTPException(409, 'Dieser Hinweis besitzt keine eindeutige zugängliche Quelle.')
    return notice, source


def check(service, unit, data):
    notice, source = context(unit, data, lock=True)
    if source['revision'] != data['source_revision'] or notice.updated_at.isoformat() != data['notification_revision']:
        raise HTTPException(409, 'Hinweis oder Quelle wurde geändert. Bitte eine neue E-Mail-Vorschau erstellen.')
    recipient = unit.user.get('email') or ''
    if recipient != data['to'][0]:
        raise HTTPException(409, 'Die persönliche E-Mail-Adresse wurde geändert. Vorschau erneut erstellen.')
    values = {key: settings.effective(unit, key)[0] for key in ('email_notifications', 'quiet_start', 'quiet_end')}
    if not settings.email_policy(values, notice.severity):
        raise HTTPException(409, 'Persönliche E-Mail-Hinweise sind aktuell durch Kanalwahl oder Ruhezeit gesperrt.')
    receipt = state.get(unit, 'notice:' + notice.id)['payload']
    if receipt.get('read_at') or receipt.get('archived_at'):
        raise HTTPException(409, 'Dieser Hinweis wurde bereits persönlich quittiert.')
    connection, config = service.config(unit, data['connection_id'], data['config_revision'])
    return source, connection, config, []


def preview(service, identifier, payload, actor_id):
    with service.work(actor_id, True) as unit:
        notice = unit.store.get_notification(identifier)
        data = dict(notification_id=identifier, notification_recipient_id=actor_id,
                    notification_revision=notice.updated_at.isoformat(), source_revision=payload.source_revision,
                    connection_id=payload.connection_id, config_revision=payload.config_revision,
                    to=[unit.user.get('email') or ''], cc=[], bcc=[], attachments=[])
        if not data['to'][0].isascii() or not ADDRESS.fullmatch(data['to'][0]):
            raise HTTPException(422, 'Für dieses Konto fehlt eine gültige persönliche E-Mail-Adresse.')
        # Visibility is checked before replay; no other user can inspect an item.
        context(unit, data, lock=True)
        operation = 'notification-preview:' + identifier
        prior = service.replay(unit, operation, payload)
        if prior:
            return prior
        source, connection, config, _ = check(service, unit, data)
        dedupe = dbs.digest(['personal-notification', actor_id, identifier, data['notification_revision'],
                             data['source_revision'], payload.connection_id, payload.config_revision, data['to']])
        existing = dbs.find_one(unit, Item, dedupe_key=dedupe)
        if existing:
            service.command(unit, operation, payload, source, existing)
            return service.public(unit, existing)
        message = EmailMessage(policy=policy.SMTP)
        message_id = f'<{uuid4()}@immomanager.local>'
        message['Message-ID'] = message_id
        message['Date'] = format_datetime(dbs.now().replace(tzinfo=timezone.utc))
        message['From'] = config['sender_email']
        message['To'] = data['to'][0]
        subject = ' '.join(notice.title.splitlines())[:998]
        message['Subject'] = subject
        message.set_content(notice.content + '\n\nQuelle: ' + source['title'], cte='quoted-printable')
        raw = message.as_bytes()
        data.update(subject=subject, body=notice.content + '\n\nQuelle: ' + source['title'],
                    channel='email', direction='outbound', envelope=data['to'], sender=config['sender_email'],
                    mime_sha256=sha(raw), origin_portfolio_ids=source['portfolio_ids'],
                    source=dict(kind=source['kind'], id=source['entity_id'], revision=source['revision'],
                                href=source['href'], portfolio_ids=source['portfolio_ids']),
                    history=[dict(state='preview', at=dbs.stamp(dbs.now()))])
        row = service.new(unit, 'notification', data)
        row = service.put(unit, row, data, connection_id=connection.id, message_id=message_id,
                          dedupe_key=dedupe, state='preview')
        service.evidence(unit, row, raw)
        service.command(unit, operation, payload, source, row)
        return service.public(unit, row)
