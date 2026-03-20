"""Test module: Security posture and hardening validation.

Verifies security headers, CORS configuration, error leakage prevention,
file upload restrictions, path traversal protection, and production
safety flags.
"""

import time

from .runner import TestContext, TestResult, test_module


@test_module("security_posture", "Security headers, CORS, error leakage, file safety, and production flags")
def test_security_posture(ctx: TestContext) -> list[TestResult]:
    results = []
    headers = {"Authorization": f"Bearer {ctx.token}"} if ctx.token else {}

    # ── Security headers ──────────────────────────────────────────────────

    t0 = time.monotonic()
    resp = ctx.client.get(f"{ctx.base_url}/portfolios", headers=headers)
    dur = round((time.monotonic() - t0) * 1000, 1)

    # X-Content-Type-Options
    xcto = resp.headers.get("x-content-type-options", "")
    results.append(TestResult(
        name="headers::x_content_type_options",
        passed=xcto == "nosniff",
        duration_ms=dur,
        message=f"X-Content-Type-Options: '{xcto}' (expected 'nosniff')",
        file_path="backend/middleware.py",
        line_hint="RequestLoggingMiddleware should set X-Content-Type-Options",
    ))

    # X-Request-ID present
    xrid = resp.headers.get("x-request-id", "")
    results.append(TestResult(
        name="headers::x_request_id",
        passed=bool(xrid),
        duration_ms=dur,
        message=f"X-Request-ID: {'present' if xrid else 'MISSING'}",
        file_path="backend/middleware.py",
    ))

    # ── Error information leakage ─────────────────────────────────────────

    # 404 should not leak internal paths
    t0 = time.monotonic()
    resp = ctx.client.get(f"{ctx.base_url}/portfolios/nonexistent", headers=headers)
    dur = round((time.monotonic() - t0) * 1000, 1)
    body_text = resp.text.lower()
    no_leak = (
        "/home/" not in body_text and
        "traceback" not in body_text and
        "file \"" not in body_text and
        ".py\"" not in body_text
    )
    results.append(TestResult(
        name="error_leakage::404_no_paths",
        passed=no_leak,
        duration_ms=dur,
        message="404 response does not leak internal paths" if no_leak else "404 response leaks internal paths!",
        file_path="backend/exceptions.py",
        line_hint="Error handlers should sanitize response bodies",
    ))

    # Invalid JSON body should return 422, not 500
    t0 = time.monotonic()
    resp = ctx.client.post(
        f"{ctx.base_url}/portfolios",
        content="{invalid json",
        headers={**headers, "Content-Type": "application/json"},
    )
    dur = round((time.monotonic() - t0) * 1000, 1)
    results.append(TestResult(
        name="error_leakage::invalid_json_handled",
        passed=resp.status_code in (400, 422),
        duration_ms=dur,
        message=f"Invalid JSON returned {resp.status_code} (expected 400/422)",
        file_path="backend/exceptions.py",
    ))

    # ── File upload security ──────────────────────────────────────────────

    # Blocked extension
    from io import BytesIO
    t0 = time.monotonic()
    resp = ctx.client.post(
        f"{ctx.base_url}/files/upload",
        files={"file": ("malicious.exe", BytesIO(b"MZ\x90"), "application/octet-stream")},
        headers=headers,
    )
    dur = round((time.monotonic() - t0) * 1000, 1)
    results.append(TestResult(
        name="file_security::exe_blocked",
        passed=resp.status_code == 400,
        duration_ms=dur,
        message=f"EXE upload returned {resp.status_code} (expected 400)",
        file_path="backend/routers/files.py",
        line_hint="_BLOCKED_EXTENSIONS check",
    ))

    # Script extension blocked
    t0 = time.monotonic()
    resp = ctx.client.post(
        f"{ctx.base_url}/files/upload",
        files={"file": ("script.sh", BytesIO(b"#!/bin/bash"), "text/plain")},
        headers=headers,
    )
    dur = round((time.monotonic() - t0) * 1000, 1)
    results.append(TestResult(
        name="file_security::sh_blocked",
        passed=resp.status_code == 400,
        duration_ms=dur,
        message=f"Shell script upload returned {resp.status_code} (expected 400)",
        file_path="backend/routers/files.py",
    ))

    # Path traversal in download
    t0 = time.monotonic()
    resp = ctx.client.get(f"{ctx.base_url}/files/download?key=../../etc/passwd", headers=headers)
    dur = round((time.monotonic() - t0) * 1000, 1)
    results.append(TestResult(
        name="file_security::path_traversal_blocked",
        passed=resp.status_code in (400, 404),
        duration_ms=dur,
        message=f"Path traversal returned {resp.status_code} (expected 400)",
        file_path="backend/routers/files.py",
        line_hint="_normalize_storage_key() path traversal check",
    ))

    # ── Configuration security ────────────────────────────────────────────

    from ...config import settings

    # JWT secret not default
    t0 = time.monotonic()
    jwt_safe = settings.jwt_secret_key != "dev-secret-key-change-in-production"
    dur = round((time.monotonic() - t0) * 1000, 1)
    results.append(TestResult(
        name="config::jwt_secret_not_default",
        passed=jwt_safe,
        duration_ms=dur,
        message="JWT secret is custom" if jwt_safe else "JWT secret is using the DEFAULT value — change in production!",
        severity="warning" if not jwt_safe else "info",
        file_path="backend/config.py",
        line_hint="jwt_secret_key setting",
    ))

    # CORS not wildcard
    cors_safe = "*" not in settings.cors_origins
    results.append(TestResult(
        name="config::cors_no_wildcard",
        passed=cors_safe,
        duration_ms=0,
        message="CORS origins are restrictive" if cors_safe else "CORS allows wildcard '*' — restrict in production!",
        severity="warning" if not cors_safe else "info",
        file_path="backend/config.py",
    ))

    # Production safety flags
    if settings.is_production:
        results.append(TestResult(
            name="config::production_update_disabled",
            passed=not settings.update_allow_in_production,
            duration_ms=0,
            message="Updates disabled in production" if not settings.update_allow_in_production else "Updates enabled in production — risky!",
            severity="warning" if settings.update_allow_in_production else "info",
            file_path="backend/config.py",
        ))
        results.append(TestResult(
            name="config::production_diagnostics_disabled",
            passed=not settings.diagnostics_allow_in_production,
            duration_ms=0,
            message="Diagnostics disabled in production" if not settings.diagnostics_allow_in_production else "Diagnostics enabled in production — information leak risk!",
            severity="warning" if settings.diagnostics_allow_in_production else "info",
            file_path="backend/config.py",
        ))

    return results
