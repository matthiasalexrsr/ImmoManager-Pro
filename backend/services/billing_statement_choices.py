"""Bounded original selection metadata through existing dispute/reference fences."""

import heapq
import re

from fastapi import HTTPException
from sqlalchemy import and_, literal, or_, select
from sqlalchemy import case as sql_case

from ..db.booking_order import bytewise_id
from ..db.orm_models import BillingPeriodORM as Period
from ..db.orm_models import ContractORM
from ..db.orm_models import UtilityStatementORM as Statement
from ..storage import NotFoundError
from .billing_dispute_validation import DisputeIntegrityError
from .billing_disputes import work
from .billing_originals import IMMUTABLE
from .billing_statement_parties import FROZEN_BINDING, KEY, SCHEMA, StatementPartyIntegrityError, party
from .billing_statement_party_storage import _PartyEntry
from .contract_workspace_search import UnicodeCasefold, ensure_sqlite_casefold
from .portfolio_scope import memory_visible
from .reference_cursor import pack_reference_cursor

FIELDS = ("id", "billing_period_id", "contract_id", "unit_id", "revision", "snapshot_hash", "status")


def _choice(statement, period):
    original = party(statement, period)
    result = {name: statement[name] for name in FIELDS}
    subject = original.identity.full_name if original is not None else f"Einheit {statement['unit_id']}"
    result["label"] = f"{period['label']} · Fassung {statement['revision']} · {subject}"
    if original is not None:
        result.update(party_binding=FROZEN_BINDING, tenant_name=original.identity.full_name)
    return result


def _frozen_columns(statement, period):
    entry = _PartyEntry(period.owner_cost_share, statement.id)
    block = period.owner_cost_share[KEY]
    schema = block["schema_version"].as_string()
    return entry, block, schema


def _sql_valid(statement, period, tenant_id=None):
    entry, block, schema = _frozen_columns(statement, period)
    original = and_(schema == SCHEMA, entry["statement_id"].as_string() == statement.id,
        entry["period_id"].as_string() == period.id, entry["revision"].as_integer() == statement.revision,
        entry["contract_id"].as_string() == statement.contract_id, entry["unit_id"].as_string() == statement.unit_id,
        entry["property_id"].as_string() == period.property_id,
        entry["source_statement_id"].as_string().is_not_distinct_from(statement.source_statement_id))
    legacy = block.as_string().is_(None)
    if tenant_id is not None:
        original = and_(original, entry["tenant_id"].as_string() == tenant_id)
        legacy = and_(legacy, statement.contract_id.in_(select(ContractORM.id).where(ContractORM.tenant_id == tenant_id)))
    return and_(statement.status.in_(IMMUTABLE), period.status.in_(IMMUTABLE),
        statement.revision == period.revision_number, statement.snapshot_hash.regexp_match(r"^[0-9a-f]{64}$"),
        or_(legacy, original))


def _lineage(case, period):
    # IDs alone keep UNION DISTINCT finite even for independently damaged
    # source cycles. Actual increasing revisions additionally reject each cycle.
    lineage = select(Statement.id).where(Statement.id == case.statement_id).cte("dispute_statement_lineage", recursive=True)
    parent = Statement.__table__.alias("source_statement")
    child_period = Period.__table__.alias("correction_period")
    edge = (select(Statement.id).join(lineage, Statement.source_statement_id == lineage.c.id)
        .join(parent, parent.c.id == lineage.c.id).join(child_period, child_period.c.id == Statement.billing_period_id)
        .where(Statement.contract_id == case.contract_id, Statement.unit_id == case.unit_id,
            child_period.c.property_id == case.property_id, child_period.c.source_period_id == parent.c.billing_period_id,
            child_period.c.start_date == period.start_date, child_period.c.end_date == period.end_date,
            Statement.revision > parent.c.revision, _sql_valid(Statement, child_period.c, case.tenant_id)))
    return lineage.union(edge)


def _sql_rows(store, query, period, case, unit_id, contract_id, after, *, selected=False):
    entry, block, schema = _frozen_columns(Statement, Period)
    statement = select(*(getattr(Statement, name) for name in FIELDS), Statement.source_statement_id,
        Period.id.label("period_id"), Period.label.label("period_label"), Period.property_id,
        Period.status.label("period_status"), Period.revision_number, schema.label("party_schema"),
        block.as_string().is_not(None).label("party_present"), entry.label("original_party"))
    statement = statement.join(Period, Period.id == Statement.billing_period_id).where(_sql_valid(Statement, Period, case.tenant_id if case else None))
    if case:
        lineage = _lineage(case, period)
        statement = statement.where(Statement.id.in_(select(lineage.c.id)), Statement.id != case.statement_id)
    else:
        statement = statement.where(Statement.billing_period_id == period.id)
    statement = statement.where(Period.property_id == period.property_id)
    if unit_id:
        statement = statement.where(Statement.unit_id == unit_id)
    if contract_id:
        statement = statement.where(Statement.contract_id == contract_id)
    subject = sql_case((block.as_string().is_not(None), entry["identity"]["full_name"].as_string()), else_=literal("Einheit ") + Statement.unit_id)
    label = Period.label + literal(" · Fassung ") + Statement.revision.cast(Period.label.type) + literal(" · ") + subject
    if selected:
        statement = statement.where(Statement.id == query.selected_id).limit(1)
    else:
        if query.search:
            ensure_sqlite_casefold(store.db)
            escaped = query.search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            strings = [getattr(Statement, name) for name in ("id", "billing_period_id", "contract_id", "unit_id", "snapshot_hash", "status")]
            strings += [label, entry["identity"]["full_name"].as_string(), sql_case((block.as_string().is_not(None), FROZEN_BINDING), else_=None)]
            statement = statement.where(or_(*(UnicodeCasefold(column).like(f"%{escaped}%", escape="\\") for column in strings)))
        identifier = bytewise_id(Statement.id)
        if after is not None:
            statement = statement.where(identifier < after)
        statement = statement.order_by(identifier.desc()).limit(query.page_size + 1)
    choices = []
    for row in store.db.execute(statement).mappings():
        values = dict(row)
        root = {"id": values["period_id"], "label": values["period_label"], "property_id": values["property_id"],
            "status": values["period_status"], "revision_number": values["revision_number"], "owner_cost_share": None}
        if values["party_present"]:
            root["owner_cost_share"] = {KEY: {"schema_version": values["party_schema"], "statements": {values["id"]: values["original_party"]}}}
        choices.append(_choice(values, root))
    return choices


