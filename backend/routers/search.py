"""Global search endpoint across all entity types."""

import logging

from fastapi import APIRouter, Query

from ..dependencies import store

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/search", tags=["Search"])


@router.get("")
def global_search(q: str = Query(..., min_length=1, description="Search query")):
    """Search across properties, tenants, contracts, units, tasks, and invoices."""
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
                "url": f"/properties",
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
                "url": f"/tenants",
            })

    # Search units
    for u in store.list_units():
        if query in u.label.lower():
            results.append({
                "entity_type": "unit",
                "id": u.id,
                "display": u.label,
                "detail": u.unit_type,
                "url": f"/units",
            })

    # Search contracts
    for c in store.list_contracts():
        if query in c.contract_number.lower():
            results.append({
                "entity_type": "contract",
                "id": c.id,
                "display": c.contract_number,
                "detail": c.status,
                "url": f"/contracts",
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
                "url": f"/tasks",
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
                "url": f"/invoices",
            })

    return {"query": q, "count": len(results), "results": results[:50]}
