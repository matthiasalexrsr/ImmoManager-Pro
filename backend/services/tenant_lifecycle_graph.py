"""Exact tenant lifecycle evidence, excluding private pre-confirmation work.

The caller owns a coherent authorized snapshot. Core existence checks disclose
only a denial for that already authorized subject; private JSON is never read.
"""

import hashlib
import json
from collections.abc import Iterable
from datetime import date, datetime
from types import SimpleNamespace
from typing import Any, NoReturn

from fastapi import HTTPException
from sqlalchemy import exists, or_, select

from ..db.contract_lifecycle_models import ContractLifecycleCommandORM, ContractLifecycleDraftORM
from ..db.orm_models import ContractORM, PropertyORM, UnitORM
from ..models import Contract, ContractCreate
from .concurrency import parse_revision
from .contract_lifecycle_validation import (
    FINAL,
    validate_command_evidence,
    validate_draft_evidence,
    validate_supersession_evidence,
)
from .portfolio_scope import current_scope
from .tenant_data_graph import TenantExportError

PERSONAL_FIELDS = {
    "contract_lifecycle_drafts": ["data.reason", "review.source_contract", "review.obligations"],
    "contract_lifecycle_commands": ["result.data.reason", "result.review", "actor_id"],
}
OPEN = frozenset({"draft", "reviewed"})


def _json(value):
    return json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False,
        default=lambda item: item.isoformat() if isinstance(item, (date, datetime)) else _invalid()))


def _invalid() -> NoReturn:
    raise TenantExportError("Invalid lifecycle evidence; no partial tenant export")


def _bytes(value):
    return json.dumps(_json(value), sort_keys=True, ensure_ascii=False, allow_nan=False,
                      separators=(",", ":")).encode("utf-8")


