from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Query, status

from ..dependencies import store
from ..models import Lead, LeadCreate, LeadPatch
from ..services.reletting import CLOSED_OUT, decision_time, lead_files, open_project_id
from ..storage import NotFoundError, ValidationError
from .reletting import remove_files

router = APIRouter(prefix="/leads", tags=["Interessenten"])


def _guard_project_decision(payload: LeadCreate, current: Lead | None = None) -> None:
    """A project decision also links a tenant; a list status cannot replace it."""
    if current and current.project_id and (payload.project_id != current.project_id or payload.unit_id != current.unit_id):
        raise HTTPException(409, "Eine Projektbewerbung bleibt ihrer Einheit zugeordnet. Bitte das Neuvermietungsprojekt öffnen.")
    if (payload.project_id or (current and current.project_id)) and (
        (payload.status == "accepted") != bool(current and current.status == "accepted")
    ):
        raise HTTPException(409, "Die Übernahme als Mieter erfolgt im Neuvermietungsprojekt über „Als Mieter übernehmen“.")


def _with_decision(changed: LeadCreate, current: Lead) -> LeadCreate:
    """A project applicant declined or withdrawn on this page gets the time of the decision, as in the project."""
    if not current.project_id:
        return changed
    return changed.model_copy(update={"decided_at": decision_time(current.status, changed.status, current.decided_at)})


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
        _guard_project_decision(payload)
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
        current = store.get_lead(lead_id)
        values = current.model_dump(include=set(LeadCreate.model_fields))
        changed = LeadCreate.model_validate({**values, **payload.model_dump(exclude_unset=True)})
        _guard_project_decision(changed, current)
        return store.update_lead(lead_id, _with_decision(changed, current))
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.patch("/{lead_id}", response_model=Lead)
def patch_lead(lead_id: str, payload: LeadPatch) -> Lead:
    try:
        current = store.get_lead(lead_id)
        changed = current.model_copy(update=payload.model_dump(exclude_unset=True))
        _guard_project_decision(changed, current)
        if current.project_id and changed.status != current.status:
            values = changed.model_dump(include=set(LeadCreate.model_fields))
            return store.update_lead(lead_id, _with_decision(LeadCreate.model_validate(values), current))
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
