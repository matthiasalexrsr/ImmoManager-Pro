"""Reproduce frozen schema profiles from repository source, never private data.

Run with the project virtualenv. Only UUID-owned temporary source/data directories
are executed. The resulting JSON contains schema DDL, no installation or keys.
"""

import argparse
import io
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
from contextlib import closing
from pathlib import Path
from zipfile import ZipFile

from backend.legacy_sqlite_upgrade.schema import catalog, catalog_hash

ROOT = Path(__file__).resolve().parents[1]
SOURCE = "1910f25"
RECIPE = """
from importlib import import_module
from backend.db import session
session.create_tables()
if __import__('os').environ['LEGACY_RECIPE'] == 'historical-receipt-checks':
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    with session.engine.connect() as connection:
        connection.exec_driver_sql('PRAGMA foreign_keys=OFF')
        connection.rollback()
        connection.exec_driver_sql('BEGIN IMMEDIATE')
        with Operations.context(MigrationContext.configure(connection)):
            import_module('backend.db.migrations.versions.w1a2b3c4d5e6_invoice_payment_receipts').downgrade()
            import_module('backend.db.migrations.versions.n1a2b3c4d5e6_credit_receipt_journal')._allocation_check(
                'allocated_amount >= 0 AND (allocated_amount = 0 OR allocated_amount <= amount)')
        connection.commit()
session.engine.dispose()
"""


def clean_environment(data: Path, database: Path) -> dict:
    allowed = {"SYSTEMROOT", "WINDIR", "PATH", "TEMP", "TMP", "COMSPEC", "PATHEXT", "LOCALAPPDATA", "APPDATA"}
    env = {key: value for key, value in os.environ.items() if key.upper() in allowed}
    env.update(DATA_DIR=str(data), DATABASE_URL="sqlite:///" + database.as_posix(),
               UPLOADS_DIR=str(data / "uploads"), INTEGRATION_STATE_FILE=str(data / "integrations.json"),
               JWT_SECRET_KEY="synthetic-legacy-reference-key-" + "x" * 48,
               ENVIRONMENT="development", STORAGE_BACKEND="sql", AUTO_MIGRATE="false",
               AI_ENABLED="false", AUTO_SEED_DEMO_DATA="false")
    return env


def build(output: Path):
    previous = json.loads(output.read_text(encoding="utf-8"))["profiles"] if output.exists() else None
    commit = subprocess.check_output(["git", "rev-parse", SOURCE + "^{commit}"], cwd=ROOT, text=True).strip()
    archive = subprocess.check_output(["git", "archive", "--format=zip", commit, "backend"], cwd=ROOT)
    with tempfile.TemporaryDirectory(prefix="immo-legacy-reference-") as temporary:
        owner = Path(temporary)
        source = owner / "source"
        source.mkdir()
        with ZipFile(io.BytesIO(archive)) as bundle:
            bundle.extractall(source)  # Input is the exact repository tree, not a user archive.
        result = {}
        for recipe in ("fresh-create-all", "historical-receipt-checks"):
            data = owner / recipe
            data.mkdir()
            database = data / "reference.sqlite"
            env = clean_environment(data, database)
            env["LEGACY_RECIPE"] = recipe
            subprocess.run([sys.executable, "-c", RECIPE], cwd=source, env=env, check=True,
                           stdout=subprocess.DEVNULL)
            with closing(sqlite3.connect(database)) as connection:
                value = catalog(connection)
                ddl = [row[0] for row in connection.execute("SELECT sql FROM sqlite_master WHERE sql IS NOT NULL AND name NOT LIKE 'sqlite_%' ORDER BY CASE type WHEN 'table' THEN 0 WHEN 'index' THEN 1 ELSE 2 END,name")]
            result["release126-" + recipe] = {"source_commit": commit, "recipe": recipe,
                "schema_sha256": catalog_hash(value), "catalog": value, "ddl": ddl}
        current = owner / "current"
        current.mkdir()
        database = current / "reference.sqlite"
        env = clean_environment(current, database)
        subprocess.run([sys.executable, "-m", "alembic", "-c", str(ROOT / "alembic.ini"), "upgrade", "head"],
                       cwd=ROOT, env=env, check=True, stdout=subprocess.DEVNULL)
        with closing(sqlite3.connect(database)) as connection:
            required = catalog(connection)["tables"]
            head = connection.execute("SELECT version_num FROM alembic_version").fetchone()[0]
        for reference in result.values():
            old = reference["catalog"]["tables"]
            reference["missing_tables"] = sorted(set(required) - set(old))
            reference["missing_columns"] = {table: sorted({row[1] for row in target["columns"]} -
                                                        {row[1] for row in old[table]["columns"]})
                for table, target in required.items() if table in old}
            reference["missing_columns"] = {key: value for key, value in reference["missing_columns"].items() if value}
            reference["validated_target_head"] = head
        if previous is not None:
            for name, reference in result.items():
                old = previous[name]
                with closing(sqlite3.connect(":memory:")) as historical:
                    for sql in old["ddl"]:
                        historical.execute(sql)
                    historical_catalog = catalog(historical)
                if old["schema_sha256"] != catalog_hash(old["catalog"]) or historical_catalog != reference["catalog"]:
                    raise RuntimeError("Frozen historical schema changed; target-only regeneration refused")
                reference["ddl"] = old["ddl"]  # Original historical DDL remains byte-for-byte frozen.
        output.write_text(json.dumps({"format": 1, "profiles": result}, ensure_ascii=False,
                                     sort_keys=True, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "backend/legacy_sqlite_upgrade/release126_profiles.json")
    build(parser.parse_args().output)
