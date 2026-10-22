"""Owners' shares of properties and units (services/ownership.py)."""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from ..auth import require_auth
from ..dependencies import store
from ..domain.clock import local_today
from ..models import UserRead
from ..models_ownership import OwnershipShare, OwnershipShareCreate, OwnershipTransfer, OwnershipTransferCreate
from ..services import ownership as service
from ..storage import NotFoundError

router = APIRouter(prefix="/ownership-shares", tags=["Eigentumsanteile"])
Actor = Annotated[UserRead, Depends(require_auth)]


@router.get("", response_model=list[OwnershipShare])
def list_shares(property_id: str | None = Query(None), unit_id: str | None = Query(None),
                owner_contact_id: str | None = Query(None)):
    return service.list_shares(store, property_id=property_id, unit_id=unit_id, owner_contact_id=owner_contact_id)


@router.get("/owners")
def list_owners():
    """The address book's owners, for selections and filters."""
    return service.owners(store)


@router.get("/overview")
def overview(property_id: str = Query(...), as_of: date | None = Query(None)):
    """Who owns the property and each unit on a day, as the reports split their money."""
    try:
        return service.overview(store, property_id, as_of or local_today())
    except NotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc


@router.get("/history")
def history(property_id: str = Query(...)):
    """Who owned the property and each unit when, and the journal of owner changes."""
    try:
        return service.history(store, property_id)
    except NotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc


@router.post("/transfers", response_model=OwnershipTransfer, status_code=status.HTTP_201_CREATED)
def record_transfer(payload: OwnershipTransferCreate, actor: Actor):
    """A sale, gift, inheritance or division on a day: shares end the day before, new ones begin."""
    return service.record_transfer(store, payload, actor.id)


@router.post("", response_model=OwnershipShare, status_code=status.HTTP_201_CREATED)
def create_share(payload: OwnershipShareCreate, actor: Actor):
    return service.create_share(store, payload, actor.id)


@router.put("/{share_id}", response_model=OwnershipShare)
def update_share(share_id: str, payload: OwnershipShareCreate, actor: Actor):
    try:
        return service.update_share(store, share_id, payload, actor.id)
    except NotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc


@router.delete("/{share_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_share(share_id: str, actor: Actor) -> None:
    try:
        service.delete_share(store, share_id, actor.id)
    except NotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
