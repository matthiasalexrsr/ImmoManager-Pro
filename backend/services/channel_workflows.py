"""Scoped German channel workflows; network effects require a persisted explicit command.

The shared SMTP/IMAP worker can call WhatsAppAdapter directly with its own outbox
lease, or use these case preparation/execution hooks. Messages engine is untouched.
"""

from __future__ import annotations

import base64
import hashlib
import mimetypes
import re
from contextlib import contextmanager
from copy import deepcopy
from typing import Any
from uuid import NAMESPACE_URL, uuid4, uuid5

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from ..db.channel_models import ChannelCaseORM as Case
from ..db.channel_models import ChannelEventORM as Event
from ..db.channel_models import ChannelEvidenceORM as Evidence
from ..db.integration_connection_models import IntegrationConnectionORM
from . import business_qol as commands
from . import document_versions as archive
from .aktenwerk import Entry, read_file
from .integrations import connection_storage as db
from .integrations.connections import Connections
from .integrations.manager import integration_manager
from .portal_adapter import ImmobilienScout24Adapter, OpenImmoFtpAdapter, ProtocolError
from .portfolio_scope import scope_context, scope_from_user
from .whatsapp_channel import WhatsAppAdapter, advance_status, template_request, webhook
from .workspace_contexts import resolve_context


class Prepare(BaseModel):
    model_config = ConfigDict(extra="forbid")
    idempotency_key: str = Field(min_length=1, max_length=128)
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    connection_id: str | None = None
    connection_revision: int | None = Field(default=None, ge=1)
    base_revision: int = Field(default=0, ge=0)
    parameters: dict = Field(default_factory=dict)


class Action(BaseModel):
    model_config = ConfigDict(extra="forbid")
    idempotency_key: str = Field(min_length=1, max_length=128)
    base_revision: int = Field(ge=1)
    action: str
    parameters: dict = Field(default_factory=dict)


@contextmanager
def work(store, actor, area=None):
    with archive.work(store, actor, write_areas=(area,) if area else ()) as unit:
        with scope_context(scope_from_user(unit.user)):
            yield unit


def area(channel):
    return "/listings" if channel in ("is24", "openimmo") else "/messages"


def kind(channel):
    return "listing" if channel in ("is24", "openimmo") else ("document" if channel == "post" else "message_thread")


def context(unit, case):
    return resolve_context(unit.store, case.source_kind, case.source_id, unit.actor_id)


def require_case(unit, identifier):
    case = db.row(unit, Case, identifier, lock=True)
    context(unit, case)
    bound = snapshot(case).get("context", {})
    scope = scope_from_user(unit.user)
    if not scope.unrestricted and not set(bound.get("portfolio_ids", [])).issubset(scope.portfolio_ids):
        raise HTTPException(404, "Ursprünglicher Aktenbezug ist nicht mehr freigegeben.")
    return case


def snapshot(case):
    return db.unseal(case.snapshot_token, "channel/" + case.id + "/snapshot")


def progress(case):
    return db.unseal(case.progress_token, "channel/" + case.id + "/progress")


def response(case):
    return {
        "id": case.id,
        "channel": case.channel,
        "source_kind": case.source_kind,
        "source_id": case.source_id,
        "state": case.state,
        "revision": case.revision,
        "source_sha256": case.source_sha256,
        "external_id": case.external_id,
        "snapshot": snapshot(case),
        "progress": progress(case),
    }


def event(unit, case, body, replay_hash=None):
    body = commands.dump(body)
    digest = replay_hash or db.digest(body)
    if db.find_one(unit, Event, case_id=case.id, replay_hash=digest):
        return False
    identifier = str(uuid4())
    db.put(
        unit,
        Event,
        {
            "id": identifier,
            "case_id": case.id,
            "replay_hash": digest,
            "data_token": db.seal(body, "channel-event/" + identifier),
            "created_at": db.now(),
        },
    )
    return True


def update(unit, case, *, state=None, details=None, external_id=None):
    data = db.values(case)
    data["revision"] += 1
    data["updated_at"] = db.now()
    if state is not None:
        data["state"] = state
    if details is not None:
        data["progress_token"] = db.seal(commands.dump(details), "channel/" + case.id + "/progress")
    if external_id is not None:
        data["external_id"] = external_id
    return db.put(unit, Case, data)


def save_bytes(unit, case, name, content):
    sha = hashlib.sha256(content).hexdigest()
    name = name + "-" + sha
    if not db.find_one(unit, Evidence, case_id=case.id, name=name, sequence=0):
        for sequence, start in enumerate(range(0, len(content), 65536)):
            block = content[start : start + 65536]
            identifier = str(uuid4())
            db.put(
                unit,
                Evidence,
                {
                    "id": identifier,
                    "case_id": case.id,
                    "name": name,
                    "sequence": sequence,
                    "sha256": hashlib.sha256(block).hexdigest(),
                    "data_token": db.seal(base64.b64encode(block).decode(), "channel-evidence/" + identifier),
                },
            )
    return {"evidence_name": name, "sha256": sha, "size": len(content)}


