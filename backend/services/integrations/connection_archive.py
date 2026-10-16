"""Offline verification of private connection state with EXPLICIT archived keys.

This module neither opens a live database nor consults runtime settings, auth,
provider registries or a default keyring. Restore callers own the connection,
transaction, budgets and exclusive access. Original response bytes are checked
before a restored run can be normalized or the installation published.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any, NoReturn
from uuid import uuid4

from sqlalchemy import MetaData, Table, func, inspect, select

from .. import secret_box

BASE_TABLES = ("integration_connections", "integration_connection_secrets", "integration_connection_mappings",
               "integration_action_runs", "integration_source_blocks", "integration_connection_events")
ATTEMPT_TABLES = ("integration_action_attempts", "integration_run_cursors")
BLOCK_BYTES = 64 * 1024
EVENT_FORMAT = "immomanager-connection-event/2"
RESULT_FORMAT = "immomanager-connection-result/2"


class ConnectionArchiveError(RuntimeError):
    def __init__(self, code: str):
        self.code = code
        super().__init__("Private Verbindungsnachweise konnten nicht vollständig geprüft werden (" + code + ").")


def _fail(code: str) -> NoReturn:
    raise ConnectionArchiveError(code)


def _json(raw: str | bytes) -> Any:
    def constant(_value):
        _fail("invalid_json_constant")
    try:
        return json.loads(raw, parse_constant=constant)
    except (ValueError, UnicodeError, TypeError, RecursionError):
        _fail("invalid_private_json")


def _canonical(value: Any) -> bytes:
    try:
        return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError, RecursionError):
        _fail("invalid_private_json")


def _stamp(value) -> str:
    try:
        moment = value if isinstance(value, datetime) else datetime.fromisoformat(value.replace("Z", "+00:00"))
        return moment.replace(tzinfo=timezone.utc).isoformat() if moment.tzinfo is None else moment.astimezone(timezone.utc).isoformat()
    except (ValueError, TypeError, AttributeError):
        _fail("invalid_timestamp")


def _identity(run, attempt) -> dict:
    return {"id": attempt["id"], "run_id": run["id"], "connection_id": run["connection_id"],
            "number": attempt["number"], "actor_id": attempt["actor_id"],
            "lease_sha256": attempt["lease_sha256"], "request_sha256": attempt["request_sha256"],
            "action": run["action"], "effect": run["effect"], "config_revision": run["config_revision"],
            "source_kind": run["source_kind"], "source_id": run["source_id"], "source_revision": run["source_revision"],
            "created_at": _stamp(attempt["created_at"])}


def verify_connection_state(connection, keys: list[secret_box.Key], *, step_bytes: int = 4 * 1024 * 1024) -> dict:
    """Stream every private family row, validating all keys and retained results.

    An old id-only result is reported separately; no stronger provenance is
    fabricated during verification. No schema or state is changed here.
    """
    if type(step_bytes) is not int or step_bytes <= 0:
        raise ValueError("step_bytes must be a positive explicit work budget")
    tables = set(inspect(connection).get_table_names())
    present = set(BASE_TABLES) & tables
    if not present:
        if set(ATTEMPT_TABLES) & tables:
            _fail("orphan_attempt_schema")
        return {"present": False, "rows": 0, "verified_result_bytes": 0, "legacy_id_only_records": 0}
    if present != set(BASE_TABLES) or bool(set(ATTEMPT_TABLES) & tables) != set(ATTEMPT_TABLES).issubset(tables):
        _fail("partial_connection_schema")
    metadata = MetaData()
    selected = (*BASE_TABLES, *(ATTEMPT_TABLES if set(ATTEMPT_TABLES).issubset(tables) else ()))
    reflected = {name: Table(name, metadata, autoload_with=connection) for name in selected}
    result: dict[str, Any] = {"present": True, "rows": 0, "verified_result_bytes": 0, "legacy_id_only_records": 0,
              "key_ids": set(), "table_counts": {}}

    def rows(name):
        table = reflected[name]
        return connection.execute(select(table).order_by(table.c.id).execution_options(yield_per=64)).mappings()

    @lru_cache(maxsize=128)
    def one(name: str, identifier: str):
        table = reflected.get(name)
        if table is None:
            _fail("missing_reference_family")
        record = connection.execute(select(table).where(table.c.id == identifier)).mappings().first()
        if record is None:
            _fail("missing_private_reference")
        return dict(record)

    def opened(token, context):
        if not isinstance(token, str) or len(token) > step_bytes * 2 + 512:
            _fail("private_artifact_budget")
        try:
            value = secret_box.open_with(keys, token, context)
            result["key_ids"].add(secret_box.token_key_id(token))
        except (secret_box.SecretError, ValueError, UnicodeError, TypeError):
            _fail("private_key_or_ciphertext")
        if len(value.encode("utf-8")) > step_bytes:
            _fail("private_artifact_budget")
        return _json(value)

    def config_refs(connection_id, refs):
        if not isinstance(refs, dict):
            _fail("invalid_secret_references")
        for field, identifier in refs.items():
            if not isinstance(field, str) or not isinstance(identifier, str):
                _fail("invalid_secret_references")
            secret = one("integration_connection_secrets", identifier)
            if secret["connection_id"] != connection_id or secret["field_name"] != field:
                _fail("secret_reference_identity")

    def snapshot(run):
        value = opened(run["config_snapshot_token"], f"connection-run/{run['id']}/configuration")
        if not isinstance(value, dict) or value.get("revision") != run["config_revision"]:
            _fail("run_config_identity")
        parent = one("integration_connections", run["connection_id"])
        if value.get("provider_id") != parent["provider_id"]:
            _fail("run_provider_identity")
        config_refs(parent["id"], value.get("secret_refs"))
        # A frozen run stores its encrypted configuration snapshot inside the
        # run's own authenticated token. It is intentionally NOT a pointer to
        # the connection's current configuration: later edits must not change
        # which parameters an already accepted action used.
        if not isinstance(value.get("config"), dict):
            _fail("run_config_identity")
        if "source" in value:
            source = value["source"] or {}
            if (source.get("kind"), source.get("entity_id"), source.get("revision")) != (
                    run["source_kind"], run["source_id"], run["source_revision"]):
                _fail("run_source_identity")
        return value

    def verify_result(run_id, manifest):
        if not isinstance(manifest, dict):
            _fail("invalid_result_manifest")
        size, count = manifest.get("bytes"), manifest.get("blocks")
        if (type(size) is not int or not 0 < size <= step_bytes or type(count) is not int or
                count != (size + BLOCK_BYTES - 1) // BLOCK_BYTES or not isinstance(manifest.get("category"), str)):
            _fail("invalid_result_manifest")
        bound = manifest.get("format") == RESULT_FORMAT
        if bound and manifest.get("run_id") != run_id:
            _fail("result_run_identity")
        model = reflected["integration_source_blocks"]
        checksum, actual_size, actual_count = hashlib.sha256(), 0, 0
        payload = bytearray()
        query = select(model).where(model.c.run_id == run_id, model.c.category == manifest["category"]).order_by(model.c.sequence)
        for block in connection.execute(query.execution_options(yield_per=32)).mappings():
            if block["sequence"] != actual_count or actual_count >= count:
                _fail("result_block_sequence")
            value = opened(block["data_token"], f"connection-block/{block['id']}")
            if isinstance(value, dict) and value.get("format") == RESULT_FORMAT:
                identity = {name: block[name] for name in ("id", "run_id", "category", "sequence", "sha256", "byte_length")}
                identity["created_at"] = _stamp(block["created_at"])
                if value.get("identity") != identity:
                    _fail("result_block_identity")
                data = value.get("data")
            elif isinstance(value, str) and not bound:
                data = value
            else:
                _fail("result_block_format")
            try:
                if not isinstance(data, str):
                    raise ValueError
                raw = base64.b64decode(data, validate=True)
            except (ValueError, binascii.Error):
                _fail("result_block_encoding")
            if (not 0 < len(raw) <= BLOCK_BYTES or len(raw) != block["byte_length"]
                    or hashlib.sha256(raw).hexdigest() != block["sha256"]):
                _fail("result_block_hash")
            checksum.update(raw)
            actual_size += len(raw)
            actual_count += 1
            payload.extend(raw)
            if actual_size > size:
                _fail("result_block_size")
        if (actual_size, actual_count, checksum.hexdigest()) != (size, count, manifest.get("sha256")):
            _fail("result_manifest_mismatch")
        result["verified_result_bytes"] += actual_size
        if not bound:
            result["legacy_id_only_records"] += 1
        return _json(bytes(payload))

    for name in selected:
        count = int(connection.scalar(select(func.count()).select_from(reflected[name])) or 0)
        result["table_counts"][name] = count
        result["rows"] += count
    for item in rows("integration_connections"):
        if not isinstance(opened(item["config_token"], f"connection/{item['id']}/config"), dict):
            _fail("invalid_connection_config")
        config_refs(item["id"], item["secret_refs"])
    for item in rows("integration_connection_secrets"):
        one("integration_connections", item["connection_id"])
        if not isinstance(opened(item["value_token"], f"connection-secret/{item['id']}"), str):
            _fail("invalid_private_secret")
    for item in rows("integration_connection_mappings"):
        one("integration_connections", item["connection_id"])
        external = opened(item["external_key_token"], f"connection-mapping/{item['id']}/key")
        raw = opened(item["observed_token"], f"connection-mapping/{item['id']}/raw")
        opened(item["manifest_token"], f"connection-mapping/{item['id']}/manifest")
        if hashlib.sha256(_canonical([item["source_kind"], external])).hexdigest() != item["external_key_hash"] or hashlib.sha256(_canonical(raw)).hexdigest() != item["source_sha256"]:
            _fail("mapping_source_hash")
    for run in rows("integration_action_runs"):
        snapshot(run)
        action = opened(run["action_manifest_token"], f"connection-run/{run['id']}/action")
        request = opened(run["request_token"], f"connection-run/{run['id']}/request")
        if (not isinstance(action, dict) or action.get("id") != run["action"] or action.get("effect") != run["effect"]
                or not isinstance(request, dict) or request.get("action") != run["action"]
                or hashlib.sha256(_canonical(request)).hexdigest() != run["request_sha256"]):
            _fail("run_request_identity")
        if run["checkpoint_token"]:
            opened(run["checkpoint_token"], f"connection-run/{run['id']}/checkpoint")
        if run["result_token"]:
            manifest = opened(run["result_token"], f"connection-run/{run['id']}/result")
            if not isinstance(manifest, dict) or manifest.get("sha256") != run["result_sha256"]:
                _fail("run_result_hash")
            if manifest.get("format") != RESULT_FORMAT:
                verify_result(run["id"], manifest)
    for item in rows("integration_connection_events"):
        one("integration_connections", item["connection_id"])
        if item["run_id"] and one("integration_action_runs", item["run_id"])["connection_id"] != item["connection_id"]:
            _fail("event_run_identity")
        event = opened(item["detail_token"], f"connection-event/{item['id']}")
        if isinstance(event, dict) and event.get("format") == EVENT_FORMAT:
            identity = {name: item[name] for name in ("id", "connection_id", "run_id", "actor_id", "event_type")}
            identity["created_at"] = _stamp(item["created_at"])
            if event.get("identity") != identity or not isinstance(event.get("detail"), dict):
                _fail("event_identity")
        elif not isinstance(event, dict):
            _fail("invalid_private_event")
        else:
            result["legacy_id_only_records"] += 1
    if "integration_action_attempts" in reflected:
        for attempt in rows("integration_action_attempts"):
            run = one("integration_action_runs", attempt["run_id"])
            value = opened(attempt["input_token"], f"connection-attempt/{attempt['id']}/input")
            if (not isinstance(value, dict) or value.get("identity") != _identity(run, attempt)
                    or value.get("configuration") != snapshot(run)
                    or hashlib.sha256(_canonical(value.get("request"))).hexdigest() != attempt["request_sha256"]):
                _fail("attempt_input_identity")
            if attempt["state"] == "finished":
                manifest = opened(attempt["manifest_token"], f"connection-attempt/{attempt['id']}/result")
                if (not isinstance(manifest, dict) or manifest.get("identity") != _identity(run, attempt)
                        or manifest.get("finished_at") != _stamp(attempt["finished_at"])
                        or manifest.get("detached") != attempt["detached"]):
                    _fail("attempt_result_identity")
                proof = manifest.get("result", {})
                if (proof.get("attempt_id") != attempt["id"] or proof.get("sha256") != attempt["result_sha256"]
                        or proof.get("bytes") != attempt["result_bytes"] or proof.get("blocks") != attempt["result_blocks"]):
                    _fail("attempt_result_manifest")
                outcome = verify_result(run["id"], proof)
                if not isinstance(outcome, dict) or (outcome.get("success") is True) != attempt["success"]:
                    _fail("attempt_success_mismatch")
            elif attempt["state"] != "started" or attempt["manifest_token"] is not None:
                _fail("invalid_attempt_state")
    # Counts are not proof: every block must be decryptable and accounted for,
    # including a spurious category that a normal result query would not see.
    for block in rows("integration_source_blocks"):
        run = one("integration_action_runs", block["run_id"])
        value = opened(block["data_token"], f"connection-block/{block['id']}")
        if isinstance(value, dict) and value.get("format") == RESULT_FORMAT:
            identity = {name: block[name] for name in ("id", "run_id", "category", "sequence", "sha256", "byte_length")}
            identity["created_at"] = _stamp(block["created_at"])
            if value.get("identity") != identity or "integration_action_attempts" not in reflected:
                _fail("orphan_bound_result_block")
            category = block["category"]
            if not isinstance(category, str) or not category.startswith("attempt-") or not category[8:].isdigit():
                _fail("unknown_bound_result_category")
            attempts = reflected["integration_action_attempts"]
            attempt = connection.execute(select(attempts).where(attempts.c.run_id == run["id"],
                attempts.c.number == int(category[8:]))).mappings().first()
            if attempt is None or attempt["state"] != "finished" or not 0 <= block["sequence"] < attempt["result_blocks"]:
                _fail("unaccounted_result_block")
        elif isinstance(value, str):
            try:
                raw = base64.b64decode(value, validate=True)
            except (ValueError, binascii.Error):
                _fail("legacy_block_encoding")
            if not 0 < len(raw) <= BLOCK_BYTES or len(raw) != block["byte_length"] or hashlib.sha256(raw).hexdigest() != block["sha256"]:
                _fail("legacy_block_hash")
            result["legacy_id_only_records"] += 1
        else:
            _fail("invalid_private_block")
    if "integration_run_cursors" in reflected:
        for cursor in rows("integration_run_cursors"):
            run = one("integration_action_runs", cursor["run_id"])
            fingerprint = cursor["cursor_sha256"]
            if (not isinstance(fingerprint, str) or len(fingerprint) != 64
                    or any(character not in "0123456789abcdef" for character in fingerprint)
                    or not 1 <= cursor["first_attempt"] <= run["attempts"]):
                _fail("invalid_cursor_checkpoint")
    result["key_ids"] = sorted(result["key_ids"])
    return result


def mark_restored_connections_unconfirmed(connection, keys: list[secret_box.Key], *, step_bytes: int = 4 * 1024 * 1024) -> int:
    """Caller-owned offline transaction; complete proof precedes every mutation."""
    if not connection.in_transaction():
        raise ValueError("The restore caller must own an explicit transaction")
    report = verify_connection_state(connection, keys, step_bytes=step_bytes)
    if not report["present"]:
        return 0
    metadata = MetaData()
    runs = Table("integration_action_runs", metadata, autoload_with=connection)
    events = Table("integration_connection_events", metadata, autoload_with=connection)
    found = connection.execute(select(runs).where(runs.c.state == "executing").order_by(runs.c.id).with_for_update()).mappings()
    count = 0
    for run in found:
        moment = datetime.now(timezone.utc).replace(tzinfo=None)
        state = "unknown" if run["effect"] == "external_write" else "retryable"
        revision = run["revision"] + 1
        identifier = str(uuid4())
        identity = {"id": identifier, "connection_id": run["connection_id"], "run_id": run["id"],
                    "actor_id": "system:restore", "event_type": "restore_interrupted", "created_at": _stamp(moment)}
        detail = {"previous_revision": run["revision"], "revision": revision, "state": state, "automatic_retry": False}
        token = secret_box.seal_with(keys, _canonical({"format": EVENT_FORMAT, "identity": identity, "detail": detail}).decode(),
                                    f"connection-event/{identifier}")
        connection.execute(events.insert().values(**{**identity, "created_at": moment, "detail_token": token}))
        connection.execute(runs.update().where(runs.c.id == run["id"]).values(state=state, revision=revision,
            lease_token=None, lease_until=None, updated_at=moment,
            safe_summary="Vor Wiederherstellung unterbrochen. Ergebnis ausdrücklich prüfen; kein automatischer Neuversand."))
        count += 1
    return count
