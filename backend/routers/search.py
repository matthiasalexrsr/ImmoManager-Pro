"""Complete keyword pages and explicit legacy semantic recommendations."""

from fastapi import APIRouter, Query

from ..dependencies import store
from ..services import global_search as service
from ..services.ai.schemas import SearchHit
from ..services.ai.semantic_search import IndexEntry, search_index
from ..services.checked_publication import CheckedPublicationRoute
from ..services.portfolio_scope import (
    current_scope,
    refresh_scope,
    require_installation_scope,
    resource_visible,
)

router = APIRouter(prefix="/search", tags=["Search"], route_class=CheckedPublicationRoute)


def _rebuild_search_index() -> None:
    if not search_index.is_available:
        return
    entries: list[IndexEntry] = []
    for source, list_name in (("property", "properties"), ("tenant", "tenants"), ("unit", "units"),
                              ("document", "documents"), ("maintenance", "maintenance_cases")):
        spec = next(value for value in service.SOURCES if value.kind == source)
        for row in getattr(store, "list_" + list_name)():
            data = row.model_dump()
            hit = service._hit(spec, data)
            text = " ".join(str(data.get(field) or "") for field in spec.fields)
            entries.append(IndexEntry(source, row.id, hit["display"], hit["detail"], hit["url"], text))
    search_index.clear()
    search_index.add_entries(entries)
    search_index.rebuild()


@router.post("/reindex")
def reindex_search() -> dict:
    require_installation_scope()
    _rebuild_search_index()
    return {"reindexed": True, "entries": search_index.entry_count, "semantic_available": search_index.is_available}


@router.get("/page")
def keyword_page(
    q: str = Query(..., min_length=1),
    after: str | None = Query(None, max_length=8192),
    limit: int = Query(50, ge=1, le=500),
):
    return service.page(store, q, after=after, limit=limit)


@router.get("")
def global_search(
    q: str = Query(..., min_length=1, description="Search query"),
    semantic: bool = Query(True, description="Legacy semantic recommendation mode"),
    after: str | None = Query(None, max_length=8192),
    limit: int = Query(50, ge=1, le=500),
):
    data = service.page(store, q, after=after, limit=limit)
    data["mode"] = "keyword_page"
    if not semantic or after is not None or not search_index.is_available or not search_index.entry_count:
        return data
    captured = current_scope()
    hits = [SearchHit(entity_type=row["entity_type"], entity_id=row["id"], display=row["display"],
                      detail=row["detail"], url=row["url"]) for row in data["results"]]
    suggestions = [value for value in search_index.search(q, hits, top_k=limit)
                   if resource_visible(value.entity_type, value.entity_id)]
    refresh_scope(captured)
    # Recommendation ranking remains available to existing callers. Complete,
    # stable enumeration is explicit and independently reachable at /page.
    return {**data, "count": len(suggestions), "semantic": True, "mode": "recommendations",
            "keyword_page_url": "/api/v1/search/page", "results": [
                {"entity_type": row.entity_type, "id": row.entity_id, "display": row.display,
                 "detail": row.detail, "url": row.url, "score": row.combined_score}
                for row in suggestions]}
