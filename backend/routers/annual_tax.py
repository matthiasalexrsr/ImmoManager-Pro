"""Reviewed annual cash classifications and immutable evidence exports."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from ..auth import UserRead, require_role
from ..dependencies import store
from ..services import annual_tax_storage as service
from ..services.annual_tax_export import prepare_download
from ..services.portfolio_scope import current_scope
from ..tax_models import AnnualTaxPreflightCreate, AnnualTaxProfileCreate, AnnualTaxProjectionCreate
from .datev import PrivateDownloadResponse

router = APIRouter(prefix="/reports/annual-tax", tags=["Jährliche Steueraufbereitung"])
FinanceActor = Annotated[UserRead, Depends(require_role("eigentuemer", "verwalter", "buchhaltung"))]


@router.get("/options")
def options(portfolio_id: str):
    return service.options(store, portfolio_id)


@router.get("/profiles")
def profiles(portfolio_id: str, tax_year: int | None = Query(None, ge=1, le=9998), offset: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=1000)):
    return service.list_profiles(store, portfolio_id, tax_year, offset, limit)


@router.post("/profiles", status_code=201)
def save_profile(command: AnnualTaxProfileCreate, actor: FinanceActor):
    return service.create_profile(store, command, actor.id)


@router.get("/profiles/{profile_id}")
def profile(profile_id: str):
    return service.get_profile(store, profile_id)


@router.post("/preflight")
def preflight(command: AnnualTaxPreflightCreate, actor: FinanceActor):
    return service.preflight(store, command)


@router.get("/projections")
def projections(portfolio_id: str, tax_year: int | None = Query(None, ge=1, le=9998), offset: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=1000)):
    return service.list_projections(store, portfolio_id, tax_year, offset, limit)


@router.get("/projections/{projection_id}")
def projection(projection_id: str):
    return service.read_projection(service.projection_row(store, projection_id))


@router.post("/projections", status_code=201)
def save_projection(command: AnnualTaxProjectionCreate, actor: FinanceActor):
    return service.create_projection(store, command, actor.id)


@router.get("/projections/{projection_id}/download")
def download(projection_id: str):
    compiled = prepare_download(store, projection_id)
    return PrivateDownloadResponse(compiled, current_scope(), media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="annual-tax-{projection_id}.zip"',
            "Content-Length": str(compiled.size), "X-Content-SHA256": compiled.sha256, "Cache-Control": "no-store"})