def read_bytes(unit, case, manifest):
    if manifest.get("document_id"):
        resolve_context(unit.store, "document", manifest["document_id"], unit.actor_id)
    if manifest.get("source"):
        source = manifest["source"]
        resolve_context(unit.store, source["kind"], source["entity_id"], unit.actor_id)
        scope = scope_from_user(unit.user)
        if not scope.unrestricted and not set(source.get("portfolio_ids", [])).issubset(scope.portfolio_ids):
            raise HTTPException(404, "Originalquelle ist nicht mehr freigegeben.")
    if unit.db is None:
        rows = [
            r
            for r in db.memory(unit, Evidence).values()
            if r.case_id == case.id and r.name == manifest["evidence_name"]
        ]
    else:
        rows = list(
            unit.db.scalars(
                select(Evidence).filter_by(case_id=case.id, name=manifest["evidence_name"]).order_by(Evidence.sequence)
            )
        )
    data = bytearray()
    for index, row in enumerate(sorted(rows, key=lambda r: r.sequence)):
        block = base64.b64decode(db.unseal(row.data_token, "channel-evidence/" + row.id), validate=True)
        if row.sequence != index or hashlib.sha256(block).hexdigest() != row.sha256:
            raise HTTPException(409, "Originalblock beschädigt.")
        data.extend(block)
    if len(data) != manifest["size"] or hashlib.sha256(data).hexdigest() != manifest["sha256"]:
        raise HTTPException(409, "Originalnachweis unvollständig oder verändert.")
    return bytes(data)


def local_file(unit, url, title="Original"):
    return read_file(unit.store, Entry("channel-source", "sonstiges", title, None, url), unit.actor_id)


def freeze(unit, channel, source_id):
    if channel not in ("is24", "openimmo", "whatsapp", "post"):
        raise HTTPException(422, "Unbekannter Kanal.")
    ctx = resolve_context(unit.store, kind(channel), source_id, unit.actor_id, include_dependencies=True)
    source: dict[str, Any] = {"context": ctx, "assets": []}
    assets = []
    if channel in ("is24", "openimmo"):
        listing = unit.store.get_listing(source_id)
        apartment = unit.store.get_unit(listing.unit_id)
        building = unit.store.get_property(apartment.property_id)
        match = re.fullmatch(r"(.*?)\s+(\d+\S*)", (building.address_line or "").strip())
        source["listing"] = {
            "external_id": listing.id,
            "title": listing.title,
            "description": listing.description,
            "features": apartment.features,
            "target_rent": listing.target_rent,
            "service_charge": listing.service_charge,
            "area_sqm": apartment.area_sqm,
            "rooms": apartment.rooms,
            "address": {
                "street": match[1] if match else building.address_line,
                "house_number": match[2] if match else "",
                "postcode": building.postal_code,
                "city": building.city,
            },
            "photos": [],
        }
        photos = sorted(
            (p for p in unit.store.list_listing_photos() if p.listing_id == source_id),
            key=lambda p: (not p.is_primary, p.sort_order, p.id),
        )
        for photo in photos:
            content, name = local_file(unit, photo.file_url)
            media = mimetypes.guess_type(name)[0]
            from .whatsapp_channel import validate_media

            if media not in ("image/jpeg", "image/png"):
                raise HTTPException(422, "Portalbilder müssen JPEG oder PNG sein.")
            try:
                validate_media(content, media)
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from None
            info = {
                "id": photo.id,
                "name": name,
                "title": photo.title or "Bild",
                "media_type": media,
                "is_primary": photo.is_primary,
                "sha256": hashlib.sha256(content).hexdigest(),
                "size": len(content),
            }
            source["assets"].append(info)
            source["listing"]["photos"].append(info)
            assets.append((info, content))
    elif channel == "post":
        document = unit.store.get_document(source_id)
        content, name = local_file(unit, document.file_url)
        if not content.startswith(b"%PDF-"):
            raise HTTPException(422, "Für den Brief wird ein PDF-Original benötigt.")
        info = {
            "id": document.id,
            "name": name,
            "title": document.title,
            "media_type": "application/pdf",
            "sha256": hashlib.sha256(content).hexdigest(),
            "size": len(content),
        }
        source["assets"].append(info)
        assets.append((info, content))
    # Complete source/dependency revisions and byte oracles; no remote fetch of photo URLs.
    serialized_source = db.canonical(commands.dump(source))  # normalizes dates/Decimals below via context conversion
    return __import__("json").loads(serialized_source), assets


def source_preview(store, actor, channel, source_id):
    with work(store, actor) as unit:
        frozen, assets = freeze(unit, channel, source_id)
        return {"source_sha256": db.digest(frozen), "snapshot": frozen, "asset_count": len(assets)}


