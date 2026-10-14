"""Rent adjustment router (T15: Index/Stepped rent)."""

from fastapi import APIRouter, HTTPException, Query, status

from ..dependencies import store
from ..models import RentAdjustment, RentAdjustmentCreate, RentAdjustmentPatch
from ..services.rent_history import apply_rent_adjustment, revert_rent_adjustment
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
        created = store.create_rent_adjustment(payload)
        if created.status == "applied":
            created, _ = apply_rent_adjustment(store, created.id)
        return created
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/{adj_id}", response_model=RentAdjustment)
def get_rent_adjustment(adj_id: str):
    try:
        return store.get_rent_adjustment(adj_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


def _save_with_status(adj_id: str, save) -> RentAdjustment:
    """Save, then make the rent history follow the status.

    "applied" writes the adjustment into the contract's rent history, leaving
    "applied" takes it out again, so the old status-only UI cannot bypass it.
    """
    try:
        before = store.get_rent_adjustment(adj_id)
        saved = save()
        if saved.status == "applied":
            saved, _ = apply_rent_adjustment(store, adj_id)
        elif before.status == "applied":
            saved = revert_rent_adjustment(store, adj_id, status=saved.status)
        return saved
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.put("/{adj_id}", response_model=RentAdjustment)
def update_rent_adjustment(adj_id: str, payload: RentAdjustmentCreate):
    return _save_with_status(adj_id, lambda: store.update_rent_adjustment(adj_id, payload))


@router.patch("/{adj_id}", response_model=RentAdjustment)
def patch_rent_adjustment(adj_id: str, payload: RentAdjustmentPatch):
    return _save_with_status(adj_id, lambda: store._patch_entity("rent_adjustment", adj_id, payload))


@router.post("/{adj_id}/apply")
def apply_adjustment(adj_id: str) -> dict:
    """Write the adjustment into the contract's rent history (only once)."""
    try:
        adjustment, warnings = apply_rent_adjustment(store, adj_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"adjustment": adjustment.model_dump(mode="json"), "warnings": warnings}


@router.post("/{adj_id}/revert", response_model=RentAdjustment)
def revert_adjustment(adj_id: str):
    """Take the adjustment out of the rent history; it is pending again."""
    try:
        return revert_rent_adjustment(store, adj_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/{adj_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_rent_adjustment(adj_id: str):
    try:
        store.delete_rent_adjustment(adj_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
