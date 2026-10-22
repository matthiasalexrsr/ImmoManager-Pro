"""A new installation and an upgraded one have the same schema.

New installations get their schema from create_all (backend.db.schema_state.initialise_empty),
upgraded ones from the migrations. Since March 2026 the ORM declared 13 indexes and the unique
account IBAN that no migration created: every upgraded database lacked them. This compares both
ways of building the schema: tables, columns, nullability, indexes, unique constraints, foreign
keys and triggers. A new model or index therefore needs its migration, and a migration its model.
"""

import os
import subprocess
import sys
from pathlib import Path

import sqlalchemy as sa
from alembic import command
from sqlalchemy.pool import NullPool

from backend.db.schema_state import alembic_config

ROOT = Path(__file__).resolve().parents[2]

# Accepted differences, each with its reason; anything else fails.
ACCEPTED = {
    "sqlite": {
        # SQLite adds a foreign key only by rebuilding the table (d1f3a5c7e9b2 adds it on PostgreSQL).
        ("foreign_keys", "fresh", ("invoices", ("source_document_id",), "documents", ("id",), "SET NULL")),
    },
    "postgresql": set(),
}
# Columns that the migrations created nullable and the ORM declares NOT NULL. The ORM always
# fills them; tightening them would rebuild large tables on SQLite for no change in behaviour.
NULLABLE_AFTER_UPGRADE = {
    ("billing_objections", "created_at"), ("billing_objections", "updated_at"),
    ("contract_occupancies", "created_at"), ("contract_occupancies", "updated_at"),
    ("contract_rent_periods", "created_at"), ("contract_rent_periods", "updated_at"),
    ("payment_allocations", "created_at"), ("payment_allocations", "updated_at"),
    ("invoices", "vat_rate"),
}


def build_fresh(url: str) -> None:
    """A new installation in a process of its own, with only the models initialise_empty registers."""
    script = ("import sys\nfrom sqlalchemy import create_engine\nfrom backend.db import schema_state\n"
              "engine = create_engine(sys.argv[1])\nschema_state.initialise_empty(engine)\nengine.dispose()\n")
    environment = dict(os.environ, PYTHONPATH=str(ROOT))
    subprocess.run([sys.executable, "-c", script, url], cwd=ROOT, env=environment, check=True, timeout=600)


def build_upgraded(url: str) -> None:
    command.upgrade(alembic_config(url), "head")


def _triggers(connection) -> set[tuple[str, str]]:
    if connection.dialect.name == "sqlite":
        rows = connection.execute(sa.text("SELECT tbl_name, name FROM sqlite_master WHERE type = 'trigger'"))
    else:
        rows = connection.execute(sa.text("SELECT tgrelid::regclass::text, tgname FROM pg_trigger "
                                          "WHERE NOT tgisinternal"))
    return {(table, name) for table, name in rows}


def _foreign_keys(connection, inspector, table: str) -> set[tuple]:
    if connection.dialect.name != "sqlite":
        return {(table, tuple(key["constrained_columns"]), key["referred_table"], tuple(key["referred_columns"]),
                 ((key.get("options") or {}).get("ondelete") or "NO ACTION").upper())
                for key in inspector.get_foreign_keys(table)}
    # The reflection misses ON DELETE of a reference added with ALTER TABLE ADD COLUMN; the pragma has it.
    keys: dict[int, list] = {}
    for _id, _seq, target, source, referred, _update, delete, _match in connection.exec_driver_sql(
            f'PRAGMA foreign_key_list("{table}")'):
        keys.setdefault(_id, []).append((source, referred, target, delete))
    return {(table, tuple(item[0] for item in parts), parts[0][2], tuple(item[1] for item in parts), parts[0][3])
            for parts in keys.values()}


def describe(url: str) -> dict[str, set]:
    engine = sa.create_engine(url, poolclass=NullPool)
    try:
        with engine.connect() as connection:
            inspector = sa.inspect(connection)
            tables = set(inspector.get_table_names()) - {"alembic_version"}
            schema: dict[str, set] = {"tables": tables, "columns": set(), "nullable": set(), "indexes": set(),
                                      "foreign_keys": set(), "triggers": _triggers(connection)}
            for table in tables:
                for column in inspector.get_columns(table):
                    schema["columns"].add((table, column["name"]))
                    if column["nullable"] and not column.get("primary_key"):
                        schema["nullable"].add((table, column["name"]))
                for index in inspector.get_indexes(table):
                    schema["indexes"].add((table, tuple(index["column_names"]), bool(index["unique"])))
                for unique in inspector.get_unique_constraints(table):
                    schema["indexes"].add((table, tuple(unique["column_names"]), True))
                schema["foreign_keys"] |= _foreign_keys(connection, inspector, table)
            return schema
    finally:
        engine.dispose()


