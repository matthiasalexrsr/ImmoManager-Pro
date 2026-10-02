"""Stopped-application invoice receipt upgrade for unversioned local SQLite.

This changes only known financial checks and their additive receipt columns.
It does not infer or stamp a historical Alembic revision. A complete protected
PREVIOUS SQLite snapshot precedes DDL; existing rows and trigger definitions
are checked inside the same exclusive transaction before publication.
"""

import argparse
import hashlib
import math
import struct
import sys
from dataclasses import dataclass
from importlib import import_module
from pathlib import Path
from typing import Any, cast

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import Table, inspect
from sqlalchemy.engine import Connection

from backend import credit_schema_upgrade as boundary

OLD_ALLOCATION = "allocated_amount >= 0 AND (allocated_amount = 0 OR allocated_amount <= amount)"
NEW_ALLOCATION = "allocated_amount >= 0 AND allocated_amount <= abs(amount)"
OLD_TARGET = "(receivable_id IS NULL) != (rent_charge_id IS NULL)"
NEW_TARGET = """(CASE WHEN receivable_id IS NULL THEN 0 ELSE 1 END) +
(CASE WHEN rent_charge_id IS NULL THEN 0 ELSE 1 END) +
(CASE WHEN invoice_id IS NULL THEN 0 ELSE 1 END) = 1"""


class InvoiceUpgradeError(boundary.CreditUpgradeError):
    """A fixed action code, never SQL, row data or a private path."""


def _quoted(name: str) -> str:
    # Names come exclusively from SQLite's own schema, never from CLI SQL.
    return '"' + name.replace('"', '""') + '"'


def _normalized(sql: str) -> str:
    return "".join(sql.lower().split())


def _check_definition(connection: Connection, table: str, name: str, allow_missing: bool = False) -> str:
    checks = [row["sqltext"] for row in inspect(connection).get_check_constraints(table)
              if row["name"] == name]
    if not checks and allow_missing:
        return ""
    if len(checks) != 1:
        raise InvoiceUpgradeError("schema_unsupported")
    return _normalized(checks[0])


def _supported(connection: Connection) -> tuple[bool, bool]:
    tables = set(inspect(connection).get_table_names())
    if not {"invoices", "bookings", "payments"} <= tables or any(name.startswith("_alembic_tmp_") for name in tables):
        raise InvoiceUpgradeError("schema_unsupported")
    fields = {column["name"] for column in inspect(connection).get_columns("invoices")}
    if not {"id", "status", "gross_amount"} <= fields:
        raise InvoiceUpgradeError("schema_unsupported")
    booking_fields = {column["name"] for column in inspect(connection).get_columns("bookings")}
    if not {"id", "amount", "allocated_amount"} <= booking_fields:
        raise InvoiceUpgradeError("schema_unsupported")
    allocation = _check_definition(connection, "bookings", "ck_bookings_allocation", True)
    target = _check_definition(connection, "payments", "ck_payments_one_target")
    if allocation == "":
        # The actual historical startup added allocated_amount with ALTER TABLE,
        # without rebuilding bookings to install the budget CHECK. Only adopt
        # this known nonzero-amount source shape; unrelated checks stay intact.
        nonzero = _check_definition(connection, "bookings", "ck_bookings_amount_nonzero")
        if nonzero not in {_normalized("amount != 0"), _normalized("amount <> 0")}:
            raise InvoiceUpgradeError("schema_unsupported")
    elif allocation not in {_normalized(OLD_ALLOCATION), _normalized(NEW_ALLOCATION)}:
        raise InvoiceUpgradeError("schema_unsupported")
    if target not in {_normalized(OLD_TARGET), _normalized(NEW_TARGET)}:
        raise InvoiceUpgradeError("schema_unsupported")
    payment_fields = {column["name"] for column in inspect(connection).get_columns("payments")}
    if not {"id", "receivable_id", "rent_charge_id"} <= payment_fields:
        raise InvoiceUpgradeError("schema_unsupported")
    if target == _normalized(NEW_TARGET) and not {"invoice_id"} <= payment_fields:
        raise InvoiceUpgradeError("schema_unsupported")
    return allocation == _normalized(NEW_ALLOCATION), target == _normalized(NEW_TARGET)


