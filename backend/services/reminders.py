"""Personal, durable reminder plans. External channels prepare drafts only.

The ordinary scheduler marks due plans; authenticated reads also project due
state when background processing is disabled. No provider is called here.
"""
from datetime import datetime, timedelta, timezone
from typing import Literal
from uuid import NAMESPACE_URL, uuid5
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import auth
from ..db.daily_models import DailyStateORM
from ..storage import NotFoundError
from . import daily_state as state
from . import document_versions as archive
from . import settings_catalogue as settings
from . import workspace_contexts as contexts
from .portfolio_scope import scope_context, scope_from_user

BERLIN = ZoneInfo('Europe/Berlin')
PREFIX = 'reminder:'
PERSONAL = '/auth/users/me/preferences'
CHANNELS = Literal['in_app', 'email_draft', 'whatsapp_web']
KINDS = Literal['task', 'contract', 'notification', 'document', 'service_contract', 'maintenance']
MAX_ACTIVE = 500


class Plan(BaseModel):
    model_config = ConfigDict(extra='forbid')
    idempotency_key: str = Field(min_length=8, max_length=120)
    source_kind: KINDS
    source_id: str = Field(min_length=1, max_length=80)
    local_due_at: datetime
    channel: CHANNELS = 'in_app'
    recipient: str = Field('', max_length=254)
    message: str = Field('', max_length=2000)


class Command(BaseModel):
    model_config = ConfigDict(extra='forbid')
    idempotency_key: str = Field(min_length=8, max_length=120)
    base_revision: int = Field(ge=1, strict=True)
    action: Literal['done', 'cancel', 'reschedule']
    local_due_at: datetime | None = None


def moment(value=None):
    value = value or datetime.now(timezone.utc)
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def utc_text(value):
    return moment(value).isoformat(timespec='seconds')


def planned_at(local, now=None):
    if local.tzinfo is not None:
        raise HTTPException(422, 'Bitte die Ortszeit ohne Zeitzonen-Zusatz angeben (Europe/Berlin).')
    local = local.replace(second=0, microsecond=0)
    due = local.replace(tzinfo=BERLIN, fold=0).astimezone(timezone.utc)
    if due.astimezone(BERLIN).replace(tzinfo=None) != local:
        raise HTTPException(422, 'Diese Uhrzeit existiert wegen der Zeitumstellung nicht. Bitte eine andere Uhrzeit wählen.')
    current = moment(now)
    if not current - timedelta(minutes=1) <= due <= current + timedelta(days=3660):
        raise HTTPException(422, 'Die Erinnerung muss in der Zukunft und innerhalb der nächsten zehn Jahre liegen.')
    return due


def source(unit, kind, identifier):
    try:
        if kind == 'notification':
            from .notification_inbox import target
            notice = unit.store.get_notification(identifier)
            resolved = target(unit.store, notice, unit.actor_id)
            if resolved is None:
                raise HTTPException(404, 'Quelle nicht zugänglich.')
            return {**resolved, 'title': notice.title}
        return contexts.resolve_context(unit.store, kind, identifier, unit.actor_id)
    except NotFoundError as exc:
        raise HTTPException(404, 'Quelle nicht zugänglich.') from exc


def rows(unit, active_only=False):
    if unit.db is None:
        return [(key[1][len(PREFIX):], value) for key, value in state.memory(unit, 'state').items()
                if key[0] == unit.actor_id and key[1].startswith(PREFIX)
                and (not active_only or value['payload']['status'] not in ('done', 'cancelled'))]
    query = select(DailyStateORM).where(DailyStateORM.owner_id == unit.actor_id, DailyStateORM.key.like(PREFIX + '%'))
    if active_only:
        query = query.where(DailyStateORM.payload['status'].as_string().not_in(('done', 'cancelled')))
    records = unit.db.scalars(query.order_by(DailyStateORM.key)).all()
    return [(row.key[len(PREFIX):], {'revision': row.revision, 'payload': row.payload}) for row in records]


def quiet_allowed(unit, now):
    values = {key: settings.effective(unit, key)[0] for key in ('quiet_start', 'quiet_end')}
    return settings.email_policy({**values, 'email_notifications': 'all'}, 'info', now)


def quiet_ends(unit, now):
    clock = settings.effective(unit, 'quiet_end')[0]
    hour, minute = map(int, clock.split(':'))
    local = moment(now).astimezone(BERLIN)
    end = local.replace(hour=hour, minute=minute, second=0, microsecond=0, fold=0)
    if end <= local:
        end += timedelta(days=1)
    return end.astimezone(timezone.utc)