def connection(unit, case):
    if not scope_from_user(unit.user).unrestricted:
        raise HTTPException(
            403, "Dieser private Integrationszugang benötigt die bestehenden installationsweiten Rechte."
        )
    conn = db.row(unit, IntegrationConnectionORM, case.connection_id, lock=True)
    expected = "whatsapp" if case.channel == "whatsapp" else "listing-portals"
    if conn.provider_id != expected or not conn.enabled or conn.archived or conn.revision != case.connection_revision:
        raise HTTPException(
            409, "Die ausgewählte Verbindung wurde geändert oder deaktiviert. Neue Vorschau erforderlich."
        )
    config = Connections(unit.store, integration_manager).effective_config(unit, conn)
    if case.channel in ("is24", "openimmo") and config.get("default_portal") != case.channel:
        raise HTTPException(409, "Verbindung und ausgewähltes Portal passen nicht zusammen.")
    return config


def prepare(store, actor, channel, source_id, payload):
    with work(store, actor, area(channel)) as unit:
        frozen, assets = freeze(unit, channel, source_id)
        ctx = frozen["context"]
        prior = commands.replay(unit, actor, "channel:prepare:" + channel + ":" + source_id, payload)
        if prior:
            return prior
        if db.digest(frozen) != payload.source_sha256:
            raise HTTPException(409, "Quelle oder Originalbilder wurden geändert. Vorschau neu laden.")
        if channel == "whatsapp":
            try:
                template_request(payload.parameters)
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from None
        if channel == "post":
            required = ("recipient_name", "street", "postcode", "city")
            if any(not str(payload.parameters.get(k, "")).strip() for k in required):
                raise HTTPException(422, "Vollständige Postanschrift angeben.")
        identifier = str(
            uuid5(
                NAMESPACE_URL,
                "immo-channel:"
                + channel
                + ":"
                + source_id
                + (":" + actor + ":" + payload.idempotency_key if channel == "whatsapp" else ""),
            )
        )
        current = db.row(unit, Case, identifier, required=False)
        if current:
            context(unit, current)
            db.revision(current, payload.base_revision)
            if current.state in (
                "unknown",
                "executing",
                "accepted",
                "sent",
                "delivered",
                "read",
                "posted",
                "franked",
                "transferred",
            ):
                raise HTTPException(
                    409, "Dieser Vorgang benötigt zuerst einen Ergebnisabgleich oder ist bereits abgeschlossen."
                )
        elif payload.base_revision:
            raise HTTPException(409, "Der erwartete Vorgang fehlt.")
        data = {
            "id": identifier,
            "channel": channel,
            "source_kind": kind(channel),
            "source_id": source_id,
            "entity_type": kind(channel),
            "entity_id": source_id,
            "created_by": actor,
            "revision": current.revision + 1 if current else 1,
            "state": "prepared",
            "source_sha256": payload.source_sha256,
            "snapshot_token": db.seal({}, "channel/" + identifier + "/snapshot"),
            "progress_token": db.seal({}, "channel/" + identifier + "/progress"),
            "connection_id": payload.connection_id,
            "connection_revision": payload.connection_revision,
            "external_id": current.external_id if current else None,
            "created_at": current.created_at if current else db.now(),
            "updated_at": db.now(),
        }
        if channel != "post":
            probe = Case(**data)
            config = connection(unit, probe)
            if channel == "is24" and not ImmobilienScout24Adapter().is_configured(config):
                raise HTTPException(422, "IS24-Zugang ist unvollständig.")
        case = db.put(unit, Case, data)
        originals = []
        for info, content in assets:
            originals.append({**info, **save_bytes(unit, case, info["id"], content)})
        frozen.update(originals=originals, parameters=deepcopy(payload.parameters))
        data = db.values(case)
        data["snapshot_token"] = db.seal(frozen, "channel/" + identifier + "/snapshot")
        case = db.put(unit, Case, data)
        event(
            unit,
            case,
            {"action": "prepared", "source_sha256": case.source_sha256, "snapshot": frozen, "revision": case.revision},
        )
        result = response(case)
        commands.save_command(unit, actor, "channel:prepare:" + channel + ":" + source_id, payload, ctx, result)
        return result


def get(store, actor, identifier):
    with work(store, actor) as unit:
        return response(require_case(unit, identifier))


def list_cases(store, actor, channel, source_id, *, cursor=None, limit=50):
    with work(store, actor) as unit:
        resolve_context(unit.store, kind(channel), source_id, actor)
        page = db.page(unit, Case, actor, cursor=cursor, limit=limit, channel=channel, source_id=source_id)
        page["items"] = [response(require_case(unit, row.id)) for row in page["items"]]
        return page