def differences(fresh_url: str, upgraded_url: str, dialect: str) -> list[tuple]:
    fresh, upgraded = describe(fresh_url), describe(upgraded_url)
    found = []
    for part in fresh:
        for item in fresh[part] - upgraded[part]:
            found.append((part, "fresh", item))
        for item in upgraded[part] - fresh[part]:
            found.append((part, "upgraded", item))
    return sorted((item for item in found if item not in ACCEPTED[dialect]
                   and not (item[0] == "nullable" and item[1] == "upgraded" and item[2] in NULLABLE_AFTER_UPGRADE)),
                  key=repr)


def test_new_and_upgraded_sqlite_databases_have_the_same_schema(tmp_path):
    fresh, upgraded = f"sqlite:///{tmp_path / 'fresh.db'}", f"sqlite:///{tmp_path / 'upgraded.db'}"
    build_fresh(fresh)
    build_upgraded(upgraded)

    assert differences(fresh, upgraded, "sqlite") == []


def test_upgraded_database_gets_the_indexes_of_a_new_installation(tmp_path):
    """Regression: the 13 indexes of 0c3db1a and the unique account IBAN existed only after create_all."""
    url = f"sqlite:///{tmp_path / 'upgraded.db'}"
    build_upgraded(url)
    indexes = describe(url)["indexes"]

    assert {("bookings", ("account_id", "booking_date"), False), ("invoices", ("status",), False),
            ("receivables", ("contract_id",), False), ("accounts", ("iban",), True)} <= indexes


def test_the_current_head_adopts_unversioned_desktop_databases():
    """A new migration must also join ORM_ADOPTION_TARGETS in migrations/env.py.

    Otherwise a desktop database created by create_all (no alembic_version) is upgraded through
    every historical migration and fails with "table … already exists".
    """
    import re

    from backend.db.schema_state import head_revision

    source = (ROOT / "backend" / "db" / "migrations" / "env.py").read_text(encoding="utf-8")
    block = re.search(r"ORM_ADOPTION_TARGETS = frozenset\(\{(.*?)\}\)", source, re.S)
    assert block and f'"{head_revision()}"' in block.group(1), (
        f"Add the new head {head_revision()} to ORM_ADOPTION_TARGETS in backend/db/migrations/env.py")


def test_upgrade_keeps_accounts_that_share_an_iban(tmp_path):
    """Existing duplicates must not stop the upgrade; the application refuses new ones."""
    url = f"sqlite:///{tmp_path / 'upgraded.db'}"
    command.upgrade(alembic_config(url), "c7e9a1b3d5f7")
    engine = sa.create_engine(url, poolclass=NullPool)
    with engine.begin() as connection:
        connection.execute(sa.text("INSERT INTO portfolios (id, name, currency, timezone, status, created_at, "
                                   "updated_at) VALUES ('pf', 'P', 'EUR', 'Europe/Berlin', 'active', '2025-01-01', "
                                   "'2025-01-01')"))
        for key in ("a1", "a2"):
            connection.execute(sa.text("INSERT INTO accounts (id, portfolio_id, name, iban, account_type, "
                                       "opening_balance, balance, created_at, updated_at) VALUES (:id, 'pf', :id, "
                                       "'DE89370400440532013000', 'bank', 0, 0, '2025-01-01', '2025-01-01')"),
                               {"id": key})
    engine.dispose()

    build_upgraded(url)

    assert ("accounts", ("iban",), True) not in describe(url)["indexes"]
    engine = sa.create_engine(url, poolclass=NullPool)
    with engine.connect() as connection:
        assert connection.execute(sa.text("SELECT COUNT(*) FROM accounts")).scalar() == 2
        assert connection.execute(sa.text("SELECT version_num FROM alembic_version")).scalar() == "d1f3a5c7e9b2"
    engine.dispose()
