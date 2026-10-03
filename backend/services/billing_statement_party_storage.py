"""Native finalization, exact subject queries and original parent retention."""

import hashlib
import json
from copy import deepcopy
from datetime import datetime, timezone

from sqlalchemy import JSON, exists, select, text
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.sql.functions import FunctionElement

from .billing_statement_parties import (
    IDENTITY_FIELDS,
    KEY,
    SCHEMA,
    PartyIdentity,
    StatementParties,
    StatementParty,
    StatementPartyIntegrityError,
    family,
    party,
)


class _PartyEntry(FunctionElement):
    type = JSON()
    inherit_cache = True


@compiles(_PartyEntry, "sqlite")
def _sqlite_entry(element, compiler, **kwargs):
    owner, identifier = (compiler.process(item, **kwargs) for item in element.clauses)
    return f"json_extract({owner}, '$.\"statement_parties\".\"statements\".' || json_quote({identifier}))"


@compiles(_PartyEntry, "postgresql")
def _postgres_entry(element, compiler, **kwargs):
    owner, identifier = (compiler.process(item, **kwargs) for item in element.clauses)
    return f"(({owner} -> 'statement_parties' -> 'statements') -> {identifier})"


def statement_snapshot_hash(store, period):
    """Exact existing settlement digest with SQL rows streamed by ID."""
    from ..models import UtilityStatement
    encoder, checksum = json.JSONEncoder(sort_keys=True, ensure_ascii=False), hashlib.sha256()
    def value(item):
        for block in encoder.iterencode(item):
            checksum.update(block.encode("utf-8"))
    checksum.update(b'{"owner_cost_share": ')
    value(period.owner_cost_share)
    checksum.update(b', "statements": [')
    if hasattr(store, "db"):
        from ..db.orm_models import UtilityStatementORM
        rows = store.db.scalars(select(UtilityStatementORM).where(UtilityStatementORM.billing_period_id == period.id)
            .order_by(UtilityStatementORM.id).execution_options(yield_per=100))
    else:
        rows = sorted((row for row in store.list_utility_statements() if row.billing_period_id == period.id), key=lambda row: row.id)
    try:
        for index, row in enumerate(rows):
            if index:
                checksum.update(b", ")
            statement = UtilityStatement.model_validate(row, from_attributes=True) if hasattr(store, "db") else row
            value(statement.model_dump(mode="json", exclude={"status", "snapshot_hash", "delivery_status", "delivered_at", "delivery_channel", "updated_at"}))
    finally:
        close = getattr(rows, "close", None)
        if close is not None:
            close()
    checksum.update(b"]}")
    return checksum.hexdigest()


def freeze(store, period, statements):
    """Called exactly once by actual finalization, within its existing locks."""
    if family(period) is not None:
        raise StatementPartyIntegrityError("Ein vorhandenes Parteienoriginal darf nicht neu eingefroren werden.")
    from .portfolio_scope import current_scope
    captured = current_scope()
    prop = store.get_property(period.property_id)
    entries = {}
    verified_sources = {}
    for statement in statements:
        contract = store.get_contract(statement.contract_id)
        unit = store.get_unit(statement.unit_id)
        if contract.unit_id != unit.id or contract.property_id != prop.id or unit.property_id != prop.id:
            raise StatementPartyIntegrityError("Vertrag und Einheit besitzen keine eindeutige Abrechnungsbindung.")
        source, source_party = None, None
        if statement.source_statement_id:
            source = store.get_utility_statement(statement.source_statement_id)
            source_period = store.get_billing_period(source.billing_period_id)
            source_party = party(source, source_period)
            if source.snapshot_hash is not None:
                if source_period.id not in verified_sources:
                    verified_sources[source_period.id] = statement_snapshot_hash(store, source_period)
                if verified_sources[source_period.id] != source.snapshot_hash:
                    raise StatementPartyIntegrityError("Die belegte Korrekturquelle weicht vom gespeicherten Original ab.")
        tenant_id = source_party.tenant_id if source_party is not None else contract.tenant_id
        if hasattr(store, "db"):
            from ..db.orm_models import TenantORM
            store.db.scalar(select(TenantORM.id).where(TenantORM.id == tenant_id).with_for_update(read=True))
        tenant = store.get_tenant(tenant_id)
        identity = source_party.identity.model_dump() if source_party is not None else {
            name: getattr(tenant, name) for name in IDENTITY_FIELDS}
        if source_party is not None and (source_party.contract_id != contract.id or source_party.unit_id != unit.id
                or source_party.property_id != prop.id or source_party.portfolio_id != prop.portfolio_id):
            raise StatementPartyIntegrityError("Korrektur besitzt eine andere ursprüngliche Parteienbindung.")
        entries[statement.id] = StatementParty(statement_id=statement.id, period_id=period.id,
            revision=statement.revision, portfolio_id=prop.portfolio_id, property_id=prop.id,
            unit_id=unit.id, contract_id=contract.id, tenant_id=tenant_id, identity=PartyIdentity.model_validate(identity),
            captured_at=datetime.now(timezone.utc), captured_by=captured.user_id if captured else None,
            basis="source_original" if source_party is not None else "contract_at_correction_finalization" if source else "contract_at_finalization",
            source_statement_id=source.id if source else None, source_snapshot_hash=source.snapshot_hash if source else None)
    return {**deepcopy(period.owner_cost_share), KEY: StatementParties(schema_version=SCHEMA, statements=entries).model_dump(mode="json")}


def subject_expressions(statement, period):
    block = period.owner_cost_share[KEY]
    entry = _PartyEntry(period.owner_cost_share, statement.id)
    return entry["tenant_id"].as_string(), entry["portfolio_id"].as_string(), entry["property_id"].as_string(), block