def channel_options(store, actor, channel):
    with work(store, actor) as unit:
        if not scope_from_user(unit.user).unrestricted:
            return []
        provider = "whatsapp" if channel == "whatsapp" else "listing-portals"
        rows = (
            list(
                unit.db.scalars(
                    select(IntegrationConnectionORM).filter_by(provider_id=provider, enabled=True, archived=False)
                )
            )
            if unit.db
            else [
                row
                for row in db.memory(unit, IntegrationConnectionORM).values()
                if row.provider_id == provider and row.enabled and not row.archived
            ]
        )
        output = []
        for row in rows:
            if channel in ("is24", "openimmo"):
                config = db.unseal(row.config_token, "connection/" + row.id + "/config")
                if config.get("default_portal") != channel:
                    continue
            output.append({"id": row.id, "name": row.name, "revision": row.revision})
        return sorted(output, key=lambda row: (row["name"], row["id"]))


def _start(store, actor, identifier, payload):
    # The command is recorded before IO; response loss or process death cannot start it twice.
    channel = get(store, actor, identifier)["channel"]
    with work(store, actor, area(channel)) as unit:
        case = require_case(unit, identifier)
        prior = commands.replay(unit, actor, "channel:action:" + identifier, payload)
        if prior:
            return case, True
        db.revision(case, payload.base_revision)
        if case.channel == "post":
            raise HTTPException(422, "Post wird ausschließlich manuell bearbeitet.")
        if payload.action not in ("send", "publish", "update", "deactivate", "reconcile"):
            raise HTTPException(422, "Unbekannte Kanalaktion.")
        if case.channel == "whatsapp" and payload.action not in ("send", "reconcile"):
            raise HTTPException(422, "WhatsApp-Aktion ungültig.")
        if payload.action != "reconcile":
            if case.state == "unknown":
                raise HTTPException(409, "Ausgang unklar. Zuerst Anbieterstatus abgleichen.")
            if case.channel == "whatsapp" and case.state != "prepared":
                raise HTTPException(409, "WhatsApp wurde bereits übergeben oder benötigt eine neue Vorbereitung.")
            fresh, _ = freeze(unit, case.channel, case.source_id)
            if db.digest(fresh) != case.source_sha256:
                raise HTTPException(409, "Quelle verändert. Neue Vorschau erforderlich.")
            if (
                case.channel in ("is24", "openimmo")
                and payload.action in ("publish", "update")
                and not snapshot(case)["originals"]
                and payload.parameters.get("publish_without_images_confirmed") is not True
            ):
                raise HTTPException(
                    422, "Keine Originalbilder gewählt. Veröffentlichung ohne Bilder ausdrücklich bestätigen."
                )
        connection(unit, case)
        detail = progress(case)
        if (
            case.channel == "whatsapp"
            and payload.parameters.get("media_id")
            and payload.parameters["media_id"] != detail.get("media", {}).get("id")
        ):
            raise HTTPException(409, "Medienkennung passt nicht zur geprüften Auswahl.")
        if payload.action != "reconcile":
            detail.update(pending=payload.action, command_key=payload.idempotency_key)
            case = update(unit, case, state="unknown", details=detail)
        commands.save_command(
            unit,
            actor,
            "channel:action:" + identifier,
            payload,
            context(unit, case),
            {"id": identifier, "status": "started"},
        )
        return case, False


def _checkpoint(store, actor, identifier, expected, *, state="unknown", detail=None, external_id=None, preflight=False):
    channel = get(store, actor, identifier)["channel"]
    with work(store, actor, area(channel)) as unit:
        case = require_case(unit, identifier)
        db.revision(case, expected)
        if case.connection_id:
            connection(unit, case)
        if preflight:
            fresh, _ = freeze(unit, case.channel, case.source_id)
            if db.digest(fresh) != case.source_sha256:
                raise HTTPException(409, "Quelle während der Übergabe geändert. Teilstand zuerst abgleichen.")
        case = update(unit, case, state=state, details=detail, external_id=external_id)
        event(
            unit, case, {"state": state, "progress": detail, "external_id": case.external_id, "revision": case.revision}
        )
        return case


