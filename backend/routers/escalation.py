"""Escalation rules and execution router (T17)."""

from datetime import date, timedelta

from fastapi import APIRouter, HTTPException, Query, status

from ..dependencies import store
from ..models import (
    EscalationRule,
    EscalationRuleCreate,
    EscalationRulePatch,
    NotificationCreate,
)
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
    """Execute all active escalation rules and generate notifications."""
    check_date = as_of or date.today()
    rules = [r for r in store.list_escalation_rules() if r.is_active]
    generated = []

    for rule in rules:
        cutoff = check_date - timedelta(days=rule.days_overdue)

        if rule.entity_type == "task":
            items = [t for t in store.list_tasks()
                     if t.status == "open" and t.due_date and t.due_date <= cutoff]
            for item in items:
                notif = store.create_notification(NotificationCreate(
                    notification_type="escalation",
                    title=f"Eskalation: {item.title}",
                    content=f"Aufgabe '{item.title}' ist seit {rule.days_overdue} Tagen überfällig. Regel: {rule.name}",
                    severity=rule.notification_severity,
                    entity_type="task",
                    entity_id=item.id,
                ))
                generated.append(notif.id)

        elif rule.entity_type == "maintenance":
            items = [m for m in store.list_maintenance_cases()
                     if m.status == "open" and m.due_date and m.due_date <= cutoff]
            for item in items:
                notif = store.create_notification(NotificationCreate(
                    notification_type="escalation",
                    title=f"Eskalation: {item.title}",
                    content=(
                        f"Instandhaltungsfall '{item.title}' ist seit"
                        f" {rule.days_overdue} Tagen überfällig. Regel: {rule.name}"
                    ),
                    severity=rule.notification_severity,
                    entity_type="maintenance",
                    entity_id=item.id,
                ))
                generated.append(notif.id)

        elif rule.entity_type == "receivable":
            items = [r for r in store.list_receivables()
                     if r.status == "open" and r.due_date <= cutoff]
            for item in items:
                notif = store.create_notification(NotificationCreate(
                    notification_type="escalation",
                    title="Eskalation: Überfällige Forderung",
                    content=(
                        f"Forderung {item.id} ist seit {rule.days_overdue} Tagen überfällig."
                        f" Betrag: {item.amount_due:.2f}€. Regel: {rule.name}"
                    ),
                    severity=rule.notification_severity,
                    entity_type="receivable",
                    entity_id=item.id,
                ))
                generated.append(notif.id)

    return {"rules_checked": len(rules), "notifications_generated": len(generated), "notification_ids": generated}
