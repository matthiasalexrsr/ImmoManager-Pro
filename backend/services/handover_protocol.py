"""Handover protocol (Übergabeprotokoll) at move-in and move-out: draft, review, finalize, correct.

A protocol belongs to one contract and its unit. As a draft it holds rooms with
their condition, defects (room, description, who answers for it, what was agreed
and until when, photos), keys (handed over, and at move-out returned) and meter
readings of the unit's meters, plus photos stored as protected uploads bound to
the protocol. The whole draft is saved at once against its revision.

Finalizing renders the reviewed facts (and the photos) into one PDF and, in one
transaction (document_versions.work):

* records the meter readings as real readings of the unit's meters for the
  protocol date (standalone_meter_readings), so the utility billing splits the
  consumption at the tenant change; an existing reading of the same meter and
  day is attached when it has the same value, a different one is refused;
* creates a document of type `handover_protocol` and archives the PDF as an
  immutable original (metadata `handover-protocol/1` with the reviewed facts);
* marks the protocol finalized. From then on the database refuses changes to
  the protocol and its parts (db/handover_guards.py); only a defect's follow-up
  (resolved on, note) stays editable.

A correction is a new draft that copies the finalized protocol and names it; its
own finalization archives a new original and takes over the meter readings the
corrected protocol recorded. The earlier original stays byte for byte.

Rights: drafting needs write access to /handover-protocols, finalizing also to
/documents and /meters (backend/permissions.py), checked again under the account
lock up to the commit. Reads follow the portfolio boundary of the contract.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import date, datetime, timezone
from io import BytesIO
from typing import Any, NamedTuple

from fastapi import HTTPException
from PIL import Image as PILImage
from sqlalchemy import insert, select

from ..db.orm_models import (
    ContractORM,
    DocumentORM,
    HandoverDefectORM,
    HandoverKeyORM,
    HandoverPhotoORM,
    HandoverProtocolORM,
    HandoverRoomORM,
    MeterORM,
    MeterReadingORM,
    PropertyORM,
    StandaloneMeterReadingORM,
    TenantORM,
    UnitORM,
)
from ..models import (
    Document,
    DocumentCreate,
    HandoverDefect,
    HandoverKey,
    HandoverPhoto,
    HandoverProtocol,
    HandoverRoom,
    Meter,
    MeterReading,
    StandaloneMeterReading,
)
from ..storage import NotFoundError
from . import document_versions as archive
from .handover_protocol_render import pdf_photo, render_pdf
from .handover_protocol_types import ContentRequest, CreateRequest, FinalizeRequest, FollowUpRequest, PhotoPatch
from .handover_protocol_validation import (
    DOC_TYPE,
    PDF_FORMAT_VERSION,
    SCHEMA_VERSION,
    VIRTUAL_PREFIX,
    HandoverValidationError,
    document_id_for,
    finalize_request_hash,
    validate_handover_snapshot,
)
from .housing_confirmation import etag
from .housing_confirmation_validation import digest
from .utility_billing import DEFAULT_UNITS, READING_TOLERANCE_DAYS

logger = logging.getLogger(__name__)

PHOTO_PREFIX = "handover-photos/"
PHOTO_EXTENSIONS = frozenset({"jpg", "jpeg", "png", "webp", "gif", "bmp", "tif", "tiff"})
MAX_PHOTOS = 60
EDIT_AREAS = ("/handover-protocols",)
FINALIZE_AREAS = ("/handover-protocols", "/documents", "/meters")
TYPE_LABELS = {"move_in": "Einzug", "move_out": "Auszug"}
FINAL_MESSAGE = ("Das Übergabeprotokoll ist abgeschlossen und bleibt unverändert. Änderungen nur über eine Korrektur.")


class _Part(NamedTuple):
    orm: Any
    model: Any
    collection: str
    column: str


PARTS = {
    "rooms": _Part(HandoverRoomORM, HandoverRoom, "handover_rooms", "protocol_id"),
    "defects": _Part(HandoverDefectORM, HandoverDefect, "handover_defects", "protocol_id"),
    "keys": _Part(HandoverKeyORM, HandoverKey, "handover_keys", "protocol_id"),
    "meter_readings": _Part(MeterReadingORM, MeterReading, "meter_readings", "handover_id"),
    "photos": _Part(HandoverPhotoORM, HandoverPhoto, "handover_photos", "protocol_id"),
}
# what the PDF and the archived evidence show of each part (a defect's follow-up is not part of it)
REVIEW_FIELDS = {
    "rooms": ("id", "position", "name", "condition", "notes"),
    "defects": ("id", "room_id", "position", "description", "responsible", "remedy", "due_date"),
    "keys": ("id", "position", "key_type", "label", "handed_over", "returned", "notes"),
    "meter_readings": ("id", "position", "meter_id", "meter_type", "meter_number", "reading_value", "unit", "notes"),
    "photos": ("id", "position", "room_id", "defect_id", "meter_reading_id", "caption", "media_type", "sha256",
               "size_bytes"),
}


def now() -> datetime:
    """Naive UTC, as stored (a session time zone of PostgreSQL never shifts it)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _utc(value: datetime | None) -> datetime:
    """Comparable stamp: records of older code paths carry aware, new ones naive UTC times."""
    if value is None:
        return datetime.min
    return value.astimezone(timezone.utc).replace(tzinfo=None) if value.tzinfo else value


def _row(orm_obj: Any) -> dict:
    return {column.key: getattr(orm_obj, column.key) for column in orm_obj.__table__.columns}


def _not_found(what: str = "Übergabeprotokoll") -> HTTPException:
    return HTTPException(404, f"{what} nicht vorhanden.")


# ─── Reading and writing through one unit (SQL session or memory store) ──────

def _sort_key(item: Any) -> tuple:
    position = getattr(item, "position", None)
    return (position if position is not None else 1_000_000, item.id)


def _parts(unit: archive.Unit, kind: str, protocol_id: str) -> list:
    part = PARTS[kind]
    if unit.db is not None:
        rows = unit.db.scalars(select(part.orm).where(getattr(part.orm, part.column) == protocol_id))
        items = [part.model.model_validate(_row(row)) for row in rows]
    else:
        items = [item for item in getattr(unit.store, part.collection).values()
                 if getattr(item, part.column) == protocol_id]
    return sorted(items, key=_sort_key)


def _put(unit: archive.Unit, kind: str, item: Any) -> None:
    part = PARTS[kind]
    if unit.db is None:
        unit.insert(getattr(unit.store, part.collection), item.id, item)
        return
    row = unit.db.get(part.orm, item.id)
    values = item.model_dump()
    if row is None:
        unit.db.add(part.orm(**values))
        return
    for name, value in values.items():
        if getattr(row, name) != value:
            setattr(row, name, value)


def _remove(unit: archive.Unit, kind: str, item_id: str) -> None:
    part = PARTS[kind]
    if unit.db is None:
        unit.remove(getattr(unit.store, part.collection), item_id)
        return
    row = unit.db.get(part.orm, item_id)
    if row is not None:
        unit.db.delete(row)


def _flush(unit: archive.Unit) -> None:
    if unit.db is not None:
        unit.db.flush()


