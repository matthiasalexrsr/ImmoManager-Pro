"""Pure offline retained-workflow proof; no auth, config, Store or commit."""

import hashlib
import json
import sqlite3
from datetime import date, datetime, timedelta, timezone
from time import monotonic
from uuid import UUID

from sqlalchemy import inspect

from .contract_lifecycle_validation import _check_etag, _object, _one, _rows
from .tenancy_workflow_types import TemplateStepInput

FIELDS = {
    "tenancy_workflow_templates": "id portfolio_id property_id unit_id direction created_by created_at",
    "tenancy_workflow_template_versions": "id template_id portfolio_id property_id unit_id direction version state based_on_version_id revision created_by created_at published_at",
    "tenancy_workflow_template_steps": "id version_id stable_key position title description default_requirement anchor offset_days assignee_user_id assignee_role depends_on_step_keys evidence_requirement",
    "tenancy_changes": "id portfolio_id property_id unit_id previous_contract_id next_contract_id mode move_out_handover_date move_in_handover_date move_out_template_version_id move_in_template_version_id state revision created_by snapshot snapshot_sha256 created_at updated_at",
    "tenancy_workflow_step_instances": "id tenancy_change_id portfolio_id template_step_key direction title_snapshot description_snapshot requirement not_applicable_reason anchor offset_days original_due_date due_date state depends_on_step_ids assignee_user_id assignee_role task_id completed_at completed_by evidence_requirement revision created_at updated_at",
    "tenancy_workflow_evidence_links": "id tenancy_change_id step_id portfolio_id kind document_id document_version_id handover_protocol_id meter_reading_id snapshot_sha256 created_by created_at",
    "tenancy_workflow_commands": "id portfolio_id actor_id idempotency_key operation subject_type subject_id request_sha256 response created_at",
}
TABLES = frozenset(FIELDS)
TERMINAL = frozenset({"completed", "not_applicable"})
OPERATIONS = {
    "create_template": "template", "create_template_version": "template_version",
    "update_template_version": "template_version", "publish_template_version": "template_version",
    "start_tenancy_change": "tenancy_change", "patch_tenancy_change": "tenancy_change",
    "reanchor_tenancy_change": "tenancy_change", "complete_tenancy_change": "tenancy_change",
    "update_workflow_step": "workflow_step", "create_workflow_task": "workflow_step",
    "add_workflow_evidence": "workflow_step", "remove_workflow_evidence": "workflow_step",
}
SUBJECT_TABLES = {"template": "tenancy_workflow_templates", "template_version": "tenancy_workflow_template_versions",
                  "tenancy_change": "tenancy_changes", "workflow_step": "tenancy_workflow_step_instances"}
PARENT_FIELDS = {
    **FIELDS, "portfolios": "id", "properties": "id portfolio_id", "units": "id property_id", "users": "id",
    "tenants": "id", "contracts": "id property_id unit_id tenant_id",
    "tasks": "id property_id unit_id title description due_date status recurrence_rule parent_task_id",
    "document_versions": "id document_id portfolio_id property_id unit_id contract_id tenant_id sha256 number",
    "handover_protocols": "id contract_id unit_id protocol_type protocol_date status updated_at",
    "meter_readings": "id handover_id meter_type meter_number reading_value unit created_at",
}


class WorkflowIntegrityError(ValueError):
    pass


def _check(deadline):
    if deadline is not None and monotonic() >= deadline:
        raise WorkflowIntegrityError("tenancy_workflow_validation_timeout")


def _require(value):
    if not value:
        raise ValueError("workflow_invariant")


def _digest(value):
    digest = hashlib.sha256()
    encoder = json.JSONEncoder(ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False, default=str)
    for block in encoder.iterencode(value):
        digest.update(block.encode("utf-8"))
    return digest.hexdigest()


def _hex(value):
    return isinstance(value, str) and len(value) == 64 and all(char in "0123456789abcdef" for char in value)


