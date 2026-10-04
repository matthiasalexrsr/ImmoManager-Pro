"""Exact approved correspondence evidence; private editor work stays opaque.

The caller owns the authorized coherent tenant snapshot. SQL reads are bounded
to the subject before reading JSON; raw existence checks return denial only.
"""

import hashlib
from collections.abc import Iterable
from types import SimpleNamespace
from typing import Any, NoReturn

from fastapi import HTTPException
from sqlalchemy import and_, exists, or_, select

from ..db.contract_correspondence_models import (
    CorrespondenceCommandORM,
    CorrespondenceDraftORM,
    CorrespondenceEventORM,
)
from ..db.contract_wizard_models import ContractTemplateORM
from ..db.orm_models import ContractORM, PropertyORM, UnitORM
from ..models import Contract
from .concurrency import parse_revision
from .contract_correspondence_render import render_text
from .contract_correspondence_types import LetterData
from .contract_correspondence_validation import (
    validate_command,
    validate_draft,
    validate_event,
    validate_event_response,
    validate_review_binding,
)
from .portfolio_scope import scoped_clause
from .tenant_data_graph import TenantExportError
from .tenant_lifecycle_graph import _actor, _bytes, _dump, _hash, _parents, _scope, _visible

OPEN = frozenset({"draft", "reviewed"})
BINDING = ("portfolio_id", "contract_id", "property_id", "unit_id", "tenant_id")
PERSONAL_FIELDS = {
    "contract_correspondence_drafts": ["recipient", "approved body", "reviewed source names", "actor_id"],
    "contract_correspondence_commands": ["frozen approval and manual observation results", "actor_id"],
    "contract_correspondence_events": ["manual reference and note", "actor_id"],
}


def _invalid() -> NoReturn:
    raise TenantExportError("Invalid correspondence evidence; no partial tenant export")


def _parent_context(store, contracts):
    """Minimal current bindings, kept private rather than added to the export."""
    db = getattr(store, "db", None)
    context = []
    for model, key, columns in (
        (PropertyORM, "property_id", (PropertyORM.id, PropertyORM.portfolio_id)),
        (UnitORM, "unit_id", (UnitORM.id, UnitORM.property_id)),
    ):
        identifiers = sorted({value[key] for value in contracts.values()})
        rows = {}
        if db is None:
            for identifier in identifiers:
                value = getattr(store, "get_property" if key == "property_id" else "get_unit")(identifier)
                rows[identifier] = {column.key: getattr(value, column.key) for column in columns}
        else:
            for start in range(0, len(identifiers), 500):
                query = select(*columns).where(model.id.in_(identifiers[start:start + 500]))
                clause = scoped_clause(model)
                if clause is not None:
                    query = query.where(clause)
                for value in db.connection().execute(query).mappings():
                    rows[value["id"]] = dict(value)
        context.append(rows)
    return context


def _binding(store, row, tenant_id, contracts, *, properties=None, units=None):
    parent = contracts.get(row.contract_id)
    if parent is None or (row.tenant_id, row.property_id, row.unit_id) != (
            tenant_id, parent["property_id"], parent["unit_id"]):
        _invalid()
    prop = store.get_property(row.property_id) if properties is None else SimpleNamespace(**properties[row.property_id])
    unit = store.get_unit(row.unit_id) if units is None else SimpleNamespace(**units[row.unit_id])
    if prop.portfolio_id != row.portfolio_id or unit.property_id != prop.id or not _visible(row.portfolio_id):
        _invalid()


