"""One exact unit context, with independently traversable bounded collections."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from ..auth import require_auth
from ..dependencies import store
from ..services.checked_publication import CheckedPublicationRoute
from ..services.contract_workspace_types import ContractWorkspaceError
from ..services.unit_workspace import UnitWorkspace, UnitWorkspaceQuery, get_unit_workspace

router = APIRouter(route_class=CheckedPublicationRoute, dependencies=[Depends(require_auth)])


@router.get("/{unit_id}/workspace", response_model=UnitWorkspace)
def workspace(unit_id: str, query: Annotated[UnitWorkspaceQuery, Query()], response: Response):
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["Vary"] = "Authorization"
    try:
        return get_unit_workspace(store, unit_id, query)
    except ContractWorkspaceError as exc:
        raise HTTPException(422, str(exc)) from exc
