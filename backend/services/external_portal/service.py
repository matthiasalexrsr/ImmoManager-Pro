"""Public projection: only granted publications and explicitly linked conversations."""
import hashlib
import io
import warnings
from uuid import uuid4

from fastapi import HTTPException
from PIL import Image, UnidentifiedImageError

from ...db.external_portal_models import (
    PortalAttachmentORM,
    PortalCaseORM,
    PortalGrantORM,
    PortalMessageORM,
    PortalPublicationORM,
)
from ...models import MaintenanceCaseCreate
from ...storage import NotFoundError
from .. import document_versions as archive
from .. import maintenance_projects
from ..integrations import connection_storage as db
from ..maintenance_rows import Rows
from .admin import _eligible_version, _manage_grant
from .common import admin_work, event, external_work, grant, public, receipt, replay, rows


def _accesses(unit, identity_id):
    result = []
    for item in rows(unit, PortalGrantORM, identity_id=identity_id, active=True):
        try:
            result.append(grant(unit, item.id, identity_id))
        except (HTTPException, NotFoundError):
            continue
    return result


def me(store, token):
    with external_work(store, token) as (unit, identity, _):
        result = []
        for access in _accesses(unit, identity.id):
            prop = unit.store.get_property(access.binding["property_id"])
            place = unit.store.get_unit(access.binding["unit_id"]) if access.binding["unit_id"] else None
            result.append({"id": access.id, "revision": access.revision, "kind": access.kind, "property": prop.name,
                           "unit": place.label if place else None})
        return {"email": identity.email, "grants": result}


def _publication(unit, identifier, identity_id):
    item = db.row(unit, PortalPublicationORM, identifier, required=False)
    if item is None or not item.active:
        raise HTTPException(404, "Veröffentlichtes Dokument nicht verfügbar.")
    access = grant(unit, item.grant_id, identity_id)
    version = _eligible_version(unit, access, item.version_id)
    if version.sha256 != item.sha256:
        raise HTTPException(409, "Veröffentlichte Fassung passt nicht zum Originalnachweis.")
    return item, version


def documents(store, token, *, search="", skip=0, limit=25):
    with external_work(store, token) as (unit, identity, _):
        result = []
        for access in _accesses(unit, identity.id):
            for item in rows(unit, PortalPublicationORM, grant_id=access.id, active=True):
                if search.casefold() not in item.title.casefold():
                    continue
                try:
                    _, version = _publication(unit, item.id, identity.id)
                except (HTTPException, NotFoundError):
                    continue
                result.append({"id": item.id, "title": item.title, "version": version.number,
                    "sha256": version.sha256, "filename": version.filename, "media_type": version.media_type, "size_bytes": version.size_bytes})
        result.sort(key=lambda row: (row["title"].casefold(), row["id"]))
        return {"items": result[skip:skip + limit], "total": len(result), "skip": skip, "limit": limit}


def document_file(store, token, identifier):
    with external_work(store, token) as (unit, identity, _):
        _, version = _publication(unit, identifier, identity.id)
        return archive.original_bytes(unit, version), version.filename, version.media_type


def _case(unit, identifier, identity_id=None):
    from ..privacy.storage import ensure_available
    ensure_available(unit.store, "portal_case", identifier)
    link = db.row(unit, PortalCaseORM, identifier, required=False, lock=True)
    if link is None or not link.active:
        raise HTTPException(404, "Vorgang nicht verfügbar.")
    access = grant(unit, link.grant_id, identity_id)
    source = Rows.of(unit)
    source.lock("maintenance_cases", link.case_id)
    case = source.require("maintenance_cases", link.case_id, "Vorgang nicht verfügbar.")
    if case.property_id != access.binding["property_id"] or case.unit_id != access.binding["unit_id"]:
        raise HTTPException(404, "Die Vorgangszuordnung hat sich geändert.")
    return link, case


def _case_view(link, case):
    return {"id": link.id, "grant_id": link.grant_id, "title": link.title, "revision": link.revision,
        "status": maintenance_projects.LEGACY_STATUSES.get(case.status, case.status), "created_at": link.created_at.isoformat(),
        "updated_at": link.updated_at.isoformat()}


