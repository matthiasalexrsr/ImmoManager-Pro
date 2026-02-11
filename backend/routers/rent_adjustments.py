"""Rent adjustment router (T15: Index/Stepped rent)."""

from fastapi import APIRouter, HTTPException, Query, status

from ..dependencies import store
from ..models import RentAdjustment, RentAdjustmentCreate, RentAdjustmentPatch
from ..storage import NotFoundError, ValidationError

router = APIRouter(prefix="/rent-adjustments", tags=["Mietanpassungen"])


@router.get("", response_model=list[RentAdjustment])
def list_rent_adjustments(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    contract_id: str | None = Query(None),
    adjustment_type: str | None = Query(None),
):
    results = store.list_rent_adjustments()
    if contract_id:
        results = [r for r in results if r.contract_id == contract_id]
    if adjustment_type:
        results = [r for r in results if r.adjustment_type == adjustment_type]
    return results[skip: skip + limit]


@router.post("", response_model=RentAdjustment, status_code=status.HTTP_201_CREATED)
def create_rent_adjustment(payload: RentAdjustmentCreate):
    try:
        return store.create_rent_adjustment(payload)
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/{adj_id}", response_model=RentAdjustment)
def get_rent_adjustment(adj_id: str):
    try:
        return store.get_rent_adjustment(adj_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.put("/{adj_id}", response_model=RentAdjustment)
def update_rent_adjustment(adj_id: str, payload: RentAdjustmentCreate):
    try:
        return store.update_rent_adjustment(adj_id, payload)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.patch("/{adj_id}", response_model=RentAdjustment)
def patch_rent_adjustment(adj_id: str, payload: RentAdjustmentPatch):
    try:
        return store._patch_entity(None, adj_id, payload, "Mietanpassung nicht gefunden")
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/{adj_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_rent_adjustment(adj_id: str):
    try:
        store.delete_rent_adjustment(adj_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
