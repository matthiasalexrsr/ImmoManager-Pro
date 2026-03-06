"""Router for billing periods, allocation keys, cost items, and utility statements.

Includes a POST endpoint to auto-generate utility statements from cost items
using the BillingEngine for cost allocation.

Status machine for billing periods:
  draft -> review -> finalized -> delivered
  finalized -> corrected (via revision endpoint)
"""

import hashlib
import json
from decimal import Decimal

from fastapi import APIRouter, HTTPException, Query, status

from ..dependencies import store
from ..domain.billing_engine import (
    AdvancePayment,
    BillingEngine,
    CostEntry,
    UnitShare,
)
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
    UtilityStatementCreate,
    UtilityStatementPatch,
)
from ..storage import NotFoundError, ValidationError

# Valid status transitions for billing periods
_PERIOD_TRANSITIONS: dict[str, set[str]] = {
    "draft": {"review", "finalized"},
    "review": {"draft", "finalized"},
    "finalized": {"delivered", "corrected"},
    "delivered": set(),
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

router = APIRouter(prefix="/billing", tags=["Abrechnung"])


def _build_consumption_by_unit(period, contract_unit_ids: set[str]) -> dict[str, Decimal]:
    """Aggregate consumption per unit from standalone meters/readings in period."""
    meters = [
        m
        for m in store.list_meters()
        if m.unit_id in contract_unit_ids and m.is_active is not False
    ]
    meter_by_id = {m.id: m for m in meters}

    readings_by_meter: dict[str, list] = {}
    for reading in store.list_standalone_meter_readings():
        meter = meter_by_id.get(reading.meter_id)
        if meter is None:
            continue
        if not (period.start_date <= reading.reading_date <= period.end_date):
            continue
        readings_by_meter.setdefault(reading.meter_id, []).append(reading)

    consumption_by_unit: dict[str, Decimal] = {}
    for meter_id, readings in readings_by_meter.items():
        if len(readings) < 2:
            continue
        sorted_readings = sorted(readings, key=lambda r: r.reading_date)
        consumption = Decimal(str(sorted_readings[-1].value)) - Decimal(str(sorted_readings[0].value))
        if consumption <= 0:
            continue
        unit_id = meter_by_id[meter_id].unit_id
        consumption_by_unit[unit_id] = consumption_by_unit.get(unit_id, Decimal("0")) + consumption

    return consumption_by_unit


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
        return store._patch_entity(
            None, period_id, payload, "Abrechnungsperiode nicht gefunden"
        )
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
        return store._patch_entity(
            None, key_id, payload, "Verteilerschlüssel nicht gefunden"
        )
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
        return store._patch_entity(
            None, item_id, payload, "Kostenposition nicht gefunden"
        )
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

    blockers: list[BillingPreflightIssue] = []
    warnings: list[BillingPreflightIssue] = []

    def add_issue(severity: str, code: str, message: str, context: str | None = None) -> None:
        issue = BillingPreflightIssue(code=code, message=message, severity=severity, context=context)
        if severity == "blocker":
            blockers.append(issue)
        else:
            warnings.append(issue)

    contracts_in_period = [
        c
        for c in store.list_contracts()
        if c.property_id == period.property_id
        and c.status == "active"
        and c.start_date <= period.end_date
        and (c.end_date is None or c.end_date >= period.start_date)
    ]

    cost_items = [ci for ci in store.list_cost_items() if ci.billing_period_id == period_id]
    used_key_ids = {ci.allocation_key_id for ci in cost_items}
    allocation_keys = {k.id: k for k in store.list_allocation_keys() if k.id in used_key_ids}

    if not contracts_in_period:
        add_issue("blocker", "NO_ACTIVE_CONTRACTS", "Keine aktiven Verträge im Abrechnungszeitraum gefunden")
    if not cost_items:
        add_issue("blocker", "NO_COST_ITEMS", "Keine Kostenpositionen für diese Periode vorhanden")

    missing_key_ids = sorted([key_id for key_id in used_key_ids if key_id not in allocation_keys])
    if missing_key_ids:
        add_issue(
            "blocker",
            "MISSING_ALLOCATION_KEYS",
            "Verteilerschlüssel für Kostenpositionen fehlen",
            ", ".join(missing_key_ids),
        )

    unit_cache = {}
    missing_unit_contract_ids: list[str] = []
    area_missing_unit_ids: list[str] = []
    non_positive_cost_ids: list[str] = []
    missing_advance_contract_ids: list[str] = []
    missing_person_count_unit_ids: list[str] = []

    requires_area = any(k.key_type == "area_sqm" for k in allocation_keys.values())
    requires_person_count = any(k.key_type == "person_count" for k in allocation_keys.values())
    requires_consumption = any(k.key_type == "consumption" for k in allocation_keys.values())

    for contract in contracts_in_period:
        try:
            unit = store.get_unit(contract.unit_id)
            unit_cache[contract.id] = unit
        except Exception:
            missing_unit_contract_ids.append(contract.id)
            continue

        if requires_area and (unit.area_sqm is None or unit.area_sqm <= 0):
            area_missing_unit_ids.append(unit.id)
        if requires_person_count and (unit.rooms is None or unit.rooms <= 0):
            missing_person_count_unit_ids.append(unit.id)

        monthly_advance = float((unit.service_charge_advance or 0) + (unit.heating_advance or 0))
        if monthly_advance <= 0:
            missing_advance_contract_ids.append(contract.id)

    for ci in cost_items:
        if ci.amount <= 0:
            non_positive_cost_ids.append(ci.id)

    consumption_units_with_data = set()
    if requires_consumption:
        contract_unit_ids = {c.unit_id for c in contracts_in_period}
        consumption_by_unit = _build_consumption_by_unit(period, contract_unit_ids)
        consumption_units_with_data = {uid for uid, val in consumption_by_unit.items() if val > 0}

    if missing_unit_contract_ids:
        add_issue(
            "blocker",
            "MISSING_UNITS",
            "Vertragszuordnungen ohne vorhandene Einheit",
            ", ".join(missing_unit_contract_ids),
        )
    if area_missing_unit_ids:
        add_issue(
            "blocker",
            "MISSING_AREA",
            "Fläche fehlt oder ist 0 für area_sqm-Verteilung",
            ", ".join(sorted(set(area_missing_unit_ids))),
        )
    if missing_person_count_unit_ids:
        add_issue(
            "blocker",
            "MISSING_PERSON_COUNT",
            "rooms fehlt oder ist 0 für person_count-Verteilung",
            ", ".join(sorted(set(missing_person_count_unit_ids))),
        )
    if requires_consumption and not consumption_units_with_data and contracts_in_period:
        add_issue(
            "blocker",
            "MISSING_CONSUMPTION",
            "Keine verwertbaren Verbrauchsdaten für consumption-Verteilung im Zeitraum",
        )
    if non_positive_cost_ids:
        add_issue(
            "warning",
            "NON_POSITIVE_COST",
            "Kostenpositionen mit <= 0 Betrag gefunden",
            ", ".join(non_positive_cost_ids),
        )
    if missing_advance_contract_ids:
        add_issue(
            "warning",
            "MISSING_ADVANCE",
            "Verträge ohne Nebenkosten-/Heizkostenvorauszahlung",
            ", ".join(missing_advance_contract_ids),
        )

    metrics = {
        "contracts_in_period": len(contracts_in_period),
        "cost_items": len(cost_items),
        "allocation_keys_used": len(used_key_ids),
        "allocation_keys_missing": len(missing_key_ids),
        "units_missing": len(missing_unit_contract_ids),
        "area_missing_units": len(set(area_missing_unit_ids)),
        "person_count_missing_units": len(set(missing_person_count_unit_ids)),
        "consumption_units_with_data": len(consumption_units_with_data),
        "contracts_without_advance": len(missing_advance_contract_ids),
        "non_positive_cost_items": len(non_positive_cost_ids),
    }

    return BillingPreflightResult(
        billing_period_id=period_id,
        has_blockers=bool(blockers),
        blockers=blockers,
        warnings=warnings,
        metrics=metrics,
    )


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
        patch_data = {}
        if stmt.status != "finalized":
            patch_data["status"] = "finalized"
        if not stmt.snapshot_hash:
            patch_data["snapshot_hash"] = snapshot
        if patch_data:
            store._patch_entity(
                None,
                stmt.id,
                UtilityStatementPatch(**patch_data),
                "Betriebskostenabrechnung nicht gefunden",
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
        return store._patch_entity(
            None, statement_id, payload, "Betriebskostenabrechnung nicht gefunden"
        )
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
    """Auto-generate utility statements for all contracts in the billing period.

    Uses cost items, allocation keys, and unit shares (area_sqm from units)
    to distribute costs. Compares with service charge advances from contracts
    to compute the balance (Nachzahlung/Guthaben).

    Existing statements for this period are deleted first (regeneration).
    """
    try:
        period = store.get_billing_period(period_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    _assert_period_mutable(period)

    property_id = period.property_id

    # Find all active contracts for the property whose dates overlap the period
    contracts_in_period = [
        c for c in store.list_contracts()
        if c.property_id == property_id
        and c.status == "active"
        and c.start_date <= period.end_date
        and (c.end_date is None or c.end_date >= period.start_date)
    ]

    if not contracts_in_period:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Keine aktiven Verträge im Abrechnungszeitraum gefunden",
        )

    # Find cost items for this period
    cost_items = [
        ci for ci in store.list_cost_items()
        if ci.billing_period_id == period_id
    ]

    if not cost_items:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Keine Kostenpositionen für diese Abrechnungsperiode vorhanden",
        )

    # Build the engine
    engine = BillingEngine()

    # Collect allocation keys used by cost items
    used_key_ids = {ci.allocation_key_id for ci in cost_items}
    allocation_keys = {
        k.id: k for k in store.list_allocation_keys()
        if k.id in used_key_ids
    }

    # Pre-fetch units for the contracts (log missing units instead of silent skip)
    unit_cache = {}
    for contract in contracts_in_period:
        try:
            unit_cache[contract.unit_id] = store.get_unit(contract.unit_id)
        except Exception:
            import logging as _log
            _log.getLogger(__name__).warning(
                "Unit %s for contract %s not found — skipping in billing calculation",
                contract.unit_id, contract.id,
            )

    contract_unit_ids = {c.unit_id for c in contracts_in_period}
    consumption_by_unit = _build_consumption_by_unit(period, contract_unit_ids)

    # Register unit shares for each allocation key
    for contract in contracts_in_period:
        unit = unit_cache.get(contract.unit_id)
        if unit is None:
            continue

        for key_id, key in allocation_keys.items():
            if key.key_type == "area_sqm":
                share_value = Decimal(str(unit.area_sqm or 0))
            elif key.key_type == "unit_count":
                share_value = Decimal("1")
            elif key.key_type == "person_count":
                share_value = Decimal(str(unit.rooms or 0))
            elif key.key_type == "consumption":
                share_value = consumption_by_unit.get(unit.id, Decimal("0"))
            else:
                # Default: equal distribution
                share_value = Decimal("1")

            if share_value <= Decimal("0"):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=(
                        f"Ungültiger Anteil für Schlüsseltyp '{key.key_type}' "
                        f"(Vertrag {contract.id}, Einheit {unit.id})"
                    ),
                )

            engine.add_unit_share(
                key_id,
                UnitShare(
                    unit_id=unit.id,
                    contract_id=contract.id,
                    share_value=share_value,
                ),
            )

    # Add cost entries
    for ci in cost_items:
        engine.add_cost(
            CostEntry(
                description=ci.description,
                amount=Decimal(str(ci.amount)),
                allocation_key_id=ci.allocation_key_id,
            )
        )

    # Calculate advances: sum of service_charge_advance * months in period for each contract
    for contract in contracts_in_period:
        unit = unit_cache.get(contract.unit_id)
        monthly_advance = (
            Decimal(str((unit.service_charge_advance or 0) + (unit.heating_advance or 0)))
            if unit else Decimal("0")
        )

        # Calculate overlapping months
        overlap_start = max(contract.start_date, period.start_date)
        overlap_end = min(contract.end_date, period.end_date) if contract.end_date else period.end_date
        if overlap_end < overlap_start:
            continue
        months = ((overlap_end.year - overlap_start.year) * 12
                  + overlap_end.month - overlap_start.month + 1)
        total_advance = monthly_advance * months

        engine.add_advance(
            AdvancePayment(
                unit_id=contract.unit_id,
                contract_id=contract.id,
                total_advance=total_advance,
            )
        )

    generated = engine.generate()

    # Delete existing statements for this period
    existing_statements = [
        us for us in store.list_utility_statements()
        if us.billing_period_id == period_id
    ]
    for us in existing_statements:
        store.delete_utility_statement(us.id)

    # Create new statements
    results: list[UtilityStatement] = []
    for stmt in generated:
        line_items_data = [
            {"description": li.description, "allocated_amount": float(li.allocated_amount)}
            for li in stmt.line_items
        ]
        created = store.create_utility_statement(
            UtilityStatementCreate(
                billing_period_id=period_id,
                contract_id=stmt.contract_id,
                unit_id=stmt.unit_id,
                total_cost=float(stmt.total_cost),
                advance_paid=float(stmt.advance_paid),
                balance=float(stmt.balance),
                line_items=line_items_data,
            )
        )
        results.append(created)

    return results


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
        period = store.get_billing_period(period_id)
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
        period = store.get_billing_period(period_id)
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
def mark_statement_delivered(statement_id: str):
    """Mark a utility statement as delivered. Requires finalized period."""
    from datetime import datetime as _dt

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
        None,
        statement_id,
        UtilityStatementPatch(
            delivery_status="delivered",
            delivered_at=_dt.utcnow(),
            status="delivered",
        ),
        "Betriebskostenabrechnung nicht gefunden",
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

    created_count = 0
    for stmt in period_statements:
        if stmt.balance > 0:
            # Nachzahlung -> Forderung
            store.create_receivable(
                ReceivableCreate(
                    contract_id=stmt.contract_id,
                    due_date=period.end_date,
                    amount_due=stmt.balance,
                    status="open",
                )
            )
            created_count += 1
        elif stmt.balance < 0:
            # Guthaben -> negative receivable for tracking
            store.create_receivable(
                ReceivableCreate(
                    contract_id=stmt.contract_id,
                    due_date=period.end_date,
                    amount_due=stmt.balance,
                    status="open",
                )
            )
            created_count += 1

    return {"period_id": period_id, "created_receivables": created_count}


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
        store.create_cost_item(
            CostItemCreate(
                billing_period_id=new_period.id,
                description=ci.description,
                amount=ci.amount,
                allocation_key_id=ci.allocation_key_id,
            )
        )

    return {
        "new_period_id": new_period.id,
        "source_period_id": period_id,
        "revision": new_revision,
        "revision_notes": revision_notes,
    }