def _find_part(unit: archive.Unit, kind: str, item_id: str) -> Any | None:
    """A part with this id anywhere the account can see (not only in one protocol)."""
    part = PARTS[kind]
    if unit.db is not None:
        row = unit.db.get(part.orm, item_id)
        return part.model.model_validate(_row(row)) if row is not None else None
    collection = getattr(unit.store, part.collection)
    return collection[item_id] if item_id in collection else None


def _protocol(unit: archive.Unit, protocol_id: str) -> HandoverProtocol:
    try:
        return unit.store.get_handover_protocol(protocol_id)
    except NotFoundError:
        raise _not_found() from None


def _save_protocol(unit: archive.Unit, protocol: HandoverProtocol) -> None:
    if unit.db is None:
        unit.insert(unit.store.handover_protocols, protocol.id, protocol)
        return
    row = unit.db.get(HandoverProtocolORM, protocol.id)
    values = protocol.model_dump()
    if row is None:
        unit.db.add(HandoverProtocolORM(**values))
        return
    for name, value in values.items():
        if getattr(row, name) != value:
            setattr(row, name, value)


def _protocols_where(unit: archive.Unit, **criteria: str) -> list[HandoverProtocol]:
    if unit.db is not None:
        query = select(HandoverProtocolORM)
        for name, value in criteria.items():
            query = query.where(getattr(HandoverProtocolORM, name) == value)
        return [HandoverProtocol.model_validate(_row(row)) for row in unit.db.scalars(query)]
    return [item for item in unit.store.handover_protocols.values()
            if all(getattr(item, name) == value for name, value in criteria.items())]


def _unit_meters(unit: archive.Unit, unit_id: str) -> list[Meter]:
    if unit.db is not None:
        meters = [Meter.model_validate(_row(row))
                  for row in unit.db.scalars(select(MeterORM).where(MeterORM.unit_id == unit_id))]
    else:
        meters = [meter for meter in unit.store.meters.values() if meter.unit_id == unit_id]
    return sorted(meters, key=lambda meter: (meter.meter_type, meter.serial_number or "", meter.id))


def _readings_of(unit: archive.Unit, meter_ids: set[str]) -> dict[str, list[StandaloneMeterReading]]:
    found: dict[str, list[StandaloneMeterReading]] = {meter_id: [] for meter_id in meter_ids}
    if not meter_ids:
        return found
    if unit.db is not None:
        query = select(StandaloneMeterReadingORM).where(StandaloneMeterReadingORM.meter_id.in_(sorted(meter_ids)))
        readings = [StandaloneMeterReading.model_validate(_row(row)) for row in unit.db.scalars(query)]
    else:
        readings = [r for r in unit.store.standalone_meter_readings.values() if r.meter_id in meter_ids]
    for reading in readings:
        found[reading.meter_id].append(reading)
    return found


def _put_reading(unit: archive.Unit, reading: StandaloneMeterReading) -> None:
    if unit.db is None:
        unit.insert(unit.store.standalone_meter_readings, reading.id, reading)
        return
    row = unit.db.get(StandaloneMeterReadingORM, reading.id)
    if row is None:
        unit.db.add(StandaloneMeterReadingORM(**reading.model_dump()))
        return
    for name, value in reading.model_dump().items():
        if getattr(row, name) != value:
            setattr(row, name, value)


# ─── Contract, unit and the subject's revisions ──────────────────────────────

def _parents(unit: archive.Unit, contract_id: str, *, lock: bool = False, protocol_id: str | None = None):
    """The contract and its subject; with `lock` (SQL) locked in the archive's order and read again."""
    store = unit.store
    try:
        contract = store.get_contract(contract_id)
    except NotFoundError:
        raise _not_found("Vertrag") from None
    if lock and unit.db is not None:
        before = (contract.property_id, contract.unit_id, contract.tenant_id)
        rows = [(TenantORM, contract.tenant_id), (PropertyORM, contract.property_id), (UnitORM, contract.unit_id),
                (ContractORM, contract.id)]
        if protocol_id is not None:
            rows.append((HandoverProtocolORM, protocol_id))
        for model, key in rows:
            if unit.db.scalar(select(model.id).where(model.id == key).with_for_update()) is None:
                raise HTTPException(404, "Vertrag, Protokoll oder Zuordnung nicht mehr vorhanden.")
        unit.db.expire_all()
        contract = store.get_contract(contract_id)
        if before != (contract.property_id, contract.unit_id, contract.tenant_id):
            raise HTTPException(409, "Die Vertragszuordnung wurde während der Prüfung geändert.")
    prop = store.get_property(contract.property_id)
    location = store.get_unit(contract.unit_id)
    tenant = store.get_tenant(contract.tenant_id)
    portfolio = store.get_portfolio(prop.portfolio_id)
    if location.property_id != prop.id:
        raise HTTPException(503, "Einheit und Objekt des Vertrags passen nicht zusammen. Bestand prüfen.")
    return contract, prop, location, tenant, portfolio


def _source(contract, prop, location, tenant, portfolio) -> dict[str, Any]:
    return {
        "portfolio": {"id": portfolio.id, "name": portfolio.name, "owner_name": portfolio.owner_name},
        "property": {"id": prop.id, "portfolio_id": prop.portfolio_id, "name": prop.name,
                     "address_line": prop.address_line, "postal_code": prop.postal_code, "city": prop.city},
        "unit": {"id": location.id, "property_id": location.property_id, "label": location.label,
                 "floor": location.floor, "rooms": location.rooms},
        "contract": {"id": contract.id, "contract_number": contract.contract_number,
                     "property_id": contract.property_id, "unit_id": contract.unit_id,
                     "tenant_id": contract.tenant_id, "status": contract.status,
                     "start_date": contract.start_date.isoformat(),
                     "end_date": contract.end_date.isoformat() if contract.end_date else None},
        "tenant": {"id": tenant.id, "full_name": tenant.full_name},
        "etags": {"portfolio": etag("portfolios", portfolio.id, portfolio.updated_at),
                  "property": etag("properties", prop.id, prop.updated_at),
                  "unit": etag("units", location.id, location.updated_at),
                  "contract": etag("contracts", contract.id, contract.updated_at),
                  "tenant": etag("tenants", tenant.id, tenant.updated_at)},
    }


def revision(protocol: HandoverProtocol) -> str:
    return etag("handover_protocols", protocol.id, protocol.updated_at)


def _require_draft(protocol: HandoverProtocol) -> None:
    if protocol.finalized_at is not None:
        raise HTTPException(409, FINAL_MESSAGE)


def _boundary(protocol_type: str, contract) -> date | None:
    """The contract date the handover belongs to: start at move-in, end at move-out."""
    return contract.start_date if protocol_type == "move_in" else contract.end_date


def _in_service(meter: Meter, day: date) -> bool:
    if meter.installation_date and meter.installation_date > day:
        return False
    if meter.removal_date:
        return meter.removal_date >= day
    return meter.is_active is not False


def _meter_options(unit: archive.Unit, unit_id: str, day: date) -> list[dict[str, Any]]:
    meters = _unit_meters(unit, unit_id)
    readings = _readings_of(unit, {meter.id for meter in meters})
    options = []
    for meter in meters:
        before = [r for r in readings[meter.id] if r.reading_date <= day]
        last = max(before, key=lambda r: (r.reading_date, r.id), default=None)
        options.append({
            "id": meter.id, "meter_type": meter.meter_type, "serial_number": meter.serial_number,
            "measure_unit": meter.measure_unit or DEFAULT_UNITS.get(meter.meter_type), "location": meter.location,
            "installation_date": meter.installation_date.isoformat() if meter.installation_date else None,
            "removal_date": meter.removal_date.isoformat() if meter.removal_date else None,
            "in_service": _in_service(meter, day),
            "last_reading": {"reading_date": last.reading_date.isoformat(), "value": last.value} if last else None,
        })
    return options