def cases(store, token, *, skip=0, limit=25):
    with external_work(store, token) as (unit, identity, _):
        result = []
        for access in _accesses(unit, identity.id):
            for row in rows(unit, PortalCaseORM, grant_id=access.id, active=True):
                try:
                    link, case = _case(unit, row.id, identity.id)
                    result.append(_case_view(link, case))
                except (HTTPException, NotFoundError):
                    continue
        result.sort(key=lambda row: (row["created_at"], row["id"]), reverse=True)
        return {"items": result[skip:skip + limit], "total": len(result), "skip": skip, "limit": limit}


def case_messages(unit, link, case, *, skip=0, limit=50):
    messages = sorted(rows(unit, PortalMessageORM, case_link_id=link.id), key=lambda row: (row.created_at, row.id))
    page = []
    for message in messages[skip:skip + limit]:
        item = public(message, ("id", "sender_kind", "body", "created_at"))
        item["attachments"] = [public(row, ("id", "filename", "media_type", "sha256")) for row in rows(unit, PortalAttachmentORM, message_id=message.id)]
        page.append(item)
    return {**_case_view(link, case), "messages": page, "total": len(messages), "skip": skip, "limit": limit}


def detail(store, token, identifier, *, skip=0, limit=50):
    with external_work(store, token) as (unit, identity, _):
        return case_messages(unit, *_case(unit, identifier, identity.id), skip=skip, limit=limit)


def _images(files):
    if len(files) > 5 or sum(len(raw) for _, raw in files) > 20 * 1024 * 1024:
        raise HTTPException(413, "Höchstens fünf Bilder mit zusammen 20 MiB sind zulässig.")
    images: list[tuple[str, bytes]] = []
    for filename, raw in files:
        if not 0 < len(raw) <= 8 * 1024 * 1024:
            raise HTTPException(413, "Ein Bild darf höchstens 8 MiB groß sein.")
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(io.BytesIO(raw)) as image:
                    if image.format not in ("JPEG", "PNG", "WEBP") or image.width * image.height > 16_000_000:
                        raise ValueError("Bildformat oder Auflösung nicht unterstützt")
                    image.verify()
                with Image.open(io.BytesIO(raw)) as image:
                    # Decode once and discard metadata/EXIF and trailing payloads.
                    output = io.BytesIO()
                    image.convert("RGB").save(output, "JPEG", quality=90)
                    safe = output.getvalue()
            images.append(("Schadensbild-" + str(len(images) + 1) + ".jpg", safe))
        except (UnidentifiedImageError, ValueError, OSError, Image.DecompressionBombError, Image.DecompressionBombWarning):
            raise HTTPException(422, "Das Bild ist beschädigt oder kein unterstütztes JPEG-, PNG- oder WebP-Bild.") from None
    return images


def _message(unit, link, body, sender, images):
    message = db.put(unit, PortalMessageORM, {"id": str(uuid4()), "case_link_id": link.id, "sender_kind": sender,
        "sender_id": unit.actor_id, "body": body, "created_at": db.now()})
    for filename, raw in images:
        db.put(unit, PortalAttachmentORM, {"id": str(uuid4()), "message_id": message.id, "filename": filename, "media_type": "image/jpeg",
            "sha256": hashlib.sha256(raw).hexdigest(), "content": raw, "created_at": db.now()})
    return message


def _command_with_images(command, files):
    # Bind uploaded bytes, not only the text command, to the retry identity.
    from ..data_transfer.common import digest
    return digest([command.model_dump(mode="json"), [(name, hashlib.sha256(raw).hexdigest()) for name, raw in files]])


def report(store, token, command, files):
    images = _images(files)
    operation = "damage:" + _command_with_images(command, files)
    with external_work(store, token) as (unit, identity, _):
        access = grant(unit, command.grant_id, identity.id)
        if previous := replay(unit, operation, command):
            return previous
        db.revision(access, command.expected_revision)
        case = maintenance_projects.create_case(unit.store, MaintenanceCaseCreate(property_id=access.binding["property_id"],
            unit_id=access.binding["unit_id"], title=command.title, description="Portal-Schadensmeldung; externe Kommunikation in der Portalakte.",
            reported_by="Portal: " + identity.email), None, _unit=unit)
        link = db.put(unit, PortalCaseORM, {"id": str(uuid4()), "grant_id": access.id, "case_id": case.id, "title": command.title,
            "active": True, "revision": 1, "created_at": db.now(), "updated_at": db.now()})
        _message(unit, link, command.body, "external", images)
        event(unit, access.id, "damage_reported", "Externe Schadensmeldung an die interne Bearbeitung übergeben.", {"case_id": case.id})
        return receipt(unit, operation, command, _case_view(link, case))


