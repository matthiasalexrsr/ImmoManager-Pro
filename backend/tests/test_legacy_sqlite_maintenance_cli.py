"""Explicit maintenance dispatch must precede application configuration."""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_legacy_cli_help_never_reaches_settings_or_app_imports():
    code = """
import importlib.abc,sys
class Refuse(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname in {'backend.config','backend.settings','backend.dependencies','backend.app','backend.updater'}:
            raise AssertionError('Application configuration was imported before explicit maintenance selection')
sys.meta_path.insert(0,Refuse())
from backend.maintenance import main
assert main(['legacy-sqlite','--help']) == 0
"""
    result = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
    assert "inspect" in result.stdout and "rollback" in result.stdout


def test_upgrade_requires_explicit_offline_before_password_or_data_selection():
    result = subprocess.run([sys.executable, "-m", "backend.maintenance", "legacy-sqlite", "upgrade",
                             "--data-dir", "synthetic-nonexistent", "--output", "synthetic.immobak"],
                            cwd=ROOT, capture_output=True, text=True, timeout=20)
    assert result.returncode == 2
    assert "--offline" in result.stderr
    assert "Passphrase" not in result.stdout
