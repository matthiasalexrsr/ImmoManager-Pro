"""Router for billing periods, allocation keys, cost items, and utility statements.

Includes a POST endpoint to auto-generate utility statements from cost items
using the BillingEngine for cost allocation.

Status machine for billing periods:
  draft -> review -> finalized -> delivered
  finalized/delivered -> disputed (an objection was recorded)
  finalized/delivered/disputed -> corrected (when its correction is finalized)

Statements of a finalized period are the issued version and never change:
not by regeneration, edits of the period or its costs, or later edits of
contracts, meters and names (the shown document is frozen at finalization).
A correction is a new period that names the version it corrects.
"""

import hashlib
import logging
import re
from contextlib import ExitStack
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import ValidationError as ModelValidationError
from sqlalchemy.exc import IntegrityError

from .. import auth
from ..auth import require_role
from ..dependencies import store
from ..models import (
    AllocationKey,
    AllocationKeyCreate,
    AllocationKeyPatch,
    BillingObjection,
    BillingObjectionCreate,
    BillingObjectionRejection,
    BillingObjectionRequest,
    BillingPeriod,
    BillingPeriodCreate,
    BillingPeriodPatch,
    BillingPreflightIssue,
    BillingPreflightResult,
    CostItem,
    CostItemCreate,
    CostItemPatch,
    UserRead,
    UtilityStatement,
    UtilityStatementPatch,
)
from ..services import business_qol as objection_commands
from ..services.billing_writes import atomic_billing, billing_write
from ..services.document_versions import Unit, check_account
from ..services.final_statements import (
    EDITABLE_STATUSES,
    FINAL_STATUSES,
    final_version_problems,
    json_safe,
    statement_snapshot_hash,
)
from ..services.portfolio_scope import current_scope, refresh_scope, scope_context, scope_from_user
from ..services.service_contracts import check_cost_item_origin
from ..services.utility_billing import compute_period_billing
from ..storage import NotFoundError, ValidationError

# Days a tenant has to settle a back payment after the statement was issued.
RECEIVABLE_DUE_DAYS = 30

# Valid status transitions for billing periods
_PERIOD_TRANSITIONS: dict[str, set[str]] = {
    "draft": {"review", "finalized"},
    "review": {"draft", "finalized"},
    "finalized": {"delivered", "corrected", "disputed"},
    "delivered": {"disputed", "corrected"},
    "disputed": {"disputed", "corrected"},  # a further objection keeps it disputed
    "corrected": set(),
}

# Every status after finalizing: the statements are issued and stay as they are,
# also while an objection is open (it is answered by a correction, a new period).
_IMMUTABLE_STATUSES = set(FINAL_STATUSES)
_CORRECTABLE_STATUSES = {"finalized", "delivered", "disputed"}
_STATUS_ONLY_BY_WORKFLOW = ("Der Status ändert sich nur über die Arbeitsschritte (Prüfung, Finalisieren, "
                            "Widerspruch, Korrektur)")


def _assert_period_mutable(period: BillingPeriod) -> None:
    """Raise 409 if the period is in an immutable state."""
    if period.status in _IMMUTABLE_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Periode ist '{period.status}' und kann nicht mehr bearbeitet werden; "
                   "Änderungen nur über eine Korrektur",
        )


def _period_statements(period_id: str) -> list[UtilityStatement]:
    return [s for s in store.list_utility_statements() if s.billing_period_id == period_id]


def _compute_snapshot_hash(period_id: str) -> str:
    """Compute a deterministic SHA-256 hash over all statement data for a period."""
    return statement_snapshot_hash(_period_statements(period_id))


def _set_period_status(period_id: str, new_status: str) -> BillingPeriod:
    """Change only the status; revision and correction link stay."""
    return store._patch_entity("billing_period", period_id, BillingPeriodPatch(status=new_status))

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/billing", tags=["Abrechnung"])


# ---------------------------------------------------------------------------
# Billing Periods
# ---------------------------------------------------------------------------


@router.get("/periods", response_model=list[BillingPeriod])
def list_billing_periods(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    property_id: str | None = Query(None),
    status_filter: str | None = Query(None, alias="status"),
    workflow_filter: Literal["preflight_blockers"] | None = Query(None),
) -> list[BillingPeriod]:
    if workflow_filter == "preflight_blockers":
        from ..services.business_kpi_sources import billing_blockers
        return billing_blockers(store, skip=skip, limit=limit, property_id=property_id, status_filter=status_filter)
    results = store.list_billing_periods()
    if property_id:
        results = [r for r in results if r.property_id == property_id]
    if status_filter:
        results = [r for r in results if r.status == status_filter]
    return results[skip : skip + limit]


@router.post("/periods", response_model=BillingPeriod, status_code=status.HTTP_201_CREATED)
def create_billing_period(payload: BillingPeriodCreate) -> BillingPeriod:
    if payload.status != "draft":
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail=f"Eine neue Periode beginnt als Entwurf. {_STATUS_ONLY_BY_WORKFLOW}")
    if payload.corrects_period_id or payload.revision != 1:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail="Korrekturen entstehen nur über „Korrektur starten“ an der finalisierten Fassung")
    try:
        return store.create_billing_period(payload)
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/periods/{period_id}", response_model=BillingPeriod)
def get_billing_period(period_id: str) -> BillingPeriod:
    try:
        return store.get_billing_period(period_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.put("/periods/{period_id}", response_model=BillingPeriod)
@atomic_billing(lambda: store, period_arg="period_id")
def update_billing_period(period_id: str, payload: BillingPeriodCreate) -> BillingPeriod:
    try:
        existing = store.get_billing_period(period_id)
        _assert_period_mutable(existing)
        if "status" in payload.model_fields_set and payload.status != existing.status:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=_STATUS_ONLY_BY_WORKFLOW)
        # status, revision and correction link are not edited here
        kept = {"status": existing.status, "revision": existing.revision,
                "corrects_period_id": existing.corrects_period_id, "revision_notes": existing.revision_notes}
        return store.update_billing_period(period_id, payload.model_copy(update=kept))
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.patch("/periods/{period_id}", response_model=BillingPeriod)
@atomic_billing(lambda: store, period_arg="period_id")
def patch_billing_period(period_id: str, payload: BillingPeriodPatch) -> BillingPeriod:
    try:
        existing = store.get_billing_period(period_id)
        _assert_period_mutable(existing)
        if payload.status is not None and payload.status != existing.status:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=_STATUS_ONLY_BY_WORKFLOW)
        return store._patch_entity("billing_period", period_id, payload)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.delete("/periods/{period_id}", status_code=status.HTTP_204_NO_CONTENT)
