"""Run a PostgreSQL-only pytest selection; skips never qualify as release proof.

Usage: python scripts/run_postgres_gate.py backend/tests/test_...py -k postgres
Tests must own disposable UUID schemas through TEST_SERVER_DATABASE_URL. This
runner never connects to a business database or substitutes a fallback URL.
"""

import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from xml.etree import ElementTree

ROOT = Path(__file__).resolve().parents[1]


def verified_case_count(report: Path) -> int:
    """Require actual passing calls, including a PostgreSQL selection identity."""
    try:
        cases = list(ElementTree.parse(report).getroot().iter("testcase"))
    except (OSError, ElementTree.ParseError):
        raise ValueError("PostgreSQL gate produced no valid pytest result report") from None
    if not cases:
        raise ValueError("PostgreSQL gate executed no test cases")
    for case in cases:
        if any(case.find(kind) is not None for kind in ("skipped", "failure", "error")):
            raise ValueError("PostgreSQL release evidence contains skipped or unsuccessful cases")
        identity = case.get("classname", "") + "." + case.get("name", "")
        if "postgres" not in identity.lower() and "test_pg_" not in identity.lower():
            raise ValueError("PostgreSQL gate must select only explicit PostgreSQL cases")
    return len(cases)


def main(arguments: list[str] | None = None) -> int:
    arguments = sys.argv[1:] if arguments is None else arguments
    source = os.environ.get("TEST_SERVER_DATABASE_URL", "")
    if not re.match(r"^postgresql(?:\+[a-z0-9_]+)?://", source):
        print("Set TEST_SERVER_DATABASE_URL to the dedicated disposable PostgreSQL service.", file=sys.stderr)
        return 1
    if not arguments:
        print("Provide an explicit PostgreSQL-only pytest selection.", file=sys.stderr)
        return 1
    with tempfile.TemporaryDirectory(prefix="immo-pg-gate-") as directory:
        report = Path(directory) / "results.xml"
        result = subprocess.run([sys.executable, "-m", "pytest", *arguments, "--junitxml=" + str(report)], cwd=ROOT)
        if result.returncode:
            return result.returncode
        try:
            count = verified_case_count(report)
        except ValueError as error:
            print(str(error), file=sys.stderr)
            return 1
    print(f"Verified {count} executed PostgreSQL cases; no skipped release evidence.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
