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


@router.get("")
def global_search(
    q: str = Query(..., min_length=1, description="Search query"),
    semantic: bool = Query(True, description="Enable semantic re-ranking"),
):
    """Search across all major entity types with optional semantic re-ranking."""
    query = q.lower().strip()
    results = []

    # Search properties
    for p in store.list_properties():
        searchable = " ".join(filter(None, [p.name, getattr(p, "street", None), getattr(p, "city", None)])).lower()
        if query in searchable:
            results.append({
                "entity_type": "property",
                "id": p.id,
                "display": p.name,
                "detail": getattr(p, "city", "") or "",
                "url": f"/properties/{p.id}",
            })

    # Search tenants
    for t in store.list_tenants():
        searchable = " ".join(filter(None, [t.full_name, getattr(t, "email", None)])).lower()
        if query in searchable:
            results.append({
                "entity_type": "tenant",
                "id": t.id,
                "display": t.full_name,
                "detail": getattr(t, "email", "") or "",
                "url": "/tenants",
            })

    # Search units
    for u in store.list_units():
        if query in u.label.lower():
            results.append({
                "entity_type": "unit",
                "id": u.id,
                "display": u.label,
                "detail": u.unit_type,
                "url": f"/units/{u.id}",
            })

    # Search contracts
    for c in store.list_contracts():
        if query in c.contract_number.lower():
            results.append({
                "entity_type": "contract",
                "id": c.id,
                "display": c.contract_number,
                "detail": c.status,
                "url": "/contracts",
            })

    # Search tasks
    for t in store.list_tasks():
        searchable = " ".join(filter(None, [t.title, getattr(t, "description", None)])).lower()
        if query in searchable:
            results.append({
                "entity_type": "task",
                "id": t.id,
                "display": t.title,
                "detail": t.status,
                "url": "/tasks",
            })

    # Search invoices
    for i in store.list_invoices():
        searchable = " ".join(filter(None, [i.supplier, getattr(i, "payment_terms", None)])).lower()
        if query in searchable:
            results.append({
                "entity_type": "invoice",
                "id": i.id,
                "display": i.supplier,
                "detail": str(i.gross_amount),
                "url": "/invoices",
            })

    # Search accounts
    for a in store.list_accounts():
        searchable = " ".join(filter(None, [a.name, getattr(a, "bank_name", None), getattr(a, "iban", None)])).lower()
        if query in searchable:
            results.append({
                "entity_type": "account",
                "id": a.id,
                "display": a.name,
                "detail": getattr(a, "account_type", "") or "",
                "url": "/accounts",
            })

    # Search bookings
    for b in store.list_bookings():
        searchable = " ".join(filter(None, [
            getattr(b, "description", None),
            getattr(b, "payment_text", None),
        ])).lower()
        if query in searchable:
            results.append({
                "entity_type": "booking",
                "id": b.id,
                "display": getattr(b, "description", None) or getattr(b, "payment_text", "") or str(b.id)[:8],
                "detail": str(getattr(b, "amount", "")),
                "url": "/bookings",
            })

    # Search maintenance cases
    for m in store.list_maintenance_cases():
        searchable = " ".join(filter(None, [m.title, getattr(m, "description", None)])).lower()
        if query in searchable:
            results.append({
                "entity_type": "maintenance",
                "id": m.id,
                "display": m.title,
                "detail": m.status,
                "url": "/maintenance",
            })

    # Search documents
    for d in store.list_documents():
        searchable = " ".join(filter(None, [d.title, getattr(d, "description", None)])).lower()
        if query in searchable:
            results.append({
                "entity_type": "document",
                "id": d.id,
                "display": d.title,
                "detail": getattr(d, "doc_type", "") or "",
                "url": "/documents",
            })

    # Search contacts
    try:
        for ct in store.list_contacts():
            searchable = " ".join(filter(None, [
                getattr(ct, "name", None),
                getattr(ct, "email", None),
                getattr(ct, "company", None),
            ])).lower()
            if query in searchable:
                results.append({
                    "entity_type": "contact",
                    "id": ct.id,
                    "display": getattr(ct, "name", "") or str(ct.id)[:8],
                    "detail": getattr(ct, "company", "") or "",
                    "url": "/contacts",
                })
    except Exception:
        logger.debug("Search failed for entity type 'contact'", exc_info=True)

    # Search deposits
    try:
        for dep in store.list_deposits():
            searchable = " ".join(filter(None, [
                getattr(dep, "notes", None),
                str(getattr(dep, "amount", "")),
            ])).lower()
            if query in searchable:
                results.append({
                    "entity_type": "deposit",
                    "id": dep.id,
                    "display": f"Kaution {str(dep.id)[:8]}",
                    "detail": getattr(dep, "status", "") or "",
                    "url": "/deposits",
                })
    except Exception:
        logger.debug("Search failed for entity type 'deposit'", exc_info=True)

    # Search categories
    try:
        for cat in store.list_categories():
            searchable = " ".join(filter(None, [cat.name, getattr(cat, "description", None)])).lower()
            if query in searchable:
                results.append({
                    "entity_type": "category",
                    "id": cat.id,
                    "display": cat.name,
                    "detail": getattr(cat, "category_type", "") or "",
                    "url": "/categories",
                })
    except Exception:
        logger.debug("Search failed for entity type 'category'", exc_info=True)

    # Search leads
    try:
        for lead in store.list_leads():
            searchable = " ".join(filter(None, [
                getattr(lead, "name", None),
                getattr(lead, "email", None),
            ])).lower()
            if query in searchable:
                results.append({
                    "entity_type": "lead",
                    "id": lead.id,
                    "display": getattr(lead, "name", "") or str(lead.id)[:8],
                    "detail": getattr(lead, "status", "") or "",
                    "url": "/leads",
                })
    except Exception:
        logger.debug("Search failed for entity type 'lead'", exc_info=True)

    # Search listings
    try:
        for lst in store.list_listings():
            searchable = " ".join(filter(None, [
                getattr(lst, "title", None),
                getattr(lst, "description", None),
            ])).lower()
            if query in searchable:
                results.append({
                    "entity_type": "listing",
                    "id": lst.id,
                    "display": getattr(lst, "title", "") or str(lst.id)[:8],
                    "detail": getattr(lst, "status", "") or "",
                    "url": "/listings",
                })
    except Exception:
        logger.debug("Search failed for entity type 'listing'", exc_info=True)

    # Search insurances
    try:
        for ins in store.list_insurances():
            searchable = " ".join(filter(None, [
                getattr(ins, "provider", None),
                getattr(ins, "policy_number", None),
                getattr(ins, "insurance_type", None),
            ])).lower()
            if query in searchable:
                results.append({
                    "entity_type": "insurance",
                    "id": ins.id,
                    "display": getattr(ins, "provider", "") or str(ins.id)[:8],
                    "detail": getattr(ins, "insurance_type", "") or "",
                    "url": "/insurances",
                })
    except Exception:
        logger.debug("Search failed for entity type 'insurance'", exc_info=True)

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