def _validate_allocation_rows(connection: Connection, deadline: float) -> None:
    # Validate before any DDL/trigger suspension, without rounding, repairing
    # counters or imposing a row limit. Capture/preservation later compares the
    # complete original rows and all other source tables independently.
    result = connection.exec_driver_sql("SELECT amount,allocated_amount FROM bookings")
    try:
        for amount, allocated in result:
            boundary._check(deadline)
            if (not isinstance(amount, (int, float)) or not isinstance(allocated, (int, float))
                    or not math.isfinite(amount) or not math.isfinite(allocated)
                    or amount == 0 or allocated < 0 or allocated > abs(amount)):
                raise InvoiceUpgradeError("allocation_invalid")
    finally:
        result.close()


def _digest_rows(connection: Connection, table: str, columns: tuple[str, ...],
                 primary_key: tuple[str, ...], deadline: float) -> tuple[int, str]:
    """Stream one SQLite row at a time; compare exact original stored values."""
    digest = hashlib.sha256()
    order = ",".join(_quoted(column) for column in primary_key) if primary_key else "rowid"
    projection = ",".join(_quoted(column) for column in columns)
    result = connection.exec_driver_sql(f"SELECT {projection} FROM {_quoted(table)} ORDER BY {order}")
    count = 0
    try:
        for row in result:
            boundary._check(deadline)
            digest.update(b"row:")
            for value in row:
                if value is None:
                    tag, encoded = b"n", b""
                elif isinstance(value, int):
                    tag, encoded = b"i", str(value).encode("ascii")
                elif isinstance(value, float):
                    tag, encoded = b"f", struct.pack(">d", value)
                elif isinstance(value, str):
                    tag, encoded = b"s", value.encode("utf-8")
                elif isinstance(value, bytes):
                    tag, encoded = b"b", value
                else:
                    raise InvoiceUpgradeError("schema_unsupported")
                digest.update(tag)
                digest.update(len(encoded).to_bytes(8, "big"))
                digest.update(encoded)
            count += 1
    finally:
        result.close()
    return count, digest.hexdigest()


def _foreign_keys(connection: Connection, table: str) -> frozenset[tuple[Any, ...]]:
    # PRAGMA identifiers/order can change during a rebuild; link semantics may not.
    return frozenset(tuple(row[1:]) for row in connection.exec_driver_sql(
        f"PRAGMA foreign_key_list({_quoted(table)})"))


def _indexes(connection: Connection, table: str) -> dict[str, tuple[Any, ...]]:
    indexes: dict[str, tuple[Any, ...]] = {}
    for row in connection.exec_driver_sql(f"PRAGMA index_list({_quoted(table)})"):
        _, name, unique, origin, partial = row
        columns = tuple(tuple(item[1:]) for item in connection.exec_driver_sql(
            f"PRAGMA index_xinfo({_quoted(name)})"))
        # Autoindex names can be reordered by reflection. Their keys must remain.
        key = name if origin == "c" else repr((origin, columns))
        sql = connection.exec_driver_sql("SELECT sql FROM sqlite_master WHERE type='index' AND name=?",
                                         (name,)).scalar() or ""
        predicate = sql[sql.upper().index("WHERE"):] if partial and "WHERE" in sql.upper() else ""
        indexes[key] = (unique, origin, partial, columns, predicate)
    return indexes


@dataclass(frozen=True)
class _OriginalTable:
    columns: tuple[str, ...]
    column_definitions: tuple[tuple[Any, ...], ...]
    primary_key: tuple[str, ...]
    foreign_keys: frozenset[tuple[Any, ...]]
    indexes: dict[str, tuple[Any, ...]]
    checks: frozenset[tuple[str | None, str]]
    rows: tuple[int, str]