def _date(value):
    result = date.fromisoformat(value) if isinstance(value, str) else value
    _require(type(result) is date)
    return result


def _stamp(value, *, utc=False):
    stamp = datetime.fromisoformat(value) if isinstance(value, str) else value
    _require(isinstance(stamp, datetime))
    if utc:
        stamp = stamp.replace(tzinfo=timezone.utc) if stamp.tzinfo is None else stamp.astimezone(timezone.utc)
    return stamp.isoformat()


def workflow_family_present(connection):
    """Complete older images are valid; partial families and empty bad DDL fail."""
    names = ({row["name"] for row in _rows(connection, "SELECT name FROM sqlite_master WHERE type='table'")}
             if isinstance(connection, sqlite3.Connection) else set(inspect(connection).get_table_names()))
    if not names & TABLES:
        return False
    if not TABLES <= names:
        raise WorkflowIntegrityError("tenancy_workflow_schema_incomplete")
    for name, expected in FIELDS.items():
        columns = ({row["name"] for row in _rows(connection, 'PRAGMA table_info("' + name + '")')}
                   if isinstance(connection, sqlite3.Connection)
                   else {column["name"] for column in inspect(connection).get_columns(name)})
        if not set(expected.split()) <= columns:
            raise WorkflowIntegrityError("tenancy_workflow_columns_incomplete")
    return True


def _parent(connection, table, identifier):
    _require(identifier)
    row = _one(connection, "SELECT " + ",".join(PARENT_FIELDS[table].split()) + " FROM " + table + " WHERE id=:id", {"id": identifier})
    _require(row is not None)
    return _object(row, ())


def _location(connection, row):
    _parent(connection, "portfolios", row.portfolio_id)
    prop = _parent(connection, "properties", row.property_id)
    _require(prop.portfolio_id == row.portfolio_id)
    if row.unit_id is not None:
        _require(_parent(connection, "units", row.unit_id).property_id == row.property_id)


def _graph(graph):
    """Iterative DAG validation without recursion or a total step limit."""
    degree: dict[str, int] = {}
    outgoing: dict[str, list[str]] = {key: [] for key in graph}
    for key, dependencies in graph.items():
        _require(isinstance(dependencies, list) and len(dependencies) == len(set(dependencies)))
        _require(key not in dependencies and all(item in graph for item in dependencies))
        degree[key] = len(dependencies)
        for dependency in dependencies:
            outgoing[dependency].append(key)
    ready, count = [key for key, value in degree.items() if value == 0], 0
    while ready:
        key = ready.pop()
        count += 1
        for following in outgoing[key]:
            degree[following] -= 1
            if degree[following] == 0:
                ready.append(following)
    _require(count == len(graph))


def _template_steps(connection, version_id):
    steps = []
    for values in _rows(connection, "SELECT * FROM tenancy_workflow_template_steps WHERE version_id=:id ORDER BY position,id", {"id": version_id}):
        row = _object(values, ("depends_on_step_keys",))
        UUID(row.id)
        data = {key: getattr(row, key) for key in TemplateStepInput.model_fields}
        typed = TemplateStepInput.model_validate(data)
        if typed.assignee_user_id:
            _parent(connection, "users", typed.assignee_user_id)
        steps.append(typed.model_dump(mode="json"))
    _require(steps and len({row["stable_key"] for row in steps}) == len(steps)
             and len({row["position"] for row in steps}) == len(steps))
    _graph({row["stable_key"]: row["depends_on_step_keys"] for row in steps})
    return steps


def _receipt(connection, operation, subject_id, *, revision=None):
    query, parameters = "SELECT * FROM tenancy_workflow_commands WHERE operation=:op AND subject_id=:id", {"op": operation, "id": subject_id}
    if revision is not None:
        sqlite = isinstance(connection, sqlite3.Connection) or connection.dialect.name == "sqlite"
        field = "CASE WHEN json_valid(response) THEN json_extract(response,'$.revision') END" if sqlite else "response::jsonb ->> 'revision'"
        query += " AND " + field + "=:revision"
        parameters["revision"] = revision
    rows = list(_rows(connection, query + " LIMIT 2", parameters))
    _require(len(rows) == 1)
    return _object(rows[0], ("response",))


