from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query, status

from ..dependencies import store
from ..models import Lead, LeadCreate, LeadPatch
from ..services.reletting import CLOSED_OUT, lead_files, open_project_id
from ..storage import NotFoundError, ValidationError
from .reletting import remove_files

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
        if payload.project_id is None and payload.status != "accepted":
            # an inquiry for a unit that is being re-let joins its project (acceptance stays there)
            unit_id = payload.unit_id
            if unit_id is None and payload.listing_id:
                try:
                    unit_id = store.get_listing(payload.listing_id).unit_id
                except (NotFoundError, KeyError):
                    unit_id = None
            project_id = open_project_id(store, unit_id)
            if project_id:
                decided = payload.decided_at or (datetime.now(timezone.utc) if payload.status in CLOSED_OUT else None)
                payload = payload.model_copy(update={"project_id": project_id, "unit_id": unit_id, "decided_at": decided})
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
        # fields the form does not show (the applicant details of a re-letting project) stay as they are
        current = store.get_lead(lead_id).model_dump(include=set(LeadCreate.model_fields))
        return store.update_lead(lead_id, LeadCreate.model_validate({**current, **payload.model_dump(exclude_unset=True)}))
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.patch("/{lead_id}", response_model=Lead)
def patch_lead(lead_id: str, payload: LeadPatch) -> Lead:
    try:
        return store._patch_entity("lead", lead_id, payload)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.delete("/{lead_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_lead(lead_id: str) -> None:
    try:
        files = lead_files(store, lead_id)
        store.delete_lead(lead_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    remove_files(files)        # the applicant's documents go with them
