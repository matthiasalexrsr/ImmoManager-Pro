"""Global search endpoint across all entity types."""

import logging

from fastapi import APIRouter, Query

from ..dependencies import store
from ..services.ai.schemas import SearchHit
from ..services.ai.semantic_search import IndexEntry, search_index

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/search", tags=["Search"])


def _rebuild_search_index() -> None:
    """Populate the semantic search index from all entities."""
    if not search_index.is_available:
        return

    entries: list[IndexEntry] = []

    for p in store.list_properties():
        text = " ".join(filter(None, [p.name, getattr(p, "street", None), getattr(p, "city", None)]))
        entries.append(IndexEntry("property", p.id, p.name, getattr(p, "city", "") or "", f"/properties/{p.id}", text))

    for t in store.list_tenants():
        text = " ".join(filter(None, [t.full_name, getattr(t, "email", None)]))
        entries.append(IndexEntry("tenant", t.id, t.full_name, getattr(t, "email", "") or "", "/tenants", text))

    for u in store.list_units():
        entries.append(IndexEntry("unit", u.id, u.label, u.unit_type, f"/units/{u.id}", u.label))

    for d in store.list_documents():
        text = " ".join(filter(None, [d.title, getattr(d, "description", None)]))
        entries.append(IndexEntry("document", d.id, d.title, getattr(d, "doc_type", "") or "", "/documents", text))

    for m in store.list_maintenance_cases():
        text = " ".join(filter(None, [m.title, getattr(m, "description", None)]))
        entries.append(IndexEntry("maintenance", m.id, m.title, m.status, "/maintenance", text))

    search_index.clear()
    search_index.add_entries(entries)
    search_index.rebuild()


@router.post("/reindex")
def reindex_search() -> dict:
    """Rebuild the semantic search index."""
    _rebuild_search_index()
    return {"reindexed": True, "entries": search_index.entry_count, "semantic_available": search_index.is_available}


_MAX_RESULTS_PER_TYPE = 10  # Cap per entity type to limit scan overhead
_MAX_TOTAL_RESULTS = 50  # Stop scanning once we have enough results


def _search_entities(entity_list, query, entity_type, fields, url, display_fn, detail_fn, results):
    """Search a single entity type and append matches to results."""
    hits = 0
    for item in entity_list:
        if len(results) >= _MAX_TOTAL_RESULTS:
            return
        searchable = " ".join(filter(None, [getattr(item, f, None) for f in fields])).lower()
        if query in searchable:
            results.append({
                "entity_type": entity_type,
                "id": item.id,
                "display": display_fn(item),
                "detail": detail_fn(item),
                "url": url(item) if callable(url) else url,
            })
            hits += 1
            if hits >= _MAX_RESULTS_PER_TYPE:
                return


