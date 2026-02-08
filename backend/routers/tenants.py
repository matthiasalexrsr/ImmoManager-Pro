from fastapi import APIRouter, HTTPException, status

from ..models import Tenant, TenantCreate
from ..routers.portfolios import store
from ..storage import NotFoundError

router = APIRouter(prefix="/tenants", tags=["Mieter"])


@router.get("", response_model=list[Tenant])
def list_tenants() -> list[Tenant]:
    return store.list_tenants()


@router.post("", response_model=Tenant, status_code=status.HTTP_201_CREATED)
def create_tenant(payload: TenantCreate) -> Tenant:
    return store.create_tenant(payload)


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


@router.delete("/{tenant_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_tenant(tenant_id: str) -> None:
    try:
        store.delete_tenant(tenant_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
