"""Test module: Frontend API contract validation.

Verifies that API responses match the data shapes the frontend expects.
Catches missing fields, wrong types, and broken contracts that would
cause JS runtime errors or blank UI panels.
"""

import time

from .runner import TestContext, TestResult, test_module

# Expected response shapes: (path, key_fields, is_list)
_CONTRACT_CHECKS = [
    ("portfolios", ["id", "name"], True),
    ("properties", ["id", "name", "address", "city"], True),
    ("units", ["id", "label", "property_id"], True),
    ("tenants", ["id", "first_name", "last_name", "email"], True),
    ("contracts", ["id", "tenant_id", "unit_id"], True),
    ("accounts", ["id", "name", "account_type"], True),
    ("bookings", ["id", "amount"], True),
    ("invoices", ["id"], True),
    ("tasks", ["id", "title", "status"], True),
    ("contacts", ["id", "name"], True),
    ("categories", ["id", "name"], True),
    ("documents", ["id"], True),
    ("notifications", ["id"], True),
    ("deposits", ["id"], True),
    ("insurances", ["id"], True),
    ("leads", ["id"], True),
    ("listings", ["id"], True),
    ("budgets", ["id"], True),
]

_SINGLETON_CONTRACTS = [
    ("admin/version", ["version"]),
    ("admin/system-status", ["status"]),
    ("reports/overview", []),
]


