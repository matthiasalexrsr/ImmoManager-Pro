"""Explicit stopped-application upgrade of legacy create_all SQLite databases."""

import argparse
import math
import sqlite3
import sys
import time
from importlib import import_module
from pathlib import Path
from typing import cast

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import Table, create_engine, inspect
from sqlalchemy.engine import URL
from sqlalchemy.pool import NullPool

from scripts.private_server_backup import BackupError, _safe_path, protected_new_file


class CreditUpgradeError(RuntimeError):
    pass


def _check(deadline):
    if time.monotonic() >= deadline:
        raise CreditUpgradeError("timeout")


def _consistent(connection):
    if connection.exec_driver_sql("PRAGMA integrity_check").scalar() != "ok":
        raise CreditUpgradeError("database_inconsistent")
    if connection.exec_driver_sql("PRAGMA foreign_key_check").first() is not None:
        raise CreditUpgradeError("database_inconsistent")


def _has_new_check(connection):
    return any(row["name"] == "ck_bookings_allocation"
               and "abs(" in row["sqltext"].lower().replace(" ", "")
               for row in inspect(connection).get_check_constraints("bookings"))


def upgrade_legacy_sqlite(database: Path, backup_output: Path, *, offline=False, timeout_seconds=300):
    """No live DDL, no overwrite, no secret configuration imports."""
    if not offline:
        raise CreditUpgradeError("offline_required")
    if (isinstance(timeout_seconds, bool) or not math.isfinite(timeout_seconds) or timeout_seconds <= 0):
        raise CreditUpgradeError("timeout_invalid")
    if backup_output.exists():
        raise CreditUpgradeError("snapshot_exists")
    try:
        database = _safe_path(database)
        backup_output = _safe_path(backup_output, existing=False)
    except (BackupError, OSError) as error:
        raise CreditUpgradeError("database_unsafe") from error
    if database == backup_output or backup_output.exists():
        raise CreditUpgradeError("snapshot_exists")
    identity = database.stat().st_dev, database.stat().st_ino
    def verify_identity():
        _safe_path(database)
        current = database.stat()
        if (current.st_dev, current.st_ino) != identity:
            raise CreditUpgradeError("database_changed")
    deadline = time.monotonic() + timeout_seconds
    engine = create_engine(URL.create("sqlite", database=str(database)),
                           poolclass=NullPool, hide_parameters=True,
                           connect_args={"timeout": timeout_seconds})
    try:
        with engine.connect() as connection:
            driver = connection.connection.driver_connection
            assert isinstance(driver, sqlite3.Connection)
            verify_identity()
            def progress():
                return int(time.monotonic() >= deadline)
            driver.set_progress_handler(progress, 1000)
            connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
            tables = set(inspect(connection).get_table_names())
            if "alembic_version" in tables and connection.exec_driver_sql("SELECT 1 FROM alembic_version LIMIT 1").first():
                raise CreditUpgradeError("database_versioned")
            if not {"bookings", "contracts", "payments", "payment_reversals", "billing_settlements"} <= tables:
                raise CreditUpgradeError("database_inconsistent")
            _consistent(connection)
            connection.rollback()
            version = connection.exec_driver_sql("PRAGMA data_version").scalar()
            connection.rollback()
            # Snapshot completes before any DDL. Its private ACL is set before bytes.
            with protected_new_file(backup_output):
                with sqlite3.connect(backup_output) as destination:
                    def backup_progress(*_):
                        _check(deadline)
                    driver.backup(destination, pages=512, progress=backup_progress, sleep=0.01)
                    if destination.execute("PRAGMA integrity_check").fetchone() != ("ok",):
                        raise CreditUpgradeError("database_inconsistent")
            _check(deadline)
            verify_identity()
            connection.exec_driver_sql("BEGIN EXCLUSIVE")
            if connection.exec_driver_sql("PRAGMA data_version").scalar() != version:
                raise CreditUpgradeError("database_changed")
            _consistent(connection)
            if not _has_new_check(connection):
                migration = import_module("backend.db.migrations.versions.n1a2b3c4d5e6_credit_receipt_journal")
                with Operations.context(MigrationContext.configure(connection)):
                    migration._allocation_check("allocated_amount >= 0 AND allocated_amount <= abs(amount)")
            from .db.credit_models import CreditReceiptORM, CreditReversalORM
            cast(Table, CreditReceiptORM.__table__).create(connection, checkfirst=True)
            cast(Table, CreditReversalORM.__table__).create(connection, checkfirst=True)
            _consistent(connection)
            if not _has_new_check(connection):
                raise CreditUpgradeError("upgrade_failed")
            _check(deadline)
            verify_identity()
            connection.commit()
            return {"upgraded": True, "backup_created": True, "scope": "local_credit_schema"}
    except CreditUpgradeError:
        raise
    except Exception as error:
        # Driver text can contain user paths/rows; report only a fixed action code.
        code = "database_busy" if isinstance(error.__cause__, sqlite3.OperationalError) and "locked" in str(error.__cause__) else "upgrade_failed"
        if time.monotonic() >= deadline:
            code = "timeout"
        raise CreditUpgradeError(code) from error
    finally:
        engine.dispose()


MESSAGES = {
    "offline_required": "Anwendung und andere Schreiber zuerst stoppen; danach mit --offline wiederholen.",
    "timeout_invalid": "Eine positive endliche Laufzeit in --timeout-seconds angeben.",
    "timeout": "Laufzeitbudget erreicht; Schreibänderungen zurückgerollt. Freien Speicher prüfen und mit größerem --timeout-seconds und neuem Sicherungsnamen wiederholen.",
    "database_unsafe": "Eine vorhandene lokale Datenbank und einen neuen Sicherungspfad ohne Verknüpfungen auswählen.",
    "snapshot_exists": "Sicherung wird nicht überschrieben. Einen neuen --backup-output wählen.",
    "database_versioned": "Diese Datenbank hat Alembic-Versionen. Den normalen dokumentierten Offline-Migrationspfad verwenden.",
    "database_changed": "Ein anderer Prozess hat nach der Sicherung geschrieben. Alle Schreiber stoppen und mit neuem Sicherungsnamen wiederholen.",
    "database_busy": "Datenbank noch in Benutzung. Alle Schreiber stoppen und mit neuem Sicherungsnamen wiederholen.",
    "database_inconsistent": "Datenbankprüfung fehlgeschlagen. Keine Migration vorgenommen; eine separat geprüfte Vollsicherung wiederherstellen.",
    "upgrade_failed": "Upgrade zurückgerollt. Die vollständige vorherige Datenbanksicherung bleibt, falls bereits erstellt. Datenbankzugriff und freien Speicher prüfen; mit neuem Sicherungsnamen wiederholen.",
}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", required=True, type=Path)
    parser.add_argument("--backup-output", required=True, type=Path)
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--timeout-seconds", default=300, type=float)
    args = parser.parse_args(argv)
    try:
        upgrade_legacy_sqlite(args.database, args.backup_output,
                              offline=args.offline, timeout_seconds=args.timeout_seconds)
    except CreditUpgradeError as error:
        print(MESSAGES.get(str(error), MESSAGES["upgrade_failed"]), file=sys.stderr)
        return 2
    print("Guthabenstruktur geprüft und aktualisiert; vollständige vorherige SQLite-Datenbank separat gesichert.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
