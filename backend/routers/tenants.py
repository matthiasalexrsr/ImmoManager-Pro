from fastapi import APIRouter, HTTPException, Query, status

from ..dependencies import store
from ..models import Tenant, TenantCreate, TenantPatch
from ..storage import NotFoundError, ValidationError

router = APIRouter(prefix="/tenants", tags=["Mieter"])


@router.get("", response_model=list[Tenant])
def list_tenants(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    sort_by: str | None = Query(None),
    sort_order: str = Query("asc"),
    archived: bool | None = Query(None, description="Filter by archived status"),
    include_archived: bool = Query(False, description="Include archived tenants"),
) -> list[Tenant]:
    if archived is not None:
        filters = {"archived": archived}
    elif not include_archived:
        filters = {"archived": False}
    else:
        filters = {}
    results = store._list_paginated(
        entity_type="tenant",
        skip=skip,
        limit=limit,
        filters=filters,
        order_by=sort_by,
        order_desc=(sort_order == "desc"),
    )
    return results


@router.patch("/{tenant_id}/archive", response_model=Tenant)
def archive_tenant(tenant_id: str) -> Tenant:
    """Archive a tenant."""
    try:
        from ..models import TenantPatch
        return store._patch_entity("tenant", tenant_id, TenantPatch(archived=True))
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.patch("/{tenant_id}/unarchive", response_model=Tenant)
def unarchive_tenant(tenant_id: str) -> Tenant:
    """Unarchive a tenant."""
    try:
        from ..models import TenantPatch
        return store._patch_entity("tenant", tenant_id, TenantPatch(archived=False))
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("", response_model=Tenant, status_code=status.HTTP_201_CREATED)
def create_tenant(payload: TenantCreate) -> Tenant:
    try:
        return store.create_tenant(payload)
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/{tenant_id}", response_model=Tenant)
def get_tenant(tenant_id: str) -> Tenant:
    try:
        return store.get_tenant(tenant_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.put("/{tenant_id}", response_model=Tenant)
def update_tenant(tenant_id: str, payload: TenantCreate) -> Tenant:
    try:
        return store.update_tenant(tenant_id, payload)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.patch("/{tenant_id}", response_model=Tenant)
def patch_tenant(tenant_id: str, payload: TenantPatch) -> Tenant:
    try:
        return store._patch_entity("tenant", tenant_id, payload)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.delete("/{tenant_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_tenant(tenant_id: str) -> None:
    try:
        store.delete_tenant(tenant_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