@test_module("frontend_contracts", "Frontend API contract validation — response shapes and required fields")
def test_frontend_contracts(ctx: TestContext) -> list[TestResult]:
    results = []
    headers = {"Authorization": f"Bearer {ctx.token}"} if ctx.token else {}

    # ── List endpoint contracts ────────────────────────────────────────────

    for path, expected_keys, is_list in _CONTRACT_CHECKS:
        full_path = f"{ctx.base_url}/{path}"
        t0 = time.monotonic()
        try:
            resp = ctx.client.get(full_path, headers=headers)
            dur = round((time.monotonic() - t0) * 1000, 1)

            if resp.status_code != 200:
                results.append(TestResult(
                    name=f"contract::{path}::reachable",
                    passed=False,
                    duration_ms=dur,
                    message=f"Status {resp.status_code} (expected 200)",
                    file_path=f"backend/routers/{path.replace('-', '_')}.py",
                ))
                continue

            body = resp.json()

            # Verify it returns a list
            if is_list and not isinstance(body, list):
                results.append(TestResult(
                    name=f"contract::{path}::is_list",
                    passed=False,
                    duration_ms=dur,
                    message=f"Expected JSON array, got {type(body).__name__}",
                    file_path=f"backend/routers/{path.replace('-', '_')}.py",
                    line_hint="List endpoint should return a JSON array",
                ))
                continue

            # If list has items, check field presence
            if isinstance(body, list) and len(body) > 0:
                sample = body[0]
                missing = [k for k in expected_keys if k not in sample]
                results.append(TestResult(
                    name=f"contract::{path}::fields",
                    passed=len(missing) == 0,
                    duration_ms=dur,
                    message=f"Missing fields: {missing}" if missing else f"All {len(expected_keys)} required fields present",
                    file_path=f"backend/routers/{path.replace('-', '_')}.py",
                    line_hint=f"Response must include: {', '.join(expected_keys)}",
                ))
            else:
                # Empty list — can't validate fields, but shape is correct
                results.append(TestResult(
                    name=f"contract::{path}::shape",
                    passed=True,
                    duration_ms=dur,
                    message="Returns empty list (shape OK, fields untested)",
                    severity="info",
                    file_path=f"backend/routers/{path.replace('-', '_')}.py",
                ))

        except Exception as exc:
            dur = round((time.monotonic() - t0) * 1000, 1)
            results.append(TestResult(
                name=f"contract::{path}",
                passed=False,
                duration_ms=dur,
                message=f"Exception: {type(exc).__name__}: {exc}",
            ))

    # ── Singleton endpoint contracts ───────────────────────────────────────

    for path, expected_keys in _SINGLETON_CONTRACTS:
        full_path = f"{ctx.base_url}/{path}"
        t0 = time.monotonic()
        try:
            resp = ctx.client.get(full_path, headers=headers)
            dur = round((time.monotonic() - t0) * 1000, 1)

            if resp.status_code != 200:
                results.append(TestResult(
                    name=f"contract::{path}::reachable",
                    passed=False,
                    duration_ms=dur,
                    message=f"Status {resp.status_code}",
                    file_path=f"backend/routers/{path.split('/')[0].replace('-', '_')}.py",
                ))
                continue

            body = resp.json()
            if not isinstance(body, dict):
                results.append(TestResult(
                    name=f"contract::{path}::is_object",
                    passed=False,
                    duration_ms=dur,
                    message=f"Expected JSON object, got {type(body).__name__}",
                    file_path=f"backend/routers/{path.split('/')[0].replace('-', '_')}.py",
                ))
                continue

            missing = [k for k in expected_keys if k not in body]
            results.append(TestResult(
                name=f"contract::{path}::fields",
                passed=len(missing) == 0,
                duration_ms=dur,
                message=f"Missing: {missing}" if missing else "All required fields present",
                file_path=f"backend/routers/{path.split('/')[0].replace('-', '_')}.py",
            ))

        except Exception as exc:
            dur = round((time.monotonic() - t0) * 1000, 1)
            results.append(TestResult(
                name=f"contract::{path}",
                passed=False,
                duration_ms=dur,
                message=f"Exception: {type(exc).__name__}: {exc}",
            ))

    # ── i18n contract ──────────────────────────────────────────────────────

    for locale in ["de-DE", "en-US"]:
        t0 = time.monotonic()
        try:
            resp = ctx.client.get(f"/i18n/{locale}")
            dur = round((time.monotonic() - t0) * 1000, 1)
            if resp.status_code == 200:
                data = resp.json()
                # Frontend expects nested dict with specific top-level keys
                expected_sections = ["pages", "common", "nav"]
                missing = [s for s in expected_sections if s not in data]
                results.append(TestResult(
                    name=f"contract::i18n::{locale}::sections",
                    passed=len(missing) == 0,
                    duration_ms=dur,
                    message=f"Missing i18n sections: {missing}" if missing else "All expected i18n sections present",
                    file_path=f"i18n/{locale}.json",
                    line_hint="Frontend useTranslation() expects 'pages', 'common', 'nav' keys",
                ))
            else:
                results.append(TestResult(
                    name=f"contract::i18n::{locale}",
                    passed=False,
                    duration_ms=dur,
                    message=f"Status {resp.status_code}",
                    file_path="backend/routers/i18n.py",
                ))
        except Exception as exc:
            dur = round((time.monotonic() - t0) * 1000, 1)
            results.append(TestResult(
                name=f"contract::i18n::{locale}",
                passed=False,
                duration_ms=dur,
                message=f"Exception: {type(exc).__name__}: {exc}",
            ))

    # ── Health endpoint contract ───────────────────────────────────────────

    t0 = time.monotonic()
    try:
        resp = ctx.client.get("/health")
        dur = round((time.monotonic() - t0) * 1000, 1)
        if resp.status_code == 200:
            body = resp.json()
            health_keys = ["status", "version", "environment"]
            missing = [k for k in health_keys if k not in body]
            results.append(TestResult(
                name="contract::health::fields",
                passed=len(missing) == 0,
                duration_ms=dur,
                message=f"Missing: {missing}" if missing else "Health endpoint has expected fields",
                file_path="backend/app.py",
                line_hint="health() return dict",
            ))
    except Exception as exc:
        results.append(TestResult(
            name="contract::health",
            passed=False,
            duration_ms=0,
            message=f"Exception: {type(exc).__name__}: {exc}",
        ))

    # ── Search response contract ───────────────────────────────────────────

    t0 = time.monotonic()
    try:
        resp = ctx.client.get(f"{ctx.base_url}/search?q=test", headers=headers)
        dur = round((time.monotonic() - t0) * 1000, 1)
        if resp.status_code == 200:
            body = resp.json()
            has_results = "results" in body
            results_is_list = isinstance(body.get("results"), list) if has_results else False
            results.append(TestResult(
                name="contract::search::shape",
                passed=has_results and results_is_list,
                duration_ms=dur,
                message="Search returns {results: [...]}" if has_results and results_is_list else f"Unexpected shape: 'results' key={'present' if has_results else 'MISSING'}, is_list={results_is_list}",
                file_path="backend/routers/search.py",
                line_hint="Frontend expects { results: [...] } shape",
            ))
    except Exception as exc:
        results.append(TestResult(
            name="contract::search",
            passed=False,
            duration_ms=0,
            message=f"Exception: {type(exc).__name__}: {exc}",
        ))

    return results