def _versions(connection, deadline):
    _require(not _one(connection, "SELECT property_id,unit_id,direction FROM tenancy_workflow_templates GROUP BY property_id,unit_id,direction HAVING COUNT(*)>1 LIMIT 1"))
    _require(not _one(connection, "SELECT template_id,version FROM tenancy_workflow_template_versions GROUP BY template_id,version HAVING COUNT(*)>1 LIMIT 1"))
    for values in _rows(connection, "SELECT * FROM tenancy_workflow_templates ORDER BY id"):
        _check(deadline)
        root = _object(values, ())
        UUID(root.id)
        _location(connection, root)
        _require(root.direction in {"move_in", "move_out"} and root.created_by)
        _stamp(root.created_at)
        _require(_one(connection, "SELECT id FROM tenancy_workflow_template_versions WHERE template_id=:id LIMIT 1", {"id": root.id}))
        _require(not _one(connection, "SELECT template_id FROM tenancy_workflow_template_versions WHERE template_id=:id AND state='published' GROUP BY template_id HAVING COUNT(*)>1", {"id": root.id}))
    for values in _rows(connection, "SELECT * FROM tenancy_workflow_template_versions ORDER BY id"):
        _check(deadline)
        row = _object(values, ())
        UUID(row.id)
        UUID(row.revision)
        root = _parent(connection, "tenancy_workflow_templates", row.template_id)
        _require(all(getattr(row, key) == getattr(root, key) for key in ("portfolio_id", "property_id", "unit_id", "direction")))
        _require(type(row.version) is int and row.version > 0 and row.created_by and row.state in {"draft", "published", "retired"})
        _stamp(row.created_at)
        if row.based_on_version_id:
            base = _parent(connection, "tenancy_workflow_template_versions", row.based_on_version_id)
            _require(base.template_id == row.template_id and base.version < row.version)
        else:
            _require(row.version == 1)
        steps = _template_steps(connection, row.id)
        if row.state == "draft":
            _require(row.published_at is None)
        else:
            publication = _receipt(connection, "publish_template_version", row.id).response
            _require(publication["state"] == "published" and publication["published_at"] == _stamp(row.published_at, utc=True))
            published_steps = [{key: item[key] for key in TemplateStepInput.model_fields} for item in publication["steps"]]
            _require(steps == published_steps)
            if row.state == "published":
                _require(publication["revision"] == row.revision)
    # Orphan steps must not disappear merely because no version references them.
    _require(not _one(connection, "SELECT s.id FROM tenancy_workflow_template_steps s LEFT JOIN tenancy_workflow_template_versions v ON v.id=s.version_id WHERE v.id IS NULL LIMIT 1"))


def _frozen_templates(connection, change):
    snapshot = change.snapshot
    expected = {"move_out": change.move_out_template_version_id, "move_in": change.move_in_template_version_id}
    expected = {key: value for key, value in expected.items() if value is not None}
    _require(isinstance(snapshot["templates"], list) and len(snapshot["templates"]) == len(expected))
    result = {}
    for item in snapshot["templates"]:
        row = _parent(connection, "tenancy_workflow_template_versions", item["id"])
        _require(row.state in {"published", "retired"} and expected.get(item["direction"]) == row.id)
        _require(row.property_id == change.property_id and row.unit_id in {None, change.unit_id} and row.portfolio_id == change.portfolio_id)
        for key in ("id", "template_id", "property_id", "unit_id", "direction", "version"):
            _require(item[key] == getattr(row, key))
        publication = _receipt(connection, "publish_template_version", row.id).response
        _require(item["revision"] == publication["revision"] and item["published_at"] == _stamp(row.published_at, utc=True))
        steps = _template_steps(connection, row.id)
        _require(item["steps"] == steps and item["direction"] not in result)
        result[item["direction"]] = steps
    return result


