"""Insurance management router."""

from fastapi import APIRouter, HTTPException, Query, status

from ..dependencies import store
from ..models import Insurance, InsuranceCreate, InsurancePatch
from ..storage import NotFoundError, ValidationError
from ._helpers import apply_sort

router = APIRouter(prefix="/insurances", tags=["Versicherungen"])


@router.get("", response_model=list[Insurance])
def list_insurances(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    property_id: str | None = Query(None),
    unit_id: str | None = Query(None),
    insurance_type: str | None = Query(None),
    sort_by: str | None = Query(None),
    sort_order: str = Query("asc"),
) -> list[Insurance]:
    results = store.list_insurances()
    if property_id:
        results = [r for r in results if r.property_id == property_id]
    if unit_id:
        results = [r for r in results if r.unit_id == unit_id]
    if insurance_type:
        results = [r for r in results if r.insurance_type == insurance_type]
    results = apply_sort(results, sort_by, sort_order)
    return results[skip: skip + limit]


@router.post("", response_model=Insurance, status_code=status.HTTP_201_CREATED)
def create_insurance(payload: InsuranceCreate) -> Insurance:
    try:
        return store.create_insurance(payload)
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/{insurance_id}", response_model=Insurance)
def get_insurance(insurance_id: str) -> Insurance:
    try:
        return store.get_insurance(insurance_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.put("/{insurance_id}", response_model=Insurance)
def update_insurance(insurance_id: str, payload: InsuranceCreate) -> Insurance:
    try:
        return store.update_insurance(insurance_id, payload)
    except (NotFoundError, ValidationError) as exc:
        code = 404 if isinstance(exc, NotFoundError) else 400
        raise HTTPException(status_code=code, detail=str(exc)) from exc


@router.patch("/{insurance_id}", response_model=Insurance)
def patch_insurance(insurance_id: str, payload: InsurancePatch) -> Insurance:
    try:
        return store._patch_entity("insurance", insurance_id, payload)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/{insurance_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_insurance(insurance_id: str) -> None:
    try:
        store.delete_insurance(insurance_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
