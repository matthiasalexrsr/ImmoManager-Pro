"""Core autotest runner — orchestrates all test modules and produces reports.

Each test module registers itself via the @test_module decorator.
The runner executes all modules, collects results, and generates a
structured Markdown report designed for Claude Code consumption.
"""

import logging
import time
import traceback
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable

logger = logging.getLogger(__name__)

# ─── Result types ─────────────────────────────────────────────────────────────


@dataclass
class TestResult:
    name: str
    passed: bool
    duration_ms: float
    message: str = ""
    details: str = ""
    severity: str = "error"  # error | warning | info
    file_path: str = ""
    line_hint: str = ""


@dataclass
class ModuleResult:
    module_name: str
    description: str
    passed: int = 0
    failed: int = 0
    warnings: int = 0
    skipped: int = 0
    duration_ms: float = 0.0
    tests: list[TestResult] = field(default_factory=list)
    error: str = ""


@dataclass
class AutotestReport:
    timestamp: str = ""
    duration_ms: float = 0.0
    total_tests: int = 0
    total_passed: int = 0
    total_failed: int = 0
    total_warnings: int = 0
    modules: list[ModuleResult] = field(default_factory=list)
    app_version: str = ""
    environment: str = ""
    store_backend: str = ""


# ─── Module registry ──────────────────────────────────────────────────────────

_MODULES: list[tuple[str, str, Callable]] = []


def test_module(name: str, description: str = ""):
    """Decorator to register a test module function.

    The function receives a TestContext and returns a list of TestResult.
    """
    def decorator(func: Callable):
        _MODULES.append((name, description, func))
        return func
    return decorator


@dataclass
class TestContext:
    """Shared context passed to every test module."""
    app: object  # FastAPI app
    client: object  # httpx.AsyncClient or TestClient
    store: object  # data store
    token: str = ""  # admin auth token
    base_url: str = "/api/v1"


# ─── Runner ───────────────────────────────────────────────────────────────────

class AutotestRunner:
    """Runs all registered test modules and produces a report."""

    def __init__(self):
        # Import all test modules to trigger registration
        from . import (  # noqa: F401
            test_api_routes,
            test_auth_security,
            test_config_validation,
            test_data_integrity,
            test_frontend_contracts,
            test_security_posture,
            test_store_operations,
        )

    def run(self) -> AutotestReport:
        """Execute all test modules and return a structured report."""
        from ...config import settings
        from ...dependencies import store

        report = AutotestReport(
            timestamp=datetime.now(timezone.utc).isoformat(),
            app_version=settings.app_version,
            environment=settings.environment.value,
            store_backend=type(store).__name__,
        )

        # Create a test client
        from fastapi.testclient import TestClient
        from ...app import app

        client = TestClient(app, raise_server_exceptions=False)

        # Register an admin user and get a token
        token = self._get_admin_token(client)

        ctx = TestContext(
            app=app,
            client=client,
            store=store,
            token=token,
        )

        start = time.monotonic()

        for mod_name, mod_desc, mod_fn in _MODULES:
            mod_result = ModuleResult(module_name=mod_name, description=mod_desc)
            mod_start = time.monotonic()

            try:
                test_results = mod_fn(ctx)
                if not isinstance(test_results, list):
                    test_results = list(test_results)

                for tr in test_results:
                    mod_result.tests.append(tr)
                    if tr.passed:
                        if tr.severity == "warning":
                            mod_result.warnings += 1
                        else:
                            mod_result.passed += 1
                    else:
                        if tr.severity == "warning":
                            mod_result.warnings += 1
                        else:
                            mod_result.failed += 1

            except Exception as exc:
                logger.exception("Test module %s crashed", mod_name)
                mod_result.error = f"{type(exc).__name__}: {exc}"
                mod_result.tests.append(TestResult(
                    name=f"{mod_name}::crash",
                    passed=False,
                    duration_ms=0,
                    message=f"Module crashed: {type(exc).__name__}: {exc}",
                    details=traceback.format_exc(),
                    severity="error",
                ))
                mod_result.failed += 1

            mod_result.duration_ms = round((time.monotonic() - mod_start) * 1000, 1)
            report.modules.append(mod_result)

        report.duration_ms = round((time.monotonic() - start) * 1000, 1)
        report.total_tests = sum(m.passed + m.failed + m.warnings for m in report.modules)
        report.total_passed = sum(m.passed for m in report.modules)
        report.total_failed = sum(m.failed for m in report.modules)
        report.total_warnings = sum(m.warnings for m in report.modules)

        return report

    def _get_admin_token(self, client) -> str:
        """Register a test admin user and return a JWT token."""
        import secrets
        username = f"autotest_admin_{secrets.token_hex(4)}"
        password = "AutoTest1234!"

        # Register
        client.post("/api/v1/auth/register", json={
            "username": username,
            "email": f"{username}@test.local",
            "full_name": "Autotest Admin",
            "password": password,
        })

        # Promote to admin
        from ...auth import _user_store
        user = _user_store.get_by_username(username)
        if user:
            _user_store.update(user["id"], {"role": "eigentuemer"})

        # Login
        resp = client.post("/api/v1/auth/login", json={
            "username": username,
            "password": password,
        })
        if resp.status_code == 200:
            return resp.json().get("access_token", "")
        return ""


