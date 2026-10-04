"""Read-only original/receipt proof for actual complete database images.

No auth, application, provider, settings or Store imports. The caller owns a
consistent transaction. Only one case journal and its actual parents are held;
the full affected statement period is hashed as a stream, never truncated.
"""

import hashlib
import json
import sqlite3
import time
from datetime import date, datetime
from decimal import Decimal
from functools import lru_cache

from sqlalchemy import JSON, Boolean, Date, DateTime, Numeric, and_, exists, or_, select

from ..db.billing_dispute_models import DISPUTE_MODELS, DISPUTE_TABLES
from ..db.billing_dispute_schema import validate_dispute_guards, validate_dispute_schema
from ..db.orm_models import Base
from ..models import UtilityStatement
from .billing_dispute_validation import DisputeIntegrityError, validate_dispute_snapshot
from .measurement_history_database import _rows
from .measurement_history_validation import MeasurementIntegrityError


def _check(deadline):
    if deadline is not None and time.monotonic() >= deadline:
        raise DisputeIntegrityError("Zeitbudget der Widerspruchsprüfung erschöpft; mit größerem Budget erneut prüfen.")


def _typed(row, table, raw):
    if raw:
        for column in table.columns:
            value = row[column.name]
            if value is None:
                continue
            if isinstance(column.type, JSON):
                row[column.name] = json.loads(value)
            elif isinstance(column.type, Boolean):
                if value not in (0, 1):
                    raise DisputeIntegrityError("Ungültiger Originalstatus im Widerspruchsjournal.")
                row[column.name] = bool(value)
            elif isinstance(column.type, DateTime):
                row[column.name] = datetime.fromisoformat(value)
            elif isinstance(column.type, Date):
                row[column.name] = date.fromisoformat(value)
            elif isinstance(column.type, Numeric):
                number = Decimal(str(value))
                row[column.name] = number.quantize(Decimal(1).scaleb(-column.type.scale)) if column.type.scale is not None else number
    return row


def _read(connection, table, clause, *, deadline):
    for row in _rows(connection, select(table).where(clause), deadline=deadline):
        yield _typed(row, table, isinstance(connection, sqlite3.Connection))


def _foreign_keys(connection, *, deadline):
    for model in DISPUTE_MODELS:
        table = model.__table__
        for foreign in table.foreign_keys:
            parent = foreign.column.table.alias()
            query = select(table.c.id).where(foreign.parent.is_not(None),
                ~exists(select(parent.c[foreign.column.name]).where(parent.c[foreign.column.name] == foreign.parent))).limit(1)
            if next(_rows(connection, query, deadline=deadline), None) is not None:
                raise DisputeIntegrityError("Widerspruchsoriginalen fehlen erforderliche Originale oder Stammdaten.")


def _parents(connection, family, *, deadline):
    case = family[DISPUTE_TABLES[0]][0]
    events, evidence = family[DISPUTE_TABLES[2]], family[DISPUTE_TABLES[3]]
    ids = {"portfolios": {case["portfolio_id"]}, "properties": {case["property_id"]},
        "units": {case["unit_id"]} - {None}, "contracts": {case["contract_id"]} - {None},
        "tenants": {case["tenant_id"]} - {None}, "billing_periods": {case["period_id"]},
        "document_versions": {row["version_id"] for row in evidence}}
    parents: dict[str, dict[str, dict]] = {name: {} for name in (*ids, "utility_statements")}
    pending = ({case["statement_id"]} | {row["correction_statement_id"] for row in events}) - {None}
    statements = Base.metadata.tables["utility_statements"]
    while pending:
        _check(deadline)
        batch = sorted(pending)[:500]
        pending.difference_update(batch)
        found = set()
        for row in _read(connection, statements, statements.c.id.in_(batch), deadline=deadline):
            found.add(row["id"])
            parents[statements.name][row["id"]] = row
            ids["billing_periods"].add(row["billing_period_id"])
            source = row["source_statement_id"]
            if source is not None and source not in parents[statements.name]:
                pending.add(source)
        if found != set(batch):
            raise DisputeIntegrityError("Verknüpfte Abrechnungsoriginale fehlen in der vollständigen Sicherung.")
    for name, identifiers in ids.items():
        table = Base.metadata.tables[name]
        values = sorted(identifiers)
        for offset in range(0, len(values), 500):
            for row in _read(connection, table, table.c.id.in_(values[offset:offset + 500]), deadline=deadline):
                parents[name][row["id"]] = row
    return parents


