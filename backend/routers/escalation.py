"""Escalation rules and execution router (T17)."""

from datetime import date

from fastapi import APIRouter, HTTPException, Query, status

from ..dependencies import store
from ..models import (
    EscalationRule,
    EscalationRuleCreate,
    EscalationRulePatch,
)
from ..services.operational_schedule import TickRequest, operational_tick, validate_escalation
from ..services.recurrence import CatchUpLimit
from ..storage import NotFoundError, ValidationError

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
    try:
        validate_escalation(payload)
        return store.create_escalation_rule(payload)
    except ValidationError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.get("/rules/{rule_id}", response_model=EscalationRule)
def get_rule(rule_id: str):
    try:
        return store.get_escalation_rule(rule_id)
    except (NotFoundError, ValidationError) as exc:
        raise HTTPException(404 if isinstance(exc, NotFoundError) else 400, str(exc)) from exc


@router.put("/rules/{rule_id}", response_model=EscalationRule)
def update_rule(rule_id: str, payload: EscalationRuleCreate):
    try:
        validate_escalation(payload)
        return store.update_escalation_rule(rule_id, payload)
    except (NotFoundError, ValidationError) as exc:
        raise HTTPException(404 if isinstance(exc, NotFoundError) else 400, str(exc)) from exc


@router.patch("/rules/{rule_id}", response_model=EscalationRule)
def patch_rule(rule_id: str, payload: EscalationRulePatch):
    try:
        current = store.get_escalation_rule(rule_id)
        merged = EscalationRuleCreate(**{**current.model_dump(include=set(EscalationRuleCreate.model_fields)), **payload.model_dump(exclude_unset=True)})
        validate_escalation(merged)
        return store._patch_entity("escalation_rule", rule_id, payload)
    except (NotFoundError, ValidationError) as exc:
        raise HTTPException(404 if isinstance(exc, NotFoundError) else 400, str(exc)) from exc


@router.delete("/rules/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_rule(rule_id: str):
    try:
        store.delete_escalation_rule(rule_id)
    except (NotFoundError, ValidationError) as exc:
        raise HTTPException(404 if isinstance(exc, NotFoundError) else 400, str(exc)) from exc


@router.post("/run", response_model=None)
def run_escalation(as_of: date | None = Query(None)):
    try:
        result = operational_tick(store, TickRequest(as_of=as_of if isinstance(as_of, date) else date.today()), kinds={"escalation"})
        return {key: result[key] for key in ("rules_checked", "notifications_generated", "notification_ids", "warnings")}
    except (ValidationError, CatchUpLimit) as exc:
        raise HTTPException(409, str(exc)) from exc