def run_all_tests() -> AutotestReport:
    """Convenience function to run all tests."""
    runner = AutotestRunner()
    return runner.run()


# ─── Report formatters ────────────────────────────────────────────────────────

def format_report_markdown(report: AutotestReport) -> str:
    """Format an autotest report as Markdown for Claude Code consumption."""
    lines = [
        "# ImmoManager Pro — Autotest Report",
        "",
        f"**Generated:** {report.timestamp}",
        f"**Version:** {report.app_version}",
        f"**Environment:** {report.environment}",
        f"**Store Backend:** {report.store_backend}",
        f"**Duration:** {report.duration_ms:.0f}ms",
        "",
        "## Summary",
        "",
        f"| Metric | Count |",
        f"|--------|-------|",
        f"| Total Tests | {report.total_tests} |",
        f"| Passed | {report.total_passed} |",
        f"| Failed | {report.total_failed} |",
        f"| Warnings | {report.total_warnings} |",
        "",
    ]

    if report.total_failed > 0:
        lines.append("## FAILURES — Action Required")
        lines.append("")
        lines.append("The following tests failed and need attention. Each entry includes")
        lines.append("the file path and suggested fix location for Claude Code to address.")
        lines.append("")

        for mod in report.modules:
            failures = [t for t in mod.tests if not t.passed and t.severity == "error"]
            if failures:
                lines.append(f"### {mod.module_name}")
                lines.append("")
                for t in failures:
                    lines.append(f"#### FAIL: `{t.name}`")
                    lines.append(f"- **Message:** {t.message}")
                    if t.file_path:
                        lines.append(f"- **File:** `{t.file_path}`")
                    if t.line_hint:
                        lines.append(f"- **Location Hint:** {t.line_hint}")
                    if t.details:
                        lines.append(f"- **Details:**")
                        lines.append(f"  ```")
                        for dl in t.details.strip().split("\n"):
                            lines.append(f"  {dl}")
                        lines.append(f"  ```")
                    lines.append("")

    if report.total_warnings > 0:
        lines.append("## Warnings")
        lines.append("")
        for mod in report.modules:
            warnings = [t for t in mod.tests if t.severity == "warning"]
            if warnings:
                lines.append(f"### {mod.module_name}")
                lines.append("")
                for t in warnings:
                    status = "PASS" if t.passed else "WARN"
                    lines.append(f"- **[{status}]** `{t.name}`: {t.message}")
                    if t.file_path:
                        lines.append(f"  - File: `{t.file_path}`")
                    if t.details:
                        lines.append(f"  - {t.details}")
                lines.append("")

    lines.append("## Module Details")
    lines.append("")

    for mod in report.modules:
        status = "PASS" if mod.failed == 0 else "FAIL"
        lines.append(f"### [{status}] {mod.module_name}")
        lines.append(f"*{mod.description}*")
        lines.append("")
        lines.append(f"| Passed | Failed | Warnings | Duration |")
        lines.append(f"|--------|--------|----------|----------|")
        lines.append(f"| {mod.passed} | {mod.failed} | {mod.warnings} | {mod.duration_ms:.0f}ms |")
        lines.append("")

        if mod.error:
            lines.append(f"> **Module Error:** {mod.error}")
            lines.append("")

        for t in mod.tests:
            icon = "PASS" if t.passed else "FAIL"
            if t.severity == "warning":
                icon = "WARN"
            lines.append(f"- [{icon}] `{t.name}` ({t.duration_ms:.0f}ms): {t.message}")

        lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("*This report was generated by the ImmoManager Pro self-testing system.*")
    lines.append("*Claude Code should read this file and fix any FAIL items listed above.*")

    return "\n".join(lines)


def format_report_json(report: AutotestReport) -> dict:
    """Format report as a JSON-serializable dict."""
    return {
        "timestamp": report.timestamp,
        "duration_ms": report.duration_ms,
        "app_version": report.app_version,
        "environment": report.environment,
        "store_backend": report.store_backend,
        "summary": {
            "total": report.total_tests,
            "passed": report.total_passed,
            "failed": report.total_failed,
            "warnings": report.total_warnings,
        },
        "modules": [
            {
                "name": m.module_name,
                "description": m.description,
                "passed": m.passed,
                "failed": m.failed,
                "warnings": m.warnings,
                "duration_ms": m.duration_ms,
                "error": m.error or None,
                "tests": [
                    {
                        "name": t.name,
                        "passed": t.passed,
                        "duration_ms": t.duration_ms,
                        "message": t.message,
                        "severity": t.severity,
                        "file_path": t.file_path or None,
                        "line_hint": t.line_hint or None,
                        "details": t.details or None,
                    }
                    for t in m.tests
                ],
            }
            for m in report.modules
        ],
    }
