"""Handover protocols (T16): the structured protocol with rooms, defects, keys, meter readings and
photos, its review and finalization into an immutable original, corrections; plus the older plain
record endpoints, which refuse to touch a finalized protocol (services/handover_protocol.py).
"""

from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Response, UploadFile, status
from sqlalchemy.exc import IntegrityError
from starlette.concurrency import run_in_threadpool

from ..auth import require_auth
from ..dependencies import store
from ..models import (
    HandoverProtocol,
    HandoverProtocolCreate,
    HandoverProtocolPatch,
    MeterReading,
    MeterReadingCreate,
    MeterReadingPatch,
    UserRead,
)
from ..services import handover_protocol as service
from ..services.handover_protocol_types import (
    ContentRequest,
    CreateRequest,
    FinalizeRequest,
    FollowUpRequest,
    PhotoPatch,
)
from ..services.upload_policy import read_limited
from ..storage import NotFoundError, ValidationError

router = APIRouter(prefix="/handover-protocols", tags=["Übergabeprotokolle"])
Actor = Annotated[UserRead, Depends(require_auth)]
_PRIVATE = {"Cache-Control": "private, no-store", "X-Content-Type-Options": "nosniff"}
_FINALIZE_ONLY = ("Abgeschlossen wird ein Protokoll nur über „Abschließen“: dabei entsteht das unveränderliche "
                  "PDF-Original.")


def _call(operation, *args, **kwargs):
    try:
        return operation(*args, **kwargs)
    except NotFoundError:
        raise HTTPException(404, "Übergabeprotokoll oder Zuordnung nicht vorhanden.") from None
    except ValidationError as error:
        raise HTTPException(409, str(error)) from None
    except IntegrityError:
        raise HTTPException(409, "Der Bestand wurde gleichzeitig geändert. Bitte den aktuellen Stand neu "
                                 "laden.") from None


def _editable(protocol_id: str) -> HandoverProtocol:
    """The protocol, if it may still change (the plain record endpoints)."""
    protocol = store.get_handover_protocol(protocol_id)
    if protocol.finalized_at is not None:
        raise HTTPException(status_code=409, detail=service.FINAL_MESSAGE)
    return protocol


def _check_record(contract_id: str, unit_id: str, status_value: str | None) -> None:
    if status_value == "finalized":
        raise HTTPException(status_code=409, detail=_FINALIZE_ONLY)
    try:
        contract = store.get_contract(contract_id)
    except NotFoundError:
        return               # the store answers "Vertrag nicht gefunden"
    if contract.unit_id != unit_id:
        raise HTTPException(status_code=400, detail="Die Einheit gehört nicht zu diesem Vertrag.")


def _check_meter(protocol: HandoverProtocol, meter_id: str | None) -> None:
    if meter_id is None:
        return
    try:
        meter = store.get_meter(meter_id)
    except NotFoundError:
        raise HTTPException(status_code=400, detail="Zähler nicht gefunden") from None
    if meter.unit_id != protocol.unit_id:
        raise HTTPException(status_code=400, detail="Der Zähler gehört nicht zur Einheit dieses Protokolls.")


# --- Structured protocol (static paths before /{protocol_id}) ---

@router.get("/source")
def protocol_source(actor: Actor, contract_id: str = Query(..., max_length=100),
                    protocol_type: str = Query(..., pattern="^(move_in|move_out)$")):
    """Proposal for a new protocol of the contract: rooms, keys, meters, date, the tenant change around it."""
    return _call(service.source, store, contract_id, protocol_type, actor.id)


@router.post("/from-contract")
def create_from_contract(payload: CreateRequest, actor: Actor):
    """Create the prefilled draft (or return the open draft of this contract and kind)."""
    return _call(service.create_from_contract, store, payload, actor.id)


# --- Handover Protocols ---

@router.get("", response_model=list[HandoverProtocol])
def list_handover_protocols(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    contract_id: str | None = Query(None),
    unit_id: str | None = Query(None),
    protocol_type: str | None = Query(None),
):
    results = store.list_handover_protocols()
    if contract_id:
        results = [r for r in results if r.contract_id == contract_id]
    if unit_id:
        results = [r for r in results if r.unit_id == unit_id]
    if protocol_type:
        results = [r for r in results if r.protocol_type == protocol_type]
    return results[skip: skip + limit]


