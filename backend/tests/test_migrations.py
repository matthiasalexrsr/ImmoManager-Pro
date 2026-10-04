"""Alembic migrations build the schema the ORM uses, also on existing databases."""

import sqlite3
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory

import backend.models  # noqa: F401  (adds the UI contract columns to the ORM)
from backend.db.orm_models import Base

ROOT = Path(__file__).resolve().parents[2]
PREVIOUS_HEAD = "f6a1b2c3d4e5"


@pytest.fixture
def migrate(tmp_path, monkeypatch):
    db_path = tmp_path / "app.db"
    url = f"sqlite:///{db_path}"
    monkeypatch.setenv("DATABASE_URL", url)  # env.py prefers it over the config
    config = Config()  # no ini file: keeps alembic from reconfiguring logging
    config.set_main_option("script_location", str(ROOT / "backend" / "db" / "migrations"))
    config.set_main_option("sqlalchemy.url", url)

    def run(revision: str = "head") -> Path:
        command.upgrade(config, revision)
        return db_path

    run.head = ScriptDirectory.from_config(config).get_current_head()  # type: ignore[attr-defined]
    run.db_path = db_path  # type: ignore[attr-defined]
    return run


def _schema(db_path: Path) -> dict[str, set[str]]:
    with sqlite3.connect(db_path) as conn:
        tables = [row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        return {table: {row[1] for row in conn.execute(f"PRAGMA table_info({table})")} for table in tables}


def _missing_from(schema: dict[str, set[str]]) -> dict[str, list[str]]:
    missing = {}
    for table in Base.metadata.sorted_tables:
        absent = sorted({column.name for column in table.columns} - schema.get(table.name, set()))
        if absent:
            missing[table.name] = absent
    return missing


def _version(db_path: Path) -> str:
    with sqlite3.connect(db_path) as conn:
        return conn.execute("SELECT version_num FROM alembic_version").fetchone()[0]


def _seed_previous_schema(db_path: Path) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.executescript("""
            INSERT INTO portfolios (id, name, currency, timezone, status, created_at, updated_at)
                VALUES ('pf', 'Bestand', 'EUR', 'Europe/Berlin', 'active', '2025-01-01', '2025-01-01');
            INSERT INTO properties (id, portfolio_id, name, property_type, status, created_at, updated_at)
                VALUES ('pr', 'pf', 'MFH', 'residential', 'active', '2025-01-01', '2025-01-01');
            INSERT INTO units (id, property_id, label, unit_type, status, area_sqm, created_at, updated_at)
                VALUES ('u1', 'pr', 'WE 1', 'residential', 'occupied', 60, '2025-01-01', '2025-01-01');
            INSERT INTO tenants (id, full_name, created_at, updated_at)
                VALUES ('t1', 'Mia Muster', '2025-01-01', '2025-01-01');
            INSERT INTO billing_periods (id, property_id, label, start_date, end_date, status, created_at, updated_at)
                VALUES ('bp', 'pr', 'BK 2024', '2024-01-01', '2024-12-31', 'draft', '2025-01-01', '2025-01-01');
            INSERT INTO allocation_keys (id, property_id, name, key_type, created_at, updated_at)
                VALUES ('k', 'pr', 'Fläche', 'area_sqm', '2025-01-01', '2025-01-01');
            INSERT INTO cost_items (id, billing_period_id, description, amount, allocation_key_id, created_at, updated_at)
                VALUES ('ci', 'bp', 'Grundsteuer', 400, 'k', '2025-01-01', '2025-01-01');
        """)


def test_migrations_build_the_orm_schema(migrate):
    """Regression: a database built by the migrations lacked 2 tables and 29 columns of the ORM."""
    db_path = migrate()

    assert _missing_from(_schema(db_path)) == {}


def test_upgrade_keeps_existing_rows(migrate):
    db_path = migrate(PREVIOUS_HEAD)
    _seed_previous_schema(db_path)

    migrate()

    with sqlite3.connect(db_path) as conn:
        assert conn.execute("SELECT description, is_recoverable FROM cost_items").fetchall() == [("Grundsteuer", 1)]
        assert conn.execute("SELECT archived FROM tenants").fetchall() == [(0,)]
    assert _version(db_path) == migrate.head


def test_database_created_without_migrations_is_adopted(migrate):
    """create_all() databases (desktop installs) have no alembic_version; upgrading them used to fail."""
    db_path = migrate(PREVIOUS_HEAD)
    _seed_previous_schema(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute("DROP TABLE alembic_version")

    migrate()

    assert _version(db_path) == migrate.head
    assert _missing_from(_schema(db_path)) == {}


def test_database_created_by_create_all_upgrades_cleanly(migrate):
    """A current desktop database already has every column; adopting it must not fail."""
    from sqlalchemy import create_engine

    engine = create_engine(f"sqlite:///{migrate.db_path}")
    Base.metadata.create_all(engine)
    engine.dispose()

    migrate()

    assert _version(migrate.db_path) == migrate.head
    assert _missing_from(_schema(migrate.db_path)) == {}