def reply(store, token, identifier, command, files):
    images = _images(files)
    operation = "reply:" + identifier + ":" + _command_with_images(command, files)
    with external_work(store, token) as (unit, identity, _):
        link, case = _case(unit, identifier, identity.id)
        if previous := replay(unit, operation, command):
            return previous
        db.revision(link, command.expected_revision)
        _message(unit, link, command.body, "external", images)
        link = db.put(unit, PortalCaseORM, {**db.values(link), "revision": link.revision + 1, "updated_at": db.now()})
        return receipt(unit, operation, command, _case_view(link, case))


def attachment(store, token, identifier):
    with external_work(store, token) as (unit, identity, _):
        image = db.row(unit, PortalAttachmentORM, identifier)
        message = db.row(unit, PortalMessageORM, image.message_id)
        _case(unit, message.case_link_id, identity.id)
        content = image.content
        if hashlib.sha256(content).hexdigest() != image.sha256:
            raise HTTPException(409, "Das Bild stimmt nicht mit seinem Prüfnachweis überein.")
        return content, image.filename, image.media_type


def internal_cases(store, actor_id, *, case_id=None, skip=0, limit=50):
    with admin_work(store, actor_id) as unit:
        result = []
        for link in rows(unit, PortalCaseORM, **({"case_id": case_id} if case_id else {})):
            try:
                _manage_grant(unit, link.grant_id)
                case = unit.store.get_maintenance_case(link.case_id)
            except (NotFoundError, HTTPException):
                continue
            result.append({**_case_view(link, case), "case_id": case.id, "active": link.active})
        return {"items": result[skip:skip + limit], "total": len(result), "skip": skip, "limit": limit}


def internal_detail(store, actor_id, identifier, *, skip=0, limit=50):
    with admin_work(store, actor_id) as unit:
        link = db.row(unit, PortalCaseORM, identifier)
        _manage_grant(unit, link.grant_id)
        case = unit.store.get_maintenance_case(link.case_id)
        return {**case_messages(unit, link, case, skip=skip, limit=limit), "case_id": case.id, "active": link.active}


def internal_reply(store, actor_id, identifier, command):
    with admin_work(store, actor_id) as unit:
        link, case = _case(unit, identifier)
        operation = "internal-reply:" + identifier
        if previous := replay(unit, operation, command):
            return previous
        db.revision(link, command.expected_revision)
        _message(unit, link, command.body, "internal", [])
        link = db.put(unit, PortalCaseORM, {**db.values(link), "revision": link.revision + 1, "updated_at": db.now()})
        event(unit, link.grant_id, "reply_published", "Interne Antwort ausdrücklich im Portal veröffentlicht.", {"case_link_id": identifier})
        return receipt(unit, operation, command, _case_view(link, case))


def share_case(store, actor_id, grant_id, command):
    from ..record_revisions import ExpectedRevision, assert_expected, revision_scope
    with admin_work(store, actor_id) as unit:
        access = grant(unit, grant_id)
        operation = "share-case:" + grant_id
        if previous := replay(unit, operation, command):
            return previous
        db.revision(access, command.grant_revision)
        source = Rows.of(unit)
        source.lock("maintenance_cases", command.case_id)
        case = source.require("maintenance_cases", command.case_id, "Schadenakte nicht gefunden.")
        with revision_scope(ExpectedRevision("maintenance_cases", case.id, command.case_updated_at)):
            assert_expected("maintenance_cases", case.id, case.updated_at)
        if (case.property_id, case.unit_id) != (access.binding["property_id"], access.binding["unit_id"]):
            raise HTTPException(403, "Die Schadenakte gehört nicht zu dieser konkreten Portalzuordnung.")
        if db.find_one(unit, PortalCaseORM, grant_id=grant_id, case_id=case.id):
            raise HTTPException(409, "Diese Akte besitzt bereits eine Portalzuordnung. Bitte die vorhandene Veröffentlichung verwalten.")
        link = db.put(unit, PortalCaseORM, {"id": str(uuid4()), "grant_id": access.id, "case_id": case.id, "title": command.title,
            "active": True, "revision": 1, "created_at": db.now(), "updated_at": db.now()})
        event(unit, grant_id, "case_shared", command.reason, {"case_id": case.id, "case_link_id": link.id})
        return receipt(unit, operation, command, _case_view(link, case))