# ─── Proposal for a new protocol ─────────────────────────────────────────────

def _superseded(protocols: list[HandoverProtocol]) -> set[str]:
    return {p.correction_of_id for p in protocols if p.correction_of_id and p.finalized_at is not None}


def _latest(protocols: list[HandoverProtocol]) -> HandoverProtocol | None:
    """The newest protocol in force: finalized ones first, a corrected one never."""
    superseded = _superseded(protocols)
    current = [p for p in protocols if p.id not in superseded]
    for candidates in ([p for p in current if p.finalized_at is not None], current):
        if candidates:
            return max(candidates, key=lambda p: (p.protocol_date, _utc(p.finalized_at or p.created_at), p.id))
    return None


def _default_rooms(location) -> list[str]:
    count = int(location.rooms or 0)
    if count < 1:
        return []
    return ["Flur", "Küche", "Bad", *(f"Zimmer {index}" for index in range(1, count + 1))]


def _suggestion(unit: archive.Unit, contract, location, tenant, portfolio, protocol_type: str) -> dict[str, Any]:
    protocols = _protocols_where(unit, unit_id=location.id)
    previous = _latest(protocols)
    if previous is not None:
        rooms = [{"name": room.name} for room in _parts(unit, "rooms", previous.id)]
        room_source = "previous_protocol" if rooms else "none"
    else:
        rooms, room_source = [], "none"
    if not rooms and _default_rooms(location):
        rooms, room_source = [{"name": name} for name in _default_rooms(location)], "unit_rooms"

    keys: list[dict[str, Any]] = []
    key_source = "none"
    move_in = None
    if protocol_type == "move_out":
        move_in = _latest([p for p in protocols if p.contract_id == contract.id and p.protocol_type == "move_in"])
    reference = move_in or previous
    if reference is not None:
        for key in _parts(unit, "keys", reference.id):
            count = key.handed_over
            if reference.protocol_type == "move_out" and key.returned is not None:
                count = key.returned       # what came back is what the next handover has
            keys.append({"key_type": key.key_type, "label": key.label, "handed_over": count, "returned": None})
        key_source = "move_in_protocol" if move_in is not None else "previous_protocol"
    day = _boundary(protocol_type, contract)
    return {
        "protocol_type": protocol_type,
        "protocol_date": day.isoformat() if day else None,
        "rooms": rooms, "room_source": room_source,
        "keys": keys, "key_source": key_source,
        "previous_protocol": {"id": previous.id, "protocol_type": previous.protocol_type,
                              "protocol_date": previous.protocol_date.isoformat(),
                              "finalized": previous.finalized_at is not None} if previous else None,
        "tenant_signature": tenant.full_name,
        "landlord_signature": portfolio.owner_name,
    }


def _summary(protocol: HandoverProtocol) -> dict[str, Any]:
    return {"id": protocol.id, "protocol_type": protocol.protocol_type,
            "protocol_date": protocol.protocol_date.isoformat(), "status": protocol.status,
            "finalized_at": protocol.finalized_at.isoformat() if protocol.finalized_at else None,
            "correction_of_id": protocol.correction_of_id, "document_id": protocol.document_id}


def _related(unit: archive.Unit, contract, location) -> dict[str, Any]:
    """The tenant change around this contract: the unit's previous and next contract."""
    contracts = [c for c in unit.store.list_contracts() if c.unit_id == location.id and c.id != contract.id]
    previous = max((c for c in contracts if c.start_date < contract.start_date), key=lambda c: c.start_date,
                   default=None)
    following = min((c for c in contracts if c.start_date > contract.start_date), key=lambda c: c.start_date,
                    default=None)

    def brief(other) -> dict | None:
        if other is None:
            return None
        return {"id": other.id, "contract_number": other.contract_number, "start_date": other.start_date.isoformat(),
                "end_date": other.end_date.isoformat() if other.end_date else None, "status": other.status}

    return {
        "previous_contract": brief(previous), "next_contract": brief(following),
        # the existing tenant-change document: the Wohnungsgeberbestätigung of the moving-in contract
        "housing_confirmation_contract_id": contract.id,
        # no letter templates for a tenant change exist in this application (see docs/HANDOVER_PROTOCOL_20261008.md)
        "templates": [],
    }


def source(store, contract_id: str, protocol_type: str, actor_id: str) -> dict[str, Any]:
    if protocol_type not in TYPE_LABELS:
        raise HTTPException(422, "Bitte Einzug oder Auszug wählen.")
    with archive.work(store, actor_id) as unit:
        contract, prop, location, tenant, portfolio = _parents(unit, contract_id)
        suggestion = _suggestion(unit, contract, location, tenant, portfolio, protocol_type)
        day = date.fromisoformat(suggestion["protocol_date"]) if suggestion["protocol_date"] else date.today()
        return {
            "contract_id": contract.id,
            "source": _source(contract, prop, location, tenant, portfolio),
            "suggestion": suggestion,
            "meters": _meter_options(unit, location.id, day),
            "protocols": [_summary(p) for p in sorted(_protocols_where(unit, contract_id=contract.id),
                                                      key=lambda p: (p.protocol_date, _utc(p.created_at)),
                                                      reverse=True)],
            "related": _related(unit, contract, location),
        }


# ─── Detail ──────────────────────────────────────────────────────────────────

def _content(unit: archive.Unit, protocol_id: str) -> dict[str, list]:
    return {kind: _parts(unit, kind, protocol_id) for kind in PARTS}


def _review_parts(protocol: HandoverProtocol, content: dict[str, list]) -> dict[str, Any]:
    parts = {kind: [item.model_dump(mode="json", include=set(REVIEW_FIELDS[kind])) for item in content[kind]]
             for kind in PARTS}
    header = protocol.model_dump(mode="json", include={
        "id", "protocol_type", "protocol_date", "tenant_present", "landlord_present", "overall_condition", "notes",
        "tenant_signature", "landlord_signature"})
    header["legacy"] = protocol.model_dump(mode="json", include={"key_count", "key_details", "damages", "photos"})
    return {"protocol": header, **parts}


def _validated_evidence(row) -> dict[str, Any]:
    archive.validate_manifest(row)
    try:
        evidence = validate_handover_snapshot(row, row.metadata_snapshot)
    except HandoverValidationError:
        raise HTTPException(503, "Das archivierte Übergabeprotokoll ist beschädigt.") from None
    if not evidence:
        raise HTTPException(404, "Kein Übergabeprotokoll.")
    return evidence


def _original(unit: archive.Unit, protocol: HandoverProtocol, content: dict[str, list]) -> dict[str, Any] | None:
    if protocol.document_id is None:
        return None
    row = archive.head(unit, protocol.document_id)
    if row is None:
        return {"document_id": protocol.document_id, "missing": True}
    evidence = _validated_evidence(row)
    current = _review_parts(protocol, content)
    review = evidence["review"]
    return {
        "document_id": row.document_id, "version_id": row.id, "pdf_sha256": row.sha256, "size_bytes": row.size_bytes,
        "created_at": row.created_at.replace(tzinfo=timezone.utc).isoformat(),
        "file_url": row.metadata_snapshot["file_url"],
        "download_url": f"/handover-protocols/{protocol.id}/document",
        # the rows still say what the archived original says (the triggers keep it so)
        "content_matches": all(review[name] == current[name] for name in current),
        "missing": False,
    }


