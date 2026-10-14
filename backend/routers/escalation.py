"""Escalation rules and execution router (T17)."""

from datetime import date, timedelta

from fastapi import APIRouter, HTTPException, Query, status

from ..dependencies import store
from ..domain.receivables import is_unpaid_debt
from ..models import (
    EscalationRule,
    EscalationRuleCreate,
    EscalationRulePatch,
    NotificationCreate,
)
from ..services.notifier import OPEN_WORK_STATUSES, Notifier, day, eur, receivable_debtor
from ..storage import NotFoundError

router = APIRouter(prefix="/escalation", tags=["Eskalation"])


@router.get("/rules", response_model=list[EscalationRule])
def list_rules(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    entity_type: str | None = Query(None),
    is_active: bool | None = Query(None),
):
    results = store.list_escalation_rules()
    if entity_type:
        results = [r for r in results if r.entity_type == entity_type]
    if is_active is not None:
        results = [r for r in results if r.is_active == is_active]
    return results[skip: skip + limit]


@router.post("/rules", response_model=EscalationRule, status_code=status.HTTP_201_CREATED)
def create_rule(payload: EscalationRuleCreate):
    return store.create_escalation_rule(payload)


@router.get("/rules/{rule_id}", response_model=EscalationRule)
def get_rule(rule_id: str):
    try:
        return store.get_escalation_rule(rule_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.put("/rules/{rule_id}", response_model=EscalationRule)
def update_rule(rule_id: str, payload: EscalationRuleCreate):
    try:
        return store.update_escalation_rule(rule_id, payload)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.patch("/rules/{rule_id}", response_model=EscalationRule)
def patch_rule(rule_id: str, payload: EscalationRulePatch):
    try:
        return store._patch_entity("escalation_rule", rule_id, payload)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/rules/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_rule(rule_id: str):
    try:
        store.delete_escalation_rule(rule_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/run", response_model=None)
def run_escalation(as_of: date | None = Query(None)):
    """Execute all active escalation rules and notify once per rule and overdue item."""
    return execute_escalation(store, as_of or date.today())


def execute_escalation(store, check_date: date) -> dict:
    """Shared by the endpoint and the scheduled job; repeats are suppressed by the Notifier."""
    rules = [r for r in store.list_escalation_rules() if r.is_active]
    notifier = Notifier(store)
    generated = []

    def escalate(rule, entity_type: str, entity_id: str, title: str, content: str) -> None:
        notif = notifier.notify(NotificationCreate(
            notification_type="escalation",
            title=title,
            content=f"{content} Regel: {rule.name}",
            severity=rule.notification_severity,
            entity_type=entity_type,
            entity_id=entity_id,
        ))
        if notif:
            generated.append(notif.id)

    for rule in rules:
        cutoff = check_date - timedelta(days=rule.days_overdue)
        overdue_for = f"seit mindestens {rule.days_overdue} Tagen überfällig"

        if rule.entity_type == "task":
            for task in store.list_tasks():
                if task.status in OPEN_WORK_STATUSES and task.due_date and task.due_date <= cutoff:
                    escalate(rule, "task", task.id, f"Eskalation: {task.title}",
                             f"Aufgabe „{task.title}“ (fällig am {day(task.due_date)}) ist {overdue_for}.")

        elif rule.entity_type == "maintenance":
            for case in store.list_maintenance_cases():
                if case.status in OPEN_WORK_STATUSES and case.due_date and case.due_date <= cutoff:
                    escalate(rule, "maintenance", case.id, f"Eskalation: {case.title}",
                             f"Instandhaltungsfall „{case.title}“ (fällig am {day(case.due_date)}) ist {overdue_for}.")

        elif rule.entity_type == "receivable":
            for receivable in store.list_receivables():
                if is_unpaid_debt(receivable) and receivable.due_date <= cutoff:
                    tenant_name, contract_number = receivable_debtor(store, receivable)
                    escalate(rule, "receivable", receivable.id, f"Eskalation: Überfällige Forderung – {tenant_name}",
                             f"Forderung über {eur(receivable.amount_due)} aus Vertrag {contract_number}"
                             f" (fällig am {day(receivable.due_date)}) ist {overdue_for}.")

    return {"rules_checked": len(rules), "notifications_generated": len(generated), "notification_ids": generated}