def _capture(connection: Connection, deadline: float) -> dict[str, _OriginalTable]:
    originals = {}
    for table in inspect(connection).get_table_names():
        columns = tuple(row["name"] for row in inspect(connection).get_columns(table))
        primary_key = tuple(inspect(connection).get_pk_constraint(table)["constrained_columns"])
        checks = frozenset((row["name"], row["sqltext"])
                           for row in inspect(connection).get_check_constraints(table))
        definitions = tuple(tuple(row[1:]) for row in connection.exec_driver_sql(f"PRAGMA table_info({_quoted(table)})"))
        originals[table] = _OriginalTable(columns, definitions, primary_key, _foreign_keys(connection, table),
            _indexes(connection, table), checks, _digest_rows(connection, table, columns, primary_key, deadline))
    return originals


def _preserved(connection: Connection, originals: dict[str, _OriginalTable], deadline: float) -> None:
    for table, original in originals.items():
        inspector = inspect(connection)
        if (not inspector.has_table(table)
                or tuple(inspector.get_pk_constraint(table)["constrained_columns"]) != original.primary_key
                or not original.foreign_keys <= _foreign_keys(connection, table)
                or _digest_rows(connection, table, original.columns, original.primary_key, deadline) != original.rows):
            raise InvoiceUpgradeError("preservation_failed")
        definitions = {row[1]: tuple(row[1:]) for row in connection.exec_driver_sql(f"PRAGMA table_info({_quoted(table)})")}
        if any(definitions.get(column[0]) != column for column in original.column_definitions):
            raise InvoiceUpgradeError("preservation_failed")
        indexes = _indexes(connection, table)
        if any(indexes.get(name) != definition for name, definition in original.indexes.items()):
            raise InvoiceUpgradeError("preservation_failed")
        # Financial checks are intentionally replaced, every other original
        # CHECK still has to be present verbatim (apart from formatting).
        replaced = {"ck_bookings_allocation"} if table == "bookings" else (
            {"ck_payments_one_target"} if table == "payments" else set())
        checks = {(row["name"], _normalized(row["sqltext"])) for row in inspector.get_check_constraints(table)}
        if any((name, _normalized(sql)) not in checks for name, sql in original.checks if name not in replaced):
            raise InvoiceUpgradeError("preservation_failed")