def _memory_valid(store, statement, period, tenant_id=None):
    if (not hasattr(store, "db") and (not memory_visible(store, "utility_statements", statement) or not memory_visible(store, "billing_periods", period))
            or statement.status not in IMMUTABLE or period.status not in IMMUTABLE or statement.revision != period.revision_number
            or not re.fullmatch(r"[0-9a-f]{64}", statement.snapshot_hash or "")):
        return False
    original = party(statement, period)
    return tenant_id is None or (original.tenant_id if original is not None else store.get_contract(statement.contract_id).tenant_id) == tenant_id


def _memory_descendant(store, statement, case, period):
    seen = set()
    while statement.id != case.statement_id:
        if statement.id in seen or not statement.source_statement_id:
            return False
        seen.add(statement.id)
        child_period = store.get_billing_period(statement.billing_period_id)
        if (statement.contract_id != case.contract_id or statement.unit_id != case.unit_id
                or child_period.property_id != case.property_id or child_period.start_date != period.start_date
                or child_period.end_date != period.end_date):
            return False
        parent = store.get_utility_statement(statement.source_statement_id)
        if (child_period.source_period_id != parent.billing_period_id or statement.revision <= parent.revision
                or not _memory_valid(store, statement, child_period, case.tenant_id)):
            return False
        statement = parent
    return bool(seen)


def _memory_rows(store, query, period, case, unit_id, contract_id, after, *, selected=False):
    def candidates():
        source = [store.utility_statements.get(query.selected_id)] if selected else store.utility_statements.values()
        for row in source:
            if row is None or not selected and after is not None and row.id >= after:
                continue
            try:
                root = store.get_billing_period(row.billing_period_id)
                if (root.property_id != period.property_id or unit_id and row.unit_id != unit_id
                        or contract_id and row.contract_id != contract_id):
                    continue
                if case:
                    if not _memory_descendant(store, row, case, period):
                        continue
                elif row.billing_period_id != period.id:
                    continue
                if not _memory_valid(store, row, root, case.tenant_id if case else None):
                    continue
                choice = _choice(row.model_dump(mode="json"), root.model_dump(mode="json"))
            except NotFoundError:
                continue
            if not selected and query.search and not any(query.search in value.casefold() for value in choice.values() if isinstance(value, str)):
                continue
            yield choice
    return list(candidates()) if selected else heapq.nlargest(query.page_size + 1, candidates(), key=lambda row: row["id"])


def statement_reference_choices(store, query, actor_id, binding, after, *, resolve_parents):
    try:
        with work(store, actor_id, period_id=query.period_id, case_id=query.dispute_case_id) as (active, case, period, _add):
            prop, unit_id, contract_id = resolve_parents(active, query)
            actual_property = active.get_property(period.property_id)
            if (prop is not None and prop.id != period.property_id
                    or query.portfolio_id and query.portfolio_id != actual_property.portfolio_id):
                raise HTTPException(422, "Auswahlkontext und Immobilien-/Portfoliobindung gehören nicht zusammen.")
            if period.status not in IMMUTABLE:
                raise HTTPException(409, "Bitte eine tatsächlich finalisierte Abrechnungsfassung auswählen.")
            if case:
                if case.statement_id is None:
                    raise HTTPException(422, "Korrekturwahl benötigt die konkrete Einzelabrechnungsakte.")
                original = active.get_utility_statement(case.statement_id)
                frozen = party(original, period)
                tenant_id = frozen.tenant_id if frozen is not None else active.get_contract(original.contract_id).tenant_id
                if (original.billing_period_id != period.id or original.contract_id != case.contract_id or original.unit_id != case.unit_id
                        or not _memory_valid(active, original, period, case.tenant_id) or original.snapshot_hash != case.snapshot_hash
                        or tenant_id != case.tenant_id):
                    raise DisputeIntegrityError("Die Aktenquelle besitzt keine gültige konkrete Originalbindung.")
            read = _sql_rows if hasattr(active, "db") else _memory_rows
            rows = read(active, query, period, case, unit_id, contract_id, after)
            selected = read(active, query, period, case, unit_id, contract_id, None, selected=True) if query.selected_id else []
            more = len(rows) > query.page_size
            items = rows[:query.page_size]
            result = {"items": items, "selected": selected[0] if selected else None, "has_more": more,
                "next_cursor": pack_reference_cursor(binding, items[-1]["id"]) if more else None}
        return result
    except NotFoundError as error:
        raise HTTPException(404, "Die ausgewählte Abrechnungsreferenz ist nicht verfügbar.") from error
    except (DisputeIntegrityError, StatementPartyIntegrityError) as error:
        raise HTTPException(409, str(error)) from error
