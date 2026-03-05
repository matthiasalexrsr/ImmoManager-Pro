"""Handover protocol and meter reading router (T16)."""

from fastapi import APIRouter, HTTPException, Query, status

from ..dependencies import store
from ..models import (
    HandoverProtocol,
    HandoverProtocolCreate,
    HandoverProtocolPatch,
    MeterReading,
    MeterReadingCreate,
    MeterReadingPatch,
)
from ..storage import NotFoundError, ValidationError

router = APIRouter(prefix="/handover-protocols", tags=["Übergabeprotokolle"])


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
        return store.update_handover_protocol(protocol_id, payload)
    except (NotFoundError, ValidationError) as exc:
        code = 404 if isinstance(exc, NotFoundError) else 400
        raise HTTPException(status_code=code, detail=str(exc)) from exc


@router.patch("/{protocol_id}", response_model=HandoverProtocol)
def patch_handover_protocol(protocol_id: str, payload: HandoverProtocolPatch):
    try:
        return store._patch_entity(None, protocol_id, payload, "Übergabeprotokoll nicht gefunden")
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/{protocol_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_handover_protocol(protocol_id: str):
    try:
        store.delete_handover_protocol(protocol_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


# --- Meter Readings ---

@router.post("/{protocol_id}/meter-readings", response_model=MeterReading, status_code=status.HTTP_201_CREATED)
def create_meter_reading(protocol_id: str, payload: MeterReadingCreate):
    if payload.handover_id != protocol_id:
        payload = MeterReadingCreate(**{**payload.model_dump(), "handover_id": protocol_id})
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
        return store._patch_entity(None, reading_id, payload, "Zählerstand nicht gefunden")
    except (NotFoundError, ValidationError) as exc:
        code = 404 if isinstance(exc, NotFoundError) else 400
        raise HTTPException(status_code=code, detail=str(exc)) from exc


@router.delete("/{protocol_id}/meter-readings/{reading_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_meter_reading(protocol_id: str, reading_id: str):
    try:
        reading = store.get_meter_reading(reading_id)
        if reading.handover_id != protocol_id:
            raise NotFoundError("Zählerstand nicht gefunden")
        store.delete_meter_reading(reading_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
