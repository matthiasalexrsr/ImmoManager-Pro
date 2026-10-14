"""Run every PostgreSQL regression and reject a green result with skipped checks.

Requires IMMO_TEST_POSTGRES_ADMIN_URL for a disposable loopback PostgreSQL server
and pg_dump/pg_restore on PATH (or PG_BIN_DIR). Fixtures own and remove their databases.
"""

from __future__ import annotations

import os
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


def main() -> int:
    if not os.environ.get("IMMO_TEST_POSTGRES_ADMIN_URL"):
        print("IMMO_TEST_POSTGRES_ADMIN_URL is required; PostgreSQL checks must not silently skip.", file=sys.stderr)
        return 2
    root = Path(__file__).resolve().parents[1]
    tests = sorted((root / "backend" / "tests").glob("test_*postgres*.py"))
    if not tests:
        print("No PostgreSQL regression files found.", file=sys.stderr)
        return 2
    nodes = [str(test.relative_to(root)) for test in tests]
    # This concurrency check shares a file with the memory/SQLite job checks.
    nodes.append("backend/tests/test_durable_jobs.py::test_postgres_workers_skip_locked_runs")
    report = root / "artifacts" / "postgres-checks.xml"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.unlink(missing_ok=True)
    result = subprocess.run(
        [sys.executable, "-m", "pytest", *nodes,
         "-q", "-ra", "--tb=short", f"--junitxml={report}"],
        cwd=root,
    )
    if result.returncode:
        return result.returncode
    if not report.exists():
        print("PostgreSQL test report missing.", file=sys.stderr)
        return 2
    cases = ET.parse(report).findall(".//testcase")
    skipped = [case for case in cases if case.find("skipped") is not None]
    if not cases or skipped:
        print(f"PostgreSQL gate refused: {len(cases)} cases, {len(skipped)} skipped.", file=sys.stderr)
        return 1
    print(f"PostgreSQL gate passed: {len(cases)} checks, none skipped.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