def _complete(store, tenant_id, contracts):
    """Never hide conflicting journal rows behind a normal portfolio filter."""
    db = getattr(store, "db", None)
    d = CorrespondenceDraftORM.__table__
    c, p, u = ContractORM.__table__, PropertyORM.__table__, UnitORM.__table__
    if db is None:
        drafts = store.__dict__.get(CorrespondenceDraftORM.__tablename__, {})
        for row in drafts.values():
            if row.contract_id in contracts or row.tenant_id == tenant_id and _visible(row.portfolio_id):
                _binding(store, row, tenant_id, contracts)
        for model in (CorrespondenceCommandORM, CorrespondenceEventORM):
            for row in store.__dict__.get(model.__tablename__, {}).values():
                parent = drafts.get(row.draft_id)
                if row.contract_id in contracts or parent is not None and parent.contract_id in contracts:
                    if parent is None or (row.portfolio_id, row.contract_id) != (parent.portfolio_id, parent.contract_id):
                        _invalid()
                    if model is CorrespondenceCommandORM and row.operation != "event" and row.actor_id != parent.actor_id:
                        _invalid()
                    if model is CorrespondenceEventORM and (row.document_version_id, row.review_hash) != (
                            parent.document_version_id, parent.review_hash):
                        _invalid()
        return
    parents = _parents(tenant_id)
    subject = or_(d.c.contract_id.in_(parents), and_(d.c.tenant_id == tenant_id, _scope(d.c.portfolio_id)))
    bound = exists(select(1).select_from(c.join(p, p.c.id == c.c.property_id).join(u,
        and_(u.c.id == c.c.unit_id, u.c.property_id == p.c.id))).where(
        c.c.id == d.c.contract_id, c.c.tenant_id == tenant_id, d.c.tenant_id == tenant_id,
        d.c.property_id == c.c.property_id, d.c.unit_id == c.c.unit_id,
        d.c.portfolio_id == p.c.portfolio_id, _scope(p.c.portfolio_id)))
    predicates = [exists(select(1).select_from(d).where(subject, ~bound))]
    for model in (CorrespondenceCommandORM, CorrespondenceEventORM):
        child = model.__table__
        child_subject = or_(child.c.contract_id.in_(parents), child.c.draft_id.in_(select(d.c.id).where(subject)))
        conditions = [d.c.id == child.c.draft_id, d.c.contract_id == child.c.contract_id,
                      d.c.portfolio_id == child.c.portfolio_id]
        if model is CorrespondenceCommandORM:
            conditions.append(or_(child.c.operation == "event", child.c.actor_id == d.c.actor_id))
        else:
            conditions.extend((child.c.document_version_id == d.c.document_version_id, child.c.review_hash == d.c.review_hash))
        parent = exists(select(1).select_from(d).where(*conditions))
        predicates.append(exists(select(1).select_from(child).where(child_subject, ~parent)))
    if db.connection().scalar(select(or_(*predicates))):
        _invalid()


def _rows(store, model, tenant_id):
    db = getattr(store, "db", None)
    if db is None:
        drafts = store.__dict__.get("contract_correspondence_drafts", {})
        selected = {row.id for row in drafts.values() if row.tenant_id == tenant_id and row.state == "approved"
                    and _visible(row.portfolio_id)}
        rows = store.__dict__.get(model.__tablename__, {}).values()
        if model is CorrespondenceDraftORM:
            return iter(sorted((row for row in rows if row.id in selected), key=lambda row: row.id))
        return iter(sorted((row for row in rows if row.draft_id in selected and _visible(row.portfolio_id)
            and (model is CorrespondenceEventORM or row.operation in {"approve", "event"})), key=lambda row: row.id))
    table, draft = model.__table__, CorrespondenceDraftORM.__table__
    statement = select(table)
    if model is not CorrespondenceDraftORM:
        statement = statement.join(draft, draft.c.id == table.c.draft_id)
        if model is CorrespondenceCommandORM:
            statement = statement.where(table.c.operation.in_(("approve", "event")))
    statement = statement.where(draft.c.tenant_id == tenant_id, draft.c.contract_id.in_(_parents(tenant_id)),
        draft.c.state == "approved", _scope(table.c.portfolio_id))
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
        records = sorted((row for row in store.__dict__.get("contract_correspondence_drafts", {}).values()
            if row.contract_id in contracts and row.state in OPEN and _visible(row.portfolio_id)), key=lambda row: row.id)
    else:
        d = CorrespondenceDraftORM.__table__
        # No body, recipient, review, actor or command JSON from private work.
        result = db.execute(select(d.c.id, d.c.revision, d.c.updated_at).where(d.c.tenant_id == tenant_id,
            d.c.contract_id.in_(_parents(tenant_id)), d.c.state.in_(OPEN), _scope(d.c.portfolio_id))
            .order_by(d.c.id).execution_options(yield_per=100)).mappings()
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
        "selection": "exact visible tenant/contract identities",
        "contents": "private recipients, bodies, actors and earlier private command replies excluded"}


