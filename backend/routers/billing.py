"""Router for billing periods, allocation keys, cost items, and utility statements.

Includes a POST endpoint to auto-generate utility statements from cost items
using the BillingEngine for cost allocation.

Status machine for billing periods:
  draft -> review -> finalized -> delivered
  finalized -> corrected (via revision endpoint)
"""

import hashlib
import json
import logging
from datetime import date, timedelta
from typing import Any

from fastapi import APIRouter, HTTPException, Query, status

from ..dependencies import store
from ..models import (
    AllocationKey,
    AllocationKeyCreate,
    AllocationKeyPatch,
    BillingPeriod,
    BillingPeriodCreate,
    BillingPeriodPatch,
    BillingPreflightIssue,
    BillingPreflightResult,
    CostItem,
    CostItemCreate,
    CostItemPatch,
    UtilityStatement,
    UtilityStatementPatch,
)
from ..services.utility_billing import compute_period_billing
from ..storage import NotFoundError, ValidationError

# Days a tenant has to settle a back payment after the statement was issued.
RECEIVABLE_DUE_DAYS = 30

# Valid status transitions for billing periods
_PERIOD_TRANSITIONS: dict[str, set[str]] = {
    "draft": {"review", "finalized"},
    "review": {"draft", "finalized"},
    "finalized": {"delivered", "corrected", "disputed"},
    "delivered": {"disputed"},
    "disputed": {"corrected"},
    "corrected": set(),
}

_IMMUTABLE_STATUSES = {"finalized", "delivered", "corrected"}


def _assert_period_mutable(period: BillingPeriod) -> None:
    """Raise 409 if the period is in an immutable state."""
    if period.status in _IMMUTABLE_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Periode ist '{period.status}' und kann nicht mehr bearbeitet werden",
        )


def _compute_snapshot_hash(period_id: str) -> str:
    """Compute a deterministic SHA-256 hash over all statement data for a period."""
    stmts = sorted(
        [s for s in store.list_utility_statements() if s.billing_period_id == period_id],
        key=lambda s: s.id,
    )
    payload = []
    for s in stmts:
        payload.append({
            "id": s.id,
            "unit_id": s.unit_id,
            "contract_id": s.contract_id,
            "total_cost": float(s.total_cost),
            "advance_paid": float(s.advance_paid),
            "balance": float(s.balance),
            "line_items": s.line_items or [],
        })
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()

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
) -> list[BillingPeriod]:
    results = store.list_billing_periods()
    if property_id:
        results = [r for r in results if r.property_id == property_id]
    if status_filter:
        results = [r for r in results if r.status == status_filter]
    return results[skip : skip + limit]


@router.post("/periods", response_model=BillingPeriod, status_code=status.HTTP_201_CREATED)
def create_billing_period(payload: BillingPeriodCreate) -> BillingPeriod:
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
def update_billing_period(period_id: str, payload: BillingPeriodCreate) -> BillingPeriod:
    try:
        existing = store.get_billing_period(period_id)
        _assert_period_mutable(existing)
        return store.update_billing_period(period_id, payload)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.patch("/periods/{period_id}", response_model=BillingPeriod)
