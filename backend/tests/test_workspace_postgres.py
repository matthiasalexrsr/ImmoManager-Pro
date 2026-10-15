"""CI gate: run private/shared workspace regressions against one owned native database.

Collected by scripts/check_postgres.py in addition to all existing native checks.
The child process binds the app and users to PostgreSQL before importing either.
"""

import os
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url


def test_workspace_and_business_regressions_on_native_postgres(tmp_path):
    admin_url = os.environ.get("IMMO_TEST_POSTGRES_ADMIN_URL")
    if not admin_url:
        pytest.skip("set IMMO_TEST_POSTGRES_ADMIN_URL for the native workspace gate")
    url = make_url(admin_url)
    if url.get_backend_name() != "postgresql" or url.host not in {"127.0.0.1", "localhost", "::1"}:
        pytest.fail("Native workspace tests require an explicitly configured loopback PostgreSQL server")
    name = f"immoqa_workspace_{uuid4().hex}"
    admin = create_engine(url, isolation_level="AUTOCOMMIT")
    root = Path(__file__).resolve().parents[2]
    report = tmp_path / "workspace-postgres.xml"
    environment = {**os.environ, "DATABASE_URL": url.set(database=name).render_as_string(hide_password=False),
                   "TEST_STORE_BACKEND": "sql", "SQLITE_PERSISTENT_STORE": "true", "ALLOW_INMEMORY_FALLBACK": "false",
                   "DATA_DIR": str(tmp_path), "UPLOADS_DIR": str(tmp_path / "uploads"),
                   "BACKUP_DIR": str(tmp_path / "backups"), "SECRET_KEYS": "",
                   "SECRET_KEY_FILE": str(tmp_path / "keyring.json"),
                   "INTEGRATION_STATE_FILE": str(tmp_path / "integrations.json"),
                   "JOB_SCHEDULER_ENABLED": "false", "BACKUP_SCHEDULE_ENABLED": "false", "PYTHONPATH": str(root)}
    nodes = [str(root / "backend" / "tests" / name) for name in (
        "test_workspace.py", "test_business_qol.py", "test_business_qol_review.py")]
    created = False
    try:
        with admin.connect() as connection:
            connection.exec_driver_sql(f'CREATE DATABASE "{name}"')
        created = True
        result = subprocess.run([sys.executable, "-m", "pytest", *nodes, "-q", "--tb=short",
                                 "-k", "not test_memory_history_failure_restores_source_and_no_partial_history",
                                 f"--junitxml={report}"], cwd=tmp_path, env=environment,
                                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600)
        assert result.returncode == 0, result.stdout + result.stderr
        assert report.exists(), "Native workspace child did not write its test report"
        cases = ET.parse(report).findall(".//testcase")
        skipped = [case for case in cases if case.find("skipped") is not None]
        names = {case.attrib["name"] for case in cases}
        required = {"test_simultaneous_retries_create_once_and_competing_updates_conflict",
                    "test_independent_request_writers_serialize_retries_and_reject_lost_updates",
                    "test_expired_same_key_processing_attempt_cannot_publish_into_new_lease",
                    "test_business_migration_adopts_partial_schema_preserving_data_and_indexes"}
        assert len(cases) >= 40 and not skipped and required.issubset(names), (
            f"Native workspace gate refused: {len(cases)} cases, {len(skipped)} skipped; missing {required - names}")
        print(f"Native workspace child gate passed: {len(cases)} cases, none skipped, independent backend PID CAS included.")
    finally:
        if created:
            with admin.connect() as connection:
                connection.exec_driver_sql(f'DROP DATABASE "{name}" WITH (FORCE)')
        admin.dispose()