def _contract(connection, change, direction):
    key = "previous_contract" if direction == "move_out" else "next_contract"
    identifier = getattr(change, key + "_id")
    frozen = change.snapshot[key]
    if identifier is None:
        _require(frozen is None)
        return
    _parent(connection, "contracts", identifier)
    _require(frozen["id"] == identifier and frozen["property_id"] == change.property_id
             and frozen["unit_id"] == change.unit_id)
    # Normal later contract corrections are recoverable online conflicts, not
    # corruption of the archived start. Its retained tenant/anchors stay frozen.
    _parent(connection, "tenants", frozen["tenant_id"])
    _date(frozen["start_date"])
    if frozen["end_date"] is not None:
        _date(frozen["end_date"])
    _require(_check_etag(frozen["etag"], identifier).isoformat() == _stamp(frozen["updated_at"], utc=True))


def _anchor(snapshot, anchor):
    if anchor == "previous_contract_end":
        value = snapshot["previous_contract"]["end_date"]
    elif anchor == "next_contract_start":
        value = snapshot["next_contract"]["start_date"]
    else:
        value = snapshot[anchor + "_date"]
    _require(value is not None)
    return _date(value)


def _task(connection, change, step):
    if step.task_id is None:
        return
    task = _parent(connection, "tasks", step.task_id)
    _require((task.property_id, task.unit_id, task.title, task.description) ==
             (change.property_id, change.unit_id, step.title_snapshot, step.description_snapshot))
    _require(_date(task.due_date) == _date(step.due_date) and task.recurrence_rule is None and task.parent_task_id is None)
    status = {"open": "open", "blocked": "open", "in_progress": "in_progress", "completed": "completed", "not_applicable": "cancelled"}[step.state]
    if change.state in {"completed", "cancelled"} and step.state not in TERMINAL:
        status = "cancelled"
    _require(task.status == status)
    _require(_receipt(connection, "create_workflow_task", step.id).response["task_id"] == step.task_id)