def _detail(unit: archive.Unit, protocol: HandoverProtocol) -> dict[str, Any]:
    contract, prop, location, tenant, portfolio = _parents(unit, protocol.contract_id)
    content = _content(unit, protocol.id)
    successors = sorted(_protocols_where(unit, correction_of_id=protocol.id), key=lambda p: _utc(p.created_at))
    corrected = None
    if protocol.correction_of_id:
        try:
            corrected = _summary(unit.store.get_handover_protocol(protocol.correction_of_id))
        except NotFoundError:
            corrected = {"id": protocol.correction_of_id, "missing": True}
    finalized = protocol.finalized_at is not None
    return {
        "protocol": {**protocol.model_dump(mode="json"), "revision": revision(protocol)},
        "state": {"finalized": finalized, "editable": not finalized,
                  # an earlier version could set the status by hand: it is no archived original
                  "legacy_status_finalized": protocol.status == "finalized" and not finalized,
                  "superseded": any(p.finalized_at is not None for p in successors)},
        **{kind: [item.model_dump(mode="json") for item in content[kind]] for kind in PARTS},
        "source": _source(contract, prop, location, tenant, portfolio),
        "meters": _meter_options(unit, location.id, protocol.protocol_date),
        "original": _original(unit, protocol, content) if finalized else None,
        "correction_of": corrected,
        "corrections": [_summary(p) for p in successors],
        "related": _related(unit, contract, location),
        "problems": _problems(unit, protocol, content, contract)[0],
    }


def detail(store, protocol_id: str, actor_id: str) -> dict[str, Any]:
    with archive.work(store, actor_id) as unit:
        return _detail(unit, _protocol(unit, protocol_id))


# ─── Creating and editing a draft ────────────────────────────────────────────

def _new_protocol(contract, location, protocol_type: str, protocol_date: date, *, tenant_signature: str | None,
                  landlord_signature: str | None, correction_of_id: str | None = None) -> HandoverProtocol:
    stamp = now()
    return HandoverProtocol(id=archive_uuid(), contract_id=contract.id, unit_id=location.id,
                            protocol_type=protocol_type, protocol_date=protocol_date, tenant_signature=tenant_signature,
                            landlord_signature=landlord_signature, status="draft", correction_of_id=correction_of_id,
                            created_at=stamp, updated_at=stamp)


def archive_uuid() -> str:
    from uuid import uuid4

    return str(uuid4())


def create_from_contract(store, payload: CreateRequest, actor_id: str) -> dict[str, Any]:
    """A draft for the contract, prefilled from the unit's last protocol (or its room count); an open one is reused."""
    with archive.work(store, actor_id, write_areas=EDIT_AREAS) as unit:
        contract, prop, location, tenant, portfolio = _parents(unit, payload.contract_id, lock=True)
        open_drafts = [p for p in _protocols_where(unit, contract_id=contract.id)
                       if p.protocol_type == payload.protocol_type and p.finalized_at is None
                       and p.correction_of_id is None]
        if open_drafts:
            draft = max(open_drafts, key=lambda p: (_utc(p.created_at), p.id))
            return {"created": False, **_detail(unit, draft)}
        suggestion = _suggestion(unit, contract, location, tenant, portfolio, payload.protocol_type)
        day = payload.protocol_date or _boundary(payload.protocol_type, contract) or date.today()
        protocol = _new_protocol(contract, location, payload.protocol_type, day,
                                 tenant_signature=suggestion["tenant_signature"],
                                 landlord_signature=suggestion["landlord_signature"])
        _save_protocol(unit, protocol)
        _flush(unit)
        stamp = protocol.created_at
        for position, room in enumerate(suggestion["rooms"]):
            _put(unit, "rooms", HandoverRoom(id=archive_uuid(), protocol_id=protocol.id, position=position,
                                             name=room["name"], created_at=stamp, updated_at=stamp))
        for position, key in enumerate(suggestion["keys"]):
            _put(unit, "keys", HandoverKey(id=archive_uuid(), protocol_id=protocol.id, position=position,
                                           key_type=key["key_type"], label=key["label"],
                                           handed_over=key["handed_over"], created_at=stamp, updated_at=stamp))
        _flush(unit)
        return {"created": True, **_detail(unit, protocol)}


def _claim(unit: archive.Unit, kind: str, item_id: str, protocol_id: str, mine: dict[str, Any]) -> Any | None:
    """The existing part with this id, if it is this protocol's; an id of another protocol is refused."""
    if item_id in mine:
        return mine[item_id]
    other = _find_part(unit, kind, item_id)
    if other is not None:
        raise HTTPException(409, "Eine Zeile gehört bereits zu einem anderen Protokoll. Bitte neu laden.")
    return None


def save_content(store, protocol_id: str, payload: ContentRequest, actor_id: str) -> dict[str, Any]:
    """Replace the draft's header fields and parts with the payload, if the draft is still at base_revision."""
    with archive.work(store, actor_id, write_areas=EDIT_AREAS) as unit:
        protocol = _protocol(unit, protocol_id)
        _parents(unit, protocol.contract_id, lock=True, protocol_id=protocol.id)
        protocol = _protocol(unit, protocol_id)
        _require_draft(protocol)
        if revision(protocol) != payload.base_revision:
            raise HTTPException(409, "Das Protokoll wurde inzwischen geändert. Bitte neu laden; Ihre Eingaben "
                                     "bleiben im Formular.")
        meters = {meter.id: meter for meter in _unit_meters(unit, protocol.unit_id)}
        for reading in payload.meter_readings:
            if reading.meter_id is not None and reading.meter_id not in meters:
                raise HTTPException(409, "Ein Zähler gehört nicht zur Einheit dieses Protokolls.")
        stamp = now()
        current = {kind: {item.id: item for item in _parts(unit, kind, protocol.id)} for kind in PARTS}
        wanted = {"rooms": {r.id for r in payload.rooms}, "defects": {d.id for d in payload.defects},
                  "keys": {k.id for k in payload.keys}, "meter_readings": {m.id for m in payload.meter_readings}}

        # photos keep their protocol; links to rows that go away are dropped first
        for photo in current["photos"].values():
            links = {"room_id": photo.room_id not in wanted["rooms"] if photo.room_id else False,
                     "defect_id": photo.defect_id not in wanted["defects"] if photo.defect_id else False,
                     "meter_reading_id": (photo.meter_reading_id not in wanted["meter_readings"]
                                          if photo.meter_reading_id else False)}
            dropped = {name: None for name, gone in links.items() if gone}
            if dropped:
                _put(unit, "photos", photo.model_copy(update={**dropped, "updated_at": stamp}))
        _flush(unit)
        for kind in ("defects", "meter_readings", "keys", "rooms"):
            for item_id in set(current[kind]) - wanted[kind]:
                _remove(unit, kind, item_id)
            _flush(unit)

        def merged(kind: str, item_id: str, values: dict) -> Any:
            existing = _claim(unit, kind, item_id, protocol.id, current[kind])
            model = PARTS[kind].model
            if existing is None:
                return model(id=item_id, protocol_id=protocol.id, created_at=stamp, updated_at=stamp, **values)
            changed = {name: value for name, value in values.items() if getattr(existing, name) != value}
            return existing.model_copy(update={**changed, "updated_at": stamp}) if changed else None

        for position, room in enumerate(payload.rooms):
            item = merged("rooms", room.id, {"position": position, **room.model_dump(exclude={"id"})})
            if item is not None:
                _put(unit, "rooms", item)
        _flush(unit)
        for position, defect in enumerate(payload.defects):
            item = merged("defects", defect.id, {"position": position, **defect.model_dump(exclude={"id"})})
            if item is not None:
                _put(unit, "defects", item)
        for position, key in enumerate(payload.keys):
            item = merged("keys", key.id, {"position": position, **key.model_dump(exclude={"id"})})
            if item is not None:
                _put(unit, "keys", item)
        for position, reading in enumerate(payload.meter_readings):
            values = reading.model_dump(exclude={"id"})
            meter = meters.get(reading.meter_id or "")
            if meter is not None:     # the meter says what it measures
                values.update(meter_type=meter.meter_type, meter_number=meter.serial_number,
                              unit=meter.measure_unit or DEFAULT_UNITS.get(meter.meter_type) or reading.unit or "")
            values["unit"] = values.get("unit") or ""
            existing = _claim(unit, "meter_readings", reading.id, protocol.id, current["meter_readings"])
            if existing is None:
                _put(unit, "meter_readings", MeterReading(id=reading.id, handover_id=protocol.id, position=position,
                                                          created_at=stamp, updated_at=stamp, **values))
            else:
                changed = {name: value for name, value in {"position": position, **values}.items()
                           if getattr(existing, name) != value}
                if changed:
                    _put(unit, "meter_readings", existing.model_copy(update={**changed, "updated_at": stamp}))
        _flush(unit)
        header = payload.model_dump(include={"protocol_date", "tenant_present", "landlord_present",
                                             "overall_condition", "notes", "tenant_signature", "landlord_signature"})
        protocol = protocol.model_copy(update={**header, "updated_at": stamp})
        _save_protocol(unit, protocol)
        _flush(unit)
        return _detail(unit, protocol)


