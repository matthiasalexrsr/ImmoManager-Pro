"""Inventory of newly issued login families, without storing JWTs or credentials.

The existing revocation service remains authoritative for individual JWTs. A
session-family revoke additionally rejects ALL access/refresh tokens of that
family. Old JWTs without a family retain the documented APIv1 token contract.
"""
from copy import deepcopy
from typing import Any
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from ..db.daily_models import DailySessionORM
from . import daily_state as state
from . import document_versions as archive

_sessions: dict[str, dict[str, Any]] = {}


def issue(user_id, expires, identifier=None):
    from .. import auth
    identifier = identifier or str(uuid4())
    expires = expires.replace(tzinfo=None)
    if auth._auth_session_factory is None:
        with auth._revocation_lock:
            row = _sessions.get(identifier)
            if row and (row['owner_id'] != user_id or row.get('revoked_at')):
                raise HTTPException(401, 'Sitzung wurde widerrufen.')
            if row is None:
                _sessions[identifier] = dict(id=identifier, owner_id=user_id, revision=1,
                    created_at=state.now(), expires_at=expires, revoked_at=None)
            else:
                row['expires_at'] = max(row['expires_at'], expires)
        return identifier
    with auth._revocation_session() as db:
        row = db.scalar(select(DailySessionORM).where(DailySessionORM.id == identifier).with_for_update())
        if row and (row.owner_id != user_id or row.revoked_at):
            raise HTTPException(401, 'Sitzung wurde widerrufen.')
        if row is None:
            db.add(DailySessionORM(id=identifier, owner_id=user_id, revision=1, created_at=state.now(), expires_at=expires))
        else:
            row.expires_at = max(row.expires_at, expires)
        db.commit()
    return identifier


def check(identifier, user_id):
    from .. import auth
    if not identifier:  # Deliberate legacy JWT compatibility, no invented inventory.
        return
    if auth._auth_session_factory is None:
        with auth._revocation_lock:
            row = _sessions.get(identifier)
            allowed = row and row['owner_id'] == user_id and not row.get('revoked_at') and row['expires_at'] > state.now()
    else:
        with auth._revocation_session() as db:
            row = db.get(DailySessionORM, identifier)
            allowed = row and row.owner_id == user_id and not row.revoked_at and row.expires_at > state.now()
    if not allowed:
        raise HTTPException(401, 'Sitzung ist abgelaufen oder widerrufen.')


def inventory(store, actor_id, current=None):
    with archive.work(store, actor_id) as unit:
        rows = (unit.db.scalars(select(DailySessionORM).where(DailySessionORM.owner_id == actor_id)
                               .order_by(DailySessionORM.created_at.desc())).all() if unit.db is not None
                else [deepcopy(row) for row in _sessions.values() if row['owner_id'] == actor_id])
        def public(row):
            data = row if isinstance(row, dict) else {key: getattr(row, key) for key in ('id', 'revision', 'created_at', 'expires_at', 'revoked_at')}
            return {key: value for key, value in data.items() if key != 'owner_id'} | {'current': data['id'] == current}
        return {'items': [public(row) for row in rows], 'legacy_notice': 'Vor dieser Version ausgestellte Tokens besitzen keine erfundene Gerätezuordnung; sie laufen nach dem bisherigen Tokenvertrag ab.'}


def revoke(store, actor_id, identifier, body):
    try:
        with archive.work(store, actor_id, write_areas=('/auth/users/me/settings',)) as unit:
            row = (unit.db.scalar(select(DailySessionORM).where(DailySessionORM.id == identifier,
                DailySessionORM.owner_id == actor_id).with_for_update()) if unit.db is not None else deepcopy(_sessions.get(identifier)))
            data = row if isinstance(row, dict) else {key: getattr(row, key) for key in ('owner_id', 'revision', 'revoked_at')} if row else None
            if not data or data['owner_id'] != actor_id:
                raise HTTPException(404, 'Sitzung nicht zugänglich.')
            fingerprint = state.digest('session-revoke:' + identifier, body)
            prior = state.replay(unit, body['idempotency_key'], fingerprint)
            if prior is not None:
                return prior
            if body['base_revision'] != data['revision']:
                raise HTTPException(409, 'Sitzung wurde geändert. Bitte neu laden.')
            revision = data['revision'] + 1
            before = deepcopy(data)
            stamp = state.now()
            if unit.db is None:
                assert isinstance(row, dict)
                row.update(revoked_at=stamp, revision=revision)
                unit.insert(_sessions, identifier, row)
            else:
                assert isinstance(row, DailySessionORM)
                row.revoked_at, row.revision = stamp, revision
                unit.db.flush()
            result = {'id': identifier, 'revision': revision, 'revoked': True}
            from .settings_catalogue import record_audit
            record_audit(unit, body['idempotency_key'], 'session_revoke', identifier, before, result)
            state.remember(unit, body['idempotency_key'], fingerprint, result)
            return result
    except SQLAlchemyError:
        raise HTTPException(503, 'Sitzungswiderruf nicht bestätigt. Denselben Befehl erneut versuchen.') from None