def _command_proofs(store, tenant_id, drafts, approvals):
    """Creation/current-review receipts, without earlier private command text."""
    db = getattr(store, "db", None)
    if db is None:
        records = (SimpleNamespace(id=row.id, draft_id=row.draft_id, actor_id=row.actor_id,
            operation=row.operation, command_key=row.command_key, request_hash=row.request_hash,
            review_revision=row.result.get("revision"), review_hash=row.result.get("review_hash"))
            for row in store.__dict__.get("contract_correspondence_commands", {}).values()
            if row.draft_id in drafts and row.operation in {"create", "review"})
    else:
        c, d = CorrespondenceCommandORM.__table__, CorrespondenceDraftORM.__table__
        # Explicit authorized parent/scope predicates avoid an ORM-generated
        # full command-row CTE, including private request/result text.
        result = db.connection().execute(select(c.c.id, c.c.draft_id, c.c.actor_id, c.c.operation, c.c.command_key,
            c.c.request_hash, c.c.result["revision"].as_string().label("review_revision"),
            c.c.result["review_hash"].as_string().label("review_hash"))
            .join(d, d.c.id == c.c.draft_id).where(d.c.tenant_id == tenant_id, d.c.state == "approved",
                d.c.contract_id.in_(_parents(tenant_id)), _scope(c.c.portfolio_id),
                c.c.operation.in_(("create", "review"))).order_by(c.c.id)
            .execution_options(yield_per=100)).mappings()
        records = (SimpleNamespace(**value) for value in result)
    proofs: dict[str, dict[str, list[dict[str, Any]]]] = {
        identifier: {"create": [], "review": []} for identifier in drafts}
    try:
        for row in records:
            draft = drafts[row.draft_id]
            if row.actor_id != draft.actor_id:
                _invalid()
            if row.operation == "create":
                if (row.command_key, row.request_hash) != (draft.create_key, draft.create_hash):
                    _invalid()
                proofs[draft.id]["create"].append({"id": row.id, "request_hash": row.request_hash})
            elif row.review_revision == approvals[draft.id]:
                validate_review_binding(draft, expected_revision=approvals[draft.id],
                    review_revision=row.review_revision, review_hash=row.review_hash)
                proofs[draft.id]["review"].append({"id": row.id, "revision": row.review_revision, "review_hash": row.review_hash})
    finally:
        if db is not None:
            result.close()
    verified = []
    for identifier, value in proofs.items():
        if len(value["create"]) != 1 or len(value["review"]) != 1:
            _invalid()
        verified.append({"draft_id": identifier, "create": value["create"][0], "review": value["review"][0]})
    return sorted(verified, key=lambda value: value["draft_id"])


