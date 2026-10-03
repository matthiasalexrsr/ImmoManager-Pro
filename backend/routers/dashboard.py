"""Dashboard endpoints for aggregated stats.

Provides efficient server-side counts instead of requiring
clients to fetch full entity lists just to count them.
"""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query
from pydantic import ValidationError

from ..dependencies import store
from ..services.checked_publication import CheckedPublicationRoute
from ..services.dashboard_summary import DashboardQuery, dashboard_summary

router = APIRouter(prefix="/dashboard", tags=["Dashboard"], route_class=CheckedPublicationRoute)

@router.get("/stats")
def get_dashboard_stats(
    as_of: date | None = None,
    preview_limit: Annotated[int, Query(ge=1, le=20)] = 5,
    tasks_after: Annotated[str | None, Query(min_length=1, max_length=8192)] = None,
    notifications_after: Annotated[str | None, Query(min_length=1, max_length=8192)] = None,
    contracts_after: Annotated[str | None, Query(min_length=1, max_length=8192)] = None,
) -> dict:
    """Complete legacy counts; additive occupancy, presence basis and live work pages."""
    try:
        query = DashboardQuery(as_of=as_of or date.today(), preview_limit=preview_limit,
            tasks_after=tasks_after, notifications_after=notifications_after, contracts_after=contracts_after)
    except ValidationError:
        raise HTTPException(422, "Ungültige Dashboardabfrage. Stichtag und Seitengröße prüfen.") from None
    return dashboard_summary(store, query)
