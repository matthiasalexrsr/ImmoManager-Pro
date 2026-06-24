"""Dashboard endpoints for aggregated stats.

Provides efficient server-side counts instead of requiring
clients to fetch full entity lists just to count them.
"""

from fastapi import APIRouter

from ..dependencies import store

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])


def _count_items(items: list, filters: dict | None = None) -> int:
    """Count already-loaded dashboard items with optional exact-match filters."""
    if not filters:
        return len(items)
    return sum(
        1 for item in items
        if all(getattr(item, key, None) == value for key, value in filters.items())
    )


@router.get("/stats")
def get_dashboard_stats() -> dict:
    """Return aggregated entity counts for the dashboard.

    Uses direct counts for core inventory and existing list APIs for
    workflow-specific operational totals.
    """
    invoices = store.list_invoices()
    receivables = store.list_receivables()
    documents = store.list_documents()
    tasks = store.list_tasks()
    notifications = store.list_notifications()
    rent_charges = store.list_rent_charges()
    billing_periods = store.list_billing_periods()
    allocation_keys = store.list_allocation_keys()
    utility_statements = store.list_utility_statements()

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
        "invoice_count": _count_items(invoices),
        "open_invoices": _count_items(invoices, {"status": "open"}),
        "paid_invoices": _count_items(invoices, {"status": "paid"}),
        "receivable_count": _count_items(receivables),
        "open_receivables": _count_items(receivables, {"status": "open"}),
        "paid_receivables": _count_items(receivables, {"status": "paid"}),
        "overdue_receivables": _count_items(receivables, {"status": "overdue"}),
        "document_count": _count_items(documents),
        "task_count": _count_items(tasks),
        "open_tasks": _count_items(tasks, {"status": "open"}),
        "notification_count": _count_items(notifications),
        "unread_notifications": _count_items(notifications, {"status": "unread"}),
        "rent_charge_count": _count_items(rent_charges),
        "open_rent_charges": _count_items(rent_charges, {"status": "open"}),
        "overdue_rent_charges": _count_items(rent_charges, {"status": "overdue"}),
        "billing_period_count": _count_items(billing_periods),
        "draft_billing_periods": _count_items(billing_periods, {"status": "draft"}),
        "finalized_billing_periods": _count_items(billing_periods, {"status": "finalized"}),
        "allocation_key_count": _count_items(allocation_keys),
        "utility_statement_count": _count_items(utility_statements),
        "draft_utility_statements": _count_items(utility_statements, {"status": "draft"}),
        "finalized_utility_statements": _count_items(utility_statements, {"status": "finalized"}),
    }