def execute(store, actor, identifier, payload, *, is24=None, whatsapp=None, openimmo=None):
    case, replayed = _start(store, actor, identifier, payload)
    if replayed:
        return get(store, actor, identifier)
    with work(store, actor) as unit:
        case = require_case(unit, identifier)
        config = connection(unit, case)
        frozen = snapshot(case)
        originals = [(info, read_bytes(unit, case, info)) for info in frozen["originals"]]
    details = progress(case)
    action = payload.action
    try:
        if case.channel == "whatsapp":
            if action == "reconcile":
                # Meta has no supported GET message status. Only a signed webhook resolves this.
                return get(store, actor, identifier)
            message = {**frozen["parameters"], "correlation": identifier}
            if payload.parameters.get("media_id"):
                media = details.get("media", {})
                if payload.parameters["media_id"] != media.get("id"):
                    raise HTTPException(409, "Gewählte Medienkennung passt nicht zum geprüften Original.")
                media_kind = "document" if media["media_type"] == "application/pdf" else "image"
                message["components"] = [
                    {"type": "header", "parameters": [{"type": media_kind, media_kind: {"id": media["id"]}}]},
                    *[c for c in message.get("components", []) if c["type"] != "header"],
                ]
            result = (whatsapp or WhatsAppAdapter()).send(message, config)
            case = _checkpoint(
                store,
                actor,
                identifier,
                case.revision,
                state=result["status"],
                detail=result,
                external_id=result["external_id"],
            )
        elif case.channel == "is24":
            adapter = is24 or ImmobilienScout24Adapter()
            listing = frozen["listing"]
            if action == "reconcile":
                external = case.external_id or adapter.reconcile_object(listing["external_id"], config)
                if not external:
                    return get(store, actor, identifier)  # absence is not authority to repeat a possibly delayed create
                status = adapter.check_status(external, config)
                # A status read resolves only publish/deactivate, never missing image/update outcomes.
                pending = details.get("pending")
                state = "unknown"
                if pending == "create":
                    state = "prepared"  # stable external id found; remaining original uploads still pending
                elif pending and pending.startswith("image:"):
                    image_id = pending.split(":", 1)[1]
                    info = next((i for i, _ in originals if i["id"] == image_id), None)
                    if info and adapter.reconcile_photo(external, info, config):
                        details = {
                            **details,
                            "uploaded": list(dict.fromkeys([*details.get("uploaded", []), info["sha256"]])),
                        }
                        state = "prepared"
                elif pending == "update" and adapter.reconcile_content(external, listing, config):
                    state = "prepared"
                elif pending in ("publish", "deactivate") and (
                    pending == "deactivate" or details.get("photos_complete")
                ):
                    expected = "published" if pending == "publish" else "unpublished"
                    if status["status"] == expected:
                        state = expected
                _checkpoint(
                    store,
                    actor,
                    identifier,
                    case.revision,
                    state=state,
                    detail={**details, "reconciliation": status},
                    external_id=external,
                )
                return get(store, actor, identifier)
            if not case.external_id:
                details = {**details, "pending": "create"}
                case = _checkpoint(store, actor, identifier, case.revision, detail=details, preflight=True)
                external = adapter.create(listing, config)
                case = _checkpoint(
                    store, actor, identifier, case.revision, detail={**details, "created": True}, external_id=external
                )
            if action == "deactivate":
                details = {**details, "pending": "deactivate"}
                case = _checkpoint(store, actor, identifier, case.revision, detail=details, preflight=True)
                adapter.write(action, case.external_id, listing, config)
                case = _checkpoint(
                    store, actor, identifier, case.revision, state="unpublished", detail={"pending": action}
                )
            else:
                if action == "update":
                    details = {**details, "pending": "update"}
                    case = _checkpoint(store, actor, identifier, case.revision, detail=details, preflight=True)
                    adapter.write("update", case.external_id, listing, config)
                uploaded = details.get("uploaded", [])
                for info, content in originals:
                    if info["sha256"] in uploaded:
                        continue
                    details = {**details, "pending": "image:" + info["id"]}
                    case = _checkpoint(store, actor, identifier, case.revision, detail=details, preflight=True)
                    adapter.upload_photo(case.external_id, info, content, config)
                    uploaded = [*uploaded, info["sha256"]]
                    details = {**details, "uploaded": uploaded, "pending": "image:" + info["id"]}
                    case = _checkpoint(store, actor, identifier, case.revision, detail=details)
                details = {**details, "photos_complete": True, "pending": "publish"}
                case = _checkpoint(store, actor, identifier, case.revision, detail=details, preflight=True)
                adapter.write("publish", case.external_id, listing, config)
                case = _checkpoint(store, actor, identifier, case.revision, state="published", detail=details)
        else:
            if action == "reconcile":
                return get(store, actor, identifier)  # transfer cannot prove import/publication
            adapter = openimmo or OpenImmoFtpAdapter()
            packet = adapter.package(
                frozen["listing"],
                originals,
                {"publish": "NEW", "update": "CHANGE", "deactivate": "DELETE"}[action],
                config,
            )
            result = adapter.transfer(packet, config)
            case = _checkpoint(
                store,
                actor,
                identifier,
                case.revision,
                state="transferred",
                detail=result,
                external_id=frozen["listing"]["external_id"],
            )
    except ProtocolError as exc:
        _checkpoint(
            store,
            actor,
            identifier,
            case.revision,
            state=exc.state,
            detail={**progress(case), "error": str(exc), "http_status": exc.status_code},
        )
    return get(store, actor, identifier)


