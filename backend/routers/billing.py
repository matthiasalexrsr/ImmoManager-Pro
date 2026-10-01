"""Router for billing periods, allocation keys, cost items, and utility statements.

Includes a POST endpoint to auto-generate utility statements from cost items
using the BillingEngine for cost allocation.

Status machine for billing periods:
  draft -> review -> finalized -> delivered
  finalized -> corrected (via revision endpoint)
"""

import logging
from decimal import Decimal
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status

from ..auth import get_current_user
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
    UtilityStatementPatch,
)
from ..services import billing_settlement as settlement
from ..services import credit_ledger
from ..services.credit_types import (
    CreditOffsetCreate,
    CreditPayoutCreate,
    CreditReceipt,
    CreditReversal,
    CreditReversalCreate,
)
from ..services.payments import FinancialConsistencyError
from ..storage import NotFoundError, ValidationError


def _assert_period_mutable(period: BillingPeriod) -> None:
    try:
        settlement.assert_mutable(period)
    except FinancialConsistencyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


def _billing_call(operation, *args):
    try:
        return operation(store, *args)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except FinancialConsistencyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _compute_snapshot_hash(period_id: str) -> str:
    return settlement.snapshot_hash([s for s in store.list_utility_statements() if s.billing_period_id == period_id],
        store.get_billing_period(period_id).owner_cost_share)


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/billing", tags=["Abrechnung"])


@router.get("/contracts/{contract_id}/credits")
def credit_summary(contract_id: str):
    return _billing_call(credit_ledger.summary, contract_id)


@router.get("/contracts/{contract_id}/credit-receipts")
def credit_receipts(contract_id: str, offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=1000)):
    return _billing_call(lambda active, cid: credit_ledger.journal(active, cid, offset=offset, limit=limit), contract_id)


@router.post("/credit-payouts", response_model=CreditReceipt, status_code=201)
def create_credit_payout(payload: CreditPayoutCreate, user=Depends(get_current_user)):
    return _billing_call(lambda active, command: credit_ledger.create_receipt(active, command, getattr(user, "id", None)), payload)


@router.post("/credit-offsets", response_model=CreditReceipt, status_code=201)
def create_credit_offset(payload: CreditOffsetCreate, user=Depends(get_current_user)):
    return _billing_call(lambda active, command: credit_ledger.create_receipt(active, command, getattr(user, "id", None)), payload)


@router.post("/credit-receipts/{receipt_id}/reversal", response_model=CreditReversal, status_code=201)
def reverse_credit_receipt(receipt_id: str, payload: CreditReversalCreate, user=Depends(get_current_user)):
    return _billing_call(lambda active, rid, command: credit_ledger.reverse_receipt(active, rid, command, getattr(user, "id", None)), receipt_id, payload)


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
    if payload.status != "draft":
        raise HTTPException(status_code=400, detail="Neue Perioden beginnen als Entwurf.")
    try:
        return store.create_billing_period(payload)
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/periods/{period_id}", response_model=BillingPeriod)
def get_billing_period(period_id: str) -> BillingPeriod:
    try:
        return store.get_billing_period(period_id)
    except FinancialConsistencyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.put("/periods/{period_id}", response_model=BillingPeriod)