def patch_billing_period(period_id: str, payload: BillingPeriodPatch) -> BillingPeriod:
    try:
        existing = store.get_billing_period(period_id)
        _assert_period_mutable(existing)
        return store._patch_entity("billing_period", period_id, payload)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.delete("/periods/{period_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_billing_period(period_id: str) -> None:
    try:
        existing = store.get_billing_period(period_id)
        _assert_period_mutable(existing)
        store.delete_billing_period(period_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


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
def create_cost_item(payload: CostItemCreate) -> CostItem:
    try:
        period = store.get_billing_period(payload.billing_period_id)
        _assert_period_mutable(period)
    except NotFoundError:
        pass  # Let store.create_cost_item raise its own ValidationError
    try:
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
def update_cost_item(item_id: str, payload: CostItemCreate) -> CostItem:
    try:
        existing = store.get_cost_item(item_id)
        period = store.get_billing_period(existing.billing_period_id)
        _assert_period_mutable(period)
        return store.update_cost_item(item_id, payload)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.patch("/cost-items/{item_id}", response_model=CostItem)
def patch_cost_item(item_id: str, payload: CostItemPatch) -> CostItem:
    try:
        existing = store.get_cost_item(item_id)
        period = store.get_billing_period(existing.billing_period_id)
        _assert_period_mutable(period)
        return store._patch_entity("cost_item", item_id, payload)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.delete("/cost-items/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
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
    if period.status not in _IMMUTABLE_STATUSES and _statements_outdated(period_id, billing):
        issues.append(BillingPreflightIssue(
            code="STATEMENTS_OUTDATED",
            message="Die Einzelabrechnungen entsprechen nicht mehr den Daten; bitte neu erzeugen",
            severity="warning",
        ))
    blockers = [i for i in issues if i.severity == "blocker"]
    return BillingPreflightResult(
        billing_period_id=period_id,
        has_blockers=bool(blockers),
        blockers=blockers,
        warnings=[i for i in issues if i.severity != "blocker"],
        metrics=billing.metrics,
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

    return store.update_billing_period(
        period_id,
        BillingPeriodCreate(
            property_id=period.property_id,
            label=period.label,
            start_date=period.start_date,
            end_date=period.end_date,
            status="review",
        ),
    )


@router.post("/periods/{period_id}/revert-draft", response_model=BillingPeriod)
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

    return store.update_billing_period(
        period_id,
        BillingPeriodCreate(
            property_id=period.property_id,
            label=period.label,
            start_date=period.start_date,
            end_date=period.end_date,
            status="draft",
        ),
    )


@router.post("/periods/{period_id}/finalize", response_model=BillingPeriod)
def finalize_billing_period(period_id: str) -> BillingPeriod:
    """Finalize billing period after successful preflight and generated statements.

    Allowed from 'draft' or 'review' status. Computes a snapshot hash for
    immutability verification and stamps it on all statements.
    """
    try:
        period = store.get_billing_period(period_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    if period.status == "finalized":
        return period

    if period.status not in ("draft", "review"):
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

    period_statements = [
        s for s in store.list_utility_statements() if s.billing_period_id == period_id
    ]
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

    # Compute immutable snapshot hash
    snapshot = _compute_snapshot_hash(period_id)

    finalized = store.update_billing_period(
        period_id,
        BillingPeriodCreate(
            property_id=period.property_id,
            label=period.label,
            start_date=period.start_date,
            end_date=period.end_date,
            status="finalized",
        ),
    )

    for stmt in period_statements:
        patch_data: dict[str, Any] = {}
        if stmt.status != "finalized":
            patch_data["status"] = "finalized"
        if not stmt.snapshot_hash:
            patch_data["snapshot_hash"] = snapshot
        if patch_data:
            store._patch_entity(
                "utility_statement",
                stmt.id,
                UtilityStatementPatch(**patch_data),
            )

    return finalized


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
def patch_utility_statement(statement_id: str, payload: UtilityStatementPatch) -> UtilityStatement:
    try:
        existing = store.get_utility_statement(statement_id)
        period = store.get_billing_period(existing.billing_period_id)
        _assert_period_mutable(period)
        return store._patch_entity("utility_statement", statement_id, payload)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.delete("/statements/{statement_id}", status_code=status.HTTP_204_NO_CONTENT)
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
def create_receivables_from_period(period_id: str):
    """Create receivables/refund bookings from finalized statement balances."""
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

    period_statements = [
        s for s in store.list_utility_statements() if s.billing_period_id == period_id
    ]
    # Calling this twice must not bill the tenants twice.
    already_billed = {r.statement_id for r in store.list_receivables() if r.statement_id}

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
        if stmt.balance == 0:
            continue
        kind = "Nachzahlung" if stmt.balance > 0 else "Guthaben"
        store.create_receivable(
            ReceivableCreate(
                contract_id=stmt.contract_id,
                due_date=due_date,
                amount_due=stmt.balance,  # negative: credit owed to the tenant
                status="open",
                statement_id=stmt.id,
                description=f"Nebenkostenabrechnung {period.label}: {kind}",
            )
        )
        created_count += 1

    return {"period_id": period_id, "created_receivables": created_count, "skipped_existing": skipped_count}


@router.post("/periods/{period_id}/revisions")
def create_period_revision(
    period_id: str,
    revision_notes: str = Query("", alias="revision_notes"),
):
    """Create a correction revision of a finalized billing period.

    Copies the period and its cost items into a new draft period with
    incremented revision numbers on all statements.
    """
    try:
        period = store.get_billing_period(period_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    # Determine next revision number
    existing_stmts = [
        s for s in store.list_utility_statements() if s.billing_period_id == period_id
    ]
    max_revision = max((s.revision for s in existing_stmts), default=1)
    new_revision = max_revision + 1

    # Create new period (draft copy)
    new_period = store.create_billing_period(
        BillingPeriodCreate(
            property_id=period.property_id,
            label=f"{period.label} (Korrektur Rev. {new_revision})",
            start_date=period.start_date,
            end_date=period.end_date,
            status="draft",
        )
    )

    # Copy cost items
    cost_items = [ci for ci in store.list_cost_items() if ci.billing_period_id == period_id]
    for ci in cost_items:
        # All fields: dropping is_recoverable would bill a non-recoverable cost.
        fields = ci.model_dump(include=set(CostItemCreate.model_fields))
        store.create_cost_item(CostItemCreate(**{**fields, "billing_period_id": new_period.id}))

    return {
        "new_period_id": new_period.id,
        "source_period_id": period_id,
        "revision": new_revision,
        "revision_notes": revision_notes,
    }


@router.post("/periods/{period_id}/dispute", response_model=BillingPeriod)
def dispute_billing_period(
    period_id: str,
    reason: str = Query("", alias="reason"),
) -> BillingPeriod:
    """Mark a finalized or delivered period as disputed.

    The period can then be corrected via the revision endpoint.
    """
    try:
        period = store.get_billing_period(period_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    allowed = _PERIOD_TRANSITIONS.get(period.status, set())
    if "disputed" not in allowed:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Widerspruch nur aus 'finalized' oder 'delivered' möglich (aktuell: '{period.status}')",
        )

    return store.update_billing_period(
        period_id,
        BillingPeriodCreate(
            property_id=period.property_id,
            label=period.label,
            start_date=period.start_date,
            end_date=period.end_date,
            status="disputed",
        ),
    )


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


def _statement_document(stmt: Any) -> dict:
    """Everything a statement shows, resolved to names: shared by PDF and text."""
    def lookup(getter: str, entity_id: Any) -> Any:
        try:
            return getattr(store, getter)(entity_id) if entity_id else None
        except Exception:
            logger.debug("Could not resolve %s %s for statement %s", getter, entity_id, stmt.id, exc_info=True)
            return None

    period = lookup("get_billing_period", stmt.billing_period_id)
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
            unit_name = li.get("basis_unit") or ""
            share = f"{li.get('key_name') or li.get('key_type') or ''}: {_num(li['basis'])} von {_num(li['total_basis'])} {unit_name}".strip()
            if li.get("days") is not None:
                share += f" · {li['days']}/{li['period_days']} Tage"
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
    return {
        "title": f"Betriebskostenabrechnung {period.label}" if period else "Betriebskostenabrechnung",
        "facts": [
            ("Objekt", ", ".join(x for x in [prop.name if prop else None, getattr(prop, "address_line", None),
                                             getattr(prop, "city", None)] if x) or "—"),
            ("Einheit", unit.label if unit else stmt.unit_id),
            ("Mieter", party),
            ("Vertrag", contract.contract_number if contract else "—"),
            ("Abrechnungszeitraum", f"{day(period.start_date)} – {day(period.end_date)}" if period else "—"),
            ("Nutzungszeitraum", usage),
        ],
        "rows": rows,
        "totals": [
            ("Ihr Kostenanteil", _eur(stmt.total_cost)),
            ("Vorauszahlungen", _eur(stmt.advance_paid)),
            ("Nachzahlung" if stmt.balance > 0 else "Guthaben", _eur(abs(stmt.balance))),
        ],
    }


def download_utility_statement_pdf(statement_id: str):
    """Generate a PDF for a single utility statement (or text fallback)."""
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
                                topMargin=22*mm, bottomMargin=18*mm)
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
