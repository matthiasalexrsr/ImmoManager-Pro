"""Authenticated read-only contract workspace; register before contract CRUD."""

from typing import Annotated

from fastapi import APIRouter, Query, Response
from fastapi.responses import JSONResponse

from ..dependencies import store
from ..services.contract_workspace import get_contract_workspace_page
from ..services.contract_workspace_types import ContractWorkspaceError, ContractWorkspacePage, ContractWorkspaceQuery

router = APIRouter(prefix="/contracts/workspace", tags=["Verträge"])


@router.get("/page", response_model=ContractWorkspacePage)
def workspace_page(query: Annotated[ContractWorkspaceQuery, Query()], response: Response):
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["Vary"] = "Authorization"
    try:
        return get_contract_workspace_page(store, query)
    except ContractWorkspaceError as exc:
        return JSONResponse(
            status_code=400,
            content={"error": {"code": exc.code, "message": str(exc), "details": [exc.detail]}},
            headers={"Cache-Control": "private, no-store", "Vary": "Authorization"},
        )
