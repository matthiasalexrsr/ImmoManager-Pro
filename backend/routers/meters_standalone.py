"""Standalone meters and readings router (not tied to handover protocols)."""

from fastapi import APIRouter, HTTPException, Query, status

from ..dependencies import store
from ..models import (
    Meter,
    MeterCreate,
    MeterPatch,
    StandaloneMeterReading,
    StandaloneMeterReadingCreate,
)
from ..storage import NotFoundError, ValidationError
from ._helpers import apply_sort

router = APIRouter(prefix="/meters", tags=["Zähler"])


# --- Meters ---

@router.get("", response_model=list[Meter])
def list_meters(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    sort_by: str | None = Query(None),
    sort_order: str = Query("asc"),
    unit_id: str | None = Query(None),
    meter_type: str | None = Query(None),
) -> list[Meter]:
    results = store.list_meters()
    if isinstance(unit_id, str) and unit_id:
        results = [m for m in results if m.unit_id == unit_id]
    if isinstance(meter_type, str) and meter_type:
        results = [m for m in results if m.meter_type == meter_type]
    results = apply_sort(results, sort_by, sort_order)
    return results[skip : skip + limit]


@router.post("", response_model=Meter, status_code=status.HTTP_201_CREATED)
def create_meter(payload: MeterCreate) -> Meter:
    try:
        return store.create_meter(payload)
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/{meter_id}", response_model=Meter)
def get_meter(meter_id: str) -> Meter:
    try:
        return store.get_meter(meter_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.put("/{meter_id}", response_model=Meter)
def update_meter(meter_id: str, payload: MeterCreate) -> Meter:
    try:
        return store.update_meter(meter_id, payload)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.patch("/{meter_id}", response_model=Meter)
def patch_meter(meter_id: str, payload: MeterPatch) -> Meter:
    try:
        return store._patch_entity("meter", meter_id, payload)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.delete("/{meter_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_meter(meter_id: str) -> None:
    try:
        store.delete_meter(meter_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


# --- Meter Readings ---

@router.get("/{meter_id}/readings", response_model=list[StandaloneMeterReading])
def list_readings_for_meter(
    meter_id: str,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    sort_by: str | None = Query(None),
    sort_order: str = Query("asc"),
) -> list[StandaloneMeterReading]:
    results = [r for r in store.list_standalone_meter_readings() if r.meter_id == meter_id]
    results = apply_sort(results, sort_by, sort_order)
    return results[skip : skip + limit]


@router.post("/{meter_id}/readings", response_model=StandaloneMeterReading, status_code=status.HTTP_201_CREATED)
def create_reading(meter_id: str, payload: StandaloneMeterReadingCreate) -> StandaloneMeterReading:
    # Ensure meter exists
    try:
        store.get_meter(meter_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    try:
        return store.create_standalone_meter_reading(payload)
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/readings/all", response_model=list[StandaloneMeterReading])
def list_all_readings(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
) -> list[StandaloneMeterReading]:
    results = store.list_standalone_meter_readings()
    return results[skip : skip + limit]


@router.delete("/readings/{reading_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_reading(reading_id: str) -> None:
    try:
        store.delete_standalone_meter_reading(reading_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
