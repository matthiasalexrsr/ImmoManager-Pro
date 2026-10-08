"""Global search endpoint across all entity types."""

import csv
import io
import logging
import tempfile
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse

from ..dependencies import store
from ..services import global_search as gs
from ..services.ai.schemas import SearchHit
from ..services.ai.semantic_search import IndexEntry, search_index
from ..services.portfolio_scope import require_installation_scope, resource_visible

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/search", tags=["Search"])


def _rebuild_search_index() -> None:
    """Populate the semantic search index from all entities."""
    if not search_index.is_available:
        return

    entries: list[IndexEntry] = []

    for p in store.list_properties():
        text = " ".join(filter(None, [p.name, p.address_line, p.postal_code, p.city]))
        entries.append(IndexEntry("property", p.id, p.name, getattr(p, "city", "") or "", f"/properties/{p.id}", text))

    for t in store.list_tenants():
        text = " ".join(filter(None, [t.full_name, getattr(t, "email", None)]))
        entries.append(IndexEntry("tenant", t.id, t.full_name, getattr(t, "email", "") or "", "/tenants", text))

    for u in store.list_units():
        entries.append(IndexEntry("unit", u.id, u.label, u.unit_type, f"/units/{u.id}", u.label))

    for d in store.list_documents():
        text = " ".join(filter(None, [d.title, getattr(d, "description", None)]))
        entries.append(IndexEntry("document", d.id, d.title, d.document_type or "", "/documents", text))

    for m in store.list_maintenance_cases():
        text = " ".join(filter(None, [m.title, getattr(m, "description", None)]))
        entries.append(IndexEntry("maintenance", m.id, m.title, m.status, "/maintenance", text))

    search_index.clear()
    search_index.add_entries(entries)
    search_index.rebuild()


@router.post("/reindex")
def reindex_search() -> dict:
    """Rebuild the semantic search index (of the whole installation)."""
    require_installation_scope()
    _rebuild_search_index()
    return {"reindexed": True, "entries": search_index.entry_count, "semantic_available": search_index.is_available}


def _page_info(entity_type: str, page: gs.Page) -> dict:
    return {"entity_type": entity_type, "total": page.total, "has_more": page.has_more,
            "next_cursor": page.next_cursor}


@router.get("")
def global_search(
    q: Annotated[str, Query(min_length=1, description="Search query")],
    semantic: Annotated[bool, Query(description="Enable semantic re-ranking (overview only)")] = True,
    type: Annotated[str | None, Query(description="One entity type: paged results")] = None,
    limit: Annotated[int, Query(ge=1, le=gs.MAX_LIMIT, description="Hits per type")] = gs.DEFAULT_LIMIT,
    cursor: Annotated[str | None, Query(description="next_cursor of the previous page")] = None,
):
    """Search all entity types (overview) or page through one type.

    Overview: up to ``limit`` hits per type plus exact ``total``/``has_more`` per type in
    ``groups``. With ``type``: one keyset page and ``next_cursor``. Sync on purpose:
    FastAPI runs it in the threadpool, off the event loop.
    """
    if not q.strip():
        raise HTTPException(422, "Suchbegriff fehlt")
    if cursor and not type:
        raise HTTPException(400, "Ein Cursor gilt nur zusammen mit type")
    try:
        if type:
            spec = gs.get_type(type)
            page = gs.search_page(store, spec, q, limit=limit, cursor=cursor)
            return {"query": q, "count": len(page.items), "results": page.items, "semantic": False,
                    "groups": [_page_info(type, page)], "total": page.total,
                    "has_more": page.has_more, "next_cursor": page.next_cursor}
        results: list[dict] = []
        groups = []
        for spec in gs.SEARCH_TYPES:
            page = gs.search_page(store, spec, q, limit=limit)
            results.extend(page.items)
            if page.total:
                groups.append(_page_info(spec.entity_type, page))
    except gs.SearchError as exc:
        raise HTTPException(400, str(exc)) from exc

    if semantic and search_index.is_available and search_index.entry_count > 0:
        keyword_hits = [
            SearchHit(entity_type=r["entity_type"], entity_id=r["id"], display=r["display"],
                      detail=r["detail"], url=r["url"])
            for r in results
        ]
        reranked = search_index.search(q, keyword_hits, top_k=max(50, len(keyword_hits)))
        # the index covers the installation: a hit found only there is checked against this account
        found = {(hit.entity_type, hit.entity_id) for hit in keyword_hits}
        reranked = [h for h in reranked
                    if (h.entity_type, h.entity_id) in found or resource_visible(h.entity_type, h.entity_id)]
        reranked_results = [
            {"entity_type": h.entity_type, "id": h.entity_id, "display": h.display, "detail": h.detail,
             "url": h.url, "score": h.combined_score}
            for h in reranked
        ]
        return {"query": q, "count": len(reranked_results), "results": reranked_results, "semantic": True,
                "groups": groups}

    return {"query": q, "count": len(results), "results": results, "semantic": False, "groups": groups}


_CSV_COLUMNS = ("entity_type", "id", "display", "detail", "url")


def _csv_cell(value) -> str:
    text = "" if value is None else str(value)
    # spreadsheet formula injection
    return "'" + text if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text


@router.get("/export", response_model=None)
def export_search(
    q: Annotated[str, Query(min_length=1)],
    type: Annotated[str, Query(description="Entity type to export")],
):
    """Every hit of one type as CSV (keyset batches, spooled to disk past 1 MiB)."""
    if not q.strip():
        raise HTTPException(422, "Suchbegriff fehlt")
    try:
        spec = gs.get_type(type)
    except gs.SearchError as exc:
        raise HTTPException(400, str(exc)) from exc
    # read everything here: the request's session and portfolio scope end before a lazy body runs
    buffer = tempfile.SpooledTemporaryFile(max_size=1 << 20, mode="w+b")
    text = io.TextIOWrapper(buffer, encoding="utf-8-sig", newline="")
    writer = csv.writer(text, delimiter=";")
    writer.writerow(_CSV_COLUMNS)
    for hit in gs.iter_all(store, spec, q):
        writer.writerow([_csv_cell(hit[column]) for column in _CSV_COLUMNS])
    text.flush()
    text.detach()
    buffer.seek(0)

    def chunks():
        try:
            while chunk := buffer.read(64 * 1024):
                yield chunk
        finally:
            buffer.close()

    return StreamingResponse(chunks(), media_type="text/csv; charset=utf-8",
                             headers={"Content-Disposition": f'attachment; filename="suche_{spec.entity_type}.csv"'})


