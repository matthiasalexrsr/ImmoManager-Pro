"""A fresh Alembic database must support every currently declared ORM field.

Uses an owned temporary database, never create_all. Real PostgreSQL migration
coverage additionally runs the same comparison in isolated CLI schema tests.
"""
import os
import subprocess
import sys
from pathlib import Path

from sqlalchemy import create_engine, inspect

from backend.compat.ui_contracts import ensure_ui_contracts
from backend.db.auth_models import AuthSetupORM  # noqa: F401
from backend.db.orm_models import Base


def assert_model_columns_exist(connection):
    ensure_ui_contracts()
    inspector = inspect(connection)
    tables = set(inspector.get_table_names())
    missing = []
    for name, table in Base.metadata.tables.items():
        if name not in tables:
            missing.append(name + ": table missing")
            continue
        available = {column["name"] for column in inspector.get_columns(name)}
        missing.extend(name + "." + column.name for column in table.columns if column.name not in available)
    assert not missing, "Migrated schema lacks application fields: " + ", ".join(missing)


def test_fresh_alembic_database_supports_all_application_fields(tmp_path):
    root = Path(__file__).resolve().parents[2]
    url = f"sqlite:///{(tmp_path / 'fresh-migrations.db').as_posix()}"
    result = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=root,
                            env={**os.environ, "DATABASE_URL": url, "PYTHONUTF8": "1"},
                            capture_output=True, encoding="utf-8", timeout=60)
    assert result.returncode == 0, result.stderr
    engine = create_engine(url)
    try:
        with engine.connect() as connection:
            assert_model_columns_exist(connection)
    finally:
        engine.dispose()
