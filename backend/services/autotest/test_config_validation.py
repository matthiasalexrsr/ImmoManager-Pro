"""Test module: Configuration and environment validation.

Verifies that all required configuration values are set, environment-specific
settings are correct, database connectivity works, and the application
startup state is healthy.
"""

import time

from .runner import TestContext, TestResult, test_module


@test_module("config_validation", "Configuration, environment, database, and startup health checks")
def test_config_validation(ctx: TestContext) -> list[TestResult]:
    results = []
    headers = {"Authorization": f"Bearer {ctx.token}"} if ctx.token else {}

    # ── Health endpoint ───────────────────────────────────────────────────

    t0 = time.monotonic()
    resp = ctx.client.get("/health")
    dur = round((time.monotonic() - t0) * 1000, 1)
    health_ok = resp.status_code == 200
    health_data = resp.json() if health_ok else {}
    results.append(TestResult(
        name="health::endpoint_ok",
        passed=health_ok,
        duration_ms=dur,
        message=f"Health status: {health_data.get('status', 'unknown')}",
        file_path="backend/app.py",
    ))

    # Check health fields
    if health_ok:
        required_fields = ["status", "version", "environment", "store_backend", "database_connected"]
        missing = [f for f in required_fields if f not in health_data]
        results.append(TestResult(
            name="health::fields_complete",
            passed=len(missing) == 0,
            duration_ms=0,
            message=f"Missing fields: {missing}" if missing else "All required fields present",
            file_path="backend/app.py",
            line_hint="health() endpoint return dict",
        ))

        results.append(TestResult(
            name="health::database_connected",
            passed=health_data.get("database_connected", False),
            duration_ms=0,
            message=f"DB connected: {health_data.get('database_connected')}",
            severity="warning" if not health_data.get("database_connected") else "info",
            file_path="backend/dependencies.py",
        ))

    # ── Version info ──────────────────────────────────────────────────────

    t0 = time.monotonic()
    resp = ctx.client.get(f"{ctx.base_url}/admin/version", headers=headers)
    dur = round((time.monotonic() - t0) * 1000, 1)
    if resp.status_code == 200:
        ver_data = resp.json()
        version = ver_data.get("version", "")
        results.append(TestResult(
            name="config::version_set",
            passed=version != "0.0.0" and bool(version),
            duration_ms=dur,
            message=f"Version: {version}",
            severity="warning" if version == "0.0.0" else "info",
            file_path="backend/config.py",
            line_hint="_get_version() fallback — check pyproject.toml has version",
        ))

    # ── Store backend ─────────────────────────────────────────────────────

    from ...dependencies import _use_sql_store, store

    store_name = type(store).__name__
    results.append(TestResult(
        name="config::store_backend",
        passed=True,
        duration_ms=0,
        message=f"Store: {store_name}, SQL enabled: {_use_sql_store}",
        severity="warning" if store_name == "InMemoryStore" else "info",
        file_path="backend/dependencies.py",
        line_hint="InMemoryStore means data won't persist across restarts",
    ))

    # ── i18n endpoint ─────────────────────────────────────────────────────

    for locale in ["de-DE", "en-US"]:
        t0 = time.monotonic()
        resp = ctx.client.get(f"/i18n/{locale}")
        dur = round((time.monotonic() - t0) * 1000, 1)
        i18n_ok = resp.status_code == 200
        key_count = 0
        if i18n_ok:
            data = resp.json()
            # Count flattened keys
            def _count_keys(d, prefix=""):
                count = 0
                if isinstance(d, dict):
                    for k, v in d.items():
                        count += _count_keys(v, f"{prefix}.{k}")
                else:
                    count = 1
                return count
            key_count = _count_keys(data)
        results.append(TestResult(
            name=f"i18n::{locale}",
            passed=i18n_ok and key_count > 10,
            duration_ms=dur,
            message=f"Status {resp.status_code}, ~{key_count} translation keys",
            severity="warning" if key_count < 50 else "info",
            file_path=f"i18n/{locale}.json" if i18n_ok else "backend/routers/i18n.py",
        ))

    # ── Search endpoint ───────────────────────────────────────────────────

    t0 = time.monotonic()
    resp = ctx.client.get(f"{ctx.base_url}/search?q=test", headers=headers)
    dur = round((time.monotonic() - t0) * 1000, 1)
    search_ok = resp.status_code == 200
    if search_ok:
        body = resp.json()
        search_ok = "results" in body
    results.append(TestResult(
        name="search::endpoint_ok",
        passed=search_ok,
        duration_ms=dur,
        message=f"Search endpoint status {resp.status_code}, has 'results' key: {search_ok}",
        file_path="backend/routers/search.py",
    ))

    # ── Diagnostics endpoint ──────────────────────────────────────────────

    t0 = time.monotonic()
    resp = ctx.client.get(f"{ctx.base_url}/diagnostics/run", headers=headers)
    dur = round((time.monotonic() - t0) * 1000, 1)
    # In production mode, should be 403; in dev mode, should be 200
    from ...config import settings
    if settings.is_production and not settings.diagnostics_allow_in_production:
        diag_ok = resp.status_code == 403
        msg = f"Diagnostics correctly blocked in production ({resp.status_code})"
    else:
        diag_ok = resp.status_code == 200
        msg = f"Diagnostics returned {resp.status_code}"
    results.append(TestResult(
        name="diagnostics::endpoint",
        passed=diag_ok,
        duration_ms=dur,
        message=msg,
        file_path="backend/routers/diagnostics.py",
    ))

    # ── CORS configuration check ──────────────────────────────────────────

    from ...config import settings as cfg
    cors_ok = len(cfg.cors_origins) > 0 and "*" not in cfg.cors_origins
    results.append(TestResult(
        name="config::cors_configured",
        passed=cors_ok,
        duration_ms=0,
        message=f"CORS origins: {cfg.cors_origins[:3]}..." if len(cfg.cors_origins) > 3 else f"CORS origins: {cfg.cors_origins}",
        severity="warning" if not cors_ok else "info",
        file_path="backend/config.py",
    ))

    return results