def change_case(store, actor_id, identifier, command):
    with admin_work(store, actor_id) as unit:
        link = db.row(unit, PortalCaseORM, identifier, lock=True)
        access = _manage_grant(unit, link.grant_id)
        operation = "case-access:" + identifier
        if previous := replay(unit, operation, command):
            return previous
        db.revision(link, command.expected_revision)
        if command.active:
            grant(unit, access.id)
            case = unit.store.get_maintenance_case(link.case_id)
            if (case.property_id, case.unit_id) != (access.binding["property_id"], access.binding["unit_id"]):
                raise HTTPException(409, "Die fachliche Zuordnung dieser Akte wurde geändert.")
        link = db.put(unit, PortalCaseORM, {**db.values(link), "active": command.active, "revision": link.revision + 1, "updated_at": db.now()})
        event(unit, access.id, "case_access_changed", command.reason, {"case_link_id": link.id, "active": link.active})
        return receipt(unit, operation, command, public(link, ("id", "active", "revision")))


def internal_attachment(store, actor_id, identifier):
    with admin_work(store, actor_id) as unit:
        image = db.row(unit, PortalAttachmentORM, identifier)
        message = db.row(unit, PortalMessageORM, image.message_id)
        link = db.row(unit, PortalCaseORM, message.case_link_id)
        _manage_grant(unit, link.grant_id)
        content = image.content
        if hashlib.sha256(content).hexdigest() != image.sha256:
            raise HTTPException(409, "Bild-Prüfsumme stimmt nicht.")
        return content, image.filename, image.media_type


def own_export(store, token):
    import json
    import zipfile
    with external_work(store, token) as (unit, identity, _):
        parts, documents, conversations = {}, [], []
        size = 0
        def put(name, content):
            nonlocal size
            size += len(content)
            if size > 64 * 1024 * 1024:
                raise HTTPException(413, "Dieser Portalexport ist größer als 64 MiB. Bitte die Verwaltung um einen vollständigen Auskunftsexport bitten.")
            parts[name] = content
        for access in _accesses(unit, identity.id):
            for item in rows(unit, PortalPublicationORM, grant_id=access.id, active=True):
                try:
                    _, version = _publication(unit, item.id, identity.id)
                except (HTTPException, NotFoundError):
                    continue
                raw = archive.original_bytes(unit, version)
                from pathlib import PurePosixPath
                suffix = PurePosixPath(version.filename).suffix.lower()
                path = "documents/" + item.id + (suffix if suffix in (".pdf", ".xml", ".jpg", ".jpeg", ".png", ".webp", ".txt") else ".bin")
                put(path, raw)
                documents.append({"title": item.title, "version": version.number, "filename": version.filename,
                    "media_type": version.media_type, "sha256": version.sha256, "path": path})
            for item in rows(unit, PortalCaseORM, grant_id=access.id, active=True):
                try:
                    link, case = _case(unit, item.id, identity.id)
                except (HTTPException, NotFoundError):
                    continue
                conversation = case_messages(unit, link, case, limit=100_000)
                for message in conversation["messages"]:
                    for entry in message["attachments"]:
                        image = db.row(unit, PortalAttachmentORM, entry["id"])
                        raw = image.content
                        if hashlib.sha256(raw).hexdigest() != image.sha256:
                            raise HTTPException(409, "Ein Bild im Portalexport hat eine ungültige Prüfsumme.")
                        entry["path"] = "images/" + image.id + ".jpg"
                        put(entry["path"], raw)
                conversations.append(conversation)
        data = {"email": identity.email, "documents": documents, "cases": conversations}
        put("data.json", json.dumps(data, ensure_ascii=False, sort_keys=True).encode())
        proof = {name: {"sha256": hashlib.sha256(content).hexdigest(), "size_bytes": len(content)} for name, content in parts.items()}
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as package:
            for name, content in parts.items():
                package.writestr(name, content)
            package.writestr("manifest.json", json.dumps({"format": "immomanager-own-portal-export/1", "files": proof}))
        return output.getvalue(), "Meine-Portalunterlagen.zip", "application/zip"