def public(unit, identifier, row, now=None):
    data = row['payload']
    result = {'id': identifier, 'revision': row['revision'], **data}
    try:
        resolved = source(unit, data['source_kind'], data['source_id'])
        result['source'] = {key: resolved[key] for key in ('kind', 'entity_id', 'revision', 'title', 'href')}
    except HTTPException as exc:
        if exc.status_code not in (403, 404, 422):
            raise
        return {'id': identifier, 'revision': row['revision'], 'status': data['status'] if data['status'] in ('done', 'cancelled') else 'blocked', 'source': None,
                'source_error': 'Quelle gelöscht oder aktuell nicht zugänglich.', 'due_at': data['due_at']}
    enabled = settings.effective(unit, 'reminders_enabled')[0]
    allowed = enabled and quiet_allowed(unit, now)
    result['delivery_paused'] = not allowed
    if data['status'] in ('scheduled', 'blocked'):
        result['status'] = 'due' if datetime.fromisoformat(data['due_at']) <= moment(now) and allowed else 'scheduled'
    return result


def page(store, actor_id, *, status=None, offset=0, limit=100, now=None):
    if status not in (None, 'active', 'due', 'done', 'cancelled'):
        raise HTTPException(422, 'Ungültige Erinnerungsansicht.')
    if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 200:
        raise HTTPException(422, 'Ungültige Erinnerungsseite.')
    with archive.work(store, actor_id) as unit, contexts.bound_actor(unit.user), scope_context(scope_from_user(unit.user)):
        items = [public(unit, identifier, row, now) for identifier, row in rows(unit, status in ('active', 'due'))]
        if status == 'active':
            items = [item for item in items if item['status'] in ('scheduled', 'due', 'blocked')]
        elif status:
            items = [item for item in items if item['status'] == status]
        items.sort(key=lambda row: (row['due_at'], row['id']))
        total = len(items)
        return {'items': items[offset:offset + limit], 'timezone': 'Europe/Berlin', 'total': total,
                'offset': offset, 'next_offset': offset + limit if offset + limit < total else None}


def create(store, actor_id, payload: Plan, *, now=None):
    recipient = payload.recipient.strip()
    if any(ord(char) < 32 for char in recipient):
        raise HTTPException(422, 'Ungültiger Empfänger.')
    if payload.channel == 'email_draft':
        from .communication import ADDRESS
        if not recipient.isascii() or not ADDRESS.fullmatch(recipient):
            raise HTTPException(422, 'Bitte eine gültige E-Mail-Adresse angeben.')
    if payload.channel == 'whatsapp_web':
        import re
        if not re.fullmatch(r'\+[1-9]\d{7,14}', recipient):
            raise HTTPException(422, 'Bitte die WhatsApp-Nummer mit internationaler Vorwahl angeben, zum Beispiel +491701234567.')
    with archive.work(store, actor_id, write_areas=(PERSONAL,)) as unit, contexts.bound_actor(unit.user), scope_context(scope_from_user(unit.user)):
        source(unit, payload.source_kind, payload.source_id)
        body = payload.model_dump(mode='json')
        fingerprint = state.digest('reminder-create', body)
        previous = state.replay(unit, payload.idempotency_key, fingerprint)
        if previous is not None:
            return public(unit, previous['id'], state.get(unit, PREFIX + previous['id']), now)
        due = planned_at(payload.local_due_at, now)
        active = rows(unit, True)
        intent = {'source_kind': payload.source_kind, 'source_id': payload.source_id, 'due_at': utc_text(due),
                  'channel': payload.channel, 'recipient': recipient, 'message': payload.message.strip()}
        for existing_id, existing in active:
            if all(existing['payload'].get(key) == value for key, value in intent.items()):
                result = public(unit, existing_id, existing, now)
                state.remember(unit, payload.idempotency_key, fingerprint, result)
                return result
        if len(active) >= MAX_ACTIVE:
            raise HTTPException(409, 'Höchstens 500 aktive persönliche Erinnerungen sind möglich. Nicht mehr benötigte Einträge zuerst abschließen oder entfernen.')
        identifier = str(uuid5(NAMESPACE_URL, actor_id + ':reminder:' + payload.idempotency_key))
        data = {**intent, 'next_check_at': utc_text(due), 'status': 'scheduled',
                'created_at': utc_text(now), 'triggered_at': None}
        row = state.put(unit, PREFIX + identifier, data, 0)
        result = public(unit, identifier, row, now)
        state.remember(unit, payload.idempotency_key, fingerprint, result)
        settings.record_audit(unit, payload.idempotency_key, 'reminder_create', identifier, None,
                              {'source_kind': payload.source_kind, 'source_id': payload.source_id, 'due_at': data['due_at'], 'channel': data['channel']})
        return result