def post_action(store, actor, identifier, payload):
    with work(store, actor, "/messages") as unit:
        case = require_case(unit, identifier)
        if case.channel != "post":
            raise HTTPException(422, "Kein Briefvorgang.")
        prior = commands.replay(unit, actor, "channel:post:" + identifier, payload)
        if prior:
            return prior
        db.revision(case, payload.base_revision)
        frozen = snapshot(case)
        details = progress(case)
        if payload.action == "frank":
            if (
                case.state != "prepared"
                or payload.parameters.get("purchased_original_confirmed") is not True
                or not payload.parameters.get("purchase_reference")
            ):
                raise HTTPException(422, "Gekauftes Original und Kaufreferenz ausdrücklich bestätigen.")
            document_id = payload.parameters.get("document_id", "")
            document = unit.store.get_document(document_id)
            resolve_context(unit.store, "document", document_id, actor)
            content, name = local_file(unit, document.file_url)
            if (
                document_id == case.source_id
                or not content
                or not content.startswith((b"%PDF-", b"\x89PNG", b"\xff\xd8\xff"))
            ):
                raise HTTPException(422, "Separaten tatsächlich gekauften Originalbeleg (PDF, PNG oder JPEG) wählen.")
            details = {
                "purchase_reference": str(payload.parameters["purchase_reference"]),
                "purchased_original": {
                    **save_bytes(unit, case, "postage", content),
                    "document_id": document_id,
                    "name": name,
                    "source": resolve_context(unit.store, "document", document_id, actor),
                },
                "confirmed_by": actor,
                "confirmed_at": db.stamp(db.now()),
                "delivery_confirmed": False,
            }
            state = "franked"
        elif payload.action == "posted":
            if case.state != "franked" or payload.parameters.get("manually_posted_confirmed") is not True:
                raise HTTPException(409, "Zuerst Frankaturoriginal zuordnen und tatsächlichen Einwurf bestätigen.")
            read_bytes(unit, case, details["purchased_original"])
            for info in frozen["originals"]:
                read_bytes(unit, case, info)
            details = {**details, "posted_by": actor, "posted_at": db.stamp(db.now()), "delivery_confirmed": False}
            state = "posted"
        else:
            raise HTTPException(422, "Unbekannte Postaktion.")
        case = update(unit, case, state=state, details=details)
        event(unit, case, {"action": payload.action, "details": details, "revision": case.revision})
        result = response(case)
        commands.save_command(unit, actor, "channel:post:" + identifier, payload, context(unit, case), result)
        return result


def receive_webhook(store, connection_id, raw, signature):
    """Public signature-authenticated entry; original body committed before acknowledgement.

    Ambiguous unsolicited messages remain in the encrypted connection inbox. No
    name/phone-only automatic party or thread assignment is performed.
    """
    from ..db.channel_models import ChannelWebhookORM

    if len(raw) > 4 * 1024 * 1024:
        raise HTTPException(413, "Webhook zu groß.")
    # Bootstrap only the owner id, never return configuration or unverified payloads.
    if hasattr(store, "db"):
        conn = store.db.get(IntegrationConnectionORM, connection_id)
    else:
        conn = (
            store.__dict__.get("_integration_connections", {})
            .get(IntegrationConnectionORM.__tablename__, {})
            .get(connection_id)
        )
    if conn is None:
        raise HTTPException(404, "Webhook nicht gefunden.")
    actor = conn.created_by
    with work(store, actor, "/integrations") as unit:
        conn = db.row(unit, IntegrationConnectionORM, connection_id, lock=True)
        if conn.provider_id != "whatsapp" or not conn.enabled or conn.archived:
            raise HTTPException(404, "Webhook nicht aktiv.")
        config = Connections(unit.store, integration_manager).effective_config(unit, conn)
        events = webhook(raw, signature, config.get("app_secret", ""), config["phone_number_id"])
        sha = hashlib.sha256(raw).hexdigest()
        if db.find_one(unit, ChannelWebhookORM, connection_id=connection_id, sha256=sha):
            return {"received": True, "replayed": True}
        identifier = str(uuid4())
        db.put(
            unit,
            ChannelWebhookORM,
            {
                "id": identifier,
                "connection_id": connection_id,
                "sha256": sha,
                "raw_token": db.seal(base64.b64encode(raw).decode(), "channel-webhook/" + identifier),
                "created_at": db.now(),
            },
        )
        for item in events:
            case = None
            if item.get("correlation"):
                case = db.row(unit, Case, item["correlation"], required=False)
            reference = item.get("reply_to") if item["kind"] == "message" else item["external_id"]
            if case is None and reference:
                if unit.db:
                    candidates = list(
                        unit.db.scalars(select(Case).filter_by(connection_id=connection_id, external_id=reference))
                    )
                else:
                    candidates = [
                        c
                        for c in db.memory(unit, Case).values()
                        if c.connection_id == connection_id and c.external_id == reference
                    ]
                if len(candidates) == 1:
                    case = candidates[0]
            if case is None or case.channel != "whatsapp" or case.connection_id != connection_id:
                continue
            context(unit, case)
            recipient = str(snapshot(case)["parameters"]["to"]).removeprefix("+")
            if item.get("recipient", item.get("sender")) != recipient:
                continue
            if item["kind"] == "status" and case.external_id not in (None, item["external_id"]):
                continue
            if event(unit, case, item):
                detail = progress(case)
                if item["kind"] == "status":
                    detail = {
                        **detail,
                        "last_webhook": item,
                        "delivery_confirmed": item["status"] in ("delivered", "read")
                        or detail.get("delivery_confirmed", False),
                    }
                    update(
                        unit,
                        case,
                        state=advance_status(case.state, item["status"]),
                        details=detail,
                        external_id=item["external_id"],
                    )
        return {"received": True, "replayed": False}