def follow_up(store, protocol_id: str, defect_id: str, payload: FollowUpRequest, actor_id: str) -> dict[str, Any]:
    """Record when a defect was resolved; allowed also after finalization (not part of the original)."""
    with archive.work(store, actor_id, write_areas=EDIT_AREAS) as unit:
        protocol = _protocol(unit, protocol_id)
        defect = next((d for d in _parts(unit, "defects", protocol.id) if d.id == defect_id), None)
        if defect is None:
            raise _not_found("Mangel")
        _put(unit, "defects", defect.model_copy(update={**payload.model_dump(), "updated_at": now()}))
        _flush(unit)
        return _detail(unit, protocol)


# ─── Photos ──────────────────────────────────────────────────────────────────

def _storage_key(file_url: str) -> str:
    from ..routers.files import _file_url_to_key

    return _file_url_to_key(file_url)


def _check_links(unit: archive.Unit, protocol_id: str, links: dict[str, str | None]) -> None:
    for name, kind in (("room_id", "rooms"), ("defect_id", "defects"), ("meter_reading_id", "meter_readings")):
        value = links.get(name)
        if value is not None and value not in {item.id for item in _parts(unit, kind, protocol_id)}:
            raise HTTPException(409, "Das Foto verweist auf eine Zeile, die (noch) nicht gespeichert ist. "
                                     "Bitte zuerst speichern.")


def add_photo(store, protocol_id: str, content: bytes, filename: str | None, content_type: str | None,
              links: dict[str, str | None], caption: str | None, actor_id: str) -> dict[str, Any]:
    """Store a photo as a protected upload of the protocol's portfolio and bind it to the draft."""
    from .file_storage import get_file_storage
    from .portfolio_scope import register_upload
    from .upload_policy import require_allowed_extension

    extension = require_allowed_extension(filename, PHOTO_EXTENSIONS)
    try:
        with PILImage.open(BytesIO(content)) as image:
            image.verify()
            media_type = PILImage.MIME.get(image.format or "", content_type or "application/octet-stream")
    except Exception:
        raise HTTPException(415, "Die Datei ist kein lesbares Foto (JPEG, PNG, WebP …).") from None
    caption = (caption or "").strip() or None
    with archive.work(store, actor_id) as unit:          # foreign or finalized: no file is written
        _require_draft(_protocol(unit, protocol_id))
    key = f"{PHOTO_PREFIX}{protocol_id}/{archive_uuid()}.{extension}"
    register_upload(key)       # a restricted account's file belongs to its portfolios until the row binds it
    storage = get_file_storage()
    storage.save(key, BytesIO(content), content_type=media_type)
    try:
        with archive.work(store, actor_id, write_areas=EDIT_AREAS) as unit:
            protocol = _protocol(unit, protocol_id)
            _parents(unit, protocol.contract_id, lock=True, protocol_id=protocol.id)
            _require_draft(_protocol(unit, protocol_id))
            _check_links(unit, protocol_id, links)
            photos = _parts(unit, "photos", protocol_id)
            if len(photos) >= MAX_PHOTOS:
                raise HTTPException(409, f"Ein Protokoll kann höchstens {MAX_PHOTOS} Fotos enthalten.")
            stamp = now()
            photo = HandoverPhoto(
                id=archive_uuid(), protocol_id=protocol_id, position=max((p.position for p in photos), default=-1) + 1,
                file_url=storage.get_url(key), caption=caption, media_type=media_type,
                sha256=hashlib.sha256(content).hexdigest(), size_bytes=len(content), uploaded_by=actor_id,
                created_at=stamp, updated_at=stamp, **links)
            _put(unit, "photos", photo)
            _flush(unit)
            return photo.model_dump(mode="json")
    except BaseException:
        storage.delete(key)
        raise


def patch_photo(store, protocol_id: str, photo_id: str, payload: PhotoPatch, actor_id: str) -> dict[str, Any]:
    with archive.work(store, actor_id, write_areas=EDIT_AREAS) as unit:
        protocol = _protocol(unit, protocol_id)
        _require_draft(protocol)
        photo = next((p for p in _parts(unit, "photos", protocol_id) if p.id == photo_id), None)
        if photo is None:
            raise _not_found("Foto")
        changes = payload.model_dump(exclude_unset=True)
        _check_links(unit, protocol_id, changes)
        photo = photo.model_copy(update={**changes, "updated_at": now()})
        _put(unit, "photos", photo)
        _flush(unit)
        return photo.model_dump(mode="json")


def forget_files(store, file_urls: set[str]) -> None:
    """Delete stored photo files no protocol refers to any more (best effort, after the commit)."""
    from .file_storage import get_file_storage

    if not file_urls:
        return
    if hasattr(store, "db"):
        used = set(store.db.scalars(select(HandoverPhotoORM.file_url).where(HandoverPhotoORM.file_url.in_(file_urls))))
    else:
        raw = object.__getattribute__(store, "__dict__")["handover_photos"]
        used = {photo.file_url for photo in raw.values() if photo.file_url in file_urls}
    for url in file_urls - used:
        try:
            get_file_storage().delete(_storage_key(url))
        except Exception:
            logger.warning("Handover photo file could not be deleted: %s", url)


