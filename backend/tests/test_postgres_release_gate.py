"""A green subprocess alone must not hide missing real PostgreSQL evidence."""

import pytest

from scripts.run_postgres_gate import main, verified_case_count


@pytest.mark.parametrize("body", [
    "<testsuites/>",
    '<testsuite><testcase name="test_pg_skipped"><skipped/></testcase></testsuite>',
    '<testsuite><testcase name="test_pg_failed"><failure/></testcase></testsuite>',
    '<testsuite><testcase name="test_pg_setup_error"><error/></testcase></testsuite>',
    '<testsuite><testcase name="test_memory_only"/></testsuite>',
    "unfinished report",
])
def test_missing_skipped_failed_or_wrong_backend_evidence_cannot_pass(tmp_path, body):
    report = tmp_path / "report.xml"
    report.write_text(body, encoding="utf-8")
    with pytest.raises(ValueError):
        verified_case_count(report)


def test_real_postgres_variants_and_dedicated_files_are_accepted(tmp_path):
    report = tmp_path / "report.xml"
    report.write_text('<testsuites><testsuite><testcase classname="tests.test_jobs_postgres" name="test_claim"/>'
        '<testcase name="test_writer[postgres-sql-auth]"/><testcase name="test_pg_revoke"/>'
        '</testsuite></testsuites>', encoding="utf-8")
    assert verified_case_count(report) == 3


@pytest.mark.parametrize("url", ["", "sqlite:///must-not-create.sqlite", "not a database URL"])
def test_gate_refuses_missing_or_non_postgres_configuration_before_running_tests(monkeypatch, url, capsys):
    monkeypatch.setenv("TEST_SERVER_DATABASE_URL", url)
    assert main(["a-test-path-that-does-not-exist"]) == 1
    assert "dedicated disposable PostgreSQL" in capsys.readouterr().err
