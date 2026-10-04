"""Actual early CLI dispatch and reviewable, per-plan scheduler commands."""

import subprocess
import sys
from pathlib import Path
from xml.etree.ElementTree import fromstring

from backend.backup_operations import __main__ as cli
from backend.tests.test_full_backup_plan import configured


def test_actual_launcher_backup_cli_does_not_load_configuration_or_application(tmp_path):
    script = """
import runpy, sys
sys.argv = ['immomanager', '--backup-operations', '--help']
try:
    runpy.run_module('backend', run_name='__main__')
except SystemExit as error:
    assert error.code == 0
else:
    raise AssertionError('help must finish')
assert 'backend.config' not in sys.modules and 'backend.app' not in sys.modules
"""
    result = subprocess.run([sys.executable, "-c", script], cwd=Path(__file__).resolve().parents[2],
                            capture_output=True, timeout=30)
    assert result.returncode == 0, result.stderr.decode(errors="replace")


def test_task_profiles_quote_paths_separate_plan_ids_and_dispatch_packaged_app(tmp_path, monkeypatch):
    directory, plan = configured(tmp_path)
    plan = plan.model_copy(update={"installation": plan.installation.model_copy(update={"app_root": tmp_path / "application with spaces"})})
    monkeypatch.setattr(cli, "_windows_sid", lambda: "S-1-5-21-1-2-3-1001")
    xml = fromstring(cli.task_xml(plan, directory))
    ns = {"t": "http://schemas.microsoft.com/windows/2004/02/mit/task"}
    assert xml.find("t:Actions/t:Exec/t:WorkingDirectory", ns).text == str(plan.installation.app_root)
    args = xml.find("t:Actions/t:Exec/t:Arguments", ns).text
    assert "backend.backup_operations" in args and "--plan-dir" in args
    assert cli.task_name(plan) != cli.task_name(type(plan)(**{**plan.model_dump(), "id": __import__("uuid").uuid4()}))
    packaged = plan.model_copy(update={"installation": plan.installation.model_copy(update={"packaged": True})})
    assert cli.run_arguments(packaged, directory)[:1] == ["--backup-operations"]
    assert b"Synthetic private full-backup passphrase" not in cli.task_xml(plan, directory)