def download_utility_statement_pdf(statement_id: str):
    """Generate a PDF for a single utility statement (or text fallback)."""
    from starlette.responses import Response as RawResponse

    try:
        stmt = store.get_utility_statement(statement_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    # Try to build a real PDF with reportlab
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.lib.units import mm
        from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

        import io
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=20*mm, rightMargin=20*mm,
                                topMargin=25*mm, bottomMargin=18*mm)
        styles = getSampleStyleSheet()
        story = []

        story.append(Paragraph("Betriebskostenabrechnung", styles["Title"]))
        story.append(Spacer(1, 12))

        # Try to resolve names
        unit_label = stmt.unit_id
        try:
            unit = store.get_unit(stmt.unit_id)
            unit_label = unit.label or stmt.unit_id
        except Exception:
            pass

        story.append(Paragraph(f"Einheit: {unit_label}", styles["Normal"]))
        story.append(Paragraph(f"Vertrag: {stmt.contract_id}", styles["Normal"]))
        story.append(Paragraph(f"Revision: {stmt.revision}", styles["Normal"]))
        story.append(Spacer(1, 12))

        # Line items table
        if stmt.line_items:
            rows = [["Kostenart", "Anteil (€)"]]
            for li in stmt.line_items:
                rows.append([
                    li.get("description", "—"),
                    f"{li.get('allocated_amount', 0):.2f} €",
                ])
            rows.append(["Gesamtkosten", f"{stmt.total_cost:.2f} €"])
            rows.append(["Vorauszahlungen", f"{stmt.advance_paid:.2f} €"])
            rows.append(["Saldo", f"{stmt.balance:.2f} €"])

            t = Table(rows)
            t.setStyle(TableStyle([
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("ALIGN", (1, 0), (1, -1), "RIGHT"),
                ("LINEBELOW", (0, 0), (-1, 0), 0.5, (0, 0, 0)),
                ("LINEABOVE", (0, -3), (-1, -3), 0.5, (0, 0, 0)),
            ]))
            story.append(t)
        else:
            story.append(Paragraph(f"Gesamtkosten: {stmt.total_cost:.2f} €", styles["Normal"]))
            story.append(Paragraph(f"Vorauszahlungen: {stmt.advance_paid:.2f} €", styles["Normal"]))
            story.append(Paragraph(f"Saldo: {stmt.balance:.2f} €", styles["Normal"]))

        doc.build(story)
        return RawResponse(
            content=buffer.getvalue(),
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="statement_{statement_id}.pdf"'},
        )
    except ImportError:
        # Fallback: plain text
        lines = [
            "Betriebskostenabrechnung",
            f"Statement ID: {stmt.id}",
            f"Einheit: {stmt.unit_id}",
            f"Vertrag: {stmt.contract_id}",
            f"Gesamtkosten: {stmt.total_cost:.2f} €",
            f"Vorauszahlung: {stmt.advance_paid:.2f} €",
            f"Saldo: {stmt.balance:.2f} €",
            f"Status: {stmt.status}",
            f"Revision: {stmt.revision}",
        ]
        return RawResponse(
            content="\n".join(lines).encode("utf-8"),
            media_type="text/plain",
            headers={"Content-Disposition": f'attachment; filename="statement_{statement_id}.txt"'},
        )


@router.get("/statements/{statement_id}/pdf")
def get_utility_statement_pdf(statement_id: str):
    """Download a PDF for a single utility statement."""
    return download_utility_statement_pdf(statement_id)