def _upgrade(connection: Connection, deadline: float) -> None:
    negative_ready, invoice_ready = _supported(connection)
    _validate_allocation_rows(connection, deadline)
    originals = _capture(connection, deadline)
    views = {name: sql for name, sql in connection.exec_driver_sql("SELECT name,sql FROM sqlite_master WHERE type='view'")}
    triggers = {name: sql for name, sql in connection.exec_driver_sql(
        "SELECT name,sql FROM sqlite_master WHERE type='trigger' AND sql IS NOT NULL")}
    # Hold every trigger, including cross-table sentinels, in this transaction.
    # Invoice historical backfill must not fire unrelated business mutations.
    for name in triggers:
        connection.exec_driver_sql(f"DROP TRIGGER {_quoted(name)}")
    with Operations.context(MigrationContext.configure(connection)):
        if not negative_ready:
            migration = import_module("backend.db.migrations.versions.n1a2b3c4d5e6_credit_receipt_journal")
            migration._allocation_check(NEW_ALLOCATION)
        if not invoice_ready or "amount_paid" not in originals["invoices"].columns:
            migration = import_module("backend.db.migrations.versions.w1a2b3c4d5e6_invoice_payment_receipts")
            migration.upgrade()
    from backend.db.credit_models import CreditReceiptORM, CreditReversalORM
    from backend.services.invoice_payment_schema import ensure_invoice_payment_immutability
    cast(Table, CreditReceiptORM.__table__).create(connection, checkfirst=True)
    cast(Table, CreditReversalORM.__table__).create(connection, checkfirst=True)
    ensure_invoice_payment_immutability(connection)
    created_triggers = {name: sql for name, sql in connection.exec_driver_sql(
        "SELECT name,sql FROM sqlite_master WHERE type='trigger' AND sql IS NOT NULL")}
    for name, sql in triggers.items():
        if name in created_triggers:
            if _normalized(sql) != _normalized(created_triggers[name]):
                raise InvoiceUpgradeError("schema_unsupported")
            connection.exec_driver_sql(f"DROP TRIGGER {_quoted(name)}")
        connection.exec_driver_sql(sql)
    after_triggers = {name: sql for name, sql in connection.exec_driver_sql(
        "SELECT name,sql FROM sqlite_master WHERE type='trigger' AND sql IS NOT NULL")}
    if any(after_triggers.get(name) != sql for name, sql in triggers.items()):
        raise InvoiceUpgradeError("preservation_failed")
    _preserved(connection, originals, deadline)
    if {name: sql for name, sql in connection.exec_driver_sql("SELECT name,sql FROM sqlite_master WHERE type='view'")} != views:
        raise InvoiceUpgradeError("preservation_failed")
    if _supported(connection) != (True, True):
        raise InvoiceUpgradeError("upgrade_failed")
    # New relationship must actually constrain payments, including installations
    # where additive read compatibility created an unnamed invoice FK earlier.
    if not any(row[1:5] == (0, "invoices", "invoice_id", "id") and row[6] == "RESTRICT"
               for row in connection.exec_driver_sql("PRAGMA foreign_key_list(payments)")):
        raise InvoiceUpgradeError("schema_unsupported")


def upgrade_legacy_sqlite(database: Path, backup_output: Path, *, offline: bool = False,
                          timeout_seconds: float = 300) -> dict[str, object]:
    """Explicit local maintenance only; no row/stock/year limits and no revision guessing."""
    try:
        result = boundary.upgrade_legacy_sqlite(database, backup_output, offline=offline,
            timeout_seconds=timeout_seconds, _upgrade=_upgrade)
    except boundary.CreditUpgradeError as error:
        raise InvoiceUpgradeError(str(error)) from error
    return {**result, "scope": "local_invoice_receipt_schema", "alembic_version_changed": False}


MESSAGES = {
    **boundary.MESSAGES,
    "schema_unsupported": "Unbekannte oder unvollständige Zahlungsstruktur. Keine Änderungen veröffentlicht. Die vorherige Datenbanksicherung bleibt erhalten; das konkrete Schema prüfen lassen, keine Alembic-Version raten.",
    "preservation_failed": "Bestandsprüfung fehlgeschlagen; Upgrade vollständig zurückgerollt. Die vorherige Datenbanksicherung bleibt erhalten. Schema und Trigger prüfen lassen und einen neuen Sicherungsnamen verwenden.",
    "allocation_invalid": "Vorhandene Bankzuordnungen verletzen das Buchungsbudget oder enthalten ungültige Zahlen. Keine Schemaänderung vorgenommen. Belege und Zuordnungen prüfen lassen; die vorherige Datenbanksicherung bleibt erhalten. Für einen neuen Versuch einen neuen Sicherungsnamen verwenden.",
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", required=True, type=Path)
    parser.add_argument("--backup-output", required=True, type=Path)
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--timeout-seconds", default=300, type=float)
    args = parser.parse_args(argv)
    try:
        upgrade_legacy_sqlite(args.database, args.backup_output, offline=args.offline,
                              timeout_seconds=args.timeout_seconds)
    except InvoiceUpgradeError as error:
        print(MESSAGES.get(str(error), MESSAGES["upgrade_failed"]), file=sys.stderr)
        return 2
    print("Rechnungszahlungsstruktur geprüft und aktualisiert. Vollständige vorherige SQLite-Datenbank separat gesichert; keine Alembic-Version gesetzt. Externe Dateien sind weiterhin separat zu sichern.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