def webhook_challenge(store, connection_id, mode, token, value):
    from .whatsapp_channel import challenge

    if hasattr(store, "db"):
        conn = store.db.get(IntegrationConnectionORM, connection_id)
    else:
        conn = (
            store.__dict__.get("_integration_connections", {})
            .get(IntegrationConnectionORM.__tablename__, {})
            .get(connection_id)
        )
    if conn is None:
        raise HTTPException(404, "Webhook nicht gefunden.")
    with work(store, conn.created_by) as unit:
        conn = db.row(unit, IntegrationConnectionORM, connection_id)
        if conn.provider_id != "whatsapp" or not conn.enabled or conn.archived:
            raise HTTPException(404, "Webhook nicht aktiv.")
        config = Connections(unit.store, integration_manager).effective_config(unit, conn)
        return challenge(mode, token, value, config.get("verify_token"))


def upload_media(store, actor, identifier, payload, adapter=None):
    """Upload only an explicitly chosen, authorized original; this never sends a message."""
    from .whatsapp_channel import validate_media

    with work(store, actor, "/messages") as unit:
        case = require_case(unit, identifier)
        prior = commands.replay(unit, actor, "channel:media:" + identifier, payload)
        if prior:
            return get(store, actor, identifier)
        db.revision(case, payload.base_revision)
        if case.channel != "whatsapp" or case.state != "prepared":
            raise HTTPException(409, "Medien nur vor Nachrichtenübergabe wählen.")
        config = connection(unit, case)
        document_id = str(payload.parameters.get("document_id", ""))
        doc_context = resolve_context(unit.store, "document", document_id, actor)
        document = unit.store.get_document(document_id)
        content, name = local_file(unit, document.file_url)
        media_type = mimetypes.guess_type(name)[0]
        try:
            validate_media(content, media_type)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from None
        info = {
            **save_bytes(unit, case, "whatsapp-media", content),
            "name": name,
            "media_type": media_type,
            "source": doc_context,
        }
        detail = {**progress(case), "media_original": info, "pending": "media_upload"}
        case = update(unit, case, state="unknown", details=detail)
        commands.save_command(
            unit,
            actor,
            "channel:media:" + identifier,
            payload,
            context(unit, case),
            {"id": identifier, "status": "started"},
        )
        event(unit, case, {"action": "media_upload_started", "original": info, "revision": case.revision})
    try:
        result = (adapter or WhatsAppAdapter()).upload(content, name, media_type, config)
        _checkpoint(store, actor, identifier, case.revision, state="prepared", detail={**detail, "media": result})
    except ProtocolError as exc:
        _checkpoint(
            store,
            actor,
            identifier,
            case.revision,
            state="prepared" if exc.state == "failed" else "unknown",
            detail={**detail, "error": str(exc)},
        )
    return get(store, actor, identifier)


def event_page(store, actor, identifier, *, cursor=None, limit=50):
    with work(store, actor) as unit:
        case = require_case(unit, identifier)
        page = db.page(unit, Event, actor, cursor=cursor, limit=limit, case_id=case.id)
        page["items"] = [
            {
                "id": row.id,
                "created_at": db.stamp(row.created_at),
                "detail": db.unseal(row.data_token, "channel-event/" + row.id),
            }
            for row in page["items"]
        ]
        return page


def inbox_page(store, actor, connection_id, *, cursor=None, limit=50):
    from ..db.channel_models import ChannelWebhookORM

    with db.work(store, actor) as unit:
        conn = db.row(unit, IntegrationConnectionORM, connection_id)
        if conn.provider_id != "whatsapp":
            raise HTTPException(404, "WhatsApp-Eingang nicht gefunden.")
        page = db.page(unit, ChannelWebhookORM, actor, cursor=cursor, limit=limit, connection_id=connection_id)
        # Only signed, already verified original payloads are shown, safely as structured data.
        page["items"] = [
            {
                "id": row.id,
                "sha256": row.sha256,
                "created_at": db.stamp(row.created_at),
                "original": __import__("json").loads(
                    base64.b64decode(db.unseal(row.raw_token, "channel-webhook/" + row.id))
                ),
            }
            for row in page["items"]
        ]
        return page


