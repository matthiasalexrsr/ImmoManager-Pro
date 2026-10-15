"""Mandatory native gate for the real message workflow, including two backend PIDs."""

import os
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url


def test_complete_message_workflow_on_native_postgres(tmp_path):
    configured = os.environ.get("IMMO_TEST_POSTGRES_ADMIN_URL")
    if not configured:
        pytest.skip("set IMMO_TEST_POSTGRES_ADMIN_URL for the native message gate")
    url = make_url(configured)
    if url.get_backend_name() != "postgresql" or url.host not in {"127.0.0.1", "localhost", "::1"}:
        pytest.fail("Native message tests require an explicitly configured loopback test server")
    name = "immoqa_messages_" + uuid4().hex
    admin = create_engine(url, isolation_level="AUTOCOMMIT")
    root = Path(__file__).resolve().parents[2]
    report = tmp_path / "messages-native.xml"
    environment = {**os.environ, "DATABASE_URL": url.set(database=name).render_as_string(hide_password=False),
                   "TEST_STORE_BACKEND": "sql", "SQLITE_PERSISTENT_STORE": "true", "ALLOW_INMEMORY_FALLBACK": "false",
                   "IMMO_EXPECT_POSTGRES": "true", "DATA_DIR": str(tmp_path), "UPLOADS_DIR": str(tmp_path / "uploads"),
                   "BACKUP_DIR": str(tmp_path / "backups"), "SECRET_KEYS": "", "SECRET_KEY_FILE": str(tmp_path / "keyring.json"),
                   "INTEGRATION_STATE_FILE": str(tmp_path / "integrations.json"), "JOB_SCHEDULER_ENABLED": "false",
                   "BACKUP_SCHEDULE_ENABLED": "false", "PYTHONPATH": str(root), "PYTHONUTF8": "1"}
    created = False
    try:
        with admin.connect() as connection:
            connection.exec_driver_sql(f'CREATE DATABASE "{name}"')
        created = True
        tests = [str(root / "backend" / "tests" / item) for item in ("test_message_workflow.py", "test_message_thread_boundary.py")]
        result = subprocess.run([sys.executable, "-m", "pytest", *tests, "-q", "--tb=short", f"--junitxml={report}"],
                                cwd=tmp_path, env=environment, capture_output=True, text=True, encoding="utf-8", timeout=300)
        assert result.returncode == 0, result.stdout + result.stderr
        assert report.exists()
        cases = ET.parse(report).findall(".//testcase")
        names = {case.attrib["name"] for case in cases}
        required = {"test_more_than_ten_thousand_same_time_messages_use_complete_bounded_keysets",
                    "test_parallel_retries_and_independent_connections_create_exactly_once",
                    "test_hidden_thread_stays_404_before_cursor_validation",
                    "test_receipt_failure_rolls_back_message_thread_and_command"}
        assert len(cases) >= 15 and not any(case.find("skipped") is not None for case in cases)
        assert required.issubset(names)
    finally:
        if created:
            with admin.connect() as connection:
                connection.exec_driver_sql(f'DROP DATABASE "{name}" WITH (FORCE)')
        admin.dispose()