@router.post("", response_model=HandoverProtocol, status_code=status.HTTP_201_CREATED)
def create_handover_protocol(payload: HandoverProtocolCreate):
    _check_record(payload.contract_id, payload.unit_id, payload.status)
    try:
        return store.create_handover_protocol(payload)
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/meter-readings", response_model=list[MeterReading])
def list_all_meter_readings(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    handover_id: str | None = Query(None),
    meter_type: str | None = Query(None),
):
    results = store.list_meter_readings()
    if handover_id:
        results = [r for r in results if r.handover_id == handover_id]
    if meter_type:
        results = [r for r in results if r.meter_type == meter_type]
    return results[skip: skip + limit]


@router.get("/{protocol_id}", response_model=HandoverProtocol)
def get_handover_protocol(protocol_id: str):
    try:
        return store.get_handover_protocol(protocol_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.put("/{protocol_id}", response_model=HandoverProtocol)
def update_handover_protocol(protocol_id: str, payload: HandoverProtocolCreate):
    try:
        _editable(protocol_id)
        _check_record(payload.contract_id, payload.unit_id, payload.status)
        return store.update_handover_protocol(protocol_id, payload)
    except (NotFoundError, ValidationError) as exc:
        code = 404 if isinstance(exc, NotFoundError) else 400
        raise HTTPException(status_code=code, detail=str(exc)) from exc


@router.patch("/{protocol_id}", response_model=HandoverProtocol)
def patch_handover_protocol(protocol_id: str, payload: HandoverProtocolPatch):
    try:
        current = _editable(protocol_id)
        changes = payload.model_dump(exclude_unset=True)
        _check_record(changes.get("contract_id", current.contract_id), changes.get("unit_id", current.unit_id),
                      changes.get("status"))
        return store._patch_entity("handover_protocol", protocol_id, payload)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/{protocol_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_handover_protocol(protocol_id: str):
    """Delete a draft with its parts and the photo files no other protocol uses; a finalized one stays."""
    try:
        _editable(protocol_id)
        files = {photo.file_url for photo in service.parts_of(store, {protocol_id})["handover_photos"]}
        store.delete_handover_protocol(protocol_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    service.forget_files(store, files)


@router.get("/{protocol_id}/detail")
def protocol_detail(protocol_id: str, actor: Actor):
    """The protocol with its parts, the unit's meters, the original (once finalized) and its corrections."""
    return _call(service.detail, store, protocol_id, actor.id)


@router.put("/{protocol_id}/content")
def save_content(protocol_id: str, payload: ContentRequest, actor: Actor):
    """Save the whole draft (header, rooms, defects, keys, meter readings) against its revision."""
    return _call(service.save_content, store, protocol_id, payload, actor.id)


@router.post("/{protocol_id}/photos", status_code=status.HTTP_201_CREATED)
async def upload_photo(protocol_id: str, actor: Actor, file: UploadFile = File(...),
                       caption: str | None = Form(None, max_length=500), room_id: str | None = Form(None),
                       defect_id: str | None = Form(None), meter_reading_id: str | None = Form(None)):
    """A photo of the draft (optionally of a room, defect or meter reading), stored as a protected upload."""
    content = await read_limited(file)
    links = {"room_id": room_id or None, "defect_id": defect_id or None, "meter_reading_id": meter_reading_id or None}
    # file and database work stay off the event loop
    return await run_in_threadpool(_call, service.add_photo, store, protocol_id, content, file.filename,
                                   file.content_type, links, caption, actor.id)


@router.patch("/{protocol_id}/photos/{photo_id}")
def patch_photo(protocol_id: str, photo_id: str, payload: PhotoPatch, actor: Actor):
    return _call(service.patch_photo, store, protocol_id, photo_id, payload, actor.id)


@router.delete("/{protocol_id}/photos/{photo_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_photo(protocol_id: str, photo_id: str, actor: Actor) -> None:
    _call(service.delete_photo, store, protocol_id, photo_id, actor.id)


@router.patch("/{protocol_id}/defects/{defect_id}/follow-up")
def defect_follow_up(protocol_id: str, defect_id: str, payload: FollowUpRequest, actor: Actor):
    """When a defect was resolved: editable also after finalization (not part of the original)."""
    return _call(service.follow_up, store, protocol_id, defect_id, payload, actor.id)


@router.post("/{protocol_id}/preview")
def preview(protocol_id: str, actor: Actor):
    """Review hash and remaining problems of the draft as it would be finalized now."""
    return _call(service.preview, store, protocol_id, actor.id)


@router.post("/{protocol_id}/preview-pdf")
def preview_pdf(protocol_id: str, actor: Actor):
    content, sha256, review_hash = _call(service.preview_pdf, store, protocol_id, actor.id)
    return Response(content, media_type="application/pdf",
                    headers={**_PRIVATE, "X-Content-SHA256": sha256, "X-Review-SHA256": review_hash})


@router.post("/{protocol_id}/finalize")
def finalize(protocol_id: str, payload: FinalizeRequest, actor: Actor):
    """Archive the reviewed PDF as an immutable original, record the meter readings, lock the protocol."""
    return _call(service.finalize, store, protocol_id, payload, actor.id)


@router.post("/{protocol_id}/corrections")
def start_correction(protocol_id: str, actor: Actor):
    """A correction draft of the finalized protocol (or the open one)."""
    return _call(service.start_correction, store, protocol_id, actor.id)


@router.get("/{protocol_id}/document")
def download_original(protocol_id: str, actor: Actor):
    content, row = _call(service.read_original, store, protocol_id, actor.id)
    return Response(content, media_type="application/pdf", headers={
        **_PRIVATE,
        "Content-Disposition": "attachment; filename*=UTF-8''" + quote(row.filename, safe=""),
        "X-Content-SHA256": row.sha256,
    })


# --- Meter Readings ---

@router.post("/{protocol_id}/meter-readings", response_model=MeterReading, status_code=status.HTTP_201_CREATED)
def create_meter_reading(protocol_id: str, payload: MeterReadingCreate):
    if payload.handover_id != protocol_id:
        payload = MeterReadingCreate(**{**payload.model_dump(), "handover_id": protocol_id})
    try:
        _check_meter(_editable(protocol_id), payload.meter_id)
    except NotFoundError:
        pass                 # the store answers "Übergabeprotokoll nicht gefunden"
    try:
        return store.create_meter_reading(payload)
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/{protocol_id}/meter-readings/{reading_id}", response_model=MeterReading)
def get_meter_reading(protocol_id: str, reading_id: str):
    try:
        reading = store.get_meter_reading(reading_id)
        if reading.handover_id != protocol_id:
            raise NotFoundError("Zählerstand nicht gefunden")
        return reading
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.put("/{protocol_id}/meter-readings/{reading_id}", response_model=MeterReading)
def update_meter_reading(protocol_id: str, reading_id: str, payload: MeterReadingCreate):
    try:
        existing = store.get_meter_reading(reading_id)
        if existing.handover_id != protocol_id:
            raise NotFoundError("Zählerstand nicht gefunden")
        if payload.handover_id != protocol_id:
            payload = MeterReadingCreate(**{**payload.model_dump(), "handover_id": protocol_id})
        _check_meter(_editable(protocol_id), payload.meter_id)
        return store.update_meter_reading(reading_id, payload)
    except (NotFoundError, ValidationError) as exc:
        code = 404 if isinstance(exc, NotFoundError) else 400
        raise HTTPException(status_code=code, detail=str(exc)) from exc


@router.patch("/{protocol_id}/meter-readings/{reading_id}", response_model=MeterReading)
def patch_meter_reading(protocol_id: str, reading_id: str, payload: MeterReadingPatch):
    try:
        existing = store.get_meter_reading(reading_id)
        if existing.handover_id != protocol_id:
            raise NotFoundError("Zählerstand nicht gefunden")
        updates = payload.model_dump(exclude_unset=True)
        if "handover_id" in updates and updates["handover_id"] != protocol_id:
            raise ValidationError("handover_id muss der URL-Protokoll-ID entsprechen")
        _check_meter(_editable(protocol_id), updates.get("meter_id"))
        return store._patch_entity("meter_reading", reading_id, payload)
    except (NotFoundError, ValidationError) as exc:
        code = 404 if isinstance(exc, NotFoundError) else 400
        raise HTTPException(status_code=code, detail=str(exc)) from exc


@router.delete("/{protocol_id}/meter-readings/{reading_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_meter_reading(protocol_id: str, reading_id: str):
    try:
        reading = store.get_meter_reading(reading_id)
        if reading.handover_id != protocol_id:
            raise NotFoundError("Zählerstand nicht gefunden")
        _editable(protocol_id)
        store.delete_meter_reading(reading_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