def _hash(value):
    checksum = hashlib.sha256()
    encoder = json.JSONEncoder(sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    for fragment in encoder.iterencode(value):
        for start in range(0, len(fragment), 16 * 1024):
            checksum.update(fragment[start:start + 16 * 1024].encode("utf-8"))
    return checksum.hexdigest()


def _dump(row, model):
    return _json({column.name: getattr(row, column.name) for column in model.__table__.columns})


def _actor(identifier):
    if (not isinstance(identifier, str) or not identifier or identifier.strip() != identifier
            or any(ord(character) < 32 for character in identifier)):
        _invalid()


def _review_shape(review):
    """Do not copy unexpected opaque JSON as a purported tenant relationship."""
    expected = {"source_contract", "source_contract_etag", "related_etags", "proposed_contract", "data",
                "obligations", "supersedes", "date_policy", "notice_policy"}
    if not isinstance(review, dict) or set(review) != expected:
        _invalid()
    source = review["source_contract"]
    if not isinstance(source, dict) or set(source) - set(Contract.model_fields):
        _invalid()
    related = review["related_etags"]
    if not isinstance(related, dict) or set(related) != {"property", "unit", "tenant"}:
        _invalid()
    for name, collection in (("property", "properties"), ("unit", "units"), ("tenant", "tenants")):
        revision = parse_revision(related[name])
        if (revision.collection, revision.entity_id) != (collection, source[name + "_id"]):
            _invalid()
    proposed = review["proposed_contract"]
    allowed = set(ContractCreate.model_fields) if review["data"]["operation"] == "renewal" else {"end_date", "status_policy"}
    if not isinstance(proposed, dict) or set(proposed) - allowed:
        _invalid()
    if review["data"]["operation"] == "renewal":
        successor = ContractCreate.model_validate(proposed)
        if any(getattr(successor, key) != source[key] for key in ("property_id", "unit_id", "tenant_id")):
            _invalid()
        if (successor.contract_number, successor.start_date.isoformat(), successor.status) != (
                review["data"]["new_contract_number"], review["data"]["new_start_date"], "active"):
            _invalid()
        if (successor.end_date.isoformat() if successor.end_date else None) != review["data"]["new_end_date"]:
            _invalid()
    elif proposed != {"end_date": review["data"]["termination_end_date"], "status_policy": "active_through_inclusive_end"}:
        _invalid()
    obligation_keys = {"rent_charge_count", "receivable_count", "receivables_due_after_end_count",
        "receivables_due_after_end_sample", "rent_period_conflict_count", "rent_period_conflict_sample",
        "policy", "snapshot_sha256"}
    obligations = review["obligations"]
    if not isinstance(obligations, dict) or set(obligations) != obligation_keys:
        _invalid()
    for name, fields in (("rent_period_conflict_sample", {"id", "month"}),
                        ("receivables_due_after_end_sample", {"id", "due_date", "description", "amount_due", "amount_paid"})):
        if not isinstance(obligations[name], list) or any(not isinstance(item, dict) or set(item) != fields for item in obligations[name]):
            _invalid()
    previous = review["supersedes"]
    if previous is not None and (not isinstance(previous, dict) or set(previous) != {"id", "termination_end_date", "review_hash"}):
        _invalid()


def _chain(drafts, contracts):
    for row in drafts.values():
        previous_id, next_id = row.supersedes_draft_id, row.superseded_by_draft_id
        if previous_id is not None:
            previous = drafts.get(previous_id)
            if previous is None:
                _invalid()
            validate_supersession_evidence(row, previous)
        if next_id is not None:
            next_row = drafts.get(next_id)
            if next_row is None or next_row.supersedes_draft_id != row.id:
                _invalid()
        if row.data["operation"] == "termination" and row.state != "superseded":
            current = contracts[row.contract_id]
            expected_status = "active" if row.state == "pending_effective" else "terminated"
            if (current["end_date"], current["status"]) != (row.data["termination_end_date"], expected_status):
                _invalid()


def _scope(column):
    captured = current_scope()
    return column.in_(captured.portfolio_ids) if captured is not None and not captured.unrestricted else True


def _parents(tenant_id):
    c, p = ContractORM.__table__, PropertyORM.__table__
    return select(c.c.id).join(p, p.c.id == c.c.property_id).where(
        c.c.tenant_id == tenant_id, _scope(p.c.portfolio_id))


def _complete(store, tenant_id, contracts):
    """Reject hidden/corrupt rows for this visible subject before reading JSON."""
    db = getattr(store, "db", None)
    if db is None:
        for row in store.__dict__.get("contract_lifecycle_drafts", {}).values():
            visible = row.contract_id in contracts or (row.tenant_id == tenant_id and _visible(row.portfolio_id))
            if visible:
                _binding(store, row, tenant_id, contracts)
        for row in store.__dict__.get("contract_lifecycle_commands", {}).values():
            draft = store.__dict__.get("contract_lifecycle_drafts", {}).get(row.draft_id)
            if row.contract_id in contracts or draft is not None and draft.contract_id in contracts:
                if (draft is None or (row.portfolio_id, row.contract_id) != (draft.portfolio_id, draft.contract_id)
                        or row.operation != "finalize" and row.actor_id != draft.actor_id):
                    _invalid()
        return
    d, j = ContractLifecycleDraftORM.__table__, ContractLifecycleCommandORM.__table__
    c, p, u = ContractORM.__table__, PropertyORM.__table__, UnitORM.__table__
    parents = _parents(tenant_id)
    subject = or_(d.c.contract_id.in_(parents), (d.c.tenant_id == tenant_id) & _scope(d.c.portfolio_id))
    bound = exists(select(1).select_from(c.join(p, p.c.id == c.c.property_id).join(u,
        (u.c.id == c.c.unit_id) & (u.c.property_id == p.c.id))).where(
        c.c.id == d.c.contract_id, c.c.tenant_id == tenant_id, d.c.tenant_id == tenant_id,
        d.c.property_id == c.c.property_id, d.c.unit_id == c.c.unit_id,
        d.c.portfolio_id == p.c.portfolio_id, _scope(p.c.portfolio_id)))
    bad_draft = exists(select(1).select_from(d).where(subject, ~bound))
    command_subject = or_(j.c.contract_id.in_(parents), j.c.draft_id.in_(select(d.c.id).where(subject)))
    command_parent = exists(select(1).select_from(d).where(
        d.c.id == j.c.draft_id, d.c.contract_id == j.c.contract_id, d.c.portfolio_id == j.c.portfolio_id,
        or_(j.c.operation == "finalize", j.c.actor_id == d.c.actor_id)))
    if db.connection().scalar(select(or_(bad_draft,
            exists(select(1).select_from(j).where(command_subject, ~command_parent))))):
        _invalid()


def _visible(portfolio_id):
    captured = current_scope()
    return captured is None or captured.unrestricted or portfolio_id in captured.portfolio_ids


def _binding(store, row, tenant_id, contracts):
    contract = contracts.get(row.contract_id)
    if contract is None or (row.tenant_id, row.property_id, row.unit_id) != (
            tenant_id, contract["property_id"], contract["unit_id"]):
        _invalid()
    prop, unit = store.get_property(row.property_id), store.get_unit(row.unit_id)
    if prop.portfolio_id != row.portfolio_id or unit.property_id != prop.id or not _visible(row.portfolio_id):
        _invalid()


def _rows(store, model, tenant_id, states=None):
    db = getattr(store, "db", None)
    if db is None:
        rows = store.__dict__.get(model.__tablename__, {}).values()
        if model is ContractLifecycleDraftORM:
            return iter(sorted((row for row in rows if row.tenant_id == tenant_id and _visible(row.portfolio_id)
                                and row.state in states), key=lambda row: row.id))
        accepted = store.__dict__.get("contract_lifecycle_drafts", {})
        return iter(sorted((row for row in rows if row.operation in {"confirm", "finalize"}
            and row.draft_id in accepted and accepted[row.draft_id].tenant_id == tenant_id
            and accepted[row.draft_id].state in FINAL and _visible(row.portfolio_id)), key=lambda row: row.id))
    table = model.__table__
    if model is ContractLifecycleDraftORM:
        statement = select(table).where(table.c.tenant_id == tenant_id,
            table.c.contract_id.in_(_parents(tenant_id)), table.c.state.in_(states), _scope(table.c.portfolio_id))
    else:
        draft = ContractLifecycleDraftORM.__table__
        statement = select(table).join(draft, draft.c.id == table.c.draft_id).where(
            draft.c.tenant_id == tenant_id, draft.c.contract_id.in_(_parents(tenant_id)),
            draft.c.state.in_(FINAL), table.c.operation.in_(("confirm", "finalize")), _scope(table.c.portfolio_id))
    result = db.execute(statement.order_by(table.c.id).execution_options(yield_per=100)).mappings()
    def records():
        try:
            for values in result:
                yield SimpleNamespace(**values)
        finally:
            result.close()
    return records()


def _private(store, tenant_id, contracts):
    checksum, count = hashlib.sha256(), 0
    db = getattr(store, "db", None)
    records: Iterable[Any]
    if db is None:
        records = (row for row in store.__dict__.get("contract_lifecycle_drafts", {}).values()
                   if row.contract_id in contracts and row.state in OPEN and _visible(row.portfolio_id))
        records = sorted(records, key=lambda row: row.id)
    else:
        d = ContractLifecycleDraftORM.__table__
        # Never SELECT data/review, actor identities, reasons or command JSON.
        result = db.execute(select(d.c.id, d.c.revision, d.c.updated_at).where(
            d.c.tenant_id == tenant_id, d.c.contract_id.in_(_parents(tenant_id)),
            d.c.state.in_(OPEN), _scope(d.c.portfolio_id)).order_by(d.c.id)
            .execution_options(yield_per=100)).mappings()
        records = (SimpleNamespace(**row) for row in result)
    try:
        for row in records:
            checksum.update(_bytes([row.id, row.revision, row.updated_at]))
            checksum.update(b"\n")
            count += 1
    finally:
        if db is not None:
            result.close()
    return {"count": count, "revision_digest": checksum.hexdigest(), "contents_exported": False,
        "selection": "exact visible tenant/contract identities; no inferred free-text references",
        "contents": "private pre-confirmation work retained; only opaque counts and revision digest included"}


def _creation_proofs(store, tenant_id, drafts):
    counts = dict.fromkeys(drafts, 0)
    db = getattr(store, "db", None)
    if db is None:
        records = (row for row in store.__dict__.get("contract_lifecycle_commands", {}).values()
                   if row.draft_id in drafts and row.operation == "create")
    else:
        j, d = ContractLifecycleCommandORM.__table__, ContractLifecycleDraftORM.__table__
        fields = ("draft_id", "actor_id", "command_key", "request_hash")
        result = db.execute(select(*(j.c[key] for key in fields)).join(d, d.c.id == j.c.draft_id).where(
            d.c.tenant_id == tenant_id, d.c.contract_id.in_(_parents(tenant_id)), d.c.state.in_(FINAL),
            j.c.operation == "create", _scope(j.c.portfolio_id)).execution_options(yield_per=100)).mappings()
        records = (SimpleNamespace(**row) for row in result)
    try:
        for record in records:
            row = drafts.get(record.draft_id)
            if row is None or (record.actor_id, record.command_key, record.request_hash) != (
                    row.actor_id, row.create_key, row.create_hash):
                _invalid()
            counts[row.id] += 1
        if any(value != 1 for value in counts.values()):
            _invalid()
    finally:
        if db is not None:
            result.close()


def append_lifecycle_graph(store, graph):
    try:
        tenant_id = graph["tenant"]["id"]
        contracts = {row["id"]: row for row in graph["contracts"]}
        _complete(store, tenant_id, contracts)
        drafts, commands, counts = {}, [], {}
        for row in _rows(store, ContractLifecycleDraftORM, tenant_id, FINAL):
            _actor(row.actor_id)
            _binding(store, row, tenant_id, contracts)
            validate_draft_evidence(row)
            _review_shape(row.review)
            # No new party can be inferred or fetched from opaque historical JSON.
            if row.successor_contract_id is not None:
                successor = contracts.get(row.successor_contract_id)
                if successor is None or any(successor[field] != getattr(row, field)
                        for field in ("property_id", "unit_id", "tenant_id")):
                    _invalid()
            drafts[row.id] = row
            counts[row.id] = {"confirm": 0, "finalize": 0}
        _chain(drafts, contracts)
        _creation_proofs(store, tenant_id, drafts)
        draft_values = []
        for row in drafts.values():
            value = _dump(row, ContractLifecycleDraftORM)
            value["source_sha256"] = _hash(value)
            draft_values.append(value)
        for row in _rows(store, ContractLifecycleCommandORM, tenant_id):
            _actor(row.actor_id)
            draft = drafts.get(row.draft_id)
            if draft is None:
                _invalid()
            validate_command_evidence(row, draft)
            allowed_result = {column.name for column in ContractLifecycleDraftORM.__table__.columns} - {"create_key", "create_hash"}
            if set(row.result) - (allowed_result | {"persistent"}):
                _invalid()
            _review_shape(row.result["review"])
            counts[draft.id][row.operation] += 1
            value = _dump(row, ContractLifecycleCommandORM)
            value["source_sha256"] = _hash(value)
            commands.append(value)
        for row in drafts.values():
            if counts[row.id] != {"confirm": 1, "finalize": int(row.finalized_contract_etag is not None)}:
                _invalid()
        graph["contract_lifecycle_drafts"], graph["contract_lifecycle_commands"] = draft_values, commands
        private = _private(store, tenant_id, contracts)
        graph["scope"]["private_lifecycle_drafts"] = private
        graph["scope"]["contract_lifecycle"] = {
            "selection": "exact stored tenant/contract/location/actor bindings; confirmed results only",
            "retention": "immutable accepted evidence retained by profile-only anonymization",
            "source_sha256": _hash([draft_values, commands, private]),
            "private_work": "open drafts and earlier create/edit/review commands excluded",
        }
        if draft_values:
            graph["schema_version"] = "tenant-data-graph/5"
        return graph
    except TenantExportError:
        raise
    except Exception as error:
        raise TenantExportError("Lifecycle privacy export failed; no partial export") from error


def require_complete_subject_scope(store, tenant_id):
    captured = current_scope()
    if captured is None or captured.unrestricted:
        return
    db = getattr(store, "db", None)
    if db is None:
        hidden = any(row.tenant_id == tenant_id and not _visible(row.portfolio_id)
                     for row in store.__dict__.get("contract_lifecycle_drafts", {}).values())
    else:
        d = ContractLifecycleDraftORM.__table__
        hidden = db.connection().scalar(select(exists(select(1).select_from(d).where(
            d.c.tenant_id == tenant_id, or_(d.c.portfolio_id.is_(None), d.c.portfolio_id.not_in(captured.portfolio_ids))))))
    if hidden:
        raise HTTPException(403, "Vertragsvorgänge dieses Mieters betreffen weitere Portfolios. "
                            "Anonymisierung benötigt Zugriff auf alle verbundenen Portfolios.")
