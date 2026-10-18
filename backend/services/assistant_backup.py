"""Offline assistant snapshot inventory/proof using explicitly supplied archive keys.

No application store, auth session, provider, default keyring or scheduler is
imported. Callers own the snapshot, restored upload directory and transaction.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, NoReturn

from sqlalchemy import MetaData, Table, create_engine, inspect, select, update
from sqlalchemy.pool import NullPool

from . import secret_box
from .file_storage import validate_key

TABLES = ("assistant_conversations", "assistant_messages", "assistant_runs", "assistant_attachments", "assistant_proposals")
VAULT_PREFIX = "assistant-private/_vault/"
AUTH_FILES = {"codex": {"auth.json"}, "claude": {".credentials.json", ".claude.json"}}


class AssistantBackupError(ValueError):
    """Only a stable diagnostic code may leave the private verification layer."""


def _fail(code: str) -> NoReturn:
    raise AssistantBackupError(code)


def _json(value: str | bytes) -> dict:
    def constant(_value):
        _fail("invalid_json_constant")
    try:
        data = json.loads(value, parse_constant=constant)
    except (ValueError, TypeError, UnicodeError, RecursionError):
        _fail("invalid_private_json")
    if not isinstance(data, dict):
        _fail("invalid_private_json")
    return data


def _open(keys: list[secret_box.Key], token: str, context: str) -> dict:
    try:
        return _json(secret_box.open_with(keys, token, context))
    except (secret_box.SecretError, ValueError, TypeError):
        _fail("private_payload_unreadable")


def _context(table: str, row: dict) -> str:
    return f"assistant/{table}/{row['owner_id']}/{row['id']}/" + (row.get("conversation_id") or "")


def _attachment(data: dict, owner: str) -> str:
    try:
        key = validate_key(data["_storage_key"])
        prefix = "assistant-private/files/" + hashlib.sha256(owner.encode()).hexdigest() + "/"
        if not key.startswith(prefix) or not re.fullmatch(r"[0-9a-f]{32}", key[len(prefix):]):
            _fail("attachment_owner_mismatch")
        if (type(data.get("byte_length")) is not int or data["byte_length"] <= 0
                or not isinstance(data.get("sha256"), str) or not re.fullmatch(r"[0-9a-f]{64}", data["sha256"])):
            _fail("invalid_attachment_metadata")
        return key
    except (KeyError, TypeError, ValueError):
        _fail("invalid_attachment_metadata")


def _verify_file(uploads: Path, key: str, data: dict) -> None:
    path = uploads / key
    try:
        if path.is_symlink() or not path.resolve().is_relative_to(uploads.resolve()) or not path.is_file():
            _fail("attachment_original_missing")
        digest, length = hashlib.sha256(), 0
        with path.open("rb") as stream:
            while block := stream.read(64 * 1024):
                digest.update(block)
                length += len(block)
        if length != data["byte_length"] or digest.hexdigest() != data["sha256"]:
            _fail("attachment_original_changed")
    except OSError:
        _fail("attachment_original_missing")


def _vault(key: str, raw: bytes, keys: list[secret_box.Key]) -> str:
    parts = key.split("/")
    if (len(parts) != 4 or parts[:2] != ["assistant-private", "_vault"]
            or not re.fullmatch(r"[0-9a-f]{64}", parts[2]) or parts[3] not in {"codex.json", "claude.json"}):
        _fail("invalid_vault_path")
    provider = parts[3][:-5]
    envelope = _json(raw)
    if envelope.get("version") != 1 or not isinstance(envelope.get("sealed"), str):
        _fail("invalid_vault_envelope")
    data = _open(keys, envelope["sealed"], "assistant-account:v1:" + parts[2] + ":" + provider)
    if data.get("version") != 1 or not isinstance(data.get("files"), dict) or not isinstance(data.get("public"), dict):
        _fail("invalid_vault_payload")
    for name, encoded in data["files"].items():
        if name not in AUTH_FILES[provider] or not isinstance(encoded, str) or len(encoded) > 4_000_000:
            _fail("invalid_vault_credentials")
        try:
            credential = base64.b64decode(encoded, validate=True)
            if len(credential) > 3_000_000:
                _fail("invalid_vault_credentials")
        except (ValueError, TypeError):
            _fail("invalid_vault_credentials")
    return secret_box.token_key_id(envelope["sealed"])


def capture_vaults(uploads: Path, keys: list[secret_box.Key]) -> tuple[dict[str, bytes], set[str]]:
    """Snapshot the exact encrypted bytes later written to the ZIP, not live paths."""
    root = uploads / "assistant-private" / "_vault"
    captured: dict[str, bytes] = {}
    identifiers: set[str] = set()
    if not root.exists():
        return captured, identifiers
    for path in sorted(root.rglob("*.json")):
        if path.is_symlink() or not path.resolve().is_relative_to(uploads.resolve()) or not path.is_file():
            _fail("invalid_vault_file")
        if path.stat().st_size > 9_000_000:
            _fail("invalid_vault_file")
        raw = path.read_bytes()
        key = path.relative_to(uploads).as_posix()
        identifiers.add(_vault(key, raw, keys))
        captured[key] = raw
    return captured, identifiers


def verify(connection, keys: list[secret_box.Key], *, uploads: Path | None = None, normalize: bool = False,
           check_files: bool = True) -> dict:
    """Decrypt all rows and verify ownership/parents before recovery transitions."""
    available = set(inspect(connection).get_table_names())
    present = available.intersection(TABLES)
    result: dict[str, Any] = {"present": bool(present), "rows": 0, "attachments": 0, "vaults": 0,
                              "restored_unknown": 0, "references": set(), "originals": {}, "vault_key_ids": set(), "table_counts": {}}
    if uploads is not None:
        vaults, ids = capture_vaults(uploads, keys)
        result.update(vaults=len(vaults), vault_key_ids=ids)
    if not present:
        return result
    if present != set(TABLES) or "users" not in available:
        _fail("partial_assistant_schema")
    metadata = MetaData()
    tables = {name: Table(name, metadata, autoload_with=connection) for name in (*TABLES, "users")}

    @lru_cache(maxsize=128)
    def one(table: str, identifier: str) -> dict:
        if not isinstance(identifier, str) or not identifier:
            _fail("invalid_assistant_reference")
        row = connection.execute(select(tables[table]).where(tables[table].c.id == identifier)).mappings().first()
        if row is None:
            _fail("missing_assistant_reference")
        return dict(row)

    def related(table: str, identifier: Any, child: dict) -> dict:
        parent = one(table, identifier)
        if parent["owner_id"] != child["owner_id"]:
            _fail("assistant_owner_mismatch")
        conversation = parent["id"] if table == "assistant_conversations" else parent["conversation_id"]
        if conversation != child.get("conversation_id", child["id"]):
            _fail("assistant_conversation_mismatch")
        return parent

    def refs(data: dict, field: str, table: str, row: dict) -> None:
        values = data.get(field, [])
        if not isinstance(values, list) or any(not isinstance(identifier, str) for identifier in values):
            _fail("invalid_assistant_reference")
        for identifier in values:
            related(table, identifier, row)

    active: list[tuple[dict, dict]] = []
    conversations: dict[str, tuple[dict, dict]] = {}
    for name in TABLES:
        count = 0
        rows = connection.execute(select(tables[name]).order_by(tables[name].c.id).execution_options(yield_per=64)).mappings()
        for raw in rows:
            row = dict(raw)
            if not isinstance(row["owner_id"], str) or not row["owner_id"] or type(row["revision"]) is not int or row["revision"] < 1:
                _fail("invalid_assistant_identity")
            one("users", row["owner_id"])
            if name != "assistant_conversations":
                related("assistant_conversations", row["conversation_id"], row)
            data = _open(keys, row["payload_token"], _context(name, row))
            if name == "assistant_conversations":
                if data.get("active_run_id"):
                    related("assistant_runs", data["active_run_id"], row)
                if normalize:
                    conversations[row["id"]] = row, data
            elif name == "assistant_attachments":
                key = _attachment(data, row["owner_id"])
                result["references"].add(key)
                expected = {field: data[field] for field in ("sha256", "byte_length")}
                if key in result["originals"] and result["originals"][key] != expected:
                    _fail("conflicting_attachment_original")
                result["originals"][key] = expected
                result["attachments"] += 1
                if check_files:
                    if uploads is None:
                        _fail("attachment_directory_required")
                    _verify_file(uploads, key, data)
            elif name == "assistant_runs":
                refs(data, "attachment_ids", "assistant_attachments", row)
                refs(data, "_proposal_ids", "assistant_proposals", row)
                for identifier in data.get("_proposal_ids", []):
                    proposed = one("assistant_proposals", identifier)
                    if _open(keys, proposed["payload_token"], _context("assistant_proposals", proposed)).get("run_id") != row["id"]:
                        _fail("assistant_proposal_run_mismatch")
                if data.get("retry_of"):
                    related("assistant_runs", data["retry_of"], row)
                if normalize and row["state"] in {"queued", "running"}:
                    active.append((row, data))
            elif name == "assistant_messages":
                if data.get("run_id"):
                    related("assistant_runs", data["run_id"], row)
                refs(data, "attachment_ids", "assistant_attachments", row)
            elif name == "assistant_proposals":
                related("assistant_runs", data.get("run_id"), row)
                if data.get("decision") and (not isinstance(data["decision"], dict) or data["decision"].get("actor_id") != row["owner_id"]):
                    _fail("assistant_decision_owner_mismatch")
                if data.get("handoff"):
                    handoff = data["handoff"]
                    if not isinstance(handoff, dict) or not isinstance(handoff.get("draft_id"), str) or "workspace_drafts" not in available:
                        _fail("assistant_draft_binding_missing")
                    if "workspace_drafts" not in tables:
                        tables["workspace_drafts"] = Table("workspace_drafts", metadata, autoload_with=connection)
                    draft = one("workspace_drafts", handoff["draft_id"])
                    if draft["owner_user_id"] != row["owner_id"]:
                        _fail("assistant_draft_owner_mismatch")
            count += 1
        result["table_counts"][name] = count
        result["rows"] += count
    if normalize:
        moment = datetime.now(timezone.utc).replace(tzinfo=None)

        def write(name: str, row: dict, data: dict, **values):
            token = secret_box.seal_with(keys, json.dumps(data, ensure_ascii=False, separators=(",", ":"), allow_nan=False), _context(name, row))
            connection.execute(update(tables[name]).where(tables[name].c.id == row["id"]).values(
                payload_token=token, revision=row["revision"] + 1, updated_at=moment, **values),
                execution_options={"stream_results": False, "yield_per": None})

        for row, data in active:
            data.pop("_lease", None)
            data["error"] = {"code": "restore_interrupted", "message": "Der Auftrag stammt aus einer Sicherung. Externen Ausgang prüfen und bei Bedarf ausdrücklich neu starten."}
            data["verification_status"] = "restored_unverified"
            data["_restore_blocked"] = {"previous_state": row["state"], "at": moment.isoformat()}
            write("assistant_runs", row, data, state="unknown")
            conversation, contents = conversations[row["conversation_id"]]
            if contents.get("active_run_id") == row["id"]:
                contents["active_run_id"] = None
        changed = {row["conversation_id"] for row, _ in active}
        for identifier in changed:
            row, data = conversations[identifier]
            write("assistant_conversations", row, data)
        result["restored_unknown"] = len(active)
    return result


def inventory(database, keys: list[secret_box.Key]) -> dict:
    """The caller supplies a consistent copied DB or its exported PG snapshot."""
    if isinstance(database, Path):
        engine = create_engine(f"sqlite:///{database.resolve().as_posix()}", poolclass=NullPool)
        try:
            with engine.connect() as connection:
                result = verify(connection, keys, check_files=False)
        finally:
            engine.dispose()
    else:
        result = verify(database, keys, check_files=False)
    return {field: result[field] for field in ("references", "originals")}


def references(database, keys: list[secret_box.Key]) -> set[str]:
    return inventory(database, keys)["references"]
