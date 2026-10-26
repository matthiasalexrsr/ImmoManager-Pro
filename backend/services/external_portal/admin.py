"""Explicit internal publication and verified-party invitation, never email sending."""
import secrets
from datetime import timedelta
from uuid import uuid4

from fastapi import HTTPException

from ...db.external_portal_models import (
    PortalGrantORM,
    PortalIdentityORM,
    PortalInvitationORM,
    PortalPublicationORM,
    PortalSessionORM,
)
from .. import document_versions as archive
from ..integrations import connection_storage as db
from .common import admin_work, binding, event, grant, origin, public, receipt, replay, rows, token_hash

GRANT_FIELDS = ("id", "identity_id", "kind", "tenant_id", "contact_id", "contract_id", "ownership_id", "binding", "active", "revision", "verification", "created_at", "updated_at")
PUBLICATION_FIELDS = ("id", "grant_id", "version_id", "title", "sha256", "active", "revision", "reason", "created_at")


def invite(store, actor_id, command):
    address = origin()
    with admin_work(store, actor_id) as unit:
        relation, party = binding(unit, command.kind, command.party_id, command.relation_id)
        operation = "invite:" + command.relation_id
        if previous := replay(unit, operation, command):
            return {**previous, "invitation_url": None, "notice": "Der Einladungsauftrag ist bereits gespeichert. Der geheime Link wird nur einmal angezeigt; bei Verlust eine neue Einladung erstellen."}
        email = str(command.email).casefold()
        known = (party.email or "").strip().casefold()
        if known and known != email:
            raise HTTPException(422, "Die Einladung muss an die geprüfte E-Mail-Adresse der Partei gehen. Bitte die Stammdaten zuerst berichtigen.")
        identity = db.find_one(unit, PortalIdentityORM, email=email)
        if identity is None:
            identity = db.put(unit, PortalIdentityORM, {"id": str(uuid4()), "email": email, "password_hash": None, "active": True,
                "revision": 1, "created_at": db.now(), "updated_at": db.now()})
        elif not identity.active:
            raise HTTPException(409, "Der externe Zugang ist deaktiviert. Eine neue Einladung darf die Deaktivierung nicht umgehen.")
        existing = next((row for row in rows(unit, PortalGrantORM, identity_id=identity.id) if row.binding == relation), None)
        if existing and existing.active:
            raise HTTPException(409, "Diese Partei hat bereits einen aktiven Zugang zu diesem Vertrags- oder Eigentumsverhältnis.")
        if existing:
            access = db.put(unit, PortalGrantORM, {**db.values(existing), "verified_by": actor_id, "verification": command.verification,
                "revision": existing.revision + 1, "updated_at": db.now()})
            for old in rows(unit, PortalInvitationORM, grant_id=access.id):
                if not old.revoked_at and not old.consumed_at:
                    db.put(unit, PortalInvitationORM, {**db.values(old), "revoked_at": db.now()})
        else:
            access = db.put(unit, PortalGrantORM, {"id": str(uuid4()), "identity_id": identity.id, "portfolio_id": relation["portfolio_id"],
                "kind": command.kind, "tenant_id": command.party_id if command.kind == "tenant" else None,
                "contact_id": command.party_id if command.kind == "owner" else None, "contract_id": command.relation_id if command.kind == "tenant" else None,
                "ownership_id": command.relation_id if command.kind == "owner" else None, "binding": relation, "active": False, "revision": 1,
                "verified_by": actor_id, "verification": command.verification, "created_at": db.now(), "updated_at": db.now()})
        token = secrets.token_urlsafe(32)
        invitation = db.put(unit, PortalInvitationORM, {"id": str(uuid4()), "grant_id": access.id, "token_sha256": token_hash(token),
            "expires_at": db.now() + timedelta(hours=command.expires_hours), "consumed_at": None, "revoked_at": None,
            "created_by": actor_id, "created_at": db.now()})
        event(unit, access.id, "invited", command.verification, {"invitation_id": invitation.id, "expires_at": invitation.expires_at.isoformat()})
        response = receipt(unit, operation, command, {"grant": public(access, GRANT_FIELDS), "email": email,
            "invitation_id": invitation.id, "expires_at": invitation.expires_at.isoformat()})
        return {**response, "invitation_url": address + "/portal/accept#" + token}


def listing(store, actor_id, *, skip=0, limit=50):
    with admin_work(store, actor_id) as unit:
        visible = rows(unit, PortalGrantORM)
        result = []
        for access in visible:
            # SQL collection scope is automatic; memory must resolve every row.
            try:
                binding(unit, access.kind, access.tenant_id or access.contact_id, access.contract_id or access.ownership_id)
            except Exception as error:
                from ...storage import NotFoundError
                if isinstance(error, (NotFoundError, HTTPException)):
                    # Stale but still in the user's property scope remains manageable.
                    try:
                        unit.store.get_property(access.binding["property_id"])
                    except (NotFoundError, HTTPException):
                        continue
                else:
                    raise
            identity = db.row(unit, PortalIdentityORM, access.identity_id)
            result.append({**public(access, GRANT_FIELDS), "email": identity.email, "identity_active": identity.active,
                           "identity_revision": identity.revision})
        return {"items": result[skip:skip + limit], "total": len(result), "skip": skip, "limit": limit}