def _review_shape(store, row, graph):
    review = row.review
    if not isinstance(review, dict) or set(review) != {"data", "source_contract", "source_contract_etag", "source_context",
            "template", "lifecycle", "rendered_body", "pdf_sha256"}:
        _invalid()
    if not isinstance(review["source_contract"], dict) or set(review["source_contract"]) - set(Contract.model_fields):
        _invalid()
    context = review["source_context"]
    if not isinstance(context, dict) or set(context) != {"portfolio_id", "property_etag", "unit_etag", "tenant_etag", "names"}:
        _invalid()
    for name, collection in (("property", "properties"), ("unit", "units"), ("tenant", "tenants")):
        revision = parse_revision(context[name + "_etag"])
        if (revision.collection, revision.entity_id) != (collection, getattr(row, name + "_id")):
            _invalid()
    names = context["names"]
    if not isinstance(names, dict) or set(names) != {"contract_number", "tenant_name", "property_name", "unit_label",
            "start_date", "end_date", "deadline_date", "deadline_basis", "recipient_name", "recipient_address"}:
        _invalid()
    if any(not isinstance(value, str) for value in names.values()):
        _invalid()
    data = LetterData.model_validate(row.data)
    if (data.template_id is not None) != (review["template"] is not None) or (
            data.lifecycle_command_id is not None) != (review["lifecycle"] is not None):
        _invalid()
    source = Contract.model_validate(review["source_contract"])
    if any(names[key] != value for key, value in {
            "contract_number": source.contract_number, "start_date": source.start_date.isoformat(),
            "end_date": source.end_date.isoformat() if source.end_date else "",
            "deadline_date": data.deadline_date.isoformat(), "deadline_basis": data.deadline_basis,
            "recipient_name": data.recipient_name, "recipient_address": data.recipient_address}.items()):
        _invalid()
    template = review["template"]
    body = data.body
    if template is not None:
        if (not isinstance(template, dict) or set(template) != {"id", "root_id", "version", "title", "body_sha256"}
                or template["id"] != data.template_id):
            _invalid()
        db = getattr(store, "db", None)
        selected = db.scalar(select(ContractTemplateORM).where(ContractTemplateORM.id == template["id"])) if db is not None else (
            store.__dict__.get("contract_template_versions", {}).get(template["id"]))
        if selected is None or selected.portfolio_id != row.portfolio_id or template != {
                "id": selected.id, "root_id": selected.root_id, "version": selected.version, "title": selected.title,
                "body_sha256": _hash(selected.body)}:
            _invalid()
        body = selected.body
    if not isinstance(body, str) or render_text(body, names) != review["rendered_body"]:
        _invalid()
    linked = review["lifecycle"]
    if linked is not None:
        if (not isinstance(linked, dict) or set(linked) != {"command_id", "draft_id", "review_hash", "result_hash", "current_state"}
                or linked["command_id"] != data.lifecycle_command_id
                or linked["current_state"] not in {"confirmed", "pending_effective", "completed"}):
            _invalid()
        command = next((value for value in graph["contract_lifecycle_commands"] if value["id"] == linked["command_id"]), None)
        draft = next((value for value in graph["contract_lifecycle_drafts"] if value["id"] == linked["draft_id"]), None)
        if command is None or draft is None or command["operation"] not in {"confirm", "finalize"} or any(
                draft[key] != getattr(row, key) for key in BINDING) or command["draft_id"] != draft["id"] or (
                linked["review_hash"], linked["result_hash"]) != (draft["review_hash"], _hash(command["result"])):
            _invalid()


