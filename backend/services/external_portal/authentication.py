"""One-use invitation acceptance, durable attempt limits and opaque sessions."""
import secrets
from datetime import timedelta, timezone
from uuid import uuid4

from fastapi import HTTPException

from ... import auth
from ...db.external_portal_models import (
    PortalAttemptORM,
    PortalGrantORM,
    PortalIdentityORM,
    PortalInvitationORM,
    PortalSessionORM,
)
from ...storage import NotFoundError
from ..integrations import connection_storage as db
from .common import event, external_work, grant, raw_work, rows, token_hash

DUMMY_HASH = auth.hash_password("portal-dummy-not-a-real-credential")


def reserve_attempt(store, label, remote_ip):
    limited = False
    now = db.now().replace(tzinfo=timezone.utc).timestamp()
    with raw_work(store) as unit:
        for value, limit in (("address:" + remote_ip, 30), ("identity:" + label.casefold(), 6)):
            identifier = token_hash(value)
            old = db.row(unit, PortalAttemptORM, identifier, required=False, lock=True)
            times = [stamp for stamp in old.times if stamp > now - 900] if old else []
            if len(times) >= limit:
                limited = True
                # Once this address is blocked, random mailbox/token labels
                # must not create an unbounded number of durable attempt rows.
                break
            else:
                db.put(unit, PortalAttemptORM, {"id": identifier, "times": [*times, now]})
    if limited:
        raise HTTPException(429, "Zu viele Anmeldeversuche. Bitte später erneut versuchen.", headers={"Retry-After": "900"})


def _session(unit, identity):
    token = secrets.token_urlsafe(32)
    db.put(unit, PortalSessionORM, {"id": str(uuid4()), "identity_id": identity.id, "identity_revision": identity.revision,
        "token_sha256": token_hash(token), "expires_at": db.now() + timedelta(hours=8), "revoked_at": None, "created_at": db.now()})
    return token, {"email": identity.email, "expires_in": 8 * 60 * 60}


def accept(store, command, remote_ip):
    reserve_attempt(store, token_hash(command.token), remote_ip)
    with raw_work(store) as unit:
        invitation = db.find_one(unit, PortalInvitationORM, token_sha256=token_hash(command.token), lock=True)
        if invitation is None or invitation.consumed_at or invitation.revoked_at or invitation.expires_at <= db.now():
            raise HTTPException(401, "Einladung ungültig, abgelaufen oder bereits verwendet.")
        access = grant(unit, invitation.grant_id, active=False)
        identity = db.row(unit, PortalIdentityORM, access.identity_id, lock=True)
        if not identity.active:
            raise HTTPException(403, "Dieser Portalzugang wurde deaktiviert.")
        if identity.password_hash:
            if not auth.verify_password(command.password, identity.password_hash):
                raise HTTPException(401, "Für diesen Portalzugang bitte das bereits festgelegte Passwort verwenden.")
        else:
            problems = auth.validate_password_strength(command.password, email=identity.email)
            if problems:
                raise HTTPException(422, "Portalpasswort zu schwach: " + "; ".join(problems))
            identity = db.put(unit, PortalIdentityORM, {**db.values(identity), "password_hash": auth.hash_password(command.password),
                "revision": identity.revision + 1, "updated_at": db.now()})
        db.put(unit, PortalGrantORM, {**db.values(access), "active": True, "revision": access.revision + 1, "updated_at": db.now()})
        db.put(unit, PortalInvitationORM, {**db.values(invitation), "consumed_at": db.now()})
        unit.user = {"id": "portal:" + identity.id}
        event(unit, access.id, "invitation_accepted", "Einmalige Einladung persönlich angenommen.")
        return _session(unit, identity)


def login(store, command, remote_ip):
    reserve_attempt(store, str(command.email), remote_ip)
    with raw_work(store) as unit:
        identity = db.find_one(unit, PortalIdentityORM, email=str(command.email).casefold(), lock=True)
        verified = auth.verify_password(command.password, identity.password_hash if identity and identity.password_hash else DUMMY_HASH)
        if not identity or not identity.active or not identity.password_hash or not verified:
            raise HTTPException(401, "Portal-Anmeldedaten ungültig oder Zugang nicht verfügbar.")
        accessible = False
        for row in rows(unit, PortalGrantORM, identity_id=identity.id, active=True):
            try:
                grant(unit, row.id, identity.id)
                accessible = True
            except (HTTPException, NotFoundError):
                continue
        if not accessible:
            raise HTTPException(401, "Portal-Anmeldedaten ungültig oder Zugang nicht verfügbar.")
        return _session(unit, identity)


def logout(store, token):
    with external_work(store, token) as (unit, _, session):
        db.put(unit, PortalSessionORM, {**db.values(session), "revoked_at": db.now()})
