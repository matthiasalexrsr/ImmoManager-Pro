from fastapi import APIRouter, HTTPException, Query, status

from ..dependencies import store
from ..models import Tenant, TenantCreate, TenantPatch
from ..storage import NotFoundError, ValidationError

router = APIRouter(prefix="/tenants", tags=["Mieter"])


@router.get("", response_model=list[Tenant])
def list_tenants(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
) -> list[Tenant]:
    results = store.list_tenants()
    return results[skip : skip + limit]


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
        return store._patch_entity(store.tenants, tenant_id, payload, "Mieter nicht gefunden")
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.delete("/{tenant_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_tenant(tenant_id: str) -> None:
    try:
        store.delete_tenant(tenant_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
