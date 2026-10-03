from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response

from ..auth import require_auth
from ..dependencies import store
from ..models import UserRead
from ..services.checked_publication import CheckedPublicationRoute
from ..services.workflow_references import ReferenceKind, WorkflowReferenceQuery, workflow_reference_choices

router = APIRouter(prefix="/workflow-references", tags=["Auswahl"], route_class=CheckedPublicationRoute)


@router.get("/{kind}")
def list_workflow_references(kind: ReferenceKind, query: Annotated[WorkflowReferenceQuery, Query()],
                             response: Response, actor: UserRead = Depends(require_auth)) -> dict:
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["Vary"] = "Authorization"
    return workflow_reference_choices(store, kind, query, actor.id)