def _steps(connection, change, templates):
    steps = [_object(row, ("depends_on_step_ids",)) for row in _rows(connection,
        "SELECT * FROM tenancy_workflow_step_instances WHERE tenancy_change_id=:id ORDER BY direction,id", {"id": change.id})]
    mapping = {(row.direction, row.template_step_key): row for row in steps}
    by_id = {row.id: row for row in steps}
    expected = {(direction, item["stable_key"]): item for direction, items in templates.items() for item in items}
    _require(len(mapping) == len(steps) and set(mapping) == set(expected))
    for key, step in mapping.items():
        frozen = expected[key]
        UUID(step.id)
        UUID(step.revision)
        _require(step.portfolio_id == change.portfolio_id and step.state in {"open", "blocked", "in_progress"} | TERMINAL)
        renamed = {"title_snapshot": "title", "description_snapshot": "description", "requirement": "default_requirement"}
        for field in ("title_snapshot", "description_snapshot", "requirement", "anchor", "offset_days", "assignee_user_id", "assignee_role", "evidence_requirement"):
            _require(getattr(step, field) == frozen[renamed.get(field, field)])
        expected_due = _anchor(change.snapshot, step.anchor) + timedelta(days=step.offset_days)
        _require(_date(step.original_due_date) == expected_due)
        _require(step.depends_on_step_ids == [mapping[step.direction, dep].id for dep in frozen["depends_on_step_keys"]])
        if step.state in TERMINAL:
            _stamp(step.completed_at)
            _require(step.completed_by)
            command = _receipt(connection, "update_workflow_step", step.id, revision=step.revision)
            response = command.response
            _require(command.actor_id == step.completed_by)
            for field in ("state", "revision", "completed_by", "not_applicable_reason", "task_id"):
                _require(response[field] == getattr(step, field))
            _require(response["due_date"] == _date(step.due_date).isoformat()
                     and response["completed_at"] == _stamp(step.completed_at, utc=True))
            if step.state == "not_applicable":
                _require(isinstance(step.not_applicable_reason, str) and step.not_applicable_reason.strip())
            else:
                _require(step.not_applicable_reason is None)
        else:
            _require(step.completed_at is None and step.completed_by is None and step.not_applicable_reason is None)
            current = dict(change.snapshot)
            current["move_out_handover_date"] = change.move_out_handover_date
            current["move_in_handover_date"] = change.move_in_handover_date
            _require(_date(step.due_date) == _anchor(current, step.anchor) + timedelta(days=step.offset_days))
        if step.state in {"in_progress", "completed"}:
            _require(all(by_id[dep].state in TERMINAL for dep in step.depends_on_step_ids))
        _task(connection, change, step)
    _graph({step.id: step.depends_on_step_ids for step in steps})
    if change.state == "completed":
        _require(all(step.state in TERMINAL for step in steps if step.requirement == "required"))
    receipt = _receipt(connection, "start_tenancy_change", change.id).response
    _change_response(connection, change, receipt)
    _require(receipt["state"] == "active")
    for field in ("move_out_handover_date", "move_in_handover_date"):
        _require(receipt[field] == change.snapshot[field])
    for response in receipt["steps"]:
        step = by_id[response["id"]]
        _require(response["due_date"] == _date(step.original_due_date).isoformat()
                 and response["state"] == ("blocked" if step.depends_on_step_ids else "open")
                 and response["blocked_by_step_ids"] == step.depends_on_step_ids
                 and response["task_id"] is None and response["completed_at"] is None
                 and response["completed_by"] is None and response["not_applicable_reason"] is None
                 and response["evidence_links"] == [])


def _changes(connection, deadline):
    _require(not _one(connection, "SELECT task_id FROM tenancy_workflow_step_instances WHERE task_id IS NOT NULL GROUP BY task_id HAVING COUNT(*)>1 LIMIT 1"))
    for values in _rows(connection, "SELECT * FROM tenancy_changes ORDER BY id"):
        _check(deadline)
        row = _object(values, ("snapshot",))
        UUID(row.id)
        UUID(row.revision)
        _location(connection, row)
        _require(row.created_by and row.unit_id and row.state in {"draft", "active", "completed", "cancelled"})
        _require(isinstance(row.snapshot, dict) and row.snapshot["schema"] == "tenancy-change-snapshot-v1"
                 and _hex(row.snapshot_sha256) and _digest(row.snapshot) == row.snapshot_sha256)
        for key in ("portfolio_id", "property_id", "unit_id", "mode"):
            _require(row.snapshot[key] == getattr(row, key))
        directions = {"move_out": {"move_out"}, "move_in": {"move_in"}, "turnover": {"move_out", "move_in"}}[row.mode]
        _require((row.previous_contract_id is not None) == ("move_out" in directions)
                 and (row.next_contract_id is not None) == ("move_in" in directions))
        _require(row.previous_contract_id is None or row.previous_contract_id != row.next_contract_id)
        _contract(connection, row, "move_out")
        _contract(connection, row, "move_in")
        templates = _frozen_templates(connection, row)
        _require(set(templates) == directions)
        _steps(connection, row, templates)
        if row.state in {"completed", "cancelled"}:
            operation = "complete_tenancy_change" if row.state == "completed" else "patch_tenancy_change"
            result = _receipt(connection, operation, row.id).response
            _require(result["state"] == row.state and result["revision"] == row.revision)
    _require(not _one(connection, "SELECT s.id FROM tenancy_workflow_step_instances s LEFT JOIN tenancy_changes c ON c.id=s.tenancy_change_id WHERE c.id IS NULL LIMIT 1"))
    for field in ("previous_contract_id", "next_contract_id"):
        _require(not _one(connection, "SELECT " + field + " FROM tenancy_changes WHERE state='active' AND " + field + " IS NOT NULL GROUP BY " + field + " HAVING COUNT(*)>1 LIMIT 1"))