def _period_hash(connection, period, *, deadline):
    checksum = hashlib.sha256()
    encoder = json.JSONEncoder(sort_keys=True, ensure_ascii=False)
    def value(item):
        for block in encoder.iterencode(item):
            _check(deadline)
            checksum.update(block.encode("utf-8"))
    checksum.update(b'{"owner_cost_share": ')
    value(period["owner_cost_share"])
    checksum.update(b', "statements": [')
    table = Base.metadata.tables["utility_statements"]
    query = select(table).where(table.c.billing_period_id == period["id"]).order_by(table.c.id)
    for index, row in enumerate(_rows(connection, query, deadline=deadline)):
        if index:
            checksum.update(b", ")
        statement = UtilityStatement.model_validate(_typed(row, table, isinstance(connection, sqlite3.Connection)))
        value(statement.model_dump(mode="json", exclude={"status", "snapshot_hash", "delivery_status",
            "delivered_at", "delivery_channel", "updated_at"}))
    checksum.update(b"]}")
    return checksum.hexdigest()


def validate_dispute_database(connection, *, deadline=None) -> bool:
    """Prove every case; entirely absent old journals remain compatible."""
    _check(deadline)
    if not validate_dispute_schema(connection):
        return False
    validate_dispute_guards(connection)
    try:
        _foreign_keys(connection, deadline=deadline)
        cases, commands, events, evidence = (Base.metadata.tables[name] for name in DISPUTE_TABLES)
        @lru_cache(maxsize=32)
        def period_hash(identifier):
            table = Base.metadata.tables["billing_periods"]
            period = next(_read(connection, table, table.c.id == identifier, deadline=deadline), None)
            if period is None:
                raise DisputeIntegrityError("Die ursprüngliche Abrechnungsperiode fehlt.")
            return _period_hash(connection, period, deadline=deadline)
        after = None
        while True:
            query = select(cases).order_by(cases.c.period_id, cases.c.id).limit(100)
            if after is not None:
                query = query.where(or_(cases.c.period_id > after[0],
                    and_(cases.c.period_id == after[0], cases.c.id > after[1])))
            page = [_typed(row, cases, isinstance(connection, sqlite3.Connection))
                    for row in _rows(connection, query, deadline=deadline)]
            if not page:
                break
            for case in page:
                family = {cases.name: [case],
                    commands.name: list(_read(connection, commands, commands.c.case_id == case["id"], deadline=deadline)),
                    events.name: list(_read(connection, events, events.c.case_id == case["id"], deadline=deadline)),
                    evidence.name: list(_read(connection, evidence, evidence.c.event_id.in_(
                        select(events.c.id).where(events.c.case_id == case["id"])), deadline=deadline))}
                parents = _parents(connection, family, deadline=deadline)
                original_hashes = {identifier: period_hash(identifier) for identifier in parents["billing_periods"]}
                validate_dispute_snapshot(family, parents=parents, verified_period_hashes=original_hashes)
            after = (page[-1]["period_id"], page[-1]["id"])
        _check(deadline)
        return True
    except DisputeIntegrityError:
        raise
    except (ValueError, TypeError, KeyError, MeasurementIntegrityError):
        raise DisputeIntegrityError("Widerspruchsoriginale sind beschädigt; vollständige unveränderte Sicherung prüfen.") from None