@atomic_billing(lambda: store, period_arg="period_id")
def delete_billing_period(period_id: str) -> None:
    try:
        existing = store.get_billing_period(period_id)
        _assert_period_mutable(existing)
        if any(o.correction_period_id == period_id and o.decision_key
               for o in store.list_billing_objections()):
            raise HTTPException(409, "Diese Korrektur gehört zu einer dokumentierten Entscheidung; "
                                     "bitte den Entwurf weiter bearbeiten und den Entscheidungsbeleg erhalten")
        store.delete_billing_period(period_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# Allocation Keys
# ---------------------------------------------------------------------------


@router.get("/allocation-keys", response_model=list[AllocationKey])
def list_allocation_keys(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    property_id: str | None = Query(None),
    key_type: str | None = Query(None),
) -> list[AllocationKey]:
    results = store.list_allocation_keys()
    if property_id:
        results = [r for r in results if r.property_id == property_id]
    if key_type:
        results = [r for r in results if r.key_type == key_type]
    return results[skip : skip + limit]


@router.post("/allocation-keys", response_model=AllocationKey, status_code=status.HTTP_201_CREATED)
def create_allocation_key(payload: AllocationKeyCreate) -> AllocationKey:
    try:
        return store.create_allocation_key(payload)
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/allocation-keys/{key_id}", response_model=AllocationKey)
def get_allocation_key(key_id: str) -> AllocationKey:
    try:
        return store.get_allocation_key(key_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.put("/allocation-keys/{key_id}", response_model=AllocationKey)
def update_allocation_key(key_id: str, payload: AllocationKeyCreate) -> AllocationKey:
    try:
        return store.update_allocation_key(key_id, payload)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.patch("/allocation-keys/{key_id}", response_model=AllocationKey)
def patch_allocation_key(key_id: str, payload: AllocationKeyPatch) -> AllocationKey:
    try:
        return store._patch_entity("allocation_key", key_id, payload)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.delete("/allocation-keys/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_allocation_key(key_id: str) -> None:
    # Deleting a key took its cost items with it, also those of finalized periods.
    used = [ci for ci in store.list_cost_items() if ci.allocation_key_id == key_id]
    if used:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Verteilerschlüssel kann nicht gelöscht werden: {len(used)} Kostenposition(en) verwenden ihn",
        )
    try:
        store.delete_allocation_key(key_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# Cost Items
# ---------------------------------------------------------------------------


@router.get("/cost-items", response_model=list[CostItem])
def list_cost_items(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    billing_period_id: str | None = Query(None),
    allocation_key_id: str | None = Query(None),
) -> list[CostItem]:
    results = store.list_cost_items()
    if billing_period_id:
        results = [r for r in results if r.billing_period_id == billing_period_id]
    if allocation_key_id:
        results = [r for r in results if r.allocation_key_id == allocation_key_id]
    return results[skip : skip + limit]


@router.post("/cost-items", response_model=CostItem, status_code=status.HTTP_201_CREATED)
@atomic_billing(lambda: store, destination_arg="payload")
def create_cost_item(payload: CostItemCreate) -> CostItem:
    try:
        period = store.get_billing_period(payload.billing_period_id)
        _assert_period_mutable(period)
    except NotFoundError:
        pass  # Let store.create_cost_item raise its own ValidationError
    try:
        check_cost_item_origin(store, payload)
        return store.create_cost_item(payload)
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/cost-items/{item_id}", response_model=CostItem)
def get_cost_item(item_id: str) -> CostItem:
    try:
        return store.get_cost_item(item_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.put("/cost-items/{item_id}", response_model=CostItem)
@atomic_billing(lambda: store, cost_arg="item_id", destination_arg="payload")
def update_cost_item(item_id: str, payload: CostItemCreate) -> CostItem:
    try:
        existing = store.get_cost_item(item_id)
        period = store.get_billing_period(existing.billing_period_id)
        _assert_period_mutable(period)
        if payload.billing_period_id != existing.billing_period_id:
            _assert_period_mutable(store.get_billing_period(payload.billing_period_id))
        # the origin of a transferred bill stays: otherwise the bill could be transferred twice
        payload = payload.model_copy(update={"service_contract_invoice_id": existing.service_contract_invoice_id})
        check_cost_item_origin(store, payload, exclude_id=item_id)
        return store.update_cost_item(item_id, payload)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.patch("/cost-items/{item_id}", response_model=CostItem)
@atomic_billing(lambda: store, cost_arg="item_id", destination_arg="payload")
def patch_cost_item(item_id: str, payload: CostItemPatch) -> CostItem:
    try:
        existing = store.get_cost_item(item_id)
        period = store.get_billing_period(existing.billing_period_id)
        _assert_period_mutable(period)
        if payload.billing_period_id is not None and payload.billing_period_id != existing.billing_period_id:
            _assert_period_mutable(store.get_billing_period(payload.billing_period_id))
        # PATCH must enforce the same source-invoice binding as PUT, using the full resulting cost.
        updated = CostItemCreate.model_validate({
            **existing.model_dump(include=set(CostItemCreate.model_fields)),
            **payload.model_dump(exclude_unset=True),
        })
        check_cost_item_origin(store, updated, exclude_id=item_id)
        return store._patch_entity("cost_item", item_id, payload)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except (ValidationError, ModelValidationError) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.delete("/cost-items/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
@atomic_billing(lambda: store, cost_arg="item_id")
def delete_cost_item(item_id: str) -> None:
    try:
        existing = store.get_cost_item(item_id)
        period = store.get_billing_period(existing.billing_period_id)
        _assert_period_mutable(period)
        store.delete_cost_item(item_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/periods/{period_id}/preflight", response_model=BillingPreflightResult)
def get_billing_period_preflight(period_id: str) -> BillingPreflightResult:
    return _run_billing_period_preflight(period_id)


def _run_billing_period_preflight(period_id: str) -> BillingPreflightResult:
    try:
        period = store.get_billing_period(period_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    billing = compute_period_billing(store, period)
    issues = [
        BillingPreflightIssue(code=i.code, message=i.message, severity=i.severity, context=i.context)
        for i in billing.issues
    ]
    metrics = dict(billing.metrics)
    if period.status not in _IMMUTABLE_STATUSES:
        if _statements_outdated(period_id, billing):
            issues.append(BillingPreflightIssue(
                code="STATEMENTS_OUTDATED",
                message="Die Einzelabrechnungen entsprechen nicht mehr den Daten; bitte neu erzeugen",
                severity="warning",
            ))
    else:
        problems = final_version_problems(period, _period_statements(period_id))
        metrics["final_version_intact"] = not problems
        if problems:
            issues.append(BillingPreflightIssue(
                code="FINAL_VERSION_ALTERED",
                message="Die gespeicherten Einzelabrechnungen entsprechen nicht der finalisierten Fassung",
                severity="blocker", context="; ".join(problems),
            ))
        elif _statements_outdated(period_id, billing):
            issues.append(BillingPreflightIssue(
                code="FINAL_VERSION_DIFFERS",
                message="Die heutigen Daten ergeben eine andere Abrechnung; die finalisierte Fassung bleibt "
                        "unverändert, Änderungen nur über eine Korrektur",
                severity="warning",
            ))
    blockers = [i for i in issues if i.severity == "blocker"]
    return BillingPreflightResult(
        billing_period_id=period_id,
        has_blockers=bool(blockers),
        blockers=blockers,
        warnings=[i for i in issues if i.severity != "blocker"],
        metrics=metrics,
    )


def _statement_fingerprint(stmt: Any) -> tuple:
    # Strings throughout: vacancy rows have no contract, old rows no usage dates.
    return (
        stmt.unit_id, stmt.contract_id or "", stmt.party, str(stmt.usage_start or ""), str(stmt.usage_end or ""),
        round(float(stmt.total_cost), 2), round(float(stmt.advance_paid), 2),
    )


def _statements_outdated(period_id: str, billing: Any) -> bool:
    """True if stored statements exist and differ from what the current data gives."""
    stored = [s for s in store.list_utility_statements() if s.billing_period_id == period_id]
    if not stored:
        return False
    if billing.blockers:
        return True
    return sorted(map(_statement_fingerprint, stored)) != sorted(map(_statement_fingerprint, billing.statements))


@router.post("/periods/{period_id}/submit-review", response_model=BillingPeriod)
@atomic_billing(lambda: store, period_arg="period_id")
def submit_period_for_review(period_id: str) -> BillingPeriod:
    """Transition period from draft to review status."""
    try:
        period = store.get_billing_period(period_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    if period.status != "draft":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Nur Perioden im Status 'draft' können zur Prüfung eingereicht werden (aktuell: '{period.status}')",
        )

    return _set_period_status(period_id, "review")


@router.post("/periods/{period_id}/revert-draft", response_model=BillingPeriod)
@atomic_billing(lambda: store, period_arg="period_id")
def revert_period_to_draft(period_id: str) -> BillingPeriod:
    """Revert period from review back to draft."""
    try:
        period = store.get_billing_period(period_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    if period.status != "review":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Nur Perioden im Status 'review' können zurückgesetzt werden (aktuell: '{period.status}')",
        )

    return _set_period_status(period_id, "draft")


@router.post("/periods/{period_id}/finalize", response_model=BillingPeriod)
@atomic_billing(lambda: store, period_arg="period_id")
def finalize_billing_period(period_id: str) -> BillingPeriod:
    """Finalize billing period after successful preflight and generated statements.

    Allowed from 'draft' or 'review' status. Freezes what each statement shows
    (names, addresses, rows, totals), computes a snapshot hash over the content
    and stamps it on all statements. Finalizing a correction marks the version
    it corrects as 'corrected' (that version itself stays as issued).
    """
    try:
        period = store.get_billing_period(period_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    if period.status == "finalized":
        return period

    if period.status not in EDITABLE_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Finalisierung nur aus 'draft' oder 'review' möglich (aktuell: '{period.status}')",
        )

    preflight = _run_billing_period_preflight(period_id)
    if preflight.has_blockers:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Finalisierung blockiert: Preflight enthält Blocker",
        )

    period_statements = _period_statements(period_id)
    if not period_statements:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Finalisierung nicht möglich: Keine Einzelabrechnungen vorhanden",
        )
    if _statements_outdated(period_id, compute_period_billing(store, period)):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Finalisierung nicht möglich: Die Einzelabrechnungen sind veraltet, bitte neu erzeugen",
        )

    # Freeze the document first: the hash covers it, later edits of names cannot change it.
    for stmt in period_statements:
        if not stmt.snapshot_hash:
            store._patch_entity("utility_statement", stmt.id, UtilityStatementPatch(
                final_document=json_safe(_live_statement_document(stmt, period))))
    snapshot = _compute_snapshot_hash(period_id)
    for stmt in _period_statements(period_id):
        patch_data: dict[str, Any] = {}
        if stmt.status != "finalized":
            patch_data["status"] = "finalized"
        if not stmt.snapshot_hash:
            patch_data["snapshot_hash"] = snapshot
        if patch_data:
            store._patch_entity("utility_statement", stmt.id, UtilityStatementPatch(**patch_data))

    finalized = _set_period_status(period_id, "finalized")
    if period.corrects_period_id:
        _close_corrected_version(period)
    return finalized


def _close_corrected_version(correction: BillingPeriod) -> None:
    """The version a finalized correction replaces: status 'corrected', its objections resolved."""
    try:
        source = store.get_billing_period(correction.corrects_period_id or "")
    except NotFoundError:
        return
    if source.status in _CORRECTABLE_STATUSES:
        _set_period_status(source.id, "corrected")
    for objection in store.list_billing_objections(source.id):
        if objection.status not in {"resolved", "rejected"}:
            _save_objection(objection, status="resolved", correction_period_id=correction.id)


# ---------------------------------------------------------------------------
# Utility Statements
# ---------------------------------------------------------------------------


@router.get("/statements", response_model=list[UtilityStatement])
def list_utility_statements(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    billing_period_id: str | None = Query(None),
    contract_id: str | None = Query(None),
    status_filter: str | None = Query(None, alias="status"),
) -> list[UtilityStatement]:
    results = store.list_utility_statements()
    if billing_period_id:
        results = [r for r in results if r.billing_period_id == billing_period_id]
    if contract_id:
        results = [r for r in results if r.contract_id == contract_id]
    if status_filter:
        results = [r for r in results if r.status == status_filter]
    return results[skip : skip + limit]


@router.get("/statements/{statement_id}", response_model=UtilityStatement)
def get_utility_statement(statement_id: str) -> UtilityStatement:
    try:
        return store.get_utility_statement(statement_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.patch("/statements/{statement_id}", response_model=UtilityStatement)
@atomic_billing(lambda: store, statement_arg="statement_id", destination_arg="payload")
def patch_utility_statement(statement_id: str, payload: UtilityStatementPatch) -> UtilityStatement:
    try:
        existing = store.get_utility_statement(statement_id)
        period = store.get_billing_period(existing.billing_period_id)
        _assert_period_mutable(period)
        if payload.billing_period_id is not None and payload.billing_period_id != existing.billing_period_id:
            _assert_period_mutable(store.get_billing_period(payload.billing_period_id))
        return store._patch_entity("utility_statement", statement_id, payload)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.delete("/statements/{statement_id}", status_code=status.HTTP_204_NO_CONTENT)
@atomic_billing(lambda: store, statement_arg="statement_id")
def delete_utility_statement(statement_id: str) -> None:
    try:
        existing = store.get_utility_statement(statement_id)
        period = store.get_billing_period(existing.billing_period_id)
        _assert_period_mutable(period)
        store.delete_utility_statement(statement_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# Generate Utility Statements
# ---------------------------------------------------------------------------


@router.post(
    "/periods/{period_id}/generate",
    response_model=list[UtilityStatement],
    status_code=status.HTTP_201_CREATED,
)
@atomic_billing(lambda: store, period_arg="period_id")
def generate_utility_statements(period_id: str) -> list[UtilityStatement]:
    """Generate the utility statements of a billing period.

    One row per usage segment of every unit: tenancies (also ended ones) and
    vacant stretches, whose share the landlord bears. Costs are shared by days
    (consumption keys by meter readings), non-recoverable costs are left out,
    and advances count per month as agreed. Existing statements of the period
    are replaced.
    """
    try:
        period = store.get_billing_period(period_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    _assert_period_mutable(period)

    billing = compute_period_billing(store, period)
    if billing.blockers:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="; ".join(f"{i.message} ({i.context})" if i.context else i.message for i in billing.blockers),
        )

    for existing in [us for us in store.list_utility_statements() if us.billing_period_id == period_id]:
        store.delete_utility_statement(existing.id)
    return [store.create_utility_statement(stmt) for stmt in billing.statements]


# ---------------------------------------------------------------------------
# Export, Delivery, Receivables, Revisions, PDF
# ---------------------------------------------------------------------------


@router.get("/periods/{period_id}/export")
def export_billing_period(period_id: str, export_format: str = Query("csv", alias="format")):
    """Export all statements for a billing period as CSV."""
    import csv
    import io

    from starlette.responses import Response as RawResponse

    try:
        store.get_billing_period(period_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    period_statements = [
        s for s in store.list_utility_statements() if s.billing_period_id == period_id
    ]

    buf = io.StringIO()
    writer = csv.writer(buf, delimiter=";")
    writer.writerow([
        "statement_id", "billing_period_id", "contract_id", "unit_id",
        "total_cost", "advance_paid", "balance", "status", "revision",
    ])
    for stmt in period_statements:
        writer.writerow([
            stmt.id, stmt.billing_period_id, stmt.contract_id, stmt.unit_id,
            f"{stmt.total_cost:.2f}", f"{stmt.advance_paid:.2f}", f"{stmt.balance:.2f}",
            stmt.status, stmt.revision,
        ])

    content = buf.getvalue()
    return RawResponse(
        content=content.encode("utf-8"),
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="billing_period_{period_id}.csv"',
        },
    )


@router.get("/periods/{period_id}/export-zip")
def export_billing_period_zip(period_id: str):
    """Export all statement PDFs for a billing period as a ZIP archive."""
    import io
    import zipfile

    from starlette.responses import Response as RawResponse

    try:
        store.get_billing_period(period_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    period_statements = [
        s for s in store.list_utility_statements() if s.billing_period_id == period_id
    ]
    if not period_statements:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Keine Einzelabrechnungen zum Exportieren vorhanden",
        )

    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for stmt in period_statements:
            pdf_response = download_utility_statement_pdf(stmt.id)
            ext = "pdf" if pdf_response.media_type == "application/pdf" else "txt"
            filename = f"statement_{stmt.id}.{ext}"
            zf.writestr(filename, pdf_response.body)

    return RawResponse(
        content=zip_buffer.getvalue(),
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="billing_period_{period_id}.zip"',
        },
    )


@router.post("/statements/{statement_id}/mark-delivered", response_model=UtilityStatement)
@atomic_billing(lambda: store, statement_arg="statement_id")
def mark_statement_delivered(
    statement_id: str,
    channel: str = "email",
):
    """Mark a utility statement as delivered. Requires finalized period.

    ``channel`` may be ``email``, ``post``, or ``portal``.
    """
    from datetime import datetime as _dt
    from datetime import timezone as _tz

    try:
        stmt = store.get_utility_statement(statement_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    period = store.get_billing_period(stmt.billing_period_id)
    if period.status not in ("finalized", "delivered"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Zustellung nur für finalisierte Perioden möglich",
        )

    return store._patch_entity(
        "utility_statement",
        statement_id,
        UtilityStatementPatch(
            delivery_status="delivered",
            delivered_at=_dt.now(_tz.utc),
            delivery_channel=channel,
            status="delivered",
        ),
    )


@router.post("/periods/{period_id}/create-receivables")
@atomic_billing(lambda: store, period_arg="period_id")
def create_receivables_from_period(period_id: str):
    """Create receivables/refund bookings from finalized statement balances.

    For a correction only the difference to what the corrected versions
    already billed is booked, so a tenant is never billed twice.
    """
    from ..models import ReceivableCreate

    try:
        period = store.get_billing_period(period_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    if period.status != "finalized":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Forderungen können nur aus finalisierten Perioden erzeugt werden",
        )

    period_statements = _period_statements(period_id)
    receivables = store.list_receivables()
    # Calling this twice must not bill the tenants twice.
    already_billed = {r.statement_id for r in receivables if r.statement_id}
    billed_before = _billed_by_corrected_versions(period, receivables)

    # Due after the tenant had time to check the statement, not at period end
    # (which made every back payment overdue the moment it was created).
    due_date = date.today() + timedelta(days=RECEIVABLE_DUE_DAYS)
    created_count = 0
    skipped_count = 0
    for stmt in period_statements:
        if stmt.contract_id is None:  # vacancy: the landlord's share, nobody to bill
            continue
        if stmt.id in already_billed:
            skipped_count += 1
            continue
        earlier = billed_before.pop(stmt.contract_id, Decimal("0"))
        amount = (Decimal(str(stmt.balance)) - earlier).quantize(Decimal("0.01"))
        if amount == 0:
            continue
        kind = "Nachzahlung" if amount > 0 else "Guthaben"
        if period.corrects_period_id:
            kind = f"Korrektur Rev. {period.revision}, {kind}"
        store.create_receivable(
            ReceivableCreate(
                contract_id=stmt.contract_id,
                due_date=due_date,
                amount_due=float(amount),  # negative: credit owed to the tenant
                status="open",
                statement_id=stmt.id,
                description=f"Nebenkostenabrechnung {period.label}: {kind}",
            )
        )
        created_count += 1

    return {"period_id": period_id, "created_receivables": created_count, "skipped_existing": skipped_count}


def _corrected_versions(period: BillingPeriod) -> list[BillingPeriod]:
    """The versions a correction replaces, newest first (rev. 2 of rev. 1, …)."""
    chain, seen = [], {period.id}
    current = period
    while current.corrects_period_id and current.corrects_period_id not in seen:
        try:
            current = store.get_billing_period(current.corrects_period_id)
        except NotFoundError:
            break
        seen.add(current.id)
        chain.append(current)
    return chain


def _billed_by_corrected_versions(period: BillingPeriod, receivables: list) -> dict[str, Decimal]:
    """contract id -> amount the corrected versions already billed (receivables of their statements)."""
    versions = {p.id for p in _corrected_versions(period)}
    if not versions:
        return {}
    contract_of = {s.id: s.contract_id for s in store.list_utility_statements()
                   if s.billing_period_id in versions and s.contract_id}
    billed: dict[str, Decimal] = {}
    for receivable in receivables:
        contract_id = contract_of.get(receivable.statement_id or "")
        if contract_id:
            billed[contract_id] = billed.get(contract_id, Decimal("0")) + Decimal(str(receivable.amount_due))
    return billed


_CORRECTION_SUFFIX = re.compile(r" \(Korrektur Rev\. \d+\)$")


@router.post("/periods/{period_id}/revisions")
@atomic_billing(lambda: store, period_arg="period_id")
def create_period_revision(
    period_id: str,
    revision_notes: str = Query("", alias="revision_notes"),
):
    """Start a correction of a finalized billing period ("Korrektur starten").

    The correction is a new draft period that names the version it corrects and
    counts the revision up; it starts with copies of the cost items. The
    corrected version and its statements stay unchanged. Open objections of the
    version are answered by this correction.
    """
    try:
        period = store.get_billing_period(period_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    if period.status not in _CORRECTABLE_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Eine Korrektur setzt eine finalisierte Fassung voraus (aktuell: '{period.status}'); "
                   "einen Entwurf bitte direkt bearbeiten",
        )
    pending = [p for p in store.list_billing_periods()
               if p.corrects_period_id == period_id and p.status in EDITABLE_STATUSES]
    if pending:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Für diese Fassung gibt es schon eine offene Korrektur: {pending[0].label}",
        )

    notes = revision_notes.strip() if isinstance(revision_notes, str) else ""  # direct calls pass the Query default
    new_revision = (period.revision or 1) + 1
    base_label = _CORRECTION_SUFFIX.sub("", period.label)
    new_period = store.create_billing_period(
        BillingPeriodCreate(
            property_id=period.property_id,
            label=f"{base_label} (Korrektur Rev. {new_revision})",
            start_date=period.start_date,
            end_date=period.end_date,
            status="draft",
            revision=new_revision,
            corrects_period_id=period.id,
            revision_notes=notes or None,
        )
    )

    # Copy cost items
    cost_items = [ci for ci in store.list_cost_items() if ci.billing_period_id == period_id]
    for ci in cost_items:
        # All fields: dropping is_recoverable would bill a non-recoverable cost.
        fields = ci.model_dump(include=set(CostItemCreate.model_fields))
        store.create_cost_item(CostItemCreate(**{**fields, "billing_period_id": new_period.id}))

    for objection in store.list_billing_objections(period_id):
        if objection.status == "open":
            _save_objection(objection, status="correction", correction_period_id=new_period.id)

    return {
        "new_period_id": new_period.id,
        "source_period_id": period_id,
        "revision": new_revision,
        "revision_notes": notes,
    }


def _save_objection(objection: BillingObjection, **changes: Any) -> BillingObjection:
    if changes.get("status", objection.status) != objection.status:
        changes.setdefault("decision_revision", objection.decision_revision + 1)
    data = BillingObjectionCreate(**{**objection.model_dump(include=set(BillingObjectionCreate.model_fields)),
                                     **changes})
    return store.update_billing_objection(objection.id, data)


@atomic_billing(lambda: store, period_arg="period_id")
def _record_objection(period_id: str, request: BillingObjectionRequest) -> BillingObjection:
    """Internal legacy write, atomic but without an actor or creation receipt.

    Authenticated HTTP callers use _record_objection_as_actor, including the old
    query route. Existing direct-call workflows retain this trusted internal API.
    """
    try:
        period = store.get_billing_period(period_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    if "disputed" not in _PERIOD_TRANSITIONS.get(period.status, set()):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Widerspruch nur gegen eine finalisierte oder zugestellte Abrechnung möglich "
                   f"(aktuell: '{period.status}')",
        )
    try:
        existing = store.list_billing_objections(period_id)
        first_status: Literal["finalized", "delivered"] | None
        if period.status == "finalized":
            first_status = "finalized"
        elif period.status == "delivered":
            first_status = "delivered"
        else:
            first_status = next((entry.source_period_status for entry in existing
                                 if entry.source_period_status is not None), None)
        objection = store.create_billing_objection(BillingObjectionCreate(
            billing_period_id=period_id,
            statement_id=request.statement_id,
            received_on=request.received_on or date.today(),
            reason=request.reason,
            source_period_status=first_status,
        ))
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    if period.status != "disputed":
        _set_period_status(period_id, "disputed")
    return objection


def _record_objection_as_actor(period_id: str, payload: BillingObjectionRequest, actor_id: str) -> BillingObjection:
    """One authorized creation and its durable receipt in the billing transaction."""
    db = getattr(store, "db", None)
    try:
        with ExitStack() as stack:
            # Match document work's memory account -> archive lock order. SQL
            # needs BEGIN IMMEDIATE/period locks before locking the account row.
            account = stack.enter_context(auth.locked_account(actor_id)) if db is None else None
            stack.enter_context(billing_write(store, [period_id]))
            if db is not None:
                account = stack.enter_context(auth.locked_account(actor_id, db))
            account = check_account(account, write_areas=("/billing/periods",))
            refresh_scope(current_scope())
            with scope_context(scope_from_user(account)):
                # Authorize today's source before reading a private command
                # receipt, including a retry after the source was corrected.
                period = store.get_billing_period(period_id)
                if payload.statement_id is not None:
                    statement = store.get_utility_statement(payload.statement_id)
                    if statement.billing_period_id != period_id:
                        raise HTTPException(400, "Die Einzelabrechnung gehört nicht zu dieser Abrechnungsperiode")
                if final_version_problems(period, _period_statements(period_id)):
                    raise HTTPException(409, "Die Originalabrechnung stimmt nicht mit ihrer finalisierten Fassung überein")
                unit = Unit(store, db, account, None)
                try:
                    operation = "billing:objection-create:" + period_id
                    if payload.idempotency_key is not None:
                        prior = objection_commands.replay(unit, actor_id, operation, payload)
                        if prior is not None:
                            existing = store.get_billing_objection(prior["objection_id"])
                            if existing.billing_period_id != period_id or existing.statement_id != payload.statement_id:
                                raise HTTPException(409, "Der gespeicherte Erfassungsbeleg passt nicht zur Abrechnung")
                            return existing
                    result = _record_objection(period_id, payload)
                    if payload.idempotency_key is not None:
                        objection_commands.save_command(unit, actor_id, operation, payload,
                            {"kind": "billing_period", "entity_id": period.id, "property_id": period.property_id},
                            {"objection_id": result.id})
                    return result
                except BaseException:
                    # Roll back the Memory receipt while both account/archive
                    # locks are still held. SQL rows share billing_write's commit.
                    unit.rollback()
                    raise
    except NotFoundError as exc:
        raise HTTPException(404, "Abrechnung oder Widerspruch nicht gefunden") from exc


@router.post("/periods/{period_id}/dispute", response_model=BillingPeriod)
def dispute_billing_period(
    period_id: str,
    reason: str = Query("", alias="reason"),
    idempotency_key: str | None = Query(None, min_length=8, max_length=120, pattern=r"^[a-zA-Z0-9:_.-]+$"),
    actor: UserRead = Depends(require_role("eigentuemer", "verwalter")),
) -> BillingPeriod:
    """Legacy query compatibility; HTTP uses the same authorized creation path.

    Supply idempotency_key for retry safety. Keyless direct calls remain the
    trusted pre-existing internal API, including its default reason.
    """
    text = reason.strip() if isinstance(reason, str) else ""  # direct calls pass the Query default
    key = idempotency_key if isinstance(idempotency_key, str) else None
    create_billing_objection(period_id, BillingObjectionRequest(reason=text or "ohne Begründung", idempotency_key=key), actor)
    return store.get_billing_period(period_id)


@router.post("/periods/{period_id}/objections", response_model=BillingObjection,
             status_code=status.HTTP_201_CREATED)
def create_billing_objection(
    period_id: str, payload: BillingObjectionRequest,
    actor: UserRead = Depends(require_role("eigentuemer", "verwalter")),
) -> BillingObjection:
    """HTTP creation is authorized/replayable; keyless direct calls are internal."""
    if isinstance(actor, UserRead):
        return _record_objection_as_actor(period_id, payload, actor.id)
    if payload.idempotency_key is not None:
        raise HTTPException(401, "Ein Erfassungsbefehl benötigt ein angemeldetes Konto")
    return _record_objection(period_id, payload)


def _decision_source(period: BillingPeriod) -> str:
    originals = _period_statements(period.id)
    if not originals or any(not source.snapshot_hash for source in originals):
        raise HTTPException(409, "Originalabrechnung fehlt oder ist nicht als unveränderliche Fassung belegt")
    if final_version_problems(period, originals):
        raise HTTPException(409, "Originalabrechnung stimmt nicht mit der finalisierten Fassung überein")
    return statement_snapshot_hash(originals)


@router.get("/objections/{objection_id}/decision-preview")
def objection_decision_preview(objection_id: str) -> dict:
    try:
        objection = store.get_billing_objection(objection_id)
        period = store.get_billing_period(objection.billing_period_id)
    except NotFoundError:
        raise HTTPException(404, "Widerspruch nicht gefunden") from None
    return {"objection": objection, "source_sha256": _decision_source(period),
            "period_status": period.status}


def decide_issued_objection(objection_id, payload, actor_id, *, action="reject"):
    if action not in {"reject", "revise"}:
        raise HTTPException(422, "Unbekannte Widerspruchsentscheidung")
    try:
        return _decide_issued_objection(objection_id, payload, actor_id, action=action)
    except (IntegrityError, ValidationError) as exc:
        # A concurrent decision on another period may claim the command key
        # after our precheck. The surrounding write has rolled back by now.
        raise HTTPException(409, "Der Entscheidungsbefehl steht im Konflikt; bitte erneut laden") from exc


def _decide_issued_objection(
    objection_id: str, payload: BillingObjectionRejection, actor_id: str, *, action: str = "reject",
) -> BillingObjection:
    """Bind a documented decision to the shown original and current account rights.

    The period lock covers revision/source checks and the whole correction or
    rejection. Account rights are held until the transaction is complete. Neither
    action creates receivables, cancellations, replacement PDFs or deliveries.
    """
    try:
        initial = store.get_billing_objection(objection_id)
    except NotFoundError:
        raise HTTPException(404, "Widerspruch nicht gefunden") from None
    db = getattr(store, "db", None)
    with ExitStack() as stack:
        # Memory follows the same account -> archive lock order as document work.
        account = stack.enter_context(auth.locked_account(actor_id)) if db is None else None
        stack.enter_context(billing_write(store, [initial.billing_period_id]))
        if db is not None:
            account = stack.enter_context(auth.locked_account(actor_id, db))
        account = check_account(account, write_areas=("/billing/objections",))
        if account.get("role") not in {"eigentuemer", "verwalter"}:
            raise HTTPException(403, "Keine Berechtigung, einen Widerspruch zu entscheiden")
        refresh_scope(current_scope())
        with scope_context(scope_from_user(account)):
            return _decide_locked_objection(initial, payload, actor_id, action)


def _decide_locked_objection(initial, payload, actor_id, action):
    try:
        current = store.get_billing_objection(initial.id)
        period = store.get_billing_period(initial.billing_period_id)
    except NotFoundError:
        raise HTTPException(404, "Widerspruch oder Abrechnungsperiode nicht gefunden") from None
    if current.billing_period_id != initial.billing_period_id:
        raise HTTPException(409, "Die Zuordnung wurde geändert; bitte erneut laden")
    target_statuses = {"rejected"} if action == "reject" else {"correction", "resolved"}
    if current.decision_key is not None:
        expected_result_revision = payload.expected_revision + (2 if current.status == "resolved" else 1)
        if (current.status in target_statuses and current.decision_key == payload.idempotency_key
                and current.decision_actor_id == actor_id and current.decision_reason == payload.rationale
                and current.decision_source_sha256 == payload.expected_source_sha256
                and current.decision_revision == expected_result_revision):
            if _decision_source(period) != current.decision_source_sha256:
                raise HTTPException(409, "Die Originalfassung stimmt nicht mehr mit dem Entscheidungsbeleg überein")
            return current
        raise HTTPException(409, "Dieser Widerspruch wurde bereits anders entschieden")
    if (current.status != "open" or period.status != "disputed"
            or current.correction_period_id is not None or current.decision_revision != payload.expected_revision):
        raise HTTPException(409, "Widerspruch oder Abrechnungsstand wurden geändert; bitte Vorschau erneut laden")
    source_hash = _decision_source(period)
    if source_hash != payload.expected_source_sha256:
        raise HTTPException(409, "Die angezeigte Originalfassung ist veraltet; bitte Vorschau erneut laden")
    pending = [p for p in store.list_billing_periods()
               if p.corrects_period_id == period.id and p.status in EDITABLE_STATUSES]
    if pending:
        raise HTTPException(409, "Eine Überarbeitung läuft bereits; bitte die vorhandene Korrektur öffnen")
    # Check key reuse before writing: memory and SQL must reject it alike.
    objections = store.list_billing_objections()
    if not hasattr(store, "db"):
        # This is a storage uniqueness invariant, including rows outside a
        # restricted actor's view; no foreign record or decision is disclosed.
        objections = object.__getattribute__(store, "__dict__")["billing_objections"].values()
    if any(o.decision_key == payload.idempotency_key for o in objections):
        raise HTTPException(409, "Dieser Entscheidungsbefehl gehört bereits zu einem anderen Widerspruch")
    if action == "revise":
        correction = create_period_revision(period.id, payload.rationale)
        # The existing correction workflow answers every open objection of
        # this version. Record the same rationale/actor/time for each of them,
        # with distinct command keys, without changing a tenant's own text.
        evidence = _decision_evidence(payload, actor_id, source_hash)
        result = store.get_billing_objection(current.id)
        for linked in store.list_billing_objections(period.id):
            if linked.correction_period_id == correction["new_period_id"] and linked.status == "correction":
                command_key = payload.idempotency_key if linked.id == current.id else hashlib.sha256(
                    (payload.idempotency_key + ":" + linked.id).encode("utf-8")).hexdigest()
                updated = _save_objection(linked, **{**evidence, "decision_key": command_key})
                if linked.id == current.id:
                    result = updated
    else:
        result = _save_objection(current, status="rejected", **_decision_evidence(payload, actor_id, source_hash))
        siblings = store.list_billing_objections(period.id)
        if not any(o.status in {"open", "correction"} for o in siblings):
            previous = current.source_period_status or next((o.source_period_status for o in siblings
                       if o.source_period_status in {"finalized", "delivered"}), None)
            if previous in {"finalized", "delivered"}:
                _set_period_status(period.id, previous)
    if _compute_snapshot_hash(period.id) != source_hash:
        raise HTTPException(503, "Die eingefrorene Originalabrechnung wurde unerwartet verändert")
    return result


def _decision_evidence(payload, actor_id, source_hash):
    return dict(decision_reason=payload.rationale, decision_actor_id=actor_id,
                decision_key=payload.idempotency_key, decided_at=datetime.now(timezone.utc),
                decision_source_sha256=source_hash)


def reject_issued_objection(objection_id, payload, actor_id):
    return decide_issued_objection(objection_id, payload, actor_id)


@router.post("/objections/{objection_id}/reject", response_model=BillingObjection)
def reject_billing_objection(
    objection_id: str, payload: BillingObjectionRejection,
    actor: UserRead = Depends(require_role("eigentuemer", "verwalter")),
) -> BillingObjection:
    return decide_issued_objection(objection_id, payload, actor.id)


@router.post("/objections/{objection_id}/revise", response_model=BillingObjection)
def revise_billing_objection(
    objection_id: str, payload: BillingObjectionRejection,
    actor: UserRead = Depends(require_role("eigentuemer", "verwalter")),
) -> BillingObjection:
    return decide_issued_objection(objection_id, payload, actor.id, action="revise")


@router.get("/objections", response_model=list[BillingObjection])
def list_billing_objections(billing_period_id: str | None = Query(None)) -> list[BillingObjection]:
    return store.list_billing_objections(billing_period_id)


# ---------------------------------------------------------------------------
# OCR-Assisted Cost Import (NK-6)
# ---------------------------------------------------------------------------


@router.post("/cost-items/import-ocr")
def import_cost_item_from_ocr(
    billing_period_id: str = Query(...),
    file_url: str = Query(...),
    allocation_key_id: str | None = Query(None),
):
    """Perform OCR on a document and return a CostItem draft with confidence scores.

    The user can review and correct the suggested fields before accepting.
    Does NOT persist the cost item — the user must POST /cost-items to save.
    """
    from ..services.file_storage import get_file_storage
    from ..services.ocr_service import _extract_invoice_fields, extract_text_from_bytes

    # Validate period exists and is mutable
    try:
        period = store.get_billing_period(billing_period_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    _assert_period_mutable(period)

    # Resolve file from storage
    storage = get_file_storage()
    from ..routers.files import _file_url_to_key
    file_key = _file_url_to_key(file_url)
    if not file_key:
        raise HTTPException(status_code=400, detail="Ungültige Datei-URL")

    file_bytes = storage.get(file_key)
    if file_bytes is None:
        raise HTTPException(status_code=404, detail="Datei nicht gefunden im Speicher")

    ext = file_key.rsplit(".", 1)[-1].lower() if "." in file_key else ""
    text = extract_text_from_bytes(file_bytes, ext)
    if not text:
        return {
            "success": False,
            "error": "Kein Text aus Dokument extrahierbar. Prüfen Sie ob pytesseract/pdfplumber installiert ist.",
            "draft": None,
            "confidence": {},
        }

    fields = _extract_invoice_fields(text)

    # Build draft CostItem suggestion
    draft = {
        "billing_period_id": billing_period_id,
        "description": fields.get("supplier") or fields.get("cost_category") or "",
        "amount": fields.get("total_amount"),
        "allocation_key_id": allocation_key_id,
        "cost_category": fields.get("cost_category"),
        "source_document_id": file_url,
    }

    # Confidence scores per field (0.0–1.0)
    confidence = {
        "description": 0.7 if fields.get("supplier") else (0.5 if fields.get("cost_category") else 0.0),
        "amount": 0.85 if fields.get("total_amount") is not None else 0.0,
        "cost_category": 0.6 if fields.get("cost_category") else 0.0,
    }

    return {
        "success": True,
        "draft": draft,
        "confidence": confidence,
        "ocr_fields": {
            "invoice_number": fields.get("invoice_number"),
            "invoice_date": fields.get("invoice_date"),
            "total_amount": fields.get("total_amount"),
            "supplier": fields.get("supplier"),
            "cost_category": fields.get("cost_category"),
        },
        "ocr_text_preview": text[:500],
    }


def _eur(value: Any) -> str:
    """1234.5 -> '1.234,50 €'."""
    return f"{float(value or 0):,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".")


def _num(value: Any) -> str:
    text = f"{float(value or 0):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return text[:-3] if text.endswith(",00") else text


def _short_day(value: Any) -> str:
    day = date.fromisoformat(value) if isinstance(value, str) else value
    return day.strftime("%d.%m.%Y")


def _share_text(li: dict) -> str:
    unit_name = li.get("basis_unit") or ""
    share = f"{li.get('key_name') or li.get('key_type') or ''}: {_num(li['basis'])} von {_num(li['total_basis'])} {unit_name}".strip()
    if li.get("days") is not None:
        share += f" · {li['days']}/{li['period_days']} Tage"
    sections = li.get("sections") or []
    if sections:
        # persons changed within the tenancy: person-days of each section
        parts = [f"{_short_day(s['start'])}–{_short_day(s['end'])}: {_num(s['basis'])} {unit_name} × {s['days']} Tage"
                 for s in sections]
        share += " (" + "; ".join(parts) + ")"
    return share


def _live_statement_document(stmt: Any, period: Any = None) -> dict:
    """Everything a statement shows, resolved to names from today's data: shared by PDF and text."""
    def lookup(getter: str, entity_id: Any) -> Any:
        try:
            return getattr(store, getter)(entity_id) if entity_id else None
        except Exception:
            logger.debug("Could not resolve %s %s for statement %s", getter, entity_id, stmt.id, exc_info=True)
            return None

    period = period or lookup("get_billing_period", stmt.billing_period_id)
    unit = lookup("get_unit", stmt.unit_id)
    prop = lookup("get_property", period.property_id) if period else None
    contract = lookup("get_contract", stmt.contract_id)
    tenant = lookup("get_tenant", contract.tenant_id) if contract else None
    party = "Leerstand (Eigentümer)" if stmt.party == "vacancy" else (tenant.full_name if tenant else "—")

    def day(value: Any) -> str:
        return value.strftime("%d.%m.%Y") if value else "—"

    rows = []
    for li in stmt.line_items or []:
        share = ""
        if li.get("basis") is not None and li.get("total_basis") is not None:
            share = _share_text(li)
        rows.append([
            li.get("description", "—"),
            _eur(li["total_amount"]) if li.get("total_amount") is not None else "",
            share,
            _eur(li.get("allocated_amount", 0)),
        ])

    usage = "—"
    if stmt.usage_start and stmt.usage_end:
        usage = f"{day(stmt.usage_start)} – {day(stmt.usage_end)}"
        if stmt.usage_days:
            usage += f" ({stmt.usage_days} Tage)"
    facts = [
        ("Objekt", ", ".join(x for x in [prop.name if prop else None, getattr(prop, "address_line", None),
                                         getattr(prop, "city", None)] if x) or "—"),
        ("Einheit", unit.label if unit else stmt.unit_id),
        ("Mieter", party),
        ("Vertrag", contract.contract_number if contract else "—"),
        ("Abrechnungszeitraum", f"{day(period.start_date)} – {day(period.end_date)}" if period else "—"),
        ("Nutzungszeitraum", usage),
    ]
    if period is not None and (period.revision or 1) > 1:
        facts.append(("Fassung", f"Korrektur Rev. {period.revision}, ersetzt die vorherige Fassung"))
    sections = stmt.advance_sections or []
    advances = [
        (f"{_short_day(s['start'])} – {_short_day(s['end'])}", f"{_eur(s['monthly'])} / Monat", _eur(s["amount"]))
        for s in sections
    ] if len(sections) > 1 else []
    return {
        "title": f"Betriebskostenabrechnung {period.label}" if period else "Betriebskostenabrechnung",
        "facts": facts,
        "rows": rows,
        "advances": advances,
        "totals": [
            ("Ihr Kostenanteil", _eur(stmt.total_cost)),
            ("Vorauszahlungen", _eur(stmt.advance_paid)),
            ("Nachzahlung" if stmt.balance > 0 else "Guthaben", _eur(abs(stmt.balance))),
        ],
    }


def _statement_document(stmt: Any) -> dict:
    """What the statement shows: the frozen version once finalized, otherwise from today's data."""
    frozen = getattr(stmt, "final_document", None)
    if not frozen:
        return _live_statement_document(stmt)
    return {
        "title": frozen.get("title", "Betriebskostenabrechnung"),
        "facts": [tuple(pair) for pair in frozen.get("facts", [])],
        "rows": [list(row) for row in frozen.get("rows", [])],
        "advances": [tuple(row) for row in frozen.get("advances", [])],
        "totals": [tuple(pair) for pair in frozen.get("totals", [])],
    }


def download_utility_statement_pdf(statement_id: str):
    """Generate a PDF for a single utility statement (or text fallback).

    A finalized statement renders from its frozen document with invariant PDF
    metadata, so the issued PDF is the same byte for byte every time.
    """
    from starlette.responses import Response as RawResponse

    try:
        stmt = store.get_utility_statement(statement_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    document = _statement_document(stmt)
    try:
        import io

        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.lib.units import mm
        from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=18*mm, rightMargin=18*mm,
                                topMargin=22*mm, bottomMargin=18*mm, invariant=1,
                                title=document["title"], creator="ImmoManager Pro")
        styles = getSampleStyleSheet()
        small = styles["BodyText"].clone("small", fontSize=8, leading=10)
        story: list[Any] = [Paragraph(document["title"], styles["Title"]), Spacer(1, 6)]

        facts = Table([[label, value] for label, value in document["facts"]], colWidths=[45*mm, 129*mm])
        facts.setStyle(TableStyle([("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"), ("FONTSIZE", (0, 0), (-1, -1), 9)]))
        story += [facts, Spacer(1, 10)]

        rows = [["Kostenart", "Gesamtkosten", "Verteilung und Ihr Anteil", "Ihr Betrag"]]
        rows += [[cell if i != 2 else Paragraph(cell, small) for i, cell in enumerate(row)] for row in document["rows"]]
        lines = Table(rows, colWidths=[38*mm, 27*mm, 82*mm, 27*mm], repeatRows=1)
        lines.setStyle(TableStyle([
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("ALIGN", (1, 0), (1, -1), "RIGHT"),
            ("ALIGN", (3, 0), (3, -1), "RIGHT"),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LINEBELOW", (0, 0), (-1, 0), 0.5, (0, 0, 0)),
        ]))
        story += [lines, Spacer(1, 10)]

        if document.get("advances"):
            advances = Table([["Vorauszahlungen", "vereinbart", "Betrag"]] + [list(row) for row in document["advances"]],
                             colWidths=[90*mm, 57*mm, 27*mm])
            advances.setStyle(TableStyle([
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
            ]))
            story += [advances, Spacer(1, 10)]

        totals = Table([[label, value] for label, value in document["totals"]], colWidths=[147*mm, 27*mm])
        totals.setStyle(TableStyle([
            ("ALIGN", (1, 0), (1, -1), "RIGHT"),
            ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
            ("LINEABOVE", (0, -1), (-1, -1), 0.5, (0, 0, 0)),
        ]))
        story.append(totals)

        doc.build(story)
        return RawResponse(
            content=buffer.getvalue(),
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="statement_{statement_id}.pdf"'},
        )
    except ImportError:
        text = [document["title"], ""]
        text += [f"{label}: {value}" for label, value in document["facts"]]
        text += [""] + [" | ".join(cell for cell in row if cell) for row in document["rows"]]
        if document.get("advances"):
            text += [""] + [" | ".join(row) for row in document["advances"]]
        text += [""] + [f"{label}: {value}" for label, value in document["totals"]]
        return RawResponse(
            content="\n".join(text).encode("utf-8"),
            media_type="text/plain",
            headers={"Content-Disposition": f'attachment; filename="statement_{statement_id}.txt"'},
        )


@router.get("/statements/{statement_id}/pdf")
def get_utility_statement_pdf(statement_id: str):
    """Download a PDF for a single utility statement."""
    return download_utility_statement_pdf(statement_id)
