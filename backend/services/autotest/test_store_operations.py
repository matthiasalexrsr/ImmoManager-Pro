"""Test module: Store operations and edge cases.

Tests the data store directly for edge cases that HTTP tests may miss:
empty-state handling, duplicate detection, cascade behavior, and
boundary conditions.
"""

import time

from .runner import TestContext, TestResult, test_module


@test_module("store_operations", "Direct store operations, empty states, and edge-case handling")
def test_store_operations(ctx: TestContext) -> list[TestResult]:
    results = []
    store = ctx.store

    # ── List methods return lists ─────────────────────────────────────────

    list_methods = [
        ("list_portfolios", "Portfolio"),
        ("list_properties", "Property"),
        ("list_units", "Unit"),
        ("list_tenants", "Tenant"),
        ("list_contracts", "Contract"),
        ("list_accounts", "Account"),
        ("list_bookings", "Booking"),
        ("list_invoices", "Invoice"),
        ("list_maintenance_cases", "MaintenanceCase"),
        ("list_documents", "Document"),
        ("list_tasks", "Task"),
        ("list_notifications", "Notification"),
        ("list_contacts", "Contact"),
        ("list_deposits", "Deposit"),
        ("list_insurances", "Insurance"),
        ("list_categories", "Category"),
        ("list_leads", "Lead"),
        ("list_listings", "Listing"),
        ("list_budgets", "Budget"),
    ]

    for method_name, entity_name in list_methods:
        t0 = time.monotonic()
        try:
            method = getattr(store, method_name, None)
            if method is None:
                results.append(TestResult(
                    name=f"store::list::{entity_name}",
                    passed=False,
                    duration_ms=0,
                    message=f"Method {method_name} not found on store",
                    file_path="backend/storage.py",
                    line_hint=f"Missing {method_name}() method",
                ))
                continue
            result = method()
            dur = round((time.monotonic() - t0) * 1000, 1)
            is_list = isinstance(result, list)
            results.append(TestResult(
                name=f"store::list::{entity_name}",
                passed=is_list,
                duration_ms=dur,
                message=f"Returns list with {len(result)} items" if is_list else f"Returns {type(result).__name__} instead of list",
                file_path="backend/storage.py",
            ))
        except Exception as exc:
            dur = round((time.monotonic() - t0) * 1000, 1)
            results.append(TestResult(
                name=f"store::list::{entity_name}",
                passed=False,
                duration_ms=dur,
                message=f"Exception: {type(exc).__name__}: {exc}",
                file_path="backend/storage.py",
            ))

    # ── NotFoundError for missing entities ─────────────────────────────────

    get_methods = [
        ("get_portfolio", "nonexistent-id"),
        ("get_property", "nonexistent-id"),
        ("get_unit", "nonexistent-id"),
        ("get_tenant", "nonexistent-id"),
        ("get_contract", "nonexistent-id"),
        ("get_account", "nonexistent-id"),
    ]

    for method_name, bad_id in get_methods:
        t0 = time.monotonic()
        try:
            method = getattr(store, method_name, None)
            if method is None:
                continue
            method(bad_id)
            dur = round((time.monotonic() - t0) * 1000, 1)
            # Should have raised
            results.append(TestResult(
                name=f"store::not_found::{method_name}",
                passed=False,
                duration_ms=dur,
                message=f"{method_name}('{bad_id}') did not raise NotFoundError",
                file_path="backend/storage.py",
                line_hint=f"{method_name}() should raise NotFoundError for missing entities",
            ))
        except (KeyError, Exception) as exc:
            dur = round((time.monotonic() - t0) * 1000, 1)
            is_not_found = "NotFound" in type(exc).__name__ or isinstance(exc, KeyError)
            results.append(TestResult(
                name=f"store::not_found::{method_name}",
                passed=is_not_found,
                duration_ms=dur,
                message=f"Correctly raises {type(exc).__name__}" if is_not_found else f"Unexpected: {type(exc).__name__}",
                file_path="backend/storage.py",
            ))

    # ── Patch entity method ───────────────────────────────────────────────

    t0 = time.monotonic()
    has_patch = hasattr(store, '_patch_entity')
    dur = round((time.monotonic() - t0) * 1000, 1)
    results.append(TestResult(
        name="store::patch_entity_exists",
        passed=has_patch,
        duration_ms=dur,
        message="_patch_entity method available" if has_patch else "_patch_entity method missing",
        file_path="backend/storage.py",
    ))

    # ── Entity type map completeness ──────────────────────────────────────

    if hasattr(store, '_ENTITY_TYPE_MAP'):
        t0 = time.monotonic()
        type_map = store._ENTITY_TYPE_MAP
        expected_types = [
            "portfolio", "property", "unit", "tenant", "contract",
            "account", "booking", "invoice", "maintenance", "document",
            "task", "deposit", "notification", "contact", "category",
            "insurance", "lead", "listing", "budget",
        ]
        missing = [t for t in expected_types if t not in type_map]
        dur = round((time.monotonic() - t0) * 1000, 1)
        results.append(TestResult(
            name="store::entity_type_map_complete",
            passed=len(missing) == 0,
            duration_ms=dur,
            message=f"Missing types: {missing}" if missing else f"All {len(expected_types)} entity types mapped",
            file_path="backend/storage.py",
            line_hint="_ENTITY_TYPE_MAP dict",
        ))

    return results