class InboundAssignment(BaseModel):
    model_config = ConfigDict(extra="forbid")
    idempotency_key: str = Field(min_length=1, max_length=128)
    thread_id: str
    thread_revision: str
    message_id: str
    confirmed: bool


def assign_inbound(store, actor, connection_id, webhook_id, payload):
    from ..db.channel_models import ChannelWebhookORM

    with db.work(store, actor, write=True) as unit:
        conn = db.row(unit, IntegrationConnectionORM, connection_id)
        if conn.provider_id != "whatsapp":
            raise HTTPException(404, "WhatsApp-Verbindung fehlt.")
        batch = db.row(unit, ChannelWebhookORM, webhook_id)
        if batch.connection_id != connection_id:
            raise HTTPException(404, "Empfangsbeleg gehört nicht zur Verbindung.")
        ctx = resolve_context(unit.store, "message_thread", payload.thread_id, actor, lock=True)
        prior = commands.replay(unit, actor, "channel:assign:" + webhook_id, payload)
        if prior:
            return prior
        if payload.confirmed is not True or ctx["revision"] != payload.thread_revision:
            raise HTTPException(409, "Gewählten Thread und aktuellen Stand ausdrücklich bestätigen.")
        raw = base64.b64decode(db.unseal(batch.raw_token, "channel-webhook/" + batch.id))
        body = __import__("json").loads(raw)
        messages = [
            message
            for entry in body["entry"]
            for change in entry["changes"]
            for message in change["value"].get("messages", [])
            if message.get("id") == payload.message_id
        ]
        if len(messages) != 1:
            raise HTTPException(409, "Keine eindeutige signierte Empfangsnachricht gefunden.")
        message = messages[0]
        identifier = str(uuid5(NAMESPACE_URL, "whatsapp-inbound:" + connection_id + ":" + payload.message_id))
        existing = db.row(unit, Case, identifier, required=False)
        if existing and existing.source_id != payload.thread_id:
            raise HTTPException(409, "Diese Nachricht wurde bereits einem anderen Thread zugeordnet.")
        if existing:
            result = response(existing)
        else:
            frozen = {
                "context": commands.dump(ctx),
                "originals": [],
                "parameters": {"to": message["from"]},
                "inbound": message,
                "signed_webhook_id": batch.id,
                "signed_webhook_sha256": batch.sha256,
            }
            data = {
                "id": identifier,
                "channel": "whatsapp",
                "source_kind": "message_thread",
                "source_id": payload.thread_id,
                "entity_type": "message_thread",
                "entity_id": payload.thread_id,
                "created_by": actor,
                "revision": 1,
                "state": "received",
                "source_sha256": db.digest(frozen),
                "snapshot_token": db.seal(frozen, "channel/" + identifier + "/snapshot"),
                "progress_token": db.seal(
                    {"direction": "inbound", "assigned_by": actor}, "channel/" + identifier + "/progress"
                ),
                "connection_id": connection_id,
                "connection_revision": conn.revision,
                "external_id": payload.message_id,
                "created_at": db.now(),
                "updated_at": db.now(),
            }
            case = db.put(unit, Case, data)
            event(unit, case, {"action": "inbound_assigned", "message": message, "webhook_id": batch.id})
            result = response(case)
        commands.save_command(unit, actor, "channel:assign:" + webhook_id, payload, ctx, result)
        return result


def receive_case_media(store, actor, identifier, payload, adapter=None):
    with work(store, actor, "/messages") as unit:
        case = require_case(unit, identifier)
        db.revision(case, payload.base_revision)
        if case.state != "received":
            raise HTTPException(409, "Medienabruf benötigt eine geprüfte Empfangsnachricht.")
        config = connection(unit, case)
        frozen = snapshot(case)
        original = frozen["inbound"]
        media = original.get(original.get("type", ""), {})
        if original.get("type") not in ("image", "document") or not media.get("id"):
            raise HTTPException(422, "Kein unterstütztes Bild/PDF in dieser Empfangsnachricht.")
        expected = case.revision
    content, metadata = (adapter or WhatsAppAdapter()).receive_media(str(media["id"]), config)
    with work(store, actor, "/messages") as unit:
        case = require_case(unit, identifier)
        db.revision(case, expected)
        connection(unit, case)
        info = {
            **save_bytes(unit, case, "received-media", content),
            "name": "empfangen."
            + (
                "pdf"
                if metadata["mime_type"] == "application/pdf"
                else "png"
                if metadata["mime_type"] == "image/png"
                else "jpg"
            ),
            "media_type": metadata["mime_type"],
            "provider_media_id": str(media["id"]),
        }
        case = update(unit, case, details={**progress(case), "received_media": info})
        event(unit, case, {"action": "received_media", "original": info, "revision": case.revision})
        return response(case)