def delete_photo(store, protocol_id: str, photo_id: str, actor_id: str) -> None:
    with archive.work(store, actor_id, write_areas=EDIT_AREAS) as unit:
        protocol = _protocol(unit, protocol_id)
        _require_draft(protocol)
        photo = next((p for p in _parts(unit, "photos", protocol_id) if p.id == photo_id), None)
        if photo is None:
            raise _not_found("Foto")
        _remove(unit, "photos", photo_id)
        _flush(unit)
    forget_files(store, {photo.file_url})


def delete_protocol(store, protocol_id: str, actor_id: str) -> None:
    """Delete a draft with its parts (and photo files no other protocol uses); a finalized one stays."""
    with archive.work(store, actor_id, write_areas=EDIT_AREAS) as unit:
        protocol = _protocol(unit, protocol_id)
        _parents(unit, protocol.contract_id, lock=True, protocol_id=protocol.id)
        _require_draft(_protocol(unit, protocol_id))
        files = {photo.file_url for photo in _parts(unit, "photos", protocol_id)}
        if unit.db is not None:
            unit.db.delete(unit.db.get(HandoverProtocolORM, protocol_id))   # parts follow (ON DELETE CASCADE)
        else:
            for kind in ("photos", "defects", "meter_readings", "keys", "rooms"):
                for item in _parts(unit, kind, protocol_id):
                    _remove(unit, kind, item.id)
            unit.remove(unit.store.handover_protocols, protocol_id)
        _flush(unit)
    forget_files(store, files)


# ─── Review: completeness, meter readings, PDF ───────────────────────────────

def _problem(code: str, message: str, *, blocking: bool = True) -> dict[str, Any]:
    return {"code": code, "message": message, "blocking": blocking}


def _predecessor_links(unit: archive.Unit, protocol: HandoverProtocol) -> dict[str, str]:
    """meter id -> reading id the corrected protocol recorded (a correction takes them over)."""
    if not protocol.correction_of_id:
        return {}
    return {reading.meter_id: reading.standalone_reading_id
            for reading in _parts(unit, "meter_readings", protocol.correction_of_id)
            if reading.meter_id and reading.standalone_reading_id}


def _meter_plan(unit: archive.Unit, protocol: HandoverProtocol, content: dict[str, list], contract
                ) -> tuple[list[tuple[str, MeterReading, StandaloneMeterReading]], list[dict]]:
    """What the finalization does with each meter reading: attach an existing reading, update the one the
    corrected protocol recorded, or create one. Conflicts are problems, nothing is written here."""
    readings = [r for r in content["meter_readings"] if r.meter_id]
    inherited = _predecessor_links(unit, protocol)
    existing = _readings_of(unit, {r.meter_id for r in readings} | set(inherited))
    by_id = {reading.id: reading for group in existing.values() for reading in group}
    day = protocol.protocol_date
    note = f"Übergabeprotokoll {TYPE_LABELS[protocol.protocol_type]} {contract.contract_number}"
    plan: list[tuple[str, MeterReading, StandaloneMeterReading]] = []
    problems = []
    for reading in readings:
        meter_id = reading.meter_id
        assert meter_id is not None
        same_day = [r for r in existing.get(meter_id, []) if r.reading_date == day]
        taken = by_id.get(inherited.get(meter_id, ""))
        if taken is not None:
            others = [r for r in same_day if r.id != taken.id]
            if others:
                problems.append(_problem("METER_READING_CONFLICT", f"Zähler {reading.meter_number or meter_id[:8]}: "
                                         f"am {day:%d.%m.%Y} gibt es bereits eine andere Ablesung."))
                continue
            plan.append(("update", reading, taken.model_copy(update={
                "reading_date": day, "value": reading.reading_value, "notes": note, "updated_at": now()})))
            continue
        if same_day:
            match = next((r for r in same_day if float(r.value) == float(reading.reading_value)), None)
            if match is None:
                values = ", ".join(sorted({str(r.value) for r in same_day}))
                problems.append(_problem("METER_READING_CONFLICT", f"Zähler {reading.meter_number or meter_id[:8]}: "
                                         f"am {day:%d.%m.%Y} ist bereits der Stand {values} erfasst. Bitte den "
                                         "Stand prüfen oder die vorhandene Ablesung unter Zähler korrigieren."))
                continue
            plan.append(("attach", reading, match))
            continue
        photo = next((p for p in content["photos"] if p.meter_reading_id == reading.id), None)
        stamp = now()
        plan.append(("create", reading, StandaloneMeterReading(
            id=archive_uuid(), meter_id=meter_id, reading_date=day, value=reading.reading_value,
            recorded_by=None, photo_url=photo.file_url if photo else None, notes=note,
            created_at=stamp, updated_at=stamp)))
    read = {r.meter_id for r in readings}
    for meter_id in sorted(set(inherited) - read):
        problems.append(_problem("CORRECTION_DROPS_METER", "Die Korrektur enthält keinen Stand für einen Zähler, den "
                                 "das korrigierte Protokoll erfasst hat. Bitte den Stand (korrigiert) wieder "
                                 "eintragen."))
    return plan, problems


def _problems(unit: archive.Unit, protocol: HandoverProtocol, content: dict[str, list], contract
              ) -> tuple[list[dict], list]:
    problems = []
    if not content["rooms"]:
        problems.append(_problem("NO_ROOMS", "Mindestens einen Raum erfassen."))
    if not (protocol.landlord_signature or "").strip():
        problems.append(_problem("LANDLORD_SIGNER_MISSING", "Name der Person, die für den Vermieter unterschreibt, "
                                                            "fehlt."))
    if protocol.tenant_present and not (protocol.tenant_signature or "").strip():
        problems.append(_problem("TENANT_SIGNER_MISSING", "Name des unterschreibenden Mieters fehlt."))
    if protocol.protocol_type == "move_out" and any(key.returned is None for key in content["keys"]):
        problems.append(_problem("KEYS_RETURN_MISSING", "Für jeden Schlüssel die zurückgegebene Anzahl eintragen."))
    if any(room.condition is None for room in content["rooms"]):
        problems.append(_problem("ROOM_NOT_ASSESSED", "Nicht jeder Raum hat einen Zustand.", blocking=False))
    if protocol.protocol_type == "move_out" and any(
            key.returned is not None and key.returned < key.handed_over for key in content["keys"]):
        problems.append(_problem("KEYS_MISSING", "Es fehlen Schlüssel; das Protokoll weist die Differenz aus.",
                                 blocking=False))
    boundary = _boundary(protocol.protocol_type, contract)
    if boundary is None:
        problems.append(_problem("CONTRACT_END_MISSING", "Der Vertrag hat kein Enddatum. Für die Abrechnung bitte "
                                 "das Auszugsdatum am Vertrag eintragen.", blocking=False))
    elif abs((protocol.protocol_date - boundary).days) > READING_TOLERANCE_DAYS:
        problems.append(_problem("DATE_FAR_FROM_CONTRACT",
                                 f"Die Übergabe liegt mehr als {READING_TOLERANCE_DAYS} Tage vom Vertragsdatum "
                                 f"({boundary:%d.%m.%Y}) entfernt; die Nebenkostenabrechnung nutzt die Zählerstände "
                                 "dann nicht als Stand zum Mieterwechsel.", blocking=False))
    meters = [m for m in _unit_meters(unit, protocol.unit_id) if _in_service(m, protocol.protocol_date)]
    read = {r.meter_id for r in content["meter_readings"] if r.meter_id}
    unread = [m for m in meters if m.id not in read]
    if unread:
        names = ", ".join(m.serial_number or m.meter_type for m in unread)
        problems.append(_problem("METER_NOT_READ", f"Ohne Stand: {names}. Die Abrechnung teilt den Verbrauch dann "
                                 "nach Tagen.", blocking=False))
    plan, meter_problems = _meter_plan(unit, protocol, content, contract)
    return problems + meter_problems, plan