def change(store, actor_id, identifier, payload: Command, *, now=None):
    with archive.work(store, actor_id, write_areas=(PERSONAL,)) as unit, contexts.bound_actor(unit.user), scope_context(scope_from_user(unit.user)):
        current = state.get(unit, PREFIX + identifier)
        if not current['revision']:
            raise HTTPException(404, 'Erinnerung nicht gefunden.')
        fingerprint = state.digest('reminder-command', [identifier, payload.model_dump(mode='json')])
        replay = state.replay(unit, payload.idempotency_key, fingerprint)
        if replay is not None:
            return public(unit, identifier, current, now)
        data = dict(current['payload'])
        if payload.action == 'reschedule':
            source(unit, data['source_kind'], data['source_id'])
            if payload.local_due_at is None:
                raise HTTPException(422, 'Bitte einen neuen Erinnerungszeitpunkt wählen.')
            data.update(due_at=utc_text(planned_at(payload.local_due_at, now)), status='scheduled', triggered_at=None)
            data['next_check_at'] = data['due_at']
        else:
            data['status'] = 'done' if payload.action == 'done' else 'cancelled'
        row = state.put(unit, PREFIX + identifier, data, payload.base_revision)
        result = public(unit, identifier, row, now)
        state.remember(unit, payload.idempotency_key, fingerprint, result)
        settings.record_audit(unit, payload.idempotency_key, 'reminder_' + payload.action, identifier,
                              {'status': current['payload']['status']}, {'status': data['status']})
        return result


def process_actor(store, actor_id, now=None):
    current = moment(now)
    changed = 0
    with archive.work(store, actor_id, write_areas=(PERSONAL,)) as unit, contexts.bound_actor(unit.user), scope_context(scope_from_user(unit.user)):
        enabled = settings.effective(unit, 'reminders_enabled')[0]
        for identifier, row in rows(unit, True):
            data = dict(row['payload'])
            if data['status'] not in ('scheduled', 'blocked') or datetime.fromisoformat(data['next_check_at']) > current:
                continue
            if not enabled:
                data['next_check_at'] = utc_text(current + timedelta(minutes=5))
                state.put(unit, PREFIX + identifier, data, row['revision'])
                changed += 1
                continue
            try:
                source(unit, data['source_kind'], data['source_id'])
            except HTTPException as exc:
                if exc.status_code not in (403, 404, 422):
                    raise
                data.update(status='blocked', next_check_at=utc_text(current + timedelta(minutes=5)))
            else:
                if quiet_allowed(unit, current):
                    data.update(status='due', triggered_at=utc_text(current))
                else:
                    data['status'] = 'scheduled'
                    data['next_check_at'] = utc_text(quiet_ends(unit, current))
            state.put(unit, PREFIX + identifier, data, row['revision'])
            changed += 1
    return changed


def tick_due(jobs, now=None):
    """Bounded recovery in the ordinary scheduler, without a second worker."""
    current = utc_text(now)
    if hasattr(jobs, 'engine'):
        from ..db.orm_models import UserORM
        with Session(jobs.engine) as db:
            candidates = db.execute(select(DailyStateORM.owner_id).join(UserORM, UserORM.id == DailyStateORM.owner_id).where(UserORM.is_active.is_(True), DailyStateORM.key.like(PREFIX + '%'),
                DailyStateORM.payload['status'].as_string().in_(('scheduled', 'blocked')),
                DailyStateORM.payload['next_check_at'].as_string() <= current)
                .order_by(DailyStateORM.owner_id, DailyStateORM.key).limit(MAX_ACTIVE)).scalars().all()
        count = 0
        for actor_id in dict.fromkeys(candidates):
            if not (auth.get_user_by_id(actor_id) or {}).get('is_active'):
                continue
            with Session(jobs.engine) as db:
                try:
                    count += process_actor(jobs.store_factory(db), actor_id, now)
                except HTTPException as exc:
                    if exc.status_code not in (401, 403):
                        raise
        return count
    store = jobs.store_factory()
    values = store.__dict__.get('_daily_state', {})
    actors = {key[0] for key, row in list(values.items()) if key[1].startswith(PREFIX)
              and row['payload'].get('status') in ('scheduled', 'blocked') and row['payload'].get('next_check_at', '') <= current}
    count = 0
    for actor in sorted(actors):
        if not (auth.get_user_by_id(actor) or {}).get('is_active'):
            continue
        try:
            count += process_actor(store, actor, now)
        except HTTPException as exc:
            if exc.status_code not in (401, 403):
                raise
    return count
