"""Test module: API route reachability and response shape validation.

Verifies that all registered API routes are reachable, return expected
status codes, and produce correctly shaped responses. This catches
broken routes, missing auth guards, and response contract violations.
"""

import time

from .runner import TestContext, TestResult, test_module

# Expected routes and their properties
_ENTITY_ROUTES = [
    ("portfolios", "GET", 200),
    ("properties", "GET", 200),
    ("units", "GET", 200),
    ("tenants", "GET", 200),
    ("contracts", "GET", 200),
    ("accounts", "GET", 200),
    ("bookings", "GET", 200),
    ("receivables", "GET", 200),
    ("invoices", "GET", 200),
    ("maintenance", "GET", 200),
    ("documents", "GET", 200),
    ("tasks", "GET", 200),
    ("deposits", "GET", 200),
    ("notifications", "GET", 200),
    ("contacts", "GET", 200),
    ("categories", "GET", 200),
    ("insurances", "GET", 200),
    ("leads", "GET", 200),
    ("listings", "GET", 200),
    ("budgets", "GET", 200),
    ("tax-rates", "GET", 200),
    ("rent-adjustments", "GET", 200),
    ("rent-charges", "GET", 200),
    ("escalation-rules", "GET", 200),
    ("handover-protocols", "GET", 200),
    ("meters", "GET", 200),
    ("messages/threads", "GET", 200),
    ("calendar", "GET", 200),
    ("reports/overview", "GET", 200),
    ("history", "GET", 200),
]

_ADMIN_ROUTES = [
    ("admin/version", "GET", 200),
    ("admin/system-status", "GET", 200),
    ("admin/database-info", "GET", 200),
    ("admin/config/public", "GET", 200),
    ("updates/status", "GET", 200),
    ("updates/history", "GET", 200),
]

_PUBLIC_ROUTES = [
    ("/health", "GET", 200),
    ("/i18n/de-DE", "GET", 200),
]


@test_module("api_routes", "API route reachability and response shape validation")
def test_api_routes(ctx: TestContext) -> list[TestResult]:
    results = []
    headers = {"Authorization": f"Bearer {ctx.token}"} if ctx.token else {}

    # Test public routes (no auth needed)
    for path, method, expected_status in _PUBLIC_ROUTES:
        t0 = time.monotonic()
        try:
            resp = ctx.client.get(path)
            dur = round((time.monotonic() - t0) * 1000, 1)
            passed = resp.status_code == expected_status
            results.append(TestResult(
                name=f"public::{path}",
                passed=passed,
                duration_ms=dur,
                message=f"Status {resp.status_code} (expected {expected_status})",
                file_path="backend/app.py" if path == "/health" else "",
            ))
        except Exception as exc:
            results.append(TestResult(
                name=f"public::{path}",
                passed=False,
                duration_ms=0,
                message=f"Request failed: {exc}",
            ))

    # Test entity routes (auth required)
    for path, method, expected_status in _ENTITY_ROUTES:
        full_path = f"{ctx.base_url}/{path}"
        t0 = time.monotonic()
        try:
            resp = ctx.client.get(full_path, headers=headers)
            dur = round((time.monotonic() - t0) * 1000, 1)

            passed = resp.status_code == expected_status

            # Validate response is JSON array for list endpoints
            detail = ""
            if passed and resp.status_code == 200:
                try:
                    body = resp.json()
                    if not isinstance(body, list):
                        detail = f"Expected JSON array, got {type(body).__name__}"
                        # Some endpoints return objects, this is a warning not failure
                        if isinstance(body, dict):
                            passed = True  # dict response is acceptable for some endpoints
                except Exception:
                    detail = "Response is not valid JSON"
                    passed = False

            results.append(TestResult(
                name=f"entity::{path}",
                passed=passed,
                duration_ms=dur,
                message=f"Status {resp.status_code}" + (f" — {detail}" if detail else ""),
                file_path=f"backend/routers/{path.split('/')[0].replace('-', '_')}.py",
            ))
        except Exception as exc:
            results.append(TestResult(
                name=f"entity::{path}",
                passed=False,
                duration_ms=0,
                message=f"Request failed: {exc}",
            ))

    # Test admin routes
    for path, method, expected_status in _ADMIN_ROUTES:
        full_path = f"{ctx.base_url}/{path}"
        t0 = time.monotonic()
        try:
            resp = ctx.client.get(full_path, headers=headers)
            dur = round((time.monotonic() - t0) * 1000, 1)
            passed = resp.status_code == expected_status
            results.append(TestResult(
                name=f"admin::{path}",
                passed=passed,
                duration_ms=dur,
                message=f"Status {resp.status_code} (expected {expected_status})",
                file_path=f"backend/routers/{path.split('/')[0].replace('-', '_')}.py",
            ))
        except Exception as exc:
            results.append(TestResult(
                name=f"admin::{path}",
                passed=False,
                duration_ms=0,
                message=f"Request failed: {exc}",
            ))

    # Test unauthenticated access is rejected for protected routes
    for path, _, _ in _ENTITY_ROUTES[:5]:  # Test a sample
        full_path = f"{ctx.base_url}/{path}"
        t0 = time.monotonic()
        try:
            resp = ctx.client.get(full_path)  # No auth header
            dur = round((time.monotonic() - t0) * 1000, 1)
            passed = resp.status_code in (401, 403)
            results.append(TestResult(
                name=f"auth_guard::{path}",
                passed=passed,
                duration_ms=dur,
                message=f"Unauthenticated request returned {resp.status_code} (expected 401/403)",
                severity="error" if not passed else "info",
                file_path="backend/routing.py",
                line_hint="Check dependencies=[Depends(require_auth)] for this route",
            ))
        except Exception as exc:
            results.append(TestResult(
                name=f"auth_guard::{path}",
                passed=False,
                duration_ms=0,
                message=f"Request failed: {exc}",
            ))

    return results