@router.get("")
def global_search(
    q: str = Query(..., min_length=1, description="Search query"),
    semantic: bool = Query(True, description="Enable semantic re-ranking"),
):
    """Search across all major entity types with optional semantic re-ranking."""
    query = q.lower().strip()
    results: list[dict] = []

    # Define search targets: (list_fn, entity_type, fields, url, display_fn, detail_fn)
    # NOTE: This still loads all entities per type. For large datasets, move to DB-side
    # ILIKE/text-search queries in a dedicated SearchService.
    _search_entities(
        store.list_properties(), query, "property",
        ["name", "street", "city"],
        lambda p: f"/properties/{p.id}",
        lambda p: p.name,
        lambda p: getattr(p, "city", "") or "",
        results,
    )
    _search_entities(
        store.list_tenants(), query, "tenant",
        ["full_name", "email"],
        "/tenants",
        lambda t: t.full_name,
        lambda t: getattr(t, "email", "") or "",
        results,
    )
    _search_entities(
        store.list_units(), query, "unit",
        ["label"],
        lambda u: f"/units/{u.id}",
        lambda u: u.label,
        lambda u: u.unit_type,
        results,
    )
    _search_entities(
        store.list_contracts(), query, "contract",
        ["contract_number"],
        "/contracts",
        lambda c: c.contract_number,
        lambda c: c.status,
        results,
    )
    _search_entities(
        store.list_tasks(), query, "task",
        ["title", "description"],
        "/tasks",
        lambda t: t.title,
        lambda t: t.status,
        results,
    )
    _search_entities(
        store.list_invoices(), query, "invoice",
        ["supplier", "payment_terms"],
        "/invoices",
        lambda i: i.supplier,
        lambda i: str(i.gross_amount),
        results,
    )
    _search_entities(
        store.list_accounts(), query, "account",
        ["name", "bank_name", "iban"],
        "/accounts",
        lambda a: a.name,
        lambda a: getattr(a, "account_type", "") or "",
        results,
    )
    _search_entities(
        store.list_bookings(), query, "booking",
        ["description", "payment_text"],
        "/bookings",
        lambda b: getattr(b, "description", None) or getattr(b, "payment_text", "") or str(b.id)[:8],
        lambda b: str(getattr(b, "amount", "")),
        results,
    )
    _search_entities(
        store.list_maintenance_cases(), query, "maintenance",
        ["title", "description"],
        "/maintenance",
        lambda m: m.title,
        lambda m: m.status,
        results,
    )
    _search_entities(
        store.list_documents(), query, "document",
        ["title", "description"],
        "/documents",
        lambda d: d.title,
        lambda d: getattr(d, "doc_type", "") or "",
        results,
    )

    # Entity types that may not exist in all store backends
    for entity_type, list_fn, fields, url, display_fn, detail_fn in [
        ("contact", store.list_contacts, ["name", "email", "company"], "/contacts",
         lambda x: getattr(x, "name", "") or str(x.id)[:8], lambda x: getattr(x, "company", "") or ""),
        ("deposit", store.list_deposits, ["notes"], "/deposits",
         lambda x: f"Kaution {str(x.id)[:8]}", lambda x: getattr(x, "status", "") or ""),
        ("category", store.list_categories, ["name", "description"], "/categories",
         lambda x: x.name, lambda x: getattr(x, "category_type", "") or ""),
        ("lead", store.list_leads, ["name", "email"], "/leads",
         lambda x: getattr(x, "name", "") or str(x.id)[:8], lambda x: getattr(x, "status", "") or ""),
        ("listing", store.list_listings, ["title", "description"], "/listings",
         lambda x: getattr(x, "title", "") or str(x.id)[:8], lambda x: getattr(x, "status", "") or ""),
        ("insurance", store.list_insurances, ["provider", "policy_number", "insurance_type"], "/insurances",
         lambda x: getattr(x, "provider", "") or str(x.id)[:8], lambda x: getattr(x, "insurance_type", "") or ""),
    ]:
        try:
            _search_entities(list_fn(), query, entity_type, fields, url, display_fn, detail_fn, results)
        except Exception:
            logger.debug("Search failed for entity type %r", entity_type, exc_info=True)

    # Apply semantic re-ranking if available and requested
    if semantic and search_index.is_available and search_index.entry_count > 0:
        keyword_hits = [
            SearchHit(
                entity_type=r["entity_type"],
                entity_id=r["id"],
                display=r["display"],
                detail=r["detail"],
                url=r["url"],
            )
            for r in results
        ]
        reranked = search_index.search(q, keyword_hits, top_k=50)
        reranked_results = [
            {
                "entity_type": h.entity_type,
                "id": h.entity_id,
                "display": h.display,
                "detail": h.detail,
                "url": h.url,
                "score": h.combined_score,
            }
            for h in reranked
        ]
        return {"query": q, "count": len(reranked_results), "results": reranked_results, "semantic": True}

    return {"query": q, "count": len(results), "results": results[:50], "semantic": False}