def _manage_grant(unit, identifier):
    access = db.row(unit, PortalGrantORM, identifier, lock=True)
    # Revoking a stale grant must still work, but a scoped administrator cannot
    # manage someone else's building by guessing a grant ID.
    unit.store.get_property(access.binding["property_id"])
    return access


def change_access(store, actor_id, identifier, command):
    with admin_work(store, actor_id) as unit:
        access = _manage_grant(unit, identifier)
        operation = "grant:" + identifier
        if previous := replay(unit, operation, command):
            return previous
        db.revision(access, command.expected_revision)
        if command.active:
            grant(unit, identifier, active=False)
            identity = db.row(unit, PortalIdentityORM, access.identity_id)
            if not identity.active or not identity.password_hash:
                raise HTTPException(409, "Die Partei muss die Einladung erst persönlich annehmen.")
        else:
            for invitation in rows(unit, PortalInvitationORM, grant_id=identifier):
                if not invitation.revoked_at:
                    db.put(unit, PortalInvitationORM, {**db.values(invitation), "revoked_at": db.now()})
        access = db.put(unit, PortalGrantORM, {**db.values(access), "active": command.active, "revision": access.revision + 1, "updated_at": db.now()})
        event(unit, identifier, "access_changed", command.reason, {"active": command.active, "revision": access.revision})
        return receipt(unit, operation, command, public(access, GRANT_FIELDS))


def _eligible_version(unit, access, version_id):
    version = archive.version_row(unit, version_id)
    if version is None:
        raise HTTPException(404, "Archivierte Dokumentversion nicht gefunden.")
    from ..privacy.storage import ensure_available
    ensure_available(unit.store, "document", version.document_id)
    _, current = archive.bind_document(unit, version.document_id, lock=True)
    version = archive.authorized_version(unit, version.document_id, version.id, current)
    place = access.binding
    if version.property_id != place["property_id"] or (place["unit_id"] and version.unit_id != place["unit_id"]):
        raise HTTPException(403, "Die Dokumentfassung gehört nicht zur konkreten Portalzuordnung.")
    if access.kind == "tenant" and (version.contract_id != access.contract_id or version.tenant_id != access.tenant_id):
        raise HTTPException(403, "Die Dokumentfassung muss genau diesem Mietverhältnis und Haushalt zugeordnet sein.")
    # An owner may receive explicitly published building records; a tenant's
    # personal contract document cannot become an owner's public building file.
    if access.kind == "owner" and (version.tenant_id or version.contract_id):
        raise HTTPException(403, "Personenbezogene Mieterunterlagen sind für diese Eigentümerveröffentlichung gesperrt.")
    return version


def publish(store, actor_id, identifier, command):
    with admin_work(store, actor_id) as unit:
        access = grant(unit, identifier)
        operation = "publish:" + identifier
        if previous := replay(unit, operation, command):
            return previous
        db.revision(access, command.grant_revision)
        version = _eligible_version(unit, access, command.version_id)
        existing = db.find_one(unit, PortalPublicationORM, grant_id=identifier, version_id=version.id)
        if existing:
            raise HTTPException(409, "Diese Fassung wurde bereits veröffentlicht. Bitte ihren Freigabestand prüfen.")
        result = db.put(unit, PortalPublicationORM, {"id": str(uuid4()), "grant_id": identifier, "version_id": version.id,
            "sha256": version.sha256, "title": command.title, "reason": command.reason, "active": True, "revision": 1,
            "published_by": actor_id, "created_at": db.now(), "updated_at": db.now()})
        event(unit, identifier, "document_published", command.reason, {"publication_id": result.id, "version_id": version.id, "sha256": version.sha256})
        return receipt(unit, operation, command, public(result, PUBLICATION_FIELDS))


def publications(store, actor_id, identifier):
    with admin_work(store, actor_id) as unit:
        _manage_grant(unit, identifier)
        return [public(row, PUBLICATION_FIELDS) for row in rows(unit, PortalPublicationORM, grant_id=identifier)]


def change_publication(store, actor_id, identifier, command):
    with admin_work(store, actor_id) as unit:
        item = db.row(unit, PortalPublicationORM, identifier, lock=True)
        access = _manage_grant(unit, item.grant_id)
        operation = "publication:" + identifier
        if previous := replay(unit, operation, command):
            return previous
        db.revision(item, command.expected_revision)
        if command.active:
            grant(unit, access.id)
            _eligible_version(unit, access, item.version_id)
        item = db.put(unit, PortalPublicationORM, {**db.values(item), "active": command.active, "revision": item.revision + 1, "updated_at": db.now()})
        event(unit, access.id, "publication_changed", command.reason, {"publication_id": identifier, "active": command.active})
        return receipt(unit, operation, command, public(item, PUBLICATION_FIELDS))


