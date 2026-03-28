"""Dashboard endpoints for aggregated stats.

Provides efficient server-side counts instead of requiring
clients to fetch full entity lists just to count them.
"""

from fastapi import APIRouter

from ..dependencies import store

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])


@router.get("/stats")
def get_dashboard_stats() -> dict:
    """Return aggregated entity counts for the dashboard.

    Uses SQL COUNT queries instead of fetching full entity lists,
    reducing data transfer from O(n) rows to a single response.
    """
    return {
        "portfolio_count": store.count_entities("portfolio"),
        "property_count": store.count_entities("property"),
        "unit_count": store.count_entities("unit"),
        "tenant_count": store.count_entities("tenant"),
        "contract_count": store.count_entities("contract"),
        "account_count": store.count_entities("account"),
        "vacant_units": store.count_entities("unit", {"status": "vacant"}),
        "occupied_units": store.count_entities("unit", {"status": "occupied"}),
        "reserved_units": store.count_entities("unit", {"status": "reserved"}),
        "active_contracts": store.count_entities("contract", {"status": "active"}),
        "open_maintenance": store.count_entities("maintenance", {"status": "open"}),
    }
