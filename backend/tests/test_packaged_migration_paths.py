"""Actual Alembic loading beyond Win32 MAX_PATH, including source migration files."""

import os
import shutil

import pytest
from alembic.script import ScriptDirectory

from backend.db import schema_state
from backend.services.filesystem_paths import filesystem_path


@pytest.mark.skipif(os.name != "nt", reason="Win32 extended path contract")
def test_alembic_loads_packaged_migrations_from_deep_install_directory(tmp_path, monkeypatch):
    expected = schema_state.head_revision()
    nested = tmp_path
    while len(str(nested)) < 270:
        nested = nested / "synthetic-deep-installation"
    target = filesystem_path(nested / "backend" / "db" / "migrations")
    shutil.copytree(filesystem_path(schema_state.MIGRATIONS_DIR), target, ignore=shutil.ignore_patterns("__pycache__"))
    monkeypatch.setattr(schema_state, "MIGRATIONS_DIR", nested / "backend" / "db" / "migrations")
    config = schema_state.alembic_config()
    assert config.get_main_option("script_location").startswith("\\\\?\\")
    scripts = ScriptDirectory.from_config(config)
    assert scripts.get_current_head() == expected
    assert len(list(scripts.walk_revisions())) > 40
