"""Exact dashboard workflow sources, filtered before SQL pagination."""

from datetime import date, timedelta
from typing import Any

from sqlalchemy import and_, case, exists, func, or_, select

from ..db.orm_models import (
    AllocationKeyORM,
    BillingPeriodORM,
    ContractORM,
    CostItemORM,
    EscalationRuleORM,
    MaintenanceCaseORM,
)
from ..domain.occupancy import NON_BILLABLE_STATUSES, billable_contracts
from ..models import BillingPeriod, MaintenanceCase

OPEN_MAINTENANCE = frozenset({"open", "in_progress", "pending", "review"})
PRE_FINAL_BILLING = frozenset({"draft", "review", "open"})


def escalation_days(rules: Any) -> int | None:
    days = [max(0, int(getattr(rule, "days_overdue", 0) or 0)) for rule in rules
            if getattr(rule, "is_active", False) and str(getattr(rule, "entity_type", "")).lower() == "maintenance"]
    return min(days) if days else None


def escalation_matches(record: Any, days: int | None, today: date) -> bool:
    return bool(days is not None and record.id and str(record.status or "").lower() in OPEN_MAINTENANCE
                and record.due_date is not None and record.due_date <= today - timedelta(days=days))


def billing_blocked(period: Any, contracts: Any, costs: Any, allocation_key_properties: dict) -> bool:
    if str(period.status or "").lower() not in PRE_FINAL_BILLING:
        return False
    period_costs = [row for row in costs if row.billing_period_id == period.id]
    return (not billable_contracts(contracts, period.property_id, period.start_date, period.end_date)
            or not period_costs or any(allocation_key_properties.get(row.allocation_key_id) != period.property_id
                                      for row in period_costs))


def _model(model: Any, orm: Any, row: Any):
    return model.model_validate({column.key: getattr(row, column.key) for column in orm.__table__.c})


def escalation_cases(store: Any, *, skip: int, limit: int, property_id: str | None = None,
                     status_filter: str | None = None, sort_by: str | None = None, descending: bool = False,
                     date_from: date | None = None, date_to: date | None = None) -> list[MaintenanceCase]:
    today = date.today()  # same calendar as the dashboard count
    if hasattr(store, "db"):
        days = store.db.scalar(select(func.min(case((EscalationRuleORM.days_overdue > 0,
            EscalationRuleORM.days_overdue), else_=0))).where(EscalationRuleORM.is_active.is_(True),
            func.lower(EscalationRuleORM.entity_type) == "maintenance"))
        if days is None:
            return []
        query = select(MaintenanceCaseORM).where(func.lower(func.coalesce(MaintenanceCaseORM.status, "")).in_(OPEN_MAINTENANCE),
            MaintenanceCaseORM.due_date <= today - timedelta(days=int(days)))
        if property_id:
            query = query.where(MaintenanceCaseORM.property_id == property_id)
        if status_filter:
            query = query.where(MaintenanceCaseORM.status == status_filter)
        if date_from:
            query = query.where(MaintenanceCaseORM.due_date >= date_from)
        if date_to:
            query = query.where(MaintenanceCaseORM.due_date <= date_to)
        column: Any = MaintenanceCaseORM.__table__.c.get(sort_by or "id")
        if column is None:
            column = MaintenanceCaseORM.id
        query = query.order_by(column.desc() if descending else column.asc(), MaintenanceCaseORM.id).offset(skip).limit(limit)
        return [_model(MaintenanceCase, MaintenanceCaseORM, row) for row in store.db.scalars(query)]
    days = escalation_days(store.escalation_rules.values())
    rows = [row for row in store.maintenance_cases.values() if escalation_matches(row, days, today)
        and (not property_id or row.property_id == property_id) and (not status_filter or row.status == status_filter)
        and (not date_from or row.due_date >= date_from) and (not date_to or row.due_date <= date_to)]
    key = sort_by if sort_by in MaintenanceCase.model_fields else "id"
    rows.sort(key=lambda row: (getattr(row, key) is None, getattr(row, key), row.id), reverse=descending)
    return rows[skip:skip + limit]


def billing_blockers(store: Any, *, skip: int, limit: int, property_id: str | None = None,
                     status_filter: str | None = None) -> list[BillingPeriod]:
    if hasattr(store, "db"):
        tenancy = exists(select(ContractORM.id).where(ContractORM.property_id == BillingPeriodORM.property_id,
            ContractORM.status.not_in(NON_BILLABLE_STATUSES), ContractORM.start_date <= BillingPeriodORM.end_date,
            or_(ContractORM.end_date.is_(None), ContractORM.end_date >= BillingPeriodORM.start_date)))
        costs = exists(select(CostItemORM.id).where(CostItemORM.billing_period_id == BillingPeriodORM.id))
        right_key = exists(select(AllocationKeyORM.id).where(AllocationKeyORM.id == CostItemORM.allocation_key_id,
            AllocationKeyORM.property_id == BillingPeriodORM.property_id).correlate(CostItemORM, BillingPeriodORM))
        invalid = exists(select(CostItemORM.id).where(CostItemORM.billing_period_id == BillingPeriodORM.id,
            ~right_key).correlate(BillingPeriodORM))
        query = select(BillingPeriodORM).where(and_(func.lower(func.coalesce(BillingPeriodORM.status, "")).in_(PRE_FINAL_BILLING),
            or_(~tenancy, ~costs, invalid)))
        if property_id:
            query = query.where(BillingPeriodORM.property_id == property_id)
        if status_filter:
            query = query.where(BillingPeriodORM.status == status_filter)
        query = query.order_by(BillingPeriodORM.id).offset(skip).limit(limit)
        return [_model(BillingPeriod, BillingPeriodORM, row) for row in store.db.scalars(query)]
    contracts = store.contracts.values()
    costs = store.cost_items.values()
    properties = {key.id: key.property_id for key in store.allocation_keys.values() if key.id and key.property_id}
    rows = [row for row in store.billing_periods.values() if billing_blocked(row, contracts, costs, properties)
        and (not property_id or row.property_id == property_id) and (not status_filter or row.status == status_filter)]
    return sorted(rows, key=lambda row: row.id)[skip:skip + limit]
