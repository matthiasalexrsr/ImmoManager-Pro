"""Unified contacts router: tenants, owners, suppliers, managers."""

from fastapi import APIRouter, HTTPException, Query, status

from ..dependencies import store
from ..models import Contact, ContactCreate, ContactPatch
from ..storage import NotFoundError, ValidationError
from ._helpers import apply_sort

router = APIRouter(prefix="/contacts", tags=["Kontakte"])


@router.get("", response_model=list[Contact])
def list_contacts(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    sort_by: str | None = Query(None),
    sort_order: str = Query("asc"),
    contact_type: str | None = Query(None),
) -> list[Contact]:
    results = store.list_contacts()
    if isinstance(contact_type, str) and contact_type:
        results = [c for c in results if c.contact_type == contact_type]
    results = apply_sort(results, sort_by, sort_order)
    return results[skip : skip + limit]


@router.post("", response_model=Contact, status_code=status.HTTP_201_CREATED)
def create_contact(payload: ContactCreate) -> Contact:
    try:
        return store.create_contact(payload)
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/{contact_id}", response_model=Contact)
def get_contact(contact_id: str) -> Contact:
    try:
        return store.get_contact(contact_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.put("/{contact_id}", response_model=Contact)
def update_contact(contact_id: str, payload: ContactCreate) -> Contact:
    try:
        return store.update_contact(contact_id, payload)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.patch("/{contact_id}", response_model=Contact)
def patch_contact(contact_id: str, payload: ContactPatch) -> Contact:
    try:
        return store._patch_entity("contact", contact_id, payload)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.delete("/{contact_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_contact(contact_id: str) -> None:
    try:
        store.delete_contact(contact_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