def eligible_documents(store, actor_id, identifier, *, skip=0, limit=25):
    from ...storage import NotFoundError
    from ..document_original_snapshot import _manifests
    with admin_work(store, actor_id) as unit:
        access = grant(unit, identifier)
        found = []
        for candidate in _manifests(unit.store):
            try:
                row = _eligible_version(unit, access, candidate.id)
            except (HTTPException, NotFoundError):
                continue
            found.append({"id": row.id, "document_id": row.document_id, "filename": row.filename, "number": row.number, "sha256": row.sha256,
                          "title": row.metadata_snapshot.get("title", row.filename)})
        return {"items": found[skip:skip + limit], "total": len(found), "skip": skip, "limit": limit}


def change_identity(store, actor_id, grant_id, command):
    from ..portfolio_scope import scope_from_user
    with admin_work(store, actor_id) as unit:
        access = _manage_grant(unit, grant_id)
        if not scope_from_user(unit.user).unrestricted:
            raise HTTPException(403, "Das Deaktivieren eines gesamten externen Kontos benötigt Zugriff auf alle Bestände. Die einzelne Zuordnung kann separat widerrufen werden.")
        identity = db.row(unit, PortalIdentityORM, access.identity_id, lock=True)
        operation = "identity:" + identity.id
        if previous := replay(unit, operation, command):
            return previous
        db.revision(identity, command.expected_revision)
        identity = db.put(unit, PortalIdentityORM, {**db.values(identity), "active": command.active,
            "revision": identity.revision + 1, "updated_at": db.now()})
        for item in rows(unit, PortalGrantORM, identity_id=identity.id):
            event(unit, item.id, "identity_changed", command.reason, {"active": command.active, "revision": identity.revision})
        return receipt(unit, operation, command, public(identity, ("id", "email", "active", "revision")))


def recover_access(store, actor_id, grant_id, command):
    """Verified administrator recovery; grants and sessions close before re-inviting."""
    from ..portfolio_scope import scope_from_user
    address = origin()
    with admin_work(store, actor_id) as unit:
        if not scope_from_user(unit.user).unrestricted:
            raise HTTPException(403, 'Das Zurücksetzen eines gesamten Portalzugangs benötigt Zugriff auf alle Bestände.')
        operation = 'recover:' + grant_id
        if previous := replay(unit, operation, command):
            return {**previous, 'invitation_url': None, 'notice': 'Der Zugang wurde bereits zurückgesetzt. Der Link wird nur einmal angezeigt. Bei Verlust den aktuellen Stand laden und nach erneuter Prüfung zurücksetzen.'}
        access = grant(unit, grant_id, active=False)
        identity = db.row(unit, PortalIdentityORM, access.identity_id, lock=True)
        db.revision(identity, command.expected_revision)
        db.revision(access, command.grant_revision)
        if not identity.active:
            raise HTTPException(409, 'Ein deaktiviertes Konto muss vor einer erneuten Einladung ausdrücklich überprüft und reaktiviert werden.')
        _, party = binding(unit, access.kind, access.tenant_id or access.contact_id, access.contract_id or access.ownership_id)
        if not party.email or party.email.strip().casefold() != identity.email:
            raise HTTPException(409, 'Die aktuelle persönliche E-Mail-Adresse und der bestehende Portalzugang stimmen nicht überein. Bitte zuerst die Identität und Stammdaten klären.')
        identity = db.put(unit, PortalIdentityORM, {**db.values(identity), 'password_hash': None,
            'revision': identity.revision + 1, 'updated_at': db.now()})
        for item in rows(unit, PortalGrantORM, identity_id=identity.id):
            db.put(unit, PortalGrantORM, {**db.values(item), 'active': False, 'revision': item.revision + 1, 'updated_at': db.now()})
            for invitation in rows(unit, PortalInvitationORM, grant_id=item.id):
                if not invitation.revoked_at:
                    db.put(unit, PortalInvitationORM, {**db.values(invitation), 'revoked_at': db.now()})
            event(unit, item.id, 'access_recovery', command.verification, {'identity_revision': identity.revision})
        for session in rows(unit, PortalSessionORM, identity_id=identity.id):
            if not session.revoked_at:
                db.put(unit, PortalSessionORM, {**db.values(session), 'revoked_at': db.now()})
        token = secrets.token_urlsafe(32)
        invitation = db.put(unit, PortalInvitationORM, {'id': str(uuid4()), 'grant_id': access.id, 'token_sha256': token_hash(token),
            'expires_at': db.now() + timedelta(hours=24), 'consumed_at': None, 'revoked_at': None,
            'created_by': actor_id, 'created_at': db.now()})
        result = receipt(unit, operation, command, {'email': identity.email, 'invitation_id': invitation.id,
            'expires_at': invitation.expires_at.isoformat(), 'identity_revision': identity.revision})
        return {**result, 'invitation_url': address + '/portal/accept#' + token}
