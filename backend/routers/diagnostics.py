"""Diagnostics API — cross-entity data consistency tests.

Runs validation checks across all entities to find orphaned references,
broken FK relationships, data inconsistencies, and missing required fields.
Results are returned as structured JSON and also written to dev_notes.log.

All tests run read-only — they never modify data.
"""

import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..config import settings
from ..dependencies import get_store

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/diagnostics", tags=["Diagnostics"])


def _check_diagnostics_allowed():
    """Guard: block diagnostics in production unless explicitly enabled.

    Diagnostics can expose entity counts, FK relationships, and internal
    structure. In production, this endpoint is disabled by default to
    prevent information leakage.  Enable via DIAGNOSTICS_ALLOW_IN_PRODUCTION=true.
    """
    if settings.is_production and not settings.diagnostics_allow_in_production:
        raise HTTPException(
            status_code=403,
            detail="Diagnostics sind in der Produktionsumgebung deaktiviert.",
        )


# ---------------------------------------------------------------------------
# Result models
# ---------------------------------------------------------------------------

class DiagnosticIssue(BaseModel):
    test: str
    severity: str  # error | warning | info
    entity_type: str
    entity_id: str | None = None
    message: str
    details: dict | None = None


class DiagnosticResult(BaseModel):
    test: str
    passed: bool
    duration_ms: float
    issues: list[DiagnosticIssue] = []
    checked: int = 0


class DiagnosticsReport(BaseModel):
    timestamp: str
    total_tests: int
    passed: int
    failed: int
    warnings: int
    total_issues: int
    duration_ms: float
    results: list[DiagnosticResult]


# ---------------------------------------------------------------------------
# Test runner infrastructure
# ---------------------------------------------------------------------------

_TESTS: list[tuple[str, Any]] = []


def diagnostic_test(name: str):
    """Register a diagnostic test function."""
    def decorator(func):
        _TESTS.append((name, func))
        return func
    return decorator


def _safe_list(store, method_name: str) -> list:
    """Safely call a store list method, returning [] on error."""
    try:
        fn = getattr(store, method_name, None)
        if fn is None:
            return []
        return fn() or []
    except Exception as exc:
        logger.warning("Diagnostics: failed to list %s: %s", method_name, exc)
        return []


def _safe_get(store, method_name: str, entity_id: str):
    """Safely get a single entity, returning None on error."""
    try:
        fn = getattr(store, method_name, None)
        if fn is None:
            return None
        return fn(entity_id)
    except Exception:
        logger.debug("Safe get failed for %s/%s", method_name, entity_id, exc_info=True)
        return None


def _ids(entities: list) -> set:
    """Extract all IDs from a list of entities."""
    return {getattr(e, "id", None) or (e.get("id") if isinstance(e, dict) else None) for e in entities} - {None}


# ---------------------------------------------------------------------------
# FK reference check helper
# ---------------------------------------------------------------------------

def _check_fk_references(
    test_name: str,
    entities: list,
    fk_field: str,
    valid_ids: set,
    entity_type: str,
    ref_type: str,
    required: bool = True,
) -> list[DiagnosticIssue]:
    """Check that all FK references in entities point to existing targets."""
    issues = []
    for entity in entities:
        fk_val = getattr(entity, fk_field, None)
        if fk_val is None:
            if required:
                issues.append(DiagnosticIssue(
                    test=test_name,
                    severity="error",
                    entity_type=entity_type,
                    entity_id=getattr(entity, "id", "?"),
                    message=f"Required FK '{fk_field}' is NULL",
                    details={"field": fk_field, "expected_type": ref_type},
                ))
            continue
        if fk_val not in valid_ids:
            issues.append(DiagnosticIssue(
                test=test_name,
                severity="error",
                entity_type=entity_type,
                entity_id=getattr(entity, "id", "?"),
                message=f"Orphaned reference: {fk_field}={fk_val} → {ref_type} not found",
                details={"field": fk_field, "value": fk_val, "expected_type": ref_type},
            ))
    return issues


# ---------------------------------------------------------------------------
# Diagnostic tests
# ---------------------------------------------------------------------------

@diagnostic_test("property_portfolio_fk")
def test_property_portfolio_fk(store):
    """Every property must reference an existing portfolio."""
    properties = _safe_list(store, "list_properties")
    portfolios = _safe_list(store, "list_portfolios")
    portfolio_ids = _ids(portfolios)
    issues = _check_fk_references(
        "property_portfolio_fk", properties, "portfolio_id",
        portfolio_ids, "Property", "Portfolio",
    )
    return issues, len(properties)


