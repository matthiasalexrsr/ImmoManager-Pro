"""Dashboard endpoints for aggregated stats.

Provides efficient server-side counts instead of requiring
clients to fetch full entity lists just to count them.
"""

from datetime import date, timedelta

from fastapi import APIRouter

from ..dependencies import store

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])

_CLOSED_STATUSES = {"archived", "cancelled", "canceled", "closed", "done", "finalized", "paid"}
_OPEN_MAINTENANCE_STATUSES = {"open", "in_progress", "pending", "review"}
_PRE_FINAL_BILLING_STATUSES = {"draft", "review", "open"}


def _count_items(items: list, filters: dict | None = None) -> int:
    """Count already-loaded dashboard items with optional exact-match filters."""
    if not filters:
        return len(items)
    return sum(
        1 for item in items
        if all(getattr(item, key, None) == value for key, value in filters.items())
    )


def _status(item) -> str:
    return str(getattr(item, "status", "") or "").lower()


def _count_dunning_receivables(receivables: list) -> int:
    return sum(
        1
        for receivable in receivables
        if getattr(receivable, "dunning_level", None)
        and _status(receivable) not in _CLOSED_STATUSES
    )


def _count_missing_contract_documents(contracts: list, documents: list) -> int:
    documented_contract_ids = {
        document.contract_id
        for document in documents
        if getattr(document, "contract_id", None)
    }
    return sum(
        1
        for contract in contracts
        if _status(contract) == "active"
        and getattr(contract, "id", None) not in documented_contract_ids
    )


def _count_overdue_maintenance(maintenance_cases: list, check_date: date) -> int:
    return sum(
        1
        for case in maintenance_cases
        if _status(case) in _OPEN_MAINTENANCE_STATUSES
        and getattr(case, "due_date", None)
        and case.due_date < check_date
    )


def _count_maintenance_escalation_candidates(
    maintenance_cases: list,
    escalation_rules: list,
    check_date: date,
) -> int:
    maintenance_rules = [
        rule
        for rule in escalation_rules
        if getattr(rule, "is_active", False)
        and str(getattr(rule, "entity_type", "")).lower() == "maintenance"
    ]
    if not maintenance_rules:
        return 0

    candidate_ids: set[str] = set()
    for rule in maintenance_rules:
        cutoff = check_date - timedelta(days=max(0, int(getattr(rule, "days_overdue", 0) or 0)))
        for case in maintenance_cases:
            if (
                _status(case) in _OPEN_MAINTENANCE_STATUSES
                and getattr(case, "due_date", None)
                and case.due_date <= cutoff
                and getattr(case, "id", None)
            ):
                candidate_ids.add(case.id)
    return len(candidate_ids)


def _contract_overlaps_period(contract, period) -> bool:
    if _status(contract) != "active":
        return False
    if getattr(contract, "property_id", None) != getattr(period, "property_id", None):
        return False
    start_date = getattr(contract, "start_date", None)
    period_start = getattr(period, "start_date", None)
    period_end = getattr(period, "end_date", None)
    if not start_date or not period_start or not period_end:
        return False
    end_date = getattr(contract, "end_date", None)
    return start_date <= period_end and (end_date is None or end_date >= period_start)


def _billing_preflight_summary(
    billing_periods: list,
    contracts: list,
    cost_items: list,
    allocation_keys: list,
) -> dict[str, int]:
    blockers = 0
    warnings = 0
    periods_checked = 0
    allocation_key_properties = {
        key.id: key.property_id
        for key in allocation_keys
        if getattr(key, "id", None) and getattr(key, "property_id", None)
    }

    for period in billing_periods:
        if _status(period) not in _PRE_FINAL_BILLING_STATUSES:
            continue

        periods_checked += 1
        period_costs = [
            item for item in cost_items
            if getattr(item, "billing_period_id", None) == getattr(period, "id", None)
        ]
        contracts_in_period = [
            contract for contract in contracts
            if _contract_overlaps_period(contract, period)
        ]

        has_blocker = not contracts_in_period or not period_costs
        for item in period_costs:
            key_id = getattr(item, "allocation_key_id", None)
            if allocation_key_properties.get(key_id) != getattr(period, "property_id", None):
                has_blocker = True
            if float(getattr(item, "amount", 0) or 0) <= 0:
                warnings += 1

        if has_blocker:
            blockers += 1

    return {
        "blockers": blockers,
        "warnings": warnings,
        "periods_checked": periods_checked,
    }


@router.get("/stats")
def get_dashboard_stats() -> dict:
    """Return aggregated entity counts for the dashboard.

    Uses direct counts for core inventory and existing list APIs for
    workflow-specific operational totals.
    """
    today = date.today()
    contracts = store.list_contracts()
    invoices = store.list_invoices()
    receivables = store.list_receivables()
    documents = store.list_documents()
    maintenance_cases = store.list_maintenance_cases()
    tasks = store.list_tasks()
    notifications = store.list_notifications()
    rent_charges = store.list_rent_charges()
    billing_periods = store.list_billing_periods()
    cost_items = store.list_cost_items()
    allocation_keys = store.list_allocation_keys()
    utility_statements = store.list_utility_statements()
    escalation_rules = store.list_escalation_rules()
    billing_preflight = _billing_preflight_summary(
        billing_periods=billing_periods,
        contracts=contracts,
        cost_items=cost_items,
        allocation_keys=allocation_keys,
    )

    return {
        "portfolio_count": store.count_entities("portfolio"),
        "property_count": store.count_entities("property"),
        "unit_count": store.count_entities("unit"),
        "tenant_count": store.count_entities("tenant"),
        "contract_count": _count_items(contracts),
        "account_count": store.count_entities("account"),
        "vacant_units": store.count_entities("unit", {"status": "vacant"}),
        "occupied_units": store.count_entities("unit", {"status": "occupied"}),
        "reserved_units": store.count_entities("unit", {"status": "reserved"}),
        "active_contracts": _count_items(contracts, {"status": "active"}),
        "open_maintenance": store.count_entities("maintenance", {"status": "open"}),
        "invoice_count": _count_items(invoices),
        "open_invoices": _count_items(invoices, {"status": "open"}),
        "paid_invoices": _count_items(invoices, {"status": "paid"}),
        "receivable_count": _count_items(receivables),
        "open_receivables": _count_items(receivables, {"status": "open"}),
        "paid_receivables": _count_items(receivables, {"status": "paid"}),
        "overdue_receivables": _count_items(receivables, {"status": "overdue"}),
        "dunning_receivables": _count_dunning_receivables(receivables),
        "document_count": _count_items(documents),
        "active_contracts_missing_documents": _count_missing_contract_documents(
            contracts,
            documents,
        ),
        "overdue_maintenance": _count_overdue_maintenance(maintenance_cases, today),
        "active_escalation_rules": _count_items(escalation_rules, {"is_active": True}),
        "maintenance_escalation_candidates": _count_maintenance_escalation_candidates(
            maintenance_cases,
            escalation_rules,
            today,
        ),
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
        "billing_preflight_periods_checked": billing_preflight["periods_checked"],
        "billing_preflight_blockers": billing_preflight["blockers"],
        "billing_preflight_warnings": billing_preflight["warnings"],
        "allocation_key_count": _count_items(allocation_keys),
        "utility_statement_count": _count_items(utility_statements),
        "draft_utility_statements": _count_items(utility_statements, {"status": "draft"}),
        "finalized_utility_statements": _count_items(utility_statements, {"status": "finalized"}),
    }
