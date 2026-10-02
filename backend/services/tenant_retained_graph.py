"""Exact retained subject projections; caller owns one authorized snapshot."""

from copy import deepcopy
from datetime import date, datetime, timedelta
from types import SimpleNamespace
from typing import Any

from fastapi import HTTPException
from sqlalchemy import and_, exists, inspect, or_, select

from ..db.contract_correspondence_models import CorrespondenceDraftORM
from ..db.document_version_models import DocumentVersionORM
from ..db.operational_job_models import OperationalJobLaneORM, OperationalJobORM, OperationalWorkItemORM
from ..db.operational_models import OperationalDispatchORM, OperationalOccurrenceORM
from ..db.orm_models import (
    ContractORM,
    HandoverProtocolORM,
    MeterReadingORM,
    PropertyORM,
    ReceivableORM,
    RentChargeORM,
    TaskORM,
)
from ..db.tenancy_workflow_models import (
    TENANCY_WORKFLOW_MODELS,
    TenancyChangeORM,
    WorkflowCommandORM,
    WorkflowEvidenceLinkORM,
    WorkflowStepInstanceORM,
    WorkflowTemplateORM,
    WorkflowTemplateStepORM,
    WorkflowTemplateVersionORM,
)
from .portfolio_scope import current_scope
from .tenancy_workflow_types import TemplateStepInput
from .tenancy_workflow_validation import OPERATIONS, _date, _digest, _hex, _stamp
from .tenant_data_graph import TenantExportError

PERSONAL_FIELDS = {
    "tenancy_workflow_templates": ["creator of the subject's used workflow template"],
    "tenancy_workflow_template_versions": ["retained version creator and provenance"],
    "tenancy_workflow_template_steps": ["subject-context template title, description and assignment"],
    "tenancy_changes": ["historical subject contract snapshot", "created_by"],
    "tenancy_workflow_step_instances": ["title_snapshot", "description_snapshot", "not_applicable_reason", "assignee_user_id", "completed_by"],
    "tenancy_workflow_evidence_links": ["original subject witness identities", "created_by"],
    "tenancy_workflow_commands": ["subject-projected historical responses", "actor_id"],
    "operational_work_items": ["subject source/effect references and execution facts"],
}
WORKFLOW = {model.__tablename__: model for model in TENANCY_WORKFLOW_MODELS}
JOBS = {model.__tablename__: model for model in (OperationalJobORM, OperationalJobLaneORM, OperationalWorkItemORM)}
ROLE_KEYS = {"move_out": "previous_contract", "move_in": "next_contract"}
STEP_STABLE = ("id", "tenancy_change_id", "template_step_key", "direction", "title_snapshot", "description_snapshot",
               "requirement", "anchor", "offset_days", "original_due_date", "assignee_user_id", "assignee_role")
CHANGE_STABLE = ("id", "portfolio_id", "property_id", "unit_id", "previous_contract_id", "next_contract_id", "mode",
                 "move_out_template_version_id", "move_in_template_version_id", "created_by", "created_at", "snapshot_sha256")
STEP_RESPONSE_FIELDS = set(STEP_STABLE) | {"not_applicable_reason", "due_date", "state", "blocked_by_step_ids", "task_id",
    "completed_at", "completed_by", "evidence_links", "revision", "etag", "actions"}
CHANGE_RESPONSE_FIELDS = set(CHANGE_STABLE) | {"move_out_handover_date", "move_in_handover_date", "state", "revision",
    "etag", "updated_at", "steps", "actions"}
VERSION_RESPONSE_FIELDS = {"id", "template_id", "portfolio_id", "property_id", "unit_id", "direction", "version", "state",
    "based_on_version_id", "revision", "etag", "created_at", "published_at", "steps", "actions"}


def _require(value):
    if not value:
        raise TenantExportError("Invalid retained subject evidence; no partial export")