@diagnostic_test("unit_property_fk")
def test_unit_property_fk(store):
    """Every unit must reference an existing property."""
    units = _safe_list(store, "list_units")
    properties = _safe_list(store, "list_properties")
    property_ids = _ids(properties)
    issues = _check_fk_references(
        "unit_property_fk", units, "property_id",
        property_ids, "Unit", "Property",
    )
    return issues, len(units)


@diagnostic_test("contract_fk_integrity")
def test_contract_fk_integrity(store):
    """Contracts must reference existing property, unit, and tenant."""
    contracts = _safe_list(store, "list_contracts")
    properties = _safe_list(store, "list_properties")
    units = _safe_list(store, "list_units")
    tenants = _safe_list(store, "list_tenants")
    property_ids = _ids(properties)
    unit_ids = _ids(units)
    tenant_ids = _ids(tenants)

    issues = []
    issues += _check_fk_references("contract_fk_integrity", contracts, "property_id", property_ids, "Contract", "Property")
    issues += _check_fk_references("contract_fk_integrity", contracts, "unit_id", unit_ids, "Contract", "Unit")
    issues += _check_fk_references("contract_fk_integrity", contracts, "tenant_id", tenant_ids, "Contract", "Tenant")
    return issues, len(contracts)


@diagnostic_test("contract_unit_property_match")
def test_contract_unit_property_match(store):
    """Contract's unit must belong to contract's property."""
    contracts = _safe_list(store, "list_contracts")
    units = _safe_list(store, "list_units")
    unit_map = {getattr(u, "id", ""): u for u in units}

    issues = []
    for contract in contracts:
        unit_id = getattr(contract, "unit_id", None)
        prop_id = getattr(contract, "property_id", None)
        if unit_id and prop_id and unit_id in unit_map:
            unit = unit_map[unit_id]
            unit_prop = getattr(unit, "property_id", None)
            if unit_prop and unit_prop != prop_id:
                issues.append(DiagnosticIssue(
                    test="contract_unit_property_match",
                    severity="error",
                    entity_type="Contract",
                    entity_id=getattr(contract, "id", "?"),
                    message=f"Unit {unit_id} belongs to property {unit_prop}, not {prop_id}",
                    details={"unit_id": unit_id, "unit_property_id": unit_prop, "contract_property_id": prop_id},
                ))
    return issues, len(contracts)


@diagnostic_test("booking_account_fk")
def test_booking_account_fk(store):
    """Every booking must reference an existing account."""
    bookings = _safe_list(store, "list_bookings")
    accounts = _safe_list(store, "list_accounts")
    account_ids = _ids(accounts)
    issues = _check_fk_references(
        "booking_account_fk", bookings, "account_id",
        account_ids, "Booking", "Account",
    )
    return issues, len(bookings)


@diagnostic_test("booking_optional_fk")
def test_booking_optional_fk(store):
    """Booking optional references (property, unit, tenant, category) must exist if set."""
    bookings = _safe_list(store, "list_bookings")
    properties = _safe_list(store, "list_properties")
    units = _safe_list(store, "list_units")
    tenants = _safe_list(store, "list_tenants")
    categories = _safe_list(store, "list_categories")

    issues = []
    issues += _check_fk_references("booking_optional_fk", bookings, "property_id", _ids(properties), "Booking", "Property", required=False)
    issues += _check_fk_references("booking_optional_fk", bookings, "unit_id", _ids(units), "Booking", "Unit", required=False)
    issues += _check_fk_references("booking_optional_fk", bookings, "tenant_id", _ids(tenants), "Booking", "Tenant", required=False)
    issues += _check_fk_references("booking_optional_fk", bookings, "category_id", _ids(categories), "Booking", "Category", required=False)
    return issues, len(bookings)


@diagnostic_test("account_portfolio_fk")
def test_account_portfolio_fk(store):
    """Every account must reference an existing portfolio."""
    accounts = _safe_list(store, "list_accounts")
    portfolios = _safe_list(store, "list_portfolios")
    portfolio_ids = _ids(portfolios)
    issues = _check_fk_references(
        "account_portfolio_fk", accounts, "portfolio_id",
        portfolio_ids, "Account", "Portfolio",
    )
    return issues, len(accounts)