def _evidence(connection, deadline):
    from .document_version_validation import verify_document_versions
    verified_documents = False
    for values in _rows(connection, "SELECT * FROM tenancy_workflow_evidence_links ORDER BY id"):
        _check(deadline)
        link = _object(values, ())
        UUID(link.id)
        step = _parent(connection, "tenancy_workflow_step_instances", link.step_id)
        change = _object(vars(_parent(connection, "tenancy_changes", link.tenancy_change_id)), ("snapshot",))
        _require(step.tenancy_change_id == change.id and step.portfolio_id == link.portfolio_id == change.portfolio_id)
        source = change.snapshot["previous_contract" if step.direction == "move_out" else "next_contract"]
        _require(link.created_by and _hex(link.snapshot_sha256))
        shape = tuple(getattr(link, key) is not None for key in ("document_id", "document_version_id", "handover_protocol_id", "meter_reading_id"))
        expected = {"document_version": (True, True, False, False), "handover_protocol": (False, False, True, False), "meter_reading": (False, False, False, True)}
        _require(shape == expected[link.kind])
        if link.kind == "document_version":
            if not verified_documents:
                verify_document_versions(connection, deadline=deadline)
                verified_documents = True
            version = _parent(connection, "document_versions", link.document_version_id)
            _require((version.document_id, version.portfolio_id, version.property_id, version.unit_id, version.contract_id, version.tenant_id) ==
                     (link.document_id, change.portfolio_id, change.property_id, change.unit_id, source["id"], source["tenant_id"]))
            payload = {"kind": link.kind, "document_id": link.document_id, "document_version_id": version.id,
                       "sha256": version.sha256, "number": version.number, "contract_id": source["id"], "tenant_id": source["tenant_id"]}
        else:
            reading = _parent(connection, "meter_readings", link.meter_reading_id) if link.kind == "meter_reading" else None
            protocol = _parent(connection, "handover_protocols", reading.handover_id if reading else link.handover_protocol_id)
            _require((protocol.status, protocol.contract_id, protocol.unit_id, protocol.protocol_type) ==
                     ("finalized", source["id"], change.unit_id, step.direction))
            protocol_snapshot = {"id": protocol.id, "contract_id": protocol.contract_id, "unit_id": protocol.unit_id,
                "protocol_type": protocol.protocol_type, "status": protocol.status, "updated_at": _stamp(protocol.updated_at)}
            if reading:
                payload = {"kind": link.kind, "id": reading.id, "handover_id": reading.handover_id,
                    "meter_type": reading.meter_type, "meter_number": reading.meter_number,
                    "reading_value": reading.reading_value, "unit": reading.unit, "created_at": _stamp(reading.created_at),
                    "protocol_snapshot": protocol_snapshot}
            else:
                payload = {"kind": link.kind, **protocol_snapshot, "protocol_date": _date(protocol.protocol_date).isoformat()}
        _require(_digest(payload) == link.snapshot_sha256)
    kinds = {"document_original": "document_version", "handover_protocol": "handover_protocol", "meter_reading": "meter_reading"}
    for step in _rows(connection, "SELECT id,evidence_requirement FROM tenancy_workflow_step_instances WHERE state='completed' AND evidence_requirement<>'none'"):
        _check(deadline)
        _require(_one(connection, "SELECT id FROM tenancy_workflow_evidence_links WHERE step_id=:id AND kind=:kind LIMIT 1", {"id": step["id"], "kind": kinds[step["evidence_requirement"]]}))


