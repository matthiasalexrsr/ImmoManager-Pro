"""Creator-bound durable monthly rental generation under /rent-charges RBAC."""
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from ..auth import get_user_by_id, require_auth
from ..dependencies import get_store
from ..models import UserRead
from ..permissions import may_write_resource
from ..services.portfolio_scope import scope_from_user
from ..services.rent_batch import (
    BatchAdvance,
    BatchConfirm,
    BatchCreate,
    BatchError,
    advance_batch,
    control_batch,
    create_batch,
    get_batch,
    list_batches,
    preview_batch,
)

router = APIRouter(prefix="/rent-charges/batches", tags=["Mietgenerierung"])


def actor(user: Annotated[UserRead, Depends(require_auth)]):
    record = get_user_by_id(user.id)
    if not record or not record["is_active"]:
        raise HTTPException(401, "Benutzer ist nicht mehr aktiv.")
    return {"actor_id": user.id, "scope": scope_from_user(record)}


def writer(identity: Annotated[dict, Depends(actor)]):
    # Same action roles as the existing monthly-generation routes. The global
    # permission middleware additionally enforces custom write_permissions.
    if not may_write_resource(identity["scope"].role, "rent-charges"):
        raise HTTPException(403, "Keine Berechtigung zur Mietgenerierung.")
    return identity


def call(operation, *args, **kwargs):
    try:
        return operation(*args, **kwargs)
    except BatchError as exc:
        raise HTTPException(exc.status, exc.detail) from exc


@router.post("", status_code=201)
def create(payload: BatchCreate, store=Depends(get_store), identity=Depends(writer)):
    return call(create_batch, store, payload, **identity)


@router.get("")
def listing(cursor: str | None = Query(None, max_length=4096), page_size: int = Query(25, ge=1, le=5000),
            store=Depends(get_store), identity=Depends(actor)):
    return call(list_batches, store, cursor=cursor, page_size=page_size, **identity)


@router.get("/{batch_id}")
def get(batch_id: str, store=Depends(get_store), identity=Depends(actor)):
    return call(get_batch, store, batch_id, **identity)


@router.get("/{batch_id}/preview")
def preview(batch_id: str, cursor: str | None = Query(None, max_length=4096), page_size: int = Query(100, ge=1, le=5000),
            store=Depends(get_store), identity=Depends(actor)):
    return call(preview_batch, store, batch_id, cursor=cursor, page_size=page_size, **identity)


@router.post("/{batch_id}/advance")
def advance(batch_id: str, payload: BatchAdvance, store=Depends(get_store), identity=Depends(writer)):
    return call(advance_batch, store, batch_id, payload, **identity)


@router.post("/{batch_id}/confirm")
def confirm(batch_id: str, payload: BatchConfirm, store=Depends(get_store), identity=Depends(writer)):
    return call(control_batch, store, batch_id, payload, "confirm", **identity)


@router.post("/{batch_id}/pause")
def pause(batch_id: str, payload: BatchAdvance, store=Depends(get_store), identity=Depends(writer)):
    return call(control_batch, store, batch_id, payload, "pause", **identity)


@router.post("/{batch_id}/resume")
def resume(batch_id: str, payload: BatchAdvance, store=Depends(get_store), identity=Depends(writer)):
    return call(control_batch, store, batch_id, payload, "resume", **identity)


@router.post("/{batch_id}/restart")
def restart(batch_id: str, payload: BatchAdvance, store=Depends(get_store), identity=Depends(writer)):
    return call(control_batch, store, batch_id, payload, "restart", **identity)