@diagnostic_test("deposit_contract_fk")
def test_deposit_contract_fk(store):
    """Every deposit must reference an existing contract."""
    deposits = _safe_list(store, "list_deposits")
    contracts = _safe_list(store, "list_contracts")
    contract_ids = _ids(contracts)
    issues = _check_fk_references(
        "deposit_contract_fk", deposits, "contract_id",
        contract_ids, "Deposit", "Contract",
    )
    return issues, len(deposits)


@diagnostic_test("receivable_contract_fk")
def test_receivable_contract_fk(store):
    """Every receivable must reference an existing contract."""
    receivables = _safe_list(store, "list_receivables")
    contracts = _safe_list(store, "list_contracts")
    contract_ids = _ids(contracts)
    issues = _check_fk_references(
        "receivable_contract_fk", receivables, "contract_id",
        contract_ids, "Receivable", "Contract",
    )
    return issues, len(receivables)


@diagnostic_test("maintenance_property_fk")
def test_maintenance_property_fk(store):
    """Every maintenance case must reference an existing property."""
    cases = _safe_list(store, "list_maintenance_cases")
    properties = _safe_list(store, "list_properties")
    property_ids = _ids(properties)
    issues = _check_fk_references(
        "maintenance_property_fk", cases, "property_id",
        property_ids, "MaintenanceCase", "Property",
    )
    return issues, len(cases)


@diagnostic_test("listing_unit_fk")
def test_listing_unit_fk(store):
    """Every listing must reference an existing unit."""
    listings = _safe_list(store, "list_listings")
    units = _safe_list(store, "list_units")
    unit_ids = _ids(units)
    issues = _check_fk_references(
        "listing_unit_fk", listings, "unit_id",
        unit_ids, "Listing", "Unit",
    )
    return issues, len(listings)


@diagnostic_test("insurance_property_fk")
def test_insurance_property_fk(store):
    """Every insurance must reference an existing property."""
    insurances = _safe_list(store, "list_insurances")
    properties = _safe_list(store, "list_properties")
    property_ids = _ids(properties)
    issues = _check_fk_references(
        "insurance_property_fk", insurances, "property_id",
        property_ids, "Insurance", "Property",
    )
    return issues, len(insurances)


@diagnostic_test("rent_adjustment_contract_fk")
def test_rent_adjustment_contract_fk(store):
    """Every rent adjustment must reference an existing contract."""
    adjustments = _safe_list(store, "list_rent_adjustments")
    contracts = _safe_list(store, "list_contracts")
    contract_ids = _ids(contracts)
    issues = _check_fk_references(
        "rent_adjustment_contract_fk", adjustments, "contract_id",
        contract_ids, "RentAdjustment", "Contract",
    )
    return issues, len(adjustments)


@diagnostic_test("entity_counts")
def test_entity_counts(store):
    """Report entity counts as info — useful for empty-state detection."""
    issues = []
    counts = {}
    for name, method in [
        ("Portfolio", "list_portfolios"), ("Property", "list_properties"),
        ("Unit", "list_units"), ("Tenant", "list_tenants"),
        ("Contract", "list_contracts"), ("Account", "list_accounts"),
        ("Booking", "list_bookings"), ("Invoice", "list_invoices"),
        ("MaintenanceCase", "list_maintenance_cases"),
        ("Document", "list_documents"), ("Task", "list_tasks"),
        ("Contact", "list_contacts"), ("Deposit", "list_deposits"),
        ("Insurance", "list_insurances"), ("Notification", "list_notifications"),
    ]:
        items = _safe_list(store, method)
        counts[name] = len(items)
        if len(items) == 0:
            issues.append(DiagnosticIssue(
                test="entity_counts",
                severity="info",
                entity_type=name,
                message=f"No {name} records found (table empty)",
            ))
    return issues, sum(counts.values())


@diagnostic_test("duplicate_contract_numbers")
def test_duplicate_contract_numbers(store):
    """Contract numbers should be unique."""
    contracts = _safe_list(store, "list_contracts")
    seen = {}
    issues = []
    for c in contracts:
        num = getattr(c, "contract_number", None)
        if not num:
            continue
        if num in seen:
            issues.append(DiagnosticIssue(
                test="duplicate_contract_numbers",
                severity="error",
                entity_type="Contract",
                entity_id=getattr(c, "id", "?"),
                message=f"Duplicate contract number: {num}",
                details={"contract_number": num, "first_id": seen[num]},
            ))
        else:
            seen[num] = getattr(c, "id", "?")
    return issues, len(contracts)