def _correction_reference(unit: archive.Unit, protocol: HandoverProtocol) -> dict[str, Any] | None:
    if not protocol.correction_of_id:
        return None
    original = _protocol(unit, protocol.correction_of_id)
    if original.finalized_at is None or original.document_id is None:
        raise HTTPException(409, "Das korrigierte Protokoll ist nicht abgeschlossen.")
    row = archive.head(unit, original.document_id)
    if row is None:
        raise HTTPException(503, "Das korrigierte Protokoll hat kein archiviertes Original.")
    _, binding = archive.bind_document(unit, original.document_id)
    row = archive.authorized_version(unit, original.document_id, row.id, binding)
    _validated_evidence(row)
    for _ in archive.verified_blocks(unit, row):
        pass
    return {"protocol_id": original.id, "document_id": original.document_id, "version_id": row.id,
            "pdf_sha256": row.sha256, "protocol_date": original.protocol_date.isoformat()}


def _photo_images(content: dict[str, list]) -> dict[str, bytes]:
    from .file_storage import get_file_storage

    storage = get_file_storage()
    images = {}
    for number, photo in enumerate(content["photos"], 1):
        data = storage.get(_storage_key(photo.file_url))
        if data is None:
            raise HTTPException(409, f"Foto {number} ist im Speicher nicht mehr vorhanden.")
        if hashlib.sha256(data).hexdigest() != photo.sha256:
            raise HTTPException(409, f"Foto {number} wurde nach dem Hochladen verändert.")
        images[photo.id] = pdf_photo(data)
    return images


def _review(unit: archive.Unit, protocol: HandoverProtocol):
    contract, prop, location, tenant, portfolio = _parents(unit, protocol.contract_id)
    content = _content(unit, protocol.id)
    problems, plan = _problems(unit, protocol, content, contract)
    base = {"format_version": PDF_FORMAT_VERSION, **_review_parts(protocol, content),
            "source": _source(contract, prop, location, tenant, portfolio),
            "correction_of": _correction_reference(unit, protocol)}
    pdf = render_pdf(base, _photo_images(content))
    review = {**base, "pdf_sha256": hashlib.sha256(pdf).hexdigest()}
    return review, digest(review), pdf, problems, plan, (contract, prop, location, tenant, portfolio)


def preview(store, protocol_id: str, actor_id: str) -> dict[str, Any]:
    with archive.work(store, actor_id) as unit:
        protocol = _protocol(unit, protocol_id)
        _require_draft(protocol)
        review, review_hash, pdf, problems, _, _ = _review(unit, protocol)
        return {"review_hash": review_hash, "pdf_sha256": review["pdf_sha256"], "size_bytes": len(pdf),
                "revision": revision(protocol), "problems": problems,
                "ready": not any(problem["blocking"] for problem in problems),
                "counts": {kind: len(review[kind]) for kind in PARTS}}


def preview_pdf(store, protocol_id: str, actor_id: str) -> tuple[bytes, str, str]:
    with archive.work(store, actor_id) as unit:
        protocol = _protocol(unit, protocol_id)
        _require_draft(protocol)
        review, review_hash, pdf, _, _, _ = _review(unit, protocol)
        return pdf, review["pdf_sha256"], review_hash


# ─── Finalization ────────────────────────────────────────────────────────────

def _replay(unit: archive.Unit, protocol: HandoverProtocol, document: Document, request_hash: str) -> dict[str, Any]:
    """The same command again (e.g. after a lost answer): the stored original, checked; never a second one."""
    if (document.contract_id != protocol.contract_id or document.document_type != DOC_TYPE
            or document.file_url != f"/uploads/{VIRTUAL_PREFIX}{document.id}.pdf"):
        raise HTTPException(409, "Die Vorgangsreferenz gehört bereits zu einem anderen Dokument.")
    row = archive.head(unit, document.id)
    if row is None:
        raise HTTPException(503, "Das gespeicherte Protokoll hat kein archiviertes Original.")
    evidence = _validated_evidence(row)
    if (row.request_sha256 != request_hash or row.actor_id != unit.actor_id
            or evidence["protocol_id"] != protocol.id or protocol.document_id != document.id):
        raise HTTPException(409, "Die Vorgangsreferenz wurde bereits mit anderen Eingaben verwendet.")
    _, binding = archive.bind_document(unit, document.id)
    archive.authorized_version(unit, document.id, row.id, binding)
    for _ in archive.verified_blocks(unit, row):
        pass
    return _detail(unit, protocol)


def finalize(store, protocol_id: str, payload: FinalizeRequest, actor_id: str) -> dict[str, Any]:
    request_hash = finalize_request_hash(protocol_id, payload.model_dump(mode="json"))
    document_id = document_id_for(actor_id, payload.idempotency_key)
    with archive.work(store, actor_id, write_areas=FINALIZE_AREAS) as unit:
        protocol = _protocol(unit, protocol_id)
        # locks first: a parallel request with the same key then finds this one's document
        _parents(unit, protocol.contract_id, lock=True, protocol_id=protocol.id)
        protocol = _protocol(unit, protocol_id)
        try:
            existing = unit.store.get_document(document_id)
        except NotFoundError:
            existing = None
        if existing is not None:
            return _replay(unit, protocol, existing, request_hash)
        _require_draft(protocol)
        review, review_hash, pdf, problems, plan, parents = _review(unit, protocol)
        contract, prop, location, tenant, portfolio = parents
        blocking = [problem["message"] for problem in problems if problem["blocking"]]
        if blocking:
            raise HTTPException(409, "Das Protokoll ist noch nicht vollständig: " + " ".join(blocking))
        if review_hash != payload.review_hash:
            raise HTTPException(409, "Das Protokoll stimmt nicht mehr mit der geprüften Vorschau überein. "
                                     "Bitte die Vorschau neu prüfen.")

        # 1. meter readings for the billing, linked from the protocol's readings
        recorded_by = (unit.user.get("full_name") or unit.user.get("username") or "")[:100] or None
        for action, reading, standalone in plan:
            if action != "attach":
                _put_reading(unit, standalone.model_copy(update={"recorded_by": recorded_by}))
        _flush(unit)
        for _, reading, standalone in plan:
            _put(unit, "meter_readings", reading.model_copy(update={"standalone_reading_id": standalone.id}))
        _flush(unit)

        # 2. the document and its immutable original, in this transaction
        stamp = archive.now()
        kind = TYPE_LABELS[protocol.protocol_type]
        values = {
            "id": document_id,
            **DocumentCreate(
                property_id=prop.id, unit_id=location.id, contract_id=contract.id,
                title=f"Übergabeprotokoll {kind} – {contract.contract_number} – {protocol.protocol_date:%d.%m.%Y}",
                document_type=DOC_TYPE, document_date=protocol.protocol_date, tags="uebergabeprotokoll",
                description=("Korrektur eines Übergabeprotokolls" if protocol.correction_of_id
                             else f"Abgeschlossenes Übergabeprotokoll ({kind})"),
                file_url=f"/uploads/{VIRTUAL_PREFIX}{document_id}.pdf",
            ).model_dump(),
            "ai_document_type": None, "ai_summary": None, "ai_entities_json": None, "ai_confidence": None,
            "ai_model": None, "ai_analyzed_at": None, "created_at": stamp, "updated_at": stamp,
        }
        document = Document.model_validate(values)
        if unit.db is not None:
            # inside this transaction: the store's create_document() would commit on its own
            unit.db.execute(insert(DocumentORM), values)
        else:
            # the virtual file is served from the archive: no upload grant to check
            unit.insert(object.__getattribute__(unit.store, "__dict__")["documents"], document.id, document)
        binding = {"portfolio_id": prop.portfolio_id, "property_id": prop.id, "unit_id": location.id,
                   "contract_id": contract.id, "tenant_id": tenant.id}
        extension = {
            "schema_version": SCHEMA_VERSION, "review": review, "review_hash": review_hash,
            "request_sha256": request_hash, "actor_id": actor_id, "idempotency_key": payload.idempotency_key,
            "protocol_id": protocol.id, "confirmed_content": True, "confirmed_signatures": True,
        }
        row = archive.publish_generated_original(unit, document, binding, pdf, request_hash,
                                                 version_id=archive_uuid(),
                                                 metadata_extra={"handover_protocol": extension})
        _validated_evidence(row)

        # 3. finalized last: from here on the triggers keep the protocol and its parts as they are
        final = now()
        protocol = protocol.model_copy(update={"status": "finalized", "finalized_at": final, "finalized_by": actor_id,
                                               "document_id": document_id, "updated_at": final})
        _save_protocol(unit, protocol)
        _flush(unit)
        return _detail(unit, protocol)


