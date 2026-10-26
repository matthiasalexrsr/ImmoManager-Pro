"""Verify portal evidence and fail closed before publishing a restored database."""
import hashlib
from uuid import uuid4

from sqlalchemy import func, insert, inspect, select, update

from ...db import external_portal_models as models
from ...db.document_version_models import DocumentVersionORM
from ..integrations import connection_storage as db


def verify(connection, *, normalize=False):
    names = set(inspect(connection).get_table_names())
    expected = {getattr(mapper.local_table, "name"): mapper.local_table for mapper in models.Base.registry.mappers
                if mapper.class_.__module__ == models.__name__}
    present = names & expected.keys()
    if not present:
        return {"present": False, "images": 0, "publications": 0, "revoked_sessions": 0}
    if present != expected.keys():
        raise ValueError("Incomplete external portal schema")
    identities = {row["id"]: row for row in connection.execute(select(models.PortalIdentityORM.__table__)).mappings()}
    grants = {row["id"]: row for row in connection.execute(select(models.PortalGrantORM.__table__)).mappings()}
    versions = {row.id: row.sha256 for row in connection.execute(select(DocumentVersionORM.id, DocumentVersionORM.sha256))}
    cases = {row["id"]: row for row in connection.execute(select(models.PortalCaseORM.__table__)).mappings()}
    messages = {row["id"]: row for row in connection.execute(select(models.PortalMessageORM.__table__)).mappings()}
    for row in grants.values():
        if row["identity_id"] not in identities or row["kind"] not in ("tenant", "owner") or row["revision"] < 1:
            raise ValueError("Invalid portal party relationship")
    for row in cases.values():
        if row["grant_id"] not in grants:
            raise ValueError("Portal case has no grant")
    for row in messages.values():
        if row["case_link_id"] not in cases or row["sender_kind"] not in ("internal", "external"):
            raise ValueError("Portal message has invalid ownership")
    count = 0
    for row in connection.execute(select(models.PortalPublicationORM.__table__)).mappings():
        if row["grant_id"] not in grants or versions.get(row["version_id"]) != row["sha256"]:
            raise ValueError("Published portal version does not match its original")
        count += 1
    image_table = models.PortalAttachmentORM.__table__
    if connection.execute(select(image_table.c.id).where(func.length(image_table.c.content) > 8 * 1024 * 1024).limit(1)).first():
        raise ValueError("Oversized portal attachment")
    images = 0
    for row in connection.execute(select(image_table)).mappings():
        raw = row["content"]
        if row["message_id"] not in messages or row["media_type"] != "image/jpeg" or not raw.startswith(b"\xff\xd8\xff") or hashlib.sha256(raw).hexdigest() != row["sha256"]:
            raise ValueError("Corrupt portal attachment")
        images += 1
    sessions = list(connection.execute(select(models.PortalSessionORM.id, models.PortalSessionORM.identity_id)))
    if any(row.identity_id not in identities for row in sessions):
        raise ValueError("Portal session has no identity")
    if normalize:
        # A backup cannot know decisions made after its capture. No restored
        # password, invitation or grant may restore access without a new review.
        for model in (models.PortalIdentityORM, models.PortalGrantORM, models.PortalPublicationORM, models.PortalCaseORM):
            connection.execute(update(model).values(active=False, revision=model.revision + 1, updated_at=db.now()))
        connection.execute(update(models.PortalSessionORM).values(revoked_at=db.now()))
        connection.execute(update(models.PortalInvitationORM).values(revoked_at=db.now()))
        for identifier in grants:
            connection.execute(insert(models.PortalEventORM).values(id=str(uuid4()), grant_id=identifier, actor_id="system:restore",
                kind="restored_access_suspended", reason="Wiederherstellung: aktuelle Lösch-, Sperr- und Freigabeentscheidungen müssen vor erneuter Veröffentlichung abgeglichen werden.", detail={}, created_at=db.now()))
    return {"present": True, "images": images, "publications": count, "revoked_sessions": len(sessions) if normalize else 0}