def _step_response(step, response):
    for field in ("id", "tenancy_change_id", "template_step_key", "direction", "title_snapshot", "description_snapshot",
                  "requirement", "anchor", "offset_days", "assignee_user_id", "assignee_role"):
        _require(response[field] == getattr(step, field))
    _require(response["original_due_date"] == _date(step.original_due_date).isoformat())
    UUID(response["revision"])


def _change_response(connection, change, response):
    for field in ("id", "portfolio_id", "property_id", "unit_id", "previous_contract_id", "next_contract_id", "mode",
                  "move_out_template_version_id", "move_in_template_version_id", "created_by", "snapshot_sha256"):
        _require(response[field] == getattr(change, field))
    _require(response["created_at"] == _stamp(change.created_at, utc=True))
    expected = {row["id"]: _object(row, ()) for row in _rows(connection,
        "SELECT * FROM tenancy_workflow_step_instances WHERE tenancy_change_id=:id", {"id": change.id})}
    _require(isinstance(response["steps"], list) and len(response["steps"]) == len(expected)
             and {row["id"] for row in response["steps"]} == set(expected))
    for item in response["steps"]:
        _step_response(expected[item["id"]], item)


def _commands(connection, deadline):
    for values in _rows(connection, "SELECT * FROM tenancy_workflow_commands ORDER BY id"):
        _check(deadline)
        row = _object(values, ("response",))
        UUID(row.id)
        _require(row.actor_id and isinstance(row.idempotency_key, str) and 1 <= len(row.idempotency_key) <= 100
                 and _hex(row.request_sha256) and OPERATIONS.get(row.operation) == row.subject_type)
        subject = _parent(connection, SUBJECT_TABLES[row.subject_type], row.subject_id)
        _require(subject.portfolio_id == row.portfolio_id and isinstance(row.response, dict))
        response = row.response
        if row.subject_type == "template":
            _require(response["template_id"] == subject.id)
            version = _parent(connection, "tenancy_workflow_template_versions", response["id"])
            _require(version.template_id == subject.id and subject.created_by == row.actor_id == version.created_by)
        else:
            _require(response["id"] == subject.id)
            version = subject if row.subject_type == "template_version" else None
        if version is not None:
            for field in ("id", "template_id", "portfolio_id", "property_id", "unit_id", "direction", "version", "based_on_version_id"):
                _require(response[field] == getattr(version, field))
            _require(response["created_at"] == _stamp(version.created_at, utc=True))
            if row.operation == "create_template_version":
                _require(version.created_by == row.actor_id)
        UUID(response["revision"])
        if row.subject_type == "workflow_step":
            _step_response(subject, response)
            if row.operation == "update_workflow_step" and response["state"] in TERMINAL:
                _require(response["completed_by"] == row.actor_id)
        else:
            _require(response["portfolio_id"] == row.portfolio_id)
        if row.subject_type == "tenancy_change":
            _change_response(connection, subject, response)
            if row.operation == "start_tenancy_change":
                _require(subject.created_by == row.actor_id)
        _stamp(row.created_at)
    _require(not _one(connection, "SELECT actor_id,idempotency_key FROM tenancy_workflow_commands GROUP BY actor_id,idempotency_key HAVING COUNT(*)>1 LIMIT 1"))


def validate_workflow_journal(connection, *, deadline=None):
    """Read-only staged connection; False for complete pre-b2 images, no DML."""
    _check(deadline)
    if not workflow_family_present(connection):
        return False
    try:
        for name in FIELDS:
            _check(deadline)
            _require(not _one(connection, "SELECT id FROM " + name + " GROUP BY id HAVING COUNT(*)>1 LIMIT 1"))
        _versions(connection, deadline)
        _changes(connection, deadline)
        _evidence(connection, deadline)
        _commands(connection, deadline)
        return True
    except WorkflowIntegrityError:
        raise
    except Exception:
        raise WorkflowIntegrityError("tenancy_workflow_journal_invalid") from None