@diagnostic_test("units_without_contracts")
def test_units_without_contracts(store):
    """Find units that have no active contracts (potential vacancy detection)."""
    units = _safe_list(store, "list_units")
    contracts = _safe_list(store, "list_contracts")
    units_with_contracts = {getattr(c, "unit_id", None) for c in contracts if getattr(c, "status", "") == "active"}
    issues = []
    for unit in units:
        uid = getattr(unit, "id", None)
        unit_status = getattr(unit, "status", "")
        if uid not in units_with_contracts and unit_status != "vacant":
            issues.append(DiagnosticIssue(
                test="units_without_contracts",
                severity="warning",
                entity_type="Unit",
                entity_id=uid,
                message=f"Unit has no active contract but status is '{unit_status}'",
                details={"status": unit_status, "label": getattr(unit, "label", "")},
            ))
    return issues, len(units)


# ---------------------------------------------------------------------------
# Log writer
# ---------------------------------------------------------------------------

_LOG_DIR = Path(__file__).resolve().parent.parent.parent
_LOG_FILE = _LOG_DIR / "diagnostics.log"


def _write_diagnostics_log(report: DiagnosticsReport) -> None:
    """Write diagnostics report to log file."""
    lines = [
        "# ImmoManager Pro — Diagnostics Report",
        f"# Generated: {report.timestamp}",
        f"# Tests: {report.total_tests} | Passed: {report.passed} | Failed: {report.failed} | Warnings: {report.warnings}",
        f"# Duration: {report.duration_ms:.1f}ms",
        "",
    ]

    for result in report.results:
        status = "PASS" if result.passed else "FAIL"
        lines.append(f"## [{status}] {result.test} (checked {result.checked} entities, {result.duration_ms:.1f}ms)")
        for issue in result.issues:
            prefix = {"error": "ERROR", "warning": "WARN", "info": "INFO"}.get(issue.severity, "???")
            lines.append(f"   [{prefix}] {issue.entity_type}")
            if issue.entity_id:
                lines.append(f"          ID: {issue.entity_id}")
            lines.append(f"          {issue.message}")
            if issue.details:
                lines.append(f"          Details: {issue.details}")
        lines.append("")

    _LOG_FILE.write_text("\n".join(lines), encoding="utf-8")
    logger.info("Diagnostics report written to %s", _LOG_FILE)


# ---------------------------------------------------------------------------
# Endpoint
# ---------------------------------------------------------------------------

@router.get("/run", response_model=DiagnosticsReport, dependencies=[Depends(_check_diagnostics_allowed)])
def run_diagnostics(store=Depends(get_store)):
    """Run all diagnostic tests and return the report."""
    start = time.monotonic()
    results = []
    total_warnings = 0

    for test_name, test_fn in _TESTS:
        t0 = time.monotonic()
        try:
            issues, checked = test_fn(store)
            duration = round((time.monotonic() - t0) * 1000, 1)
            passed = not any(i.severity == "error" for i in issues)
            total_warnings += sum(1 for i in issues if i.severity == "warning")
            results.append(DiagnosticResult(
                test=test_name,
                passed=passed,
                duration_ms=duration,
                issues=issues,
                checked=checked,
            ))
        except Exception as exc:
            duration = round((time.monotonic() - t0) * 1000, 1)
            logger.error("Diagnostic test %s crashed: %s", test_name, exc, exc_info=True)
            results.append(DiagnosticResult(
                test=test_name,
                passed=False,
                duration_ms=duration,
                issues=[DiagnosticIssue(
                    test=test_name,
                    severity="error",
                    entity_type="Diagnostics",
                    message=f"Test crashed: {type(exc).__name__}: {exc}",
                )],
            ))

    total_duration = round((time.monotonic() - start) * 1000, 1)
    passed_count = sum(1 for r in results if r.passed)
    failed_count = sum(1 for r in results if not r.passed)
    total_issues = sum(len(r.issues) for r in results)

    report = DiagnosticsReport(
        timestamp=datetime.now(timezone.utc).isoformat(),
        total_tests=len(results),
        passed=passed_count,
        failed=failed_count,
        warnings=total_warnings,
        total_issues=total_issues,
        duration_ms=total_duration,
        results=results,
    )

    _write_diagnostics_log(report)
    return report
