"""DDL-free TEHA local metadata endpoints.

Root owns router registration/activation. This module performs no provider I/O.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response

from ..auth import require_role
from ..services.checked_publication import CheckedPublicationRoute
from ..services.portfolio_scope import require_installation_scope
from ..services.providers.teha_field_manifest import manifest


def _require_teha_administration(
    response: Response,
    actor=Depends(require_role("eigentuemer", "verwalter")),
):
    # Integration history/config are installation-scoped today. Do not imply a
    # portfolio-scoped private provider history until that core contract exists.
    if actor.role != "eigentuemer" and actor.portfolio_access != "all":
        raise HTTPException(403, "Installationsverwaltung erforderlich")
    require_installation_scope()
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["Vary"] = "Authorization"


router = APIRouter(
    prefix="/integrations/teha",
    tags=["TEHA"],
    route_class=CheckedPublicationRoute,
    dependencies=[Depends(_require_teha_administration)],
)


@router.get("/field-manifest")
def get_field_manifest() -> dict[str, object]:
    """Return observed field names/types policy only; never private values."""
    return manifest()