def update_billing_period(period_id: str, payload: BillingPeriodCreate) -> BillingPeriod:
    try:
        existing = store.get_billing_period(period_id)
        _assert_period_mutable(existing)
        return store.update_billing_period(period_id, payload)
    except FinancialConsistencyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
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
    except FinancialConsistencyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.delete("/periods/{period_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_billing_period(period_id: str) -> None:
    try:
        existing = store.get_billing_period(period_id)
        _assert_period_mutable(existing)
        store.delete_billing_period(period_id)
    except FinancialConsistencyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
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
    except FinancialConsistencyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.put("/allocation-keys/{key_id}", response_model=AllocationKey)
def update_allocation_key(key_id: str, payload: AllocationKeyCreate) -> AllocationKey:
    try:
        return store.update_allocation_key(key_id, payload)
    except FinancialConsistencyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.patch("/allocation-keys/{key_id}", response_model=AllocationKey)
def patch_allocation_key(key_id: str, payload: AllocationKeyPatch) -> AllocationKey:
    try:
        return store._patch_entity("allocation_key", key_id, payload)
    except FinancialConsistencyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.delete("/allocation-keys/{key_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_allocation_key(key_id: str) -> None:
    try:
        store.delete_allocation_key(key_id)
    except FinancialConsistencyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
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
    except FinancialConsistencyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.put("/cost-items/{item_id}", response_model=CostItem)
def update_cost_item(item_id: str, payload: CostItemCreate) -> CostItem:
    try:
        existing = store.get_cost_item(item_id)
        period = store.get_billing_period(existing.billing_period_id)
        _assert_period_mutable(period)
        return store.update_cost_item(item_id, payload)
    except FinancialConsistencyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
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
    except FinancialConsistencyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.delete("/cost-items/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_cost_item(item_id: str) -> None:
    try:
        existing = store.get_cost_item(item_id)
        period = store.get_billing_period(existing.billing_period_id)
        _assert_period_mutable(period)
        store.delete_cost_item(item_id)
    except FinancialConsistencyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/periods/{period_id}/preflight", response_model=BillingPreflightResult)
def get_billing_period_preflight(period_id: str) -> BillingPreflightResult:
    return _run_billing_period_preflight(period_id)


def _run_billing_period_preflight(period_id: str) -> BillingPreflightResult:
    try:
        period = store.get_billing_period(period_id)
    except FinancialConsistencyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
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

    contracts_in_period = settlement.eligible_contracts(store, period)
    overlaps = settlement.overlapping_contract_ids(contracts_in_period, period)
    if overlaps:
        add_issue("blocker", "OVERLAPPING_CONTRACTS", "Vertragszeiträume derselben Einheit überschneiden sich", ", ".join(sorted(overlaps)))

    all_cost_items = [ci for ci in store.list_cost_items() if ci.billing_period_id == period_id]
    cost_items = [ci for ci in all_cost_items if ci.is_recoverable]
    used_key_ids = {ci.allocation_key_id for ci in cost_items}
    allocation_keys = {k.id: k for k in store.list_allocation_keys() if k.id in used_key_ids}

    if not contracts_in_period:
        add_issue("blocker", "NO_ACTIVE_CONTRACTS", "Keine gültigen Verträge im Abrechnungszeitraum gefunden (Entwürfe und stornierte Verträge sind ausgeschlossen)")
    if not all_cost_items:
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

    vacant_days = settlement.property_vacancy(store, period, contracts_in_period)
    vacant_units = {uid: days for uid, days in vacant_days.items() if days > 0}
    if vacant_units:
        missing_owner_area = [uid for uid in vacant_units if requires_area and not (store.get_unit(uid).area_sqm or 0) > 0]
        if missing_owner_area:
            add_issue("blocker", "MISSING_OWNER_AREA", "Für den Eigentümeranteil fehlen Flächen leerstehender Einheiten", ", ".join(sorted(missing_owner_area)))
        unsupported = [k.name for k in allocation_keys.values() if k.key_type in {"person_count", "consumption"}]
        if unsupported:
            add_issue("blocker", "VACANCY_ALLOCATION_BASIS_MISSING",
                "Leerstand kann bei Personen-/Verbrauchsschlüsseln ohne datierte Bewohner- bzw. Verbrauchsanteile des Eigentümers nicht zuverlässig aufgeteilt werden",
                ", ".join(unsupported))
        else:
            add_issue("warning", "OWNER_VACANCY_SHARE", "Leerstandsanteile werden dem Eigentümer zugeordnet; die Bezugsbasis umfasst alle aktuell konfigurierten Einheiten",
                ", ".join(f"{store.get_unit(uid).label}: {days} Tage" for uid, days in sorted(vacant_units.items())))
    unknown_keys = [k.name for k in allocation_keys.values() if k.key_type not in {"area_sqm", "unit_count", "person_count", "consumption"}]
    if unknown_keys:
        add_issue("blocker", "UNKNOWN_ALLOCATION_TYPE", "Verteilerschlüssel ohne unterstützte Berechnungsbasis", ", ".join(unknown_keys))

    for contract in contracts_in_period:
        try:
            unit = store.get_unit(contract.unit_id)
            unit_cache[contract.id] = unit
        except Exception:
            logger.debug("Unit %s for contract %s not found during billing validation", contract.unit_id, contract.id, exc_info=True)
            missing_unit_contract_ids.append(contract.id)
            continue

        if requires_area and (unit.area_sqm is None or unit.area_sqm <= 0):
            area_missing_unit_ids.append(unit.id)
        _pc = unit.person_count if getattr(unit, "person_count", None) else unit.rooms
        if requires_person_count and (_pc is None or _pc <= 0):
            missing_person_count_unit_ids.append(unit.id)

        actual_advance, _ = settlement.actual_paid_advances(store, contract, period)
        if actual_advance <= 0:
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
            "person_count (oder rooms als Fallback) fehlt oder ist 0 für person_count-Verteilung",
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
            "Verträge ohne gebuchte bezahlte Nebenkosten-/Heizkostenvorauszahlung zum Periodenende",
            ", ".join(missing_advance_contract_ids),
        )

    metrics: dict[str, float | int | str | bool] = {
        "contracts_in_period": len(contracts_in_period),
        "cost_items": len(all_cost_items),
        "vacant_units": len(vacant_units),
        "vacant_unit_days": sum(vacant_units.values()),
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
    except FinancialConsistencyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
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
    except FinancialConsistencyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
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
    """Finalize all statement snapshots and the period in a single transaction."""
    return _billing_call(settlement.finalize_period, period_id, lambda: _run_billing_period_preflight(period_id))


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
    except FinancialConsistencyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.patch("/statements/{statement_id}", response_model=UtilityStatement)
def patch_utility_statement(statement_id: str, payload: UtilityStatementPatch) -> UtilityStatement:
    try:
        existing = store.get_utility_statement(statement_id)
        period = store.get_billing_period(existing.billing_period_id)
        _assert_period_mutable(period)
        return store._patch_entity("utility_statement", statement_id, payload)
    except FinancialConsistencyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.delete("/statements/{statement_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_utility_statement(statement_id: str) -> None:
    try:
        existing = store.get_utility_statement(statement_id)
        period = store.get_billing_period(existing.billing_period_id)
        _assert_period_mutable(period)
        store.delete_utility_statement(statement_id)
    except FinancialConsistencyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
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
    """Generate historic occupied-tenancy statements from paid monthly snapshots."""
    return _billing_call(settlement.replace_statements, period_id,
        lambda period: _build_utility_statements(period))


def _build_utility_statements(period: BillingPeriod) -> tuple[list[UtilityStatement], dict]:
    period_id = period.id
    contracts_in_period = settlement.eligible_contracts(store, period)
    if settlement.overlapping_contract_ids(contracts_in_period, period):
        raise HTTPException(status_code=400, detail="Überschneidende Vertragszeiträume derselben Einheit müssen vor der Abrechnung geklärt werden.")

    if not contracts_in_period:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Keine gültigen Verträge im Abrechnungszeitraum gefunden (Entwürfe und stornierte Verträge sind ausgeschlossen)",
        )

    preflight = _run_billing_period_preflight(period_id)
    if preflight.has_blockers:
        raise HTTPException(status_code=400, detail="Abrechnung blockiert: " + "; ".join(i.message for i in preflight.blockers))
    all_cost_items = sorted((ci for ci in store.list_cost_items() if ci.billing_period_id == period_id), key=lambda ci: ci.id)
    cost_items = [ci for ci in all_cost_items if ci.is_recoverable]

    # Build the engine
    engine = BillingEngine()

    # Collect allocation keys used by cost items
    used_key_ids = {ci.allocation_key_id for ci in cost_items}
    allocation_keys = {
        k.id: k for k in store.list_allocation_keys()
        if k.id in used_key_ids
    }

    if used_key_ids - set(allocation_keys):
        raise HTTPException(status_code=400, detail="Verteilerschlüssel fehlen.")
    unit_cache = {u.id: u for u in store.list_units() if u.property_id == period.property_id}
    vacant_days = settlement.property_vacancy(store, period, contracts_in_period)
    period_days = (period.end_date - period.start_date).days + 1

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
                _pc = unit.person_count if getattr(unit, "person_count", None) else unit.rooms
                share_value = Decimal(str(_pc or 0))
            elif key.key_type == "consumption":
                share_value = consumption_by_unit.get(unit.id, Decimal("0"))
            else:
                raise HTTPException(status_code=400, detail=f"Nicht unterstützter Verteilerschlüssel: {key.key_type}")

            if share_value <= Decimal("0"):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=(
                        f"Ungültiger Anteil für Schlüsseltyp '{key.key_type}' "
                        f"(Vertrag {contract.id}, Einheit {unit.id})"
                    ),
                )

            overlap_start = max(contract.start_date, period.start_date)
            overlap_end = min(contract.end_date or period.end_date, period.end_date)
            occupied_days = (overlap_end - overlap_start).days + 1
            period_days = (period.end_date - period.start_date).days + 1
            share_value = share_value * Decimal(occupied_days) / Decimal(period_days)
            engine.add_unit_share(
                key_id,
                UnitShare(
                    unit_id=unit.id,
                    contract_id=contract.id,
                    share_value=share_value,
                ),
            )

    # Even a period containing owner-only costs can produce zero-cost tenant
    # statements and refund actually paid advances without inventing rent debts.
    for contract in contracts_in_period:
        engine.add_unit_share("__tenancies__", UnitShare(unit_id=contract.unit_id,
            contract_id=contract.id, share_value=Decimal("1")))
    owner_ids = set()
    for unit_id, vacant in sorted(vacant_days.items()):
        if not vacant:
            continue
        unit = unit_cache[unit_id]
        owner_id = f"owner:{unit_id}"
        owner_ids.add(owner_id)
        for key_id, key in allocation_keys.items():
            base = Decimal(str(unit.area_sqm)) if key.key_type == "area_sqm" else Decimal("1")
            engine.add_unit_share(key_id, UnitShare(unit_id=unit_id, contract_id=owner_id,
                share_value=base * vacant / period_days))

    # Add cost entries
    for ci in cost_items:
        engine.add_cost(
            CostEntry(
                description=ci.description,
                amount=Decimal(str(ci.amount)),
                allocation_key_id=ci.allocation_key_id,
            )
        )

    advance_evidence = {}
    for contract in contracts_in_period:
        total_advance, details = settlement.actual_paid_advances(store, contract, period)
        advance_evidence[contract.id] = details
        engine.add_advance(AdvancePayment(unit_id=contract.unit_id,
            contract_id=contract.id, total_advance=total_advance))

    generated = engine.generate()

    owner_lines = [{"cost_item_id": cost_items[index].id, "description": line.description,
        "allocated_amount": float(line.allocated_amount), "unit_id": stmt.unit_id, "reason": "vacancy"}
        for stmt in generated if stmt.contract_id in owner_ids for index, line in enumerate(stmt.line_items)
        if line.allocated_amount != 0]
    owner_lines.extend({"cost_item_id": ci.id, "description": ci.description, "allocated_amount": ci.amount,
        "unit_id": None, "reason": "non_recoverable"} for ci in all_cost_items if not ci.is_recoverable)
    vacancy_amount = sum((stmt.total_cost for stmt in generated if stmt.contract_id in owner_ids), Decimal("0"))
    non_recoverable = sum((Decimal(str(ci.amount)) for ci in all_cost_items if not ci.is_recoverable), Decimal("0"))
    owner = {"total_amount": float(vacancy_amount + non_recoverable),
        "recoverable_vacancy_amount": float(vacancy_amount), "non_recoverable_amount": float(non_recoverable),
        "property_cost_total": float(sum((Decimal(str(ci.amount)) for ci in all_cost_items), Decimal("0"))),
        "tenant_cost_total": float(sum((stmt.total_cost for stmt in generated if stmt.contract_id not in owner_ids), Decimal("0"))),
        "vacant_unit_days": {uid: days for uid, days in vacant_days.items() if days},
        "line_items": owner_lines, "policy": "property_units_occupied_days"}
    statements = [UtilityStatement(id=str(uuid4()), billing_period_id=period_id,
        contract_id=stmt.contract_id, unit_id=stmt.unit_id, total_cost=float(stmt.total_cost),
        advance_paid=float(stmt.advance_paid), balance=float(stmt.balance),
        advance_details=advance_evidence[stmt.contract_id],
        line_items=[{"description": li.description, "allocated_amount": float(li.allocated_amount)}
                    for li in stmt.line_items]) for stmt in generated if stmt.contract_id not in owner_ids]
    return statements, owner


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
    except FinancialConsistencyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
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
    except FinancialConsistencyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
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
def mark_statement_delivered(statement_id: str, channel: str = "email") -> UtilityStatement:
    return _billing_call(settlement.mark_delivered, statement_id, channel)


@router.post("/periods/{period_id}/create-receivables")
def create_receivables_from_period(period_id: str):
    """Book each finalized debt or available credit exactly once, atomically."""
    return _billing_call(settlement.post_settlements, period_id)


@router.get("/periods/{period_id}/settlements")
def list_period_settlements(period_id: str):
    return _billing_call(settlement.settlement_summary, period_id)


@router.post("/periods/{period_id}/revisions")
def create_period_revision(period_id: str, revision_notes: str = Query("", alias="revision_notes")):
    return _billing_call(settlement.create_revision, period_id, revision_notes if isinstance(revision_notes, str) else "")


@router.post("/periods/{period_id}/dispute", response_model=BillingPeriod)
def dispute_billing_period(period_id: str, reason: str = Query("", alias="reason")) -> BillingPeriod:
    return _billing_call(settlement.dispute_period, period_id)


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
    except FinancialConsistencyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
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


def download_utility_statement_pdf(statement_id: str):
    """Generate a PDF for a single utility statement (or text fallback)."""
    from starlette.responses import Response as RawResponse

    try:
        stmt = store.get_utility_statement(statement_id)
    except FinancialConsistencyError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    # Try to build a real PDF with reportlab
    try:
        import io

        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.lib.units import mm
        from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
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
            logger.debug("Could not resolve unit label for %s", stmt.unit_id, exc_info=True)

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
