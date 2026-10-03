"""Read-only, per-ledger native proof for offline backup and recovery.

No application/auth/store imports or DDL. The caller supplies an offline or
consistent transaction. Raw SQLite archives and SQLAlchemy connections share
the same typed statements and pure original-evidence validator.
"""

import json
import sqlite3
import time

from sqlalchemy import JSON, Boolean, exists, func, select
from sqlalchemy.dialects.sqlite import dialect as sqlite_dialect

from ..db.measurement_history_models import MEASUREMENT_MODELS, MEASUREMENT_TABLES
from ..db.measurement_history_schema import validate_measurement_guards, validate_measurement_schema
from ..db.orm_models import Base
from .measurement_history_validation import MeasurementIntegrityError, validate_measurement_snapshot


def _check(deadline):
    if deadline is not None and time.monotonic() >= deadline:
        raise MeasurementIntegrityError("Zeitbudget der historischen Quellenprüfung erschöpft; erneut mit größerem Budget prüfen.")


def _rows(connection, statement, *, deadline):
    """Use named bound parameters for raw SQLite; never interpolate values."""
    _check(deadline)
    if isinstance(connection, sqlite3.Connection):
        compiled = statement.compile(dialect=sqlite_dialect(paramstyle="named"),
                                     compile_kwargs={"render_postcompile": True})
        result = connection.execute(str(compiled), compiled.params)
        names = [item[0] for item in result.description]
    else:
        result = connection.execute(statement)
        names = list(result.keys())
    try:
        while batch := result.fetchmany(100):
            _check(deadline)
            for row in batch:
                yield dict(zip(names, row, strict=True))
    finally:
        result.close()


def _table_rows(connection, table, clause, *, deadline):
    for row in _rows(connection, select(table).where(clause), deadline=deadline):
        if isinstance(connection, sqlite3.Connection):
            for column in table.columns:
                value = row[column.name]
                if value is not None and isinstance(column.type, JSON):
                    row[column.name] = json.loads(value)
                elif value is not None and isinstance(column.type, Boolean):
                    if value not in (0, 1):
                        raise MeasurementIntegrityError("Ungültiger Originalstatus in historischer Quellenfamilie.")
                    row[column.name] = bool(value)
        yield row


def _one(connection, statement, *, deadline):
    return next(_rows(connection, statement.limit(1), deadline=deadline), None)


def _parents(connection, family, *, deadline):
    ledger = family[MEASUREMENT_TABLES[0]][0]
    facts, evidence = family[MEASUREMENT_TABLES[2]], family[MEASUREMENT_TABLES[3]]
    identifiers = {"units": {ledger["id"]}, "properties": {ledger["property_id"]},
        "meters": {row["meter_id"] for row in facts if row["meter_id"]},
        "allocation_keys": {row["allocation_key_id"] for row in facts if row["allocation_key_id"]},
        "contracts": {row["contract_id"] for row in facts if row["contract_id"]},
        "tenants": {row["tenant_id"] for row in facts if row["tenant_id"]},
        "document_versions": {row["version_id"] for row in evidence}}
    result: dict[str, dict[str, dict]] = {}
    fields = {"units": ("id", "property_id"), "properties": ("id", "portfolio_id"),
        "meters": ("id",), "allocation_keys": ("id", "property_id"),
        "contracts": ("id", "unit_id", "tenant_id"), "tenants": ("id",),
        "document_versions": ("id", "sha256", "portfolio_id", "property_id", "unit_id")}
    for name, values in identifiers.items():
        table = Base.metadata.tables[name]
        items = sorted(values)
        result[name] = {}
        for offset in range(0, len(items), 500):
            statement = select(*(table.c[field] for field in fields[name])).where(table.c.id.in_(items[offset:offset + 500]))
            for row in _rows(connection, statement, deadline=deadline):
                result[name][row["id"]] = row
    return result


def _foreign_keys(connection, *, deadline):
    # Schema checks prove each declared FK; also detect rows loaded with SQLite
    # FK enforcement disabled. No whole-parent inventory is needed.
    for model in MEASUREMENT_MODELS:
        table = model.__table__
        for foreign in table.foreign_keys:
            parent = foreign.column.table.alias()
            missing = select(table.c.id).where(foreign.parent.is_not(None),
                ~exists(select(parent.c.id).where(parent.c[foreign.column.name] == foreign.parent)))
            if _one(connection, missing, deadline=deadline):
                raise MeasurementIntegrityError("Historischen Quellen fehlen erforderliche Originale oder Stammdaten.")


def _physical_assignment_overlap(connection, *, deadline):
    facts = Base.metadata.tables[MEASUREMENT_TABLES[2]]
    successor = facts.alias("successor")
    effective = select(facts.c.id, facts.c.meter_id, facts.c.valid_from, facts.c.valid_until).where(
        facts.c.kind == "assignment", facts.c.withdrawn.is_(False),
        ~exists(select(successor.c.id).where(successor.c.predecessor_id == facts.c.id))).subquery()
    ordered = select(effective.c.id, effective.c.valid_from,
        func.max(effective.c.valid_until).over(partition_by=effective.c.meter_id,
            order_by=(effective.c.valid_from, effective.c.valid_until, effective.c.id),
            rows=(None, -1)).label("previous_end")).subquery()
    if _one(connection, select(ordered.c.id).where(ordered.c.previous_end > ordered.c.valid_from), deadline=deadline):
        raise MeasurementIntegrityError("Historische Zählerbetriebszeiten überschneiden sich zwischen Einheiten.")


def validate_measurement_database(connection, *, deadline=None) -> bool:
    """Validate all sources, retaining only one unit's journal at a time."""
    _check(deadline)
    if not validate_measurement_schema(connection):
        return False  # Entirely absent legacy family; never synthesize sources.
    validate_measurement_guards(connection)
    try:
        _foreign_keys(connection, deadline=deadline)
        ledger_table, command_table, fact_table, evidence_table = (
            Base.metadata.tables[name] for name in MEASUREMENT_TABLES)
        after = None
        while True:
            statement = select(ledger_table).order_by(ledger_table.c.id).limit(100)
            if after is not None:
                statement = statement.where(ledger_table.c.id > after)
            ledgers = list(_rows(connection, statement, deadline=deadline))
            if not ledgers:
                break
            for ledger in ledgers:
                _check(deadline)
                facts = list(_table_rows(connection, fact_table, fact_table.c.ledger_id == ledger["id"], deadline=deadline))
                family = {ledger_table.name: [ledger],
                    command_table.name: list(_table_rows(connection, command_table,
                        command_table.c.ledger_id == ledger["id"], deadline=deadline)),
                    fact_table.name: facts,
                    evidence_table.name: list(_table_rows(connection, evidence_table,
                        evidence_table.c.fact_id.in_(select(fact_table.c.id).where(fact_table.c.ledger_id == ledger["id"])),
                        deadline=deadline))}
                validate_measurement_snapshot(family, parents=_parents(connection, family, deadline=deadline))
            after = ledgers[-1]["id"]
        _physical_assignment_overlap(connection, deadline=deadline)
        _check(deadline)
        return True
    except MeasurementIntegrityError:
        raise
    except (ValueError, TypeError, KeyError):
        raise MeasurementIntegrityError("Historische Originale sind beschädigt; vollständige unveränderte Sicherung prüfen.") from None
