from fastapi import APIRouter, HTTPException, Query, status

from ..dependencies import store
from ..models import Lead, LeadCreate, LeadPatch
from ..storage import NotFoundError, ValidationError

router = APIRouter(prefix="/leads", tags=["Interessenten"])


@router.get("", response_model=list[Lead])
def list_leads(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    status_filter: str | None = Query(None, alias="status"),
    unit_id: str | None = Query(None),
    listing_id: str | None = Query(None),
    source: str | None = Query(None),
) -> list[Lead]:
    results = store.list_leads()
    if status_filter:
        results = [r for r in results if r.status == status_filter]
    if unit_id:
        results = [r for r in results if r.unit_id == unit_id]
    if listing_id:
        results = [r for r in results if r.listing_id == listing_id]
    if source:
        results = [r for r in results if r.source == source]
    return results[skip : skip + limit]


@router.post("", response_model=Lead, status_code=status.HTTP_201_CREATED)
def create_lead(payload: LeadCreate) -> Lead:
    try:
        return store.create_lead(payload)
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/{lead_id}", response_model=Lead)
def get_lead(lead_id: str) -> Lead:
    try:
        return store.get_lead(lead_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.put("/{lead_id}", response_model=Lead)
def update_lead(lead_id: str, payload: LeadCreate) -> Lead:
    try:
        return store.update_lead(lead_id, payload)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.patch("/{lead_id}", response_model=Lead)
def patch_lead(lead_id: str, payload: LeadPatch) -> Lead:
    try:
        return store._patch_entity(store.leads, lead_id, payload, "Interessent nicht gefunden")
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.delete("/{lead_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_lead(lead_id: str) -> None:
    try:
        store.delete_lead(lead_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
