"""Personal SQL inbox publication; Phase A deliberately exposes no read command."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import JSONResponse
from pydantic import Field

from ..auth import require_auth
from ..dependencies import get_store
from ..models import UserRead
from ..services import notification_inbox
from ..services.checked_publication import CheckedPublicationRoute
from ..services.notification_inbox_types import InboxPage, InboxQuery
from ..services.portfolio_scope import current_scope, scope_from_user

router = APIRouter(
    prefix="/notifications/inbox",
    tags=["Persönliche Benachrichtigungen"],
    route_class=CheckedPublicationRoute,
)

_PRIVATE_HEADERS = {"Cache-Control": "private, no-store", "Vary": "Authorization"}
_UNAVAILABLE_MESSAGES = {
    "inbox_schema_unavailable": (
        "Die persönliche Inbox ist noch nicht verfügbar. "
        "Die Installation muss nach vollständiger Sicherung ausdrücklich aktualisiert werden."
    ),
    "inbox_persistence_unavailable": (
        "Die persönliche Inbox benötigt eine gemeinsame persistente Datenbank "
        "für Benutzer und Benachrichtigungen. Die Installation lokal prüfen."
    ),
}


class InboxHTTPQuery(InboxQuery):
    """HTTP strings are parsed once; the service still receives strict InboxQuery."""

    limit: int = Field(default=10, ge=1, le=100)


@router.get("", response_model=InboxPage)
def page(
    query: Annotated[InboxHTTPQuery, Query()],
    response: Response,
    user: UserRead = Depends(require_auth),
    store=Depends(get_store),
) -> InboxPage | JSONResponse:
    response.headers.update(_PRIVATE_HEADERS)
    if current_scope() != scope_from_user(user.model_dump()):
        raise HTTPException(
            403, "Eine aktuelle Benutzerbindung ist erforderlich.", headers=_PRIVATE_HEADERS
        )
    domain_query = InboxQuery.model_validate(query.model_dump())
    try:
        return notification_inbox.list_inbox(
            store, domain_query, read_actions_enabled=False
        )
    except HTTPException as error:
        code = error.detail.get("code") if isinstance(error.detail, dict) else None
        if (error.status_code != 503 or not isinstance(code, str)
                or code not in _UNAVAILABLE_MESSAGES):
            raise
        message = _UNAVAILABLE_MESSAGES[code]
        return JSONResponse(
            status_code=503,
            content={"error": {"code": code, "message": message}, "detail": message},
            headers={**_PRIVATE_HEADERS, "Retry-After": "2"},
        )