def append_correspondence_graph(store, graph):
    try:
        tenant_id = graph["tenant"]["id"]
        contracts = {value["id"]: value for value in graph["contracts"]}
        properties, units = _parent_context(store, contracts)
        _complete(store, tenant_id, contracts)
        versions = {value["id"]: value for value in graph["document_versions"]}
        documents = {value["id"]: value for value in graph["documents"]}
        drafts, counts = {}, {}
        for row in _rows(store, CorrespondenceDraftORM, tenant_id):
            _actor(row.actor_id)
            _binding(store, row, tenant_id, contracts, properties=properties, units=units)
            validate_draft(row)
            _review_shape(store, row, graph)
            original = versions.get(row.document_version_id)
            if row.document_id not in documents or original is None or any(original[key] != getattr(row, key) for key in BINDING) or (
                    original["document_id"], original["number"], original["operation"], original["sha256"], original["actor_id"]) != (
                    row.document_id, 1, "archive_original", row.review["pdf_sha256"], row.actor_id):
                _invalid()
            drafts[row.id], counts[row.id] = row, {"approve": 0, "event": 0}
        events = {}
        for row in _rows(store, CorrespondenceEventORM, tenant_id):
            _actor(row.actor_id)
            events[row.id] = row
        by_draft: dict[str, list[int]] = {}
        for row in events.values():
            draft = drafts.get(row.draft_id)
            if draft is None:
                _invalid()
            dispatch = events.get(row.data.get("dispatch_event_id"))
            validate_event(row, draft, dispatch)
            by_draft.setdefault(draft.id, []).append(row.event_revision)
        for revisions in by_draft.values():
            if sorted(revisions) != list(range(1, len(revisions) + 1)):
                _invalid()
        commands, approvals = [], {}
        result_fields = {"id", *BINDING, "actor_id", "revision", "state", "data", "source_contract_etag", "review", "review_hash",
                         "document_id", "document_version_id", "created_at", "approved_at", "persistent", "delivery_policy", "download_url"}
        for row in _rows(store, CorrespondenceCommandORM, tenant_id):
            _actor(row.actor_id)
            draft = drafts.get(row.draft_id)
            if draft is None:
                _invalid()
            validate_command(row, draft)
            if set(row.result) != result_fields | ({"event"} if row.operation == "event" else set()):
                _invalid()
            if row.operation == "event":
                event = events.get(row.result["event"]["id"])
                if event is None:
                    _invalid()
                validate_event_response(row, event)
            else:
                approvals[draft.id] = row.request["expected_revision"]
            counts[draft.id][row.operation] += 1
            value = _dump(row, CorrespondenceCommandORM)
            value["source_sha256"] = _hash(value)
            commands.append(value)
        for draft in drafts.values():
            if counts[draft.id] != {"approve": 1, "event": len(by_draft.get(draft.id, []))}:
                _invalid()
        proofs = _command_proofs(store, tenant_id, drafts, approvals)
        values = []
        for mapping, model in ((drafts, CorrespondenceDraftORM), (events, CorrespondenceEventORM)):
            current = []
            for row in mapping.values():
                value = _dump(row, model)
                value["source_sha256"] = _hash(value)
                current.append(value)
            values.append(current)
        graph["contract_correspondence_drafts"], graph["contract_correspondence_commands"], graph["contract_correspondence_events"] = (
            values[0], commands, values[1])
        private = _private(store, tenant_id, contracts)
        graph["scope"]["private_correspondence_drafts"] = private
        graph["scope"]["contract_correspondence"] = {
            "selection": "exact stored tenant/contract/parent identities; approved evidence and manual observations only",
            "retention": "immutable recipients, source names, letters and observations retained by profile-only anonymization",
            "delivery_policy": "manual_observation_only",
            "originals": "exact verified DocumentVersion originals included in document_version_contents",
            "command_proofs": proofs,
            "source_sha256": _hash([values[0], commands, values[1], private, proofs]),
            "private_work": "open drafts and create/edit/review command bodies excluded",
        }
        if drafts:
            graph["schema_version"] = "tenant-data-graph/6"
        return graph
    except TenantExportError:
        raise
    except Exception as error:
        raise TenantExportError("Correspondence privacy export failed; no partial export") from error


def require_complete_subject_scope(store, tenant_id):
    from .portfolio_scope import current_scope
    captured = current_scope()
    if captured is None or captured.unrestricted:
        return
    db = getattr(store, "db", None)
    if db is None:
        hidden = any(row.tenant_id == tenant_id and not _visible(row.portfolio_id)
                     for row in store.__dict__.get("contract_correspondence_drafts", {}).values())
    else:
        table = CorrespondenceDraftORM.__table__
        hidden = db.connection().scalar(select(exists(select(1).select_from(table).where(table.c.tenant_id == tenant_id,
            or_(table.c.portfolio_id.is_(None), table.c.portfolio_id.not_in(captured.portfolio_ids))))))
    if hidden:
        raise HTTPException(403, "Korrespondenz dieses Mieters betrifft weitere Portfolios. "
                            "Anonymisierung benötigt Zugriff auf alle verbundenen Portfolios.")