def _subject_rows(store, tenant_id):
    from ..db.orm_models import BillingPeriodORM as Period
    from ..db.orm_models import UtilityStatementORM as Statement
    from ..models import BillingPeriod, UtilityStatement
    from .portfolio_scope import memory_visible
    if hasattr(store, "db"):
        subject, _portfolio, _property, _block = subject_expressions(Statement, Period)
        query = select(Statement, Period).join(Period, Statement.billing_period_id == Period.id).where(subject == tenant_id).order_by(Statement.id)
        result = store.db.execute(query.execution_options(yield_per=100))
        try:
            for statement, period in result:
                yield UtilityStatement.model_validate(statement, from_attributes=True), BillingPeriod.model_validate(period, from_attributes=True)
        finally:
            result.close()
    else:
        for statement in sorted(store.utility_statements.values(), key=lambda row: row.id):
            period = store.billing_periods.get(statement.billing_period_id)
            if period is None or not memory_visible(store, "billing_periods", period):
                continue
            original = party(statement, period)
            if original is not None and original.tenant_id == tenant_id:
                yield statement, period


def require_complete_scope(store, tenant_id):
    from fastapi import HTTPException

    from .portfolio_scope import current_scope
    captured = current_scope()
    if captured is None or captured.unrestricted:
        return
    if hasattr(store, "db"):
        from ..db.orm_models import BillingPeriodORM as Period
        from ..db.orm_models import UtilityStatementORM as Statement
        subject, portfolio, _property, _block = subject_expressions(Statement.__table__.c, Period.__table__.c)
        raw = Statement.__table__.join(Period.__table__, Statement.billing_period_id == Period.id)
        hidden = store.db.connection().scalar(select(exists(select(Statement.__table__.c.id).select_from(raw)
            .where(subject == tenant_id, portfolio.not_in(captured.portfolio_ids)))))
    else:
        hidden = False
        for statement in store.utility_statements.values():
            period = store.billing_periods.get(statement.billing_period_id)
            if period is not None:
                original = party(statement, period)
                if original is not None and original.tenant_id == tenant_id and original.portfolio_id not in captured.portfolio_ids:
                    hidden = True
                    break
    if hidden:
        raise HTTPException(403, "Die belegte ursprüngliche Mietpartei liegt auch in weiteren Portfolios. Vollständige Originalberechtigung herstellen.")


def append_graph(store, graph):
    tenant_id = graph["tenant"]["id"]
    require_complete_scope(store, tenant_id)
    graph["frozen_utility_statement_originals"] = []
    verified = {}
    for statement, period in _subject_rows(store, tenant_id):
        original = party(statement, period)
        if period.id not in verified:
            verified[period.id] = statement_snapshot_hash(store, period)
        if statement.snapshot_hash != verified[period.id]:
            raise StatementPartyIntegrityError("Gespeichertes Parteienoriginal besitzt keinen gültigen Abrechnungsoriginalhash.")
        graph["frozen_utility_statement_originals"].append({"statement": statement.model_dump(mode="json"),
            "original_party": original.model_dump(mode="json")})
    graph["scope"]["frozen_statement_parties"] = "Belegte Parteien neuer Finalfassungen nach eingefrorener tenant_id; alte Fassungen besitzen keinen damaligen Identitätsnachweis. Gemeinsame Periodenparteien werden nicht exportiert."
    return graph


PERSONAL_FIELDS = {"frozen_utility_statement_originals": ["original tenant reference", "original full name and postal identity", "finalization capture and source revision"]}

PARENT_FIELDS = {"portfolios": "portfolio_id", "properties": "property_id", "units": "unit_id",
                 "contracts": "contract_id", "tenants": "tenant_id", "utility_statements": "statement_id", "billing_periods": "period_id"}


def parent_property_ids(store, table, identifier):
    field = PARENT_FIELDS.get(table)
    if field is None:
        return set()
    if hasattr(store, "db"):
        from ..db.orm_models import BillingPeriodORM as Period
        from ..db.orm_models import UtilityStatementORM as Statement
        entry = _PartyEntry(Period.__table__.c.owner_cost_share, Statement.__table__.c.id)
        raw = Statement.__table__.join(Period.__table__, Statement.billing_period_id == Period.id)
        return set(store.db.connection().scalars(select(entry["property_id"].as_string()).select_from(raw)
            .where(entry[field].as_string() == identifier).distinct()))
    result = set()
    for statement in store.utility_statements.values():
        period = store.billing_periods.get(statement.billing_period_id)
        if period is not None:
            original = party(statement, period)
            if original is not None and getattr(original, field) == identifier:
                result.add(original.property_id)
    return result


def guard_parent(store, table, identifier):
    if parent_property_ids(store, table, identifier):
        from fastapi import HTTPException
        raise HTTPException(409, "Die finalisierte Abrechnungsfassung benötigt ihre ursprüngliche Mietpartei und Objektbindung. Für eine andere Mietpartei einen eigenen Vertrag verwenden; Originale erhalten.")


def lock_subject(store, tenant_id):
    require_complete_scope(store, tenant_id)
    if not hasattr(store, "db"):
        return
    if store.db.get_bind().dialect.name == "postgresql":
        for property_id in sorted(parent_property_ids(store, "tenants", tenant_id)):
            identifier = int.from_bytes(hashlib.sha256(("measurement:" + property_id).encode()).digest()[:8], "big", signed=True)
            if not store.db.scalar(text("SELECT pg_try_advisory_xact_lock(:identifier)"), {"identifier": identifier}):
                from .tenant_privacy import PrivacyConflict
                raise PrivacyConflict("Eine neue Abrechnungsparteienfassung wird gerade finalisiert. Vorschau neu laden und erneut versuchen.")