# ─── Corrections ─────────────────────────────────────────────────────────────

def start_correction(store, protocol_id: str, actor_id: str) -> dict[str, Any]:
    """A draft copying the finalized protocol and naming it; an open correction draft is reused."""
    with archive.work(store, actor_id, write_areas=EDIT_AREAS) as unit:
        original = _protocol(unit, protocol_id)
        _parents(unit, original.contract_id, lock=True, protocol_id=original.id)
        original = _protocol(unit, protocol_id)
        if original.finalized_at is None:
            raise HTTPException(409, "Nur ein abgeschlossenes Protokoll wird korrigiert; einen Entwurf bitte direkt "
                                     "bearbeiten.")
        successors = _protocols_where(unit, correction_of_id=original.id)
        draft = next((p for p in successors if p.finalized_at is None), None)
        if draft is not None:
            return {"created": False, **_detail(unit, draft)}
        if successors:
            raise HTTPException(409, "Dieses Protokoll wurde bereits korrigiert. Bitte die neueste Fassung korrigieren.")
        stamp = now()
        copy = original.model_copy(update={"id": archive_uuid(), "status": "draft", "correction_of_id": original.id,
                                           "document_id": None, "finalized_at": None, "finalized_by": None,
                                           "created_at": stamp, "updated_at": stamp})
        _save_protocol(unit, copy)
        _flush(unit)
        content = _content(unit, original.id)
        renamed: dict[str, str] = {}

        def clone(item: Any, **links: Any) -> Any:
            renamed[item.id] = archive_uuid()
            return item.model_copy(update={"id": renamed[item.id], "created_at": stamp, "updated_at": stamp, **links})

        for room in content["rooms"]:
            _put(unit, "rooms", clone(room, protocol_id=copy.id))
        _flush(unit)
        for defect in content["defects"]:
            _put(unit, "defects", clone(defect, protocol_id=copy.id, room_id=renamed.get(defect.room_id or "")))
        for key in content["keys"]:
            _put(unit, "keys", clone(key, protocol_id=copy.id))
        for reading in content["meter_readings"]:
            _put(unit, "meter_readings", clone(reading, handover_id=copy.id, standalone_reading_id=None))
        _flush(unit)
        for photo in content["photos"]:      # the same files: deleting the copy's row keeps the original's file
            _put(unit, "photos", clone(photo, protocol_id=copy.id, room_id=renamed.get(photo.room_id or ""),
                                       defect_id=renamed.get(photo.defect_id or ""),
                                       meter_reading_id=renamed.get(photo.meter_reading_id or "")))
        _flush(unit)
        return {"created": True, **_detail(unit, copy)}


# ─── Reading the archived original ───────────────────────────────────────────

def _verified(unit: archive.Unit, document: Document) -> tuple[bytes, Any]:
    row = archive.head(unit, document.id)
    if row is None:
        raise HTTPException(404, "Das Protokoll hat kein archiviertes Original.")
    _, binding = archive.bind_document(unit, document.id)
    row = archive.authorized_version(unit, document.id, row.id, binding)
    _validated_evidence(row)
    return archive.original_bytes(unit, row), row


def read_original(store, protocol_id: str, actor_id: str) -> tuple[bytes, Any]:
    with archive.work(store, actor_id) as unit:
        protocol = _protocol(unit, protocol_id)
        if protocol.document_id is None:
            raise HTTPException(404, "Das Protokoll ist noch nicht abgeschlossen.")
        try:
            document = unit.store.get_document(protocol.document_id)
        except NotFoundError:
            raise _not_found("Dokument") from None
        return _verified(unit, document)


def read_pdf_for_key(store, key: str, actor_id: str) -> bytes | None:
    """/uploads/handover-protocols/<id>.pdf: always the verified original, never a file on disk."""
    if not key.startswith(VIRTUAL_PREFIX) or not key.endswith(".pdf"):
        return None
    identifier = key[len(VIRTUAL_PREFIX):-4]
    from uuid import UUID

    try:
        if str(UUID(identifier)) != identifier:
            raise ValueError
    except ValueError:
        raise HTTPException(404, "Protokoll nicht vorhanden.") from None
    with archive.work(store, actor_id) as unit:
        try:
            document = unit.store.get_document(identifier)
        except NotFoundError:
            raise HTTPException(404, "Protokoll nicht vorhanden.") from None
        if document.file_url != f"/uploads/{key}" or document.document_type != DOC_TYPE:
            raise HTTPException(404, "Protokoll nicht vorhanden.")
        return _verified(unit, document)[0]


# ─── Data subject access (DSGVO) ─────────────────────────────────────────────

def parts_of(store, protocol_ids: set[str]) -> dict[str, list]:
    """Rooms, defects, keys, meter readings and photos of the protocols, for the data access export."""
    found: dict[str, list] = {}
    for kind, part in PARTS.items():
        column = getattr(part.orm, part.column)
        if hasattr(store, "db"):
            rows = store.db.scalars(select(part.orm).where(column.in_(sorted(protocol_ids)))) if protocol_ids else []
            items = [part.model.model_validate(_row(row)) for row in rows]
        else:
            items = [item for item in getattr(store, part.collection).values()
                     if getattr(item, part.column) in protocol_ids]
        found[f"handover_{kind}"] = sorted(items, key=lambda item: (getattr(item, part.column), *_sort_key(item)))
    return found
