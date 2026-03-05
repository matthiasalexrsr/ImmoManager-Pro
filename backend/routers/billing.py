"""Router for billing periods, allocation keys, cost items, and utility statements.

Includes a POST endpoint to auto-generate utility statements from cost items
using the BillingEngine for cost allocation.
"""

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
        return store.update_billing_period(period_id, payload)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.patch("/periods/{period_id}", response_model=BillingPeriod)
def patch_billing_period(period_id: str, payload: BillingPeriodPatch) -> BillingPeriod:
    try:
        return store._patch_entity(
            None, period_id, payload, "Abrechnungsperiode nicht gefunden"
        )
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.delete("/periods/{period_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_billing_period(period_id: str) -> None:
    try:
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
        return store.update_cost_item(item_id, payload)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.patch("/cost-items/{item_id}", response_model=CostItem)
def patch_cost_item(item_id: str, payload: CostItemPatch) -> CostItem:
    try:
        return store._patch_entity(
            None, item_id, payload, "Kostenposition nicht gefunden"
        )
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.delete("/cost-items/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_cost_item(item_id: str) -> None:
    try:
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


@router.post("/periods/{period_id}/finalize", response_model=BillingPeriod)
def finalize_billing_period(period_id: str) -> BillingPeriod:
    """Finalize billing period after successful preflight and generated statements."""
    try:
        period = store.get_billing_period(period_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    if period.status == "finalized":
        return period

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
        if stmt.status != "finalized":
            store._patch_entity(
                None,
                stmt.id,
                UtilityStatementPatch(status="finalized"),
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
        return store._patch_entity(
            None, statement_id, payload, "Betriebskostenabrechnung nicht gefunden"
        )
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.delete("/statements/{statement_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_utility_statement(statement_id: str) -> None:
    try:
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
        created = store.create_utility_statement(
            UtilityStatementCreate(
                billing_period_id=period_id,
                contract_id=stmt.contract_id,
                unit_id=stmt.unit_id,
                total_cost=float(stmt.total_cost),
                advance_paid=float(stmt.advance_paid),
                balance=float(stmt.balance),
            )
        )
        results.append(created)

    return results