def _json(value):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {key: _json(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json(item) for item in value]
    return value


def _value(row, model):
    return _json({column.name: deepcopy(getattr(row, column.name)) for column in model.__table__.columns})


def _visible(portfolio_id):
    scope = current_scope()
    return scope is None or scope.unrestricted or portfolio_id in scope.portfolio_ids


def _scope(column):
    scope = current_scope()
    return True if scope is None or scope.unrestricted else column.in_(scope.portfolio_ids)


def _rows(store, model, predicate, memory, *, columns=None):
    if getattr(store, "db", None) is None:
        selected = sorted((row for row in store.__dict__.get(model.__tablename__, {}).values() if memory(row)), key=lambda row: row.id)
        return iter(selected if columns is None else (SimpleNamespace(**{key: getattr(row, key) for key in columns}) for row in selected))
    table = model.__table__
    fields = list(table.c) if columns is None else [table.c[key] for key in columns]
    result = store.db.connection().execute(select(*fields).where(predicate).order_by(table.c.id)
                                         .execution_options(yield_per=500)).mappings()

    def records():
        try:
            for values in result:
                yield SimpleNamespace(**values)
        finally:
            result.close()
    return records()


def _one(store, model, identifier):
    rows = list(_rows(store, model, model.id == identifier, lambda row: row.id == identifier))
    _require(len(rows) == 1)
    return rows[0]


def _effect(store, model, key):
    if getattr(store, "db", None) is None:
        collection = "occurrences" if model is OperationalOccurrenceORM else "dispatches"
        row = store.__dict__.get("_operational_state", {}).get(collection, {}).get(key)
        _require(row is not None)
        return row
    fields = ("target_id", "target_kind", "schedule_id") if model is OperationalOccurrenceORM else ("notification_id", "entity_id", "entity_type")
    table = model.__table__
    rows = store.db.connection().execute(select(*(table.c[name] for name in fields)).where(table.c.key == key).limit(2)).mappings().all()
    _require(len(rows) == 1)
    return SimpleNamespace(**rows[0])


def _family(store, models):
    db = getattr(store, "db", None)
    if db is None:
        return any(store.__dict__.get(name) for name in models)
    names = set(inspect(db.connection()).get_table_names())
    present = set(models) & names
    _require(not present or present == set(models))
    if present:
        for name, model in models.items():
            fields = {column["name"] for column in inspect(db.connection()).get_columns(name)}
            _require(set(model.__table__.c.keys()) <= fields)
    return bool(present)


def _directions(snapshot, tenant_id):
    _require(isinstance(snapshot, dict))
    return {direction for direction, key in ROLE_KEYS.items()
            if isinstance(snapshot.get(key), dict) and snapshot[key].get("tenant_id") == tenant_id}


def _subject(tenant_id):
    snapshot = TenancyChangeORM.__table__.c.snapshot
    return or_(*(snapshot[key]["tenant_id"].as_string() == tenant_id for key in ROLE_KEYS.values()))


def _binding(store, change):
    _require(_visible(change.portfolio_id))
    prop = store.get_property(change.property_id)
    unit = store.get_unit(change.unit_id)
    _require(prop.portfolio_id == change.portfolio_id and unit.property_id == change.property_id)
    _require(_hex(change.snapshot_sha256) and _digest(change.snapshot) == change.snapshot_sha256)
    _require(change.snapshot.get("schema") == "tenancy-change-snapshot-v1")
    _require(set(change.snapshot) == {"schema", "portfolio_id", "property_id", "unit_id", "mode", "move_out_handover_date",
                                    "move_in_handover_date", "previous_contract", "next_contract", "templates"})
    for key in ("portfolio_id", "property_id", "unit_id", "mode"):
        _require(change.snapshot[key] == getattr(change, key))
    for direction, key in ROLE_KEYS.items():
        source = change.snapshot.get(key)
        _require((source is None) == (getattr(change, key + "_id") is None))
        if source is not None:
            _require(set(source) == {"id", "contract_number", "property_id", "unit_id", "tenant_id", "start_date", "end_date", "status", "updated_at", "etag"})
            _require(source["id"] == getattr(change, key + "_id") and source["property_id"] == change.property_id
                     and source["unit_id"] == change.unit_id)
            # Presence proves the retained source identity. Its live party may
            # legitimately differ; never export that corrected counterpart.
            _one(store, ContractORM, source["id"])


def _witness(store, row, change, step):
    source = change.snapshot[ROLE_KEYS[step.direction]]
    shape = tuple(getattr(row, name) is not None for name in ("document_id", "document_version_id", "handover_protocol_id", "meter_reading_id"))
    _require(shape == {"document_version": (True, True, False, False), "handover_protocol": (False, False, True, False),
                       "meter_reading": (False, False, False, True)}.get(row.kind))
    if row.kind == "document_version":
        version = _one(store, DocumentVersionORM, row.document_version_id)
        _require((version.document_id, version.portfolio_id, version.property_id, version.unit_id, version.contract_id, version.tenant_id) ==
                 (row.document_id, change.portfolio_id, change.property_id, change.unit_id, source["id"], source["tenant_id"]))
        payload = {"kind": row.kind, "document_id": row.document_id, "document_version_id": version.id, "sha256": version.sha256,
                   "number": version.number, "contract_id": source["id"], "tenant_id": source["tenant_id"]}
    else:
        reading = _one(store, MeterReadingORM, row.meter_reading_id) if row.kind == "meter_reading" else None
        protocol = _one(store, HandoverProtocolORM, reading.handover_id if reading else row.handover_protocol_id)
        _require((protocol.status, protocol.contract_id, protocol.unit_id, protocol.protocol_type) ==
                 ("finalized", source["id"], change.unit_id, step.direction))
        base = {"id": protocol.id, "contract_id": protocol.contract_id, "unit_id": protocol.unit_id,
                "protocol_type": protocol.protocol_type, "status": protocol.status, "updated_at": _stamp(protocol.updated_at)}
        payload = ({"kind": row.kind, "id": reading.id, "handover_id": reading.handover_id, "meter_type": reading.meter_type,
                    "meter_number": reading.meter_number, "reading_value": reading.reading_value, "unit": reading.unit,
                    "created_at": _stamp(reading.created_at), "protocol_snapshot": base} if reading else
                   {"kind": row.kind, **base, "protocol_date": _date(protocol.protocol_date).isoformat()})
    _require(_digest(payload) == row.snapshot_sha256)


def _proof(row, value):
    value["source_sha256"] = _digest(row)
    value["projection_sha256"] = _digest(value)
    return value


def _step_reply(store, change, step, response, step_map):
    _require(isinstance(response, dict) and set(response) == STEP_RESPONSE_FIELDS)
    for field in STEP_STABLE:
        _require(response[field] == _json(getattr(step, field)))
    _require(response["task_id"] in {None, step.task_id})
    _require(isinstance(response["blocked_by_step_ids"], list) and all(
        identifier in step_map and step_map[identifier].direction == step.direction for identifier in response["blocked_by_step_ids"]))
    for link in response["evidence_links"]:
        _require(set(link) == {"id", "kind", "document_id", "document_version_id", "handover_protocol_id", "meter_reading_id", "snapshot_sha256", "created_at"})
        _witness(store, SimpleNamespace(**link), change, step)


def _project_change(value, directions):
    value = deepcopy(value)
    for direction, key in ROLE_KEYS.items():
        if direction not in directions:
            for field in (key + "_id", direction + "_template_version_id", direction + "_handover_date"):
                value.pop(field, None)
            if "snapshot" in value:
                value["snapshot"].pop(key, None)
                value["snapshot"].pop(direction + "_handover_date", None)
    if "snapshot" in value:
        value["snapshot"]["templates"] = [item for item in value["snapshot"]["templates"] if item["direction"] in directions]
    if "steps" in value:
        value["steps"] = [item for item in value["steps"] if item["direction"] in directions]
    value.pop("actions", None)
    for item in value.get("steps", []):
        item.pop("actions", None)
    value["subject_directions"] = sorted(directions)
    return value


def _receipt(store, operation, identifier):
    records = list(_rows(store, WorkflowCommandORM, and_(WorkflowCommandORM.operation == operation,
        WorkflowCommandORM.subject_id == identifier), lambda row: row.operation == operation and row.subject_id == identifier))
    _require(len(records) == 1)
    return records[0]


def _workflow(store, graph):
    for name in WORKFLOW:
        graph[name] = []
    if not _family(store, WORKFLOW):
        return
    tenant_id = graph["tenant"]["id"]
    d = TenancyChangeORM.__table__
    subject = _subject(tenant_id)
    db = getattr(store, "db", None)
    scope = current_scope()
    if db is not None and scope is not None and not scope.unrestricted:
        # This unscoped check publishes only refusal for an authorized subject,
        # and reads no snapshot or hidden counterpart contents.
        if db.connection().scalar(select(exists(select(1).select_from(d).where(subject, ~_scope(d.c.portfolio_id))))):
            raise HTTPException(403, "Historische Mieterwechsel betreffen weitere Portfolios. Vollständige Auskunft benötigt deren Zugriff.")
    roots, versions, definitions, commands = {}, {}, {}, {}
    selected = _rows(store, TenancyChangeORM, and_(subject, _scope(d.c.portfolio_id)),
                     lambda row: bool(_directions(row.snapshot, tenant_id)))
    for change in selected:
        if not _visible(change.portfolio_id):
            raise HTTPException(403, "Historische Mieterwechsel betreffen weitere Portfolios. Vollständige Auskunft benötigt deren Zugriff.")
        _binding(store, change)
        directions = _directions(change.snapshot, tenant_id)
        change_value = _value(change, TenancyChangeORM)
        start = _receipt(store, "start_tenancy_change", change.id)
        _require(start.portfolio_id == change.portfolio_id and start.actor_id == change.created_by
                 and start.subject_type == "tenancy_change" and start.response["snapshot_sha256"] == change.snapshot_sha256)
        all_steps = list(_rows(store, WorkflowStepInstanceORM, WorkflowStepInstanceORM.tenancy_change_id == change.id,
                               lambda row: row.tenancy_change_id == change.id))
        step_map = {row.id: row for row in all_steps}
        _require(len(step_map) == len(all_steps) and {row["id"] for row in start.response["steps"]} == set(step_map))
        own_steps = {row.id: row for row in all_steps if row.direction in directions}
        for frozen in change.snapshot["templates"]:
            if frozen["direction"] not in directions:
                continue
            _require(set(frozen) == {"id", "template_id", "property_id", "unit_id", "direction", "version", "revision", "published_at", "steps"}
                     and frozen["id"] == getattr(change, frozen["direction"] + "_template_version_id"))
            version = _one(store, WorkflowTemplateVersionORM, frozen["id"])
            root = _one(store, WorkflowTemplateORM, version.template_id)
            _require(version.state in {"published", "retired"} and version.portfolio_id == root.portfolio_id == change.portfolio_id
                     and version.property_id == root.property_id == change.property_id
                     and version.unit_id == root.unit_id and version.unit_id in {None, change.unit_id}
                     and frozen["direction"] == version.direction == root.direction)
            for field in ("id", "template_id", "property_id", "unit_id", "direction", "version"):
                _require(frozen[field] == getattr(version, field))
            _require(frozen["published_at"] == _stamp(version.published_at, utc=True))
            publication = _receipt(store, "publish_template_version", version.id)
            _require(publication.portfolio_id == change.portfolio_id and publication.response["revision"] == frozen["revision"])
            live_definitions = list(_rows(store, WorkflowTemplateStepORM, WorkflowTemplateStepORM.version_id == version.id,
                                          lambda row: row.version_id == version.id))
            typed = sorted((TemplateStepInput.model_validate({key: getattr(row, key) for key in TemplateStepInput.model_fields})
                            .model_dump(mode="json") for row in live_definitions), key=lambda row: row["position"])
            _require(typed == frozen["steps"] and typed == [{key: item[key] for key in TemplateStepInput.model_fields}
                                                           for item in publication.response["steps"]])
            roots[root.id] = _proof(_value(root, WorkflowTemplateORM), _value(root, WorkflowTemplateORM))
            versions[version.id] = _proof(_value(version, WorkflowTemplateVersionORM), _value(version, WorkflowTemplateVersionORM))
            for row in live_definitions:
                definitions[row.id] = _proof(_value(row, WorkflowTemplateStepORM), _value(row, WorkflowTemplateStepORM))
            expected = {item["stable_key"]: item for item in typed}
            actual = [row for row in own_steps.values() if row.direction == frozen["direction"]]
            _require({row.template_step_key for row in actual} == set(expected) and len(actual) == len(expected))
            for row in actual:
                _require(row.portfolio_id == change.portfolio_id and row.tenancy_change_id == change.id)
                definition = expected[row.template_step_key]
                for field, key in (("title_snapshot", "title"), ("description_snapshot", "description"), ("requirement", "default_requirement"),
                                   ("anchor", "anchor"), ("offset_days", "offset_days"), ("assignee_user_id", "assignee_user_id"),
                                   ("assignee_role", "assignee_role"), ("evidence_requirement", "evidence_requirement")):
                    _require(getattr(row, field) == definition[key])
                by_key = {item.template_step_key: item for item in actual}
                _require(row.depends_on_step_ids == [by_key[key].id for key in definition["depends_on_step_keys"]])
                anchor = (change.snapshot["previous_contract"]["end_date"] if row.anchor == "previous_contract_end" else
                          change.snapshot["next_contract"]["start_date"] if row.anchor == "next_contract_start" else
                          change.snapshot[row.anchor + "_date"])
                _require(_date(row.original_due_date) == _date(anchor) + timedelta(days=row.offset_days))
                value = _value(row, WorkflowStepInstanceORM)
                graph["tenancy_workflow_step_instances"].append(_proof(value, deepcopy(value)))
                if row.task_id is not None:
                    task = _one(store, TaskORM, row.task_id)
                    creation = _receipt(store, "create_workflow_task", row.id)
                    _require(creation.response["task_id"] == row.task_id and creation.portfolio_id == change.portfolio_id)
                    _require((task.property_id, task.unit_id, task.title, task.description) ==
                             (change.property_id, change.unit_id, row.title_snapshot, row.description_snapshot))
        _require({row.direction for row in own_steps.values()} == directions)
        graph["tenancy_changes"].append(_proof(change_value, _project_change(change_value, directions)))
        own_step_ids = select(WorkflowStepInstanceORM.id).where(WorkflowStepInstanceORM.tenancy_change_id == change.id,
                                                              WorkflowStepInstanceORM.direction.in_(directions))
        all_step_ids = select(WorkflowStepInstanceORM.id).where(WorkflowStepInstanceORM.tenancy_change_id == change.id)
        evidence = _rows(store, WorkflowEvidenceLinkORM, or_(WorkflowEvidenceLinkORM.tenancy_change_id == change.id,
            WorkflowEvidenceLinkORM.step_id.in_(own_step_ids)), lambda row: row.tenancy_change_id == change.id or row.step_id in own_steps)
        for row in evidence:
            _require(row.tenancy_change_id == change.id and row.step_id in step_map and row.portfolio_id == change.portfolio_id
                     and _hex(row.snapshot_sha256))
            if row.step_id in own_steps:
                _witness(store, row, change, own_steps[row.step_id])
                value = _value(row, WorkflowEvidenceLinkORM)
                graph["tenancy_workflow_evidence_links"].append(_proof(value, deepcopy(value)))
        kinds = {"document_original": "document_version", "handover_protocol": "handover_protocol", "meter_reading": "meter_reading"}
        for row in own_steps.values():
            if row.state == "completed" and row.evidence_requirement != "none":
                _require(any(link["step_id"] == row.id and link["kind"] == kinds[row.evidence_requirement]
                             for link in graph["tenancy_workflow_evidence_links"]))
        version_ids = {item["id"] for item in change.snapshot["templates"] if item["direction"] in directions}
        root_ids = {versions[identifier]["template_id"] for identifier in version_ids}
        command_subject = or_(WorkflowCommandORM.subject_id == change.id, WorkflowCommandORM.subject_id.in_(all_step_ids),
                              WorkflowCommandORM.subject_id.in_(version_ids), WorkflowCommandORM.subject_id.in_(root_ids))
        for row in _rows(store, WorkflowCommandORM, command_subject,
                         lambda row: row.subject_id in {change.id} | set(step_map) | version_ids | root_ids):
            _require(row.portfolio_id == change.portfolio_id and _hex(row.request_sha256)
                     and OPERATIONS.get(row.operation) == row.subject_type)
            value = _value(row, WorkflowCommandORM)
            response = value["response"]
            if row.subject_type == "tenancy_change":
                _require(row.subject_id == change.id and set(response) == CHANGE_RESPONSE_FIELDS)
                for field in CHANGE_STABLE:
                    # SQL storage timestamps are naive; command JSON is UTC.
                    if field == "created_at":
                        _require(datetime.fromisoformat(response[field]).replace(tzinfo=None) == change.created_at.replace(tzinfo=None))
                    else:
                        _require(response[field] == change_value[field])
                for item in response["steps"]:
                    _require(item["id"] in step_map)
                    if step_map[item["id"]].direction in directions:
                        _step_reply(store, change, step_map[item["id"]], item, step_map)
                response = _project_change(response, directions)
            elif row.subject_type == "workflow_step":
                _require(row.subject_id in step_map and response["id"] == row.subject_id)
                if row.subject_id not in own_steps:
                    continue
                _step_reply(store, change, own_steps[row.subject_id], response, step_map)
                if row.operation == "update_workflow_step" and response["state"] in {"completed", "not_applicable"}:
                    _require(response["completed_by"] == row.actor_id)
                response.pop("actions", None)
            else:
                _require(row.subject_type in {"template", "template_version"} and set(response) == VERSION_RESPONSE_FIELDS)
                _require((response["template_id"] == row.subject_id if row.subject_type == "template" else response["id"] == row.subject_id))
                if response.get("id") not in versions:
                    continue  # An unused draft is not subject evidence.
                _require(response["template_id"] in root_ids and response["direction"] in directions)
                for item in response["steps"]:
                    _require(set(item) == set(TemplateStepInput.model_fields) | {"id"})
                response.pop("actions", None)
            projected = deepcopy(value)
            projected["response"] = response
            commands[row.id] = _proof(_value(row, WorkflowCommandORM), projected)
        for step in own_steps.values():
            if step.state not in {"completed", "not_applicable"}:
                _require(step.completed_at is None and step.completed_by is None and step.not_applicable_reason is None)
                continue
            receipts = [row for row in commands.values() if row["operation"] == "update_workflow_step"
                        and row["subject_id"] == step.id and row["response"]["revision"] == step.revision]
            _require(len(receipts) == 1 and receipts[0]["actor_id"] == step.completed_by)
            response = receipts[0]["response"]
            for field in ("state", "revision", "completed_by", "not_applicable_reason", "task_id"):
                _require(response[field] == getattr(step, field))
            _require(response["completed_at"] == _stamp(step.completed_at, utc=True)
                     and response["due_date"] == _date(step.due_date).isoformat())
            _require((isinstance(step.not_applicable_reason, str) and bool(step.not_applicable_reason.strip()))
                     if step.state == "not_applicable" else step.not_applicable_reason is None)
    for name, values in (("tenancy_workflow_templates", roots), ("tenancy_workflow_template_versions", versions),
                         ("tenancy_workflow_template_steps", definitions), ("tenancy_workflow_commands", commands)):
        graph[name] = sorted(values.values(), key=lambda row: row["id"])


def _jobs(store, graph):
    for name in JOBS:
        graph[name] = []
    if not _family(store, JOBS):
        return
    tenant_id = graph["tenant"]["id"]
    own = {"overdue_rent_charge": {row["id"] for row in graph["rent_charges"]},
           "overdue_receivable": {row["id"] for row in graph["receivables"]}}
    c, p = ContractORM.__table__, PropertyORM.__table__
    parents = select(c.c.id).join(p, p.c.id == c.c.property_id).where(c.c.tenant_id == tenant_id, _scope(p.c.portfolio_id))
    sql_sources = {"overdue_rent_charge": select(RentChargeORM.id).where(RentChargeORM.contract_id.in_(parents)),
                   "overdue_receivable": select(ReceivableORM.id).where(ReceivableORM.contract_id.in_(parents)),
                   "correspondence": select(CorrespondenceDraftORM.id).where(CorrespondenceDraftORM.tenant_id == tenant_id,
                       CorrespondenceDraftORM.state == "approved", _scope(CorrespondenceDraftORM.portfolio_id))}
    correspondence = {row.id: row for row in _rows(store, CorrespondenceDraftORM,
        CorrespondenceDraftORM.id.in_(sql_sources["correspondence"]),
        lambda row: row.tenant_id == tenant_id and row.state == "approved" and _visible(row.portfolio_id))}
    own["correspondence"] = set(correspondence)
    lanes: dict[str, dict[str, Any]] = {}
    jobs: dict[str, dict[str, Any]] = {}
    lane_parents = {}
    item = OperationalWorkItemORM.__table__
    condition = and_(item.c.kind == "source", or_(*(item.c.source_id.in_(query) for query in sql_sources.values())))
    selected = _rows(store, OperationalWorkItemORM, condition, lambda row: row.kind == "source" and
                     any(row.source_id in identifiers for identifiers in own.values()))
    for row in selected:
        if row.lane_id not in lane_parents:
            found = list(_rows(store, OperationalJobLaneORM, OperationalJobLaneORM.id == row.lane_id,
                               lambda lane: lane.id == row.lane_id, columns=("id", "job_id", "family")))
            _require(len(found) == 1)
            lane_parents[row.lane_id] = found[0]
        parent = lane_parents[row.lane_id]
        _require(parent.job_id == row.job_id and parent.family in own and row.source_id in own[parent.family]
                 and row.action_key == parent.family + ":" + row.source_id
                 and _hex(row.planned_revision))
        if row.job_id not in jobs:
            _require(next(_rows(store, OperationalJobORM, OperationalJobORM.id == row.job_id,
                               lambda job: job.id == row.job_id, columns=("id",)), None) is not None)
        hash_field = "review_hash" if parent.family == "correspondence" else "executed_revision"
        _require(isinstance(row.result, dict) and not set(row.result) - {hash_field, "target_id", "effect_key"})
        if hash_field in row.result:
            _require(_hex(row.result[hash_field]))
            if parent.family == "correspondence":
                _require(row.result[hash_field] == correspondence[row.source_id].review_hash)
        effect = row.result.get("effect_key")
        _require(not row.result.get("target_id") or isinstance(effect, str) and bool(effect))
        if effect:
            if parent.family == "correspondence":
                original = _effect(store, OperationalOccurrenceORM, effect)
                _require(original.target_id == row.result.get("target_id") and original.target_kind == "calendar"
                         and original.schedule_id.startswith("contract-correspondence:" + row.source_id + ":"))
            else:
                original = _effect(store, OperationalDispatchORM, effect)
                _require(original.notification_id == row.result.get("target_id") and original.entity_id == row.source_id
                         and original.entity_type == parent.family.removeprefix("overdue_"))
        value = _value(row, OperationalWorkItemORM)
        graph["operational_work_items"].append(_proof(value, deepcopy(value)))
        lanes.setdefault(parent.id, {"id": parent.id, "job_id": row.job_id, "family": parent.family, "subject_work_item_count": 0})["subject_work_item_count"] += 1
        jobs.setdefault(row.job_id, {"id": row.job_id, "subject_work_item_count": 0})["subject_work_item_count"] += 1
    selected_items = {row["id"]: row for row in graph["operational_work_items"]}
    source_item_ids = select(item.c.id).where(condition).correlate(None)
    command_condition = and_(item.c.kind == "command", item.c.result["request"]["operation"].as_string() == "retry",
                             item.c.result["request"]["source_id"].as_string().in_(source_item_ids))
    for row in _rows(store, OperationalWorkItemORM, command_condition, lambda row: row.kind == "command" and
        row.result.get("request", {}).get("operation") == "retry" and row.result.get("request", {}).get("source_id") in selected_items):
        result = row.result
        _require(row.lane_id is None and row.source_id is None and row.planned_revision is None and row.state == "done"
                 and set(result) == {"request_hash", "request", "receipt"} and row.job_id in jobs
                 and result["receipt"]["id"] == row.job_id and _digest(result["request"]) == result["request_hash"]
                 and selected_items[result["request"]["source_id"]]["job_id"] == row.job_id
                 and row.action_key == "command:" + _digest(result["request"]["request"]["idempotency_key"]))
        original = _value(row, OperationalWorkItemORM)
        projected = deepcopy(original)
        projected["result"] = {"request_hash": result["request_hash"], "request": {"operation": "retry", "source_id": result["request"]["source_id"]},
                               "receipt": {"id": result["receipt"]["id"]}}
        graph["operational_work_items"].append(_proof(original, projected))
    graph["operational_work_items"].sort(key=lambda row: row["id"])
    graph["operational_jobs"] = sorted(jobs.values(), key=lambda row: row["id"])
    graph["operational_job_lanes"] = sorted(lanes.values(), key=lambda row: row["id"])


def append_retained_graph(store, graph):
    try:
        _workflow(store, graph)
        _jobs(store, graph)
        for name in WORKFLOW | JOBS:
            _require(len({row["id"] for row in graph[name]}) == len(graph[name]))
        graph["scope"]["retained_workflow_jobs"] = {
            "schema_version": "tenant-retained-workflow-jobs/1",
            "selection": "stored frozen workflow tenant identities; each matched direction only; jobs through present exact subject source relationships",
            "counterpart": "other contract direction and its steps/receipts explicitly omitted",
            "job_scope": "subject work items and parent reference counts only; global parameters, counters, leases and job-wide commands excluded",
            "historical_job_party": "current obligation relationship only; no earlier unrecorded party identity inferred",
            "unbound_sources": "deleted/unassigned job sources cannot be attributed without stored subject evidence and are excluded",
            "hashes": "source_sha256 hashes actual stored records; projection_sha256 hashes exported projection before that field; original workflow requests are not reconstructed",
            "retention": "all original facts remain retained by profile-only anonymization",
            "projection_sha256": _digest({name: graph[name] for name in WORKFLOW | JOBS}),
        }
        if any(graph[name] for name in WORKFLOW | JOBS):
            graph["schema_version"] = "tenant-data-graph/retained-1"
        return graph
    except (TenantExportError, HTTPException):
        raise
    except Exception as error:
        raise TenantExportError("Retained subject export failed; no partial export") from error
