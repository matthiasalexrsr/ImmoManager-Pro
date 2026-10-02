"""Offline journal verification. No auth/config imports or live store access."""

import hashlib
import json
import sqlite3
from collections.abc import Mapping
from contextlib import closing
from datetime import date, datetime, timezone
from types import SimpleNamespace
from urllib.parse import quote
from uuid import UUID

from sqlalchemy import inspect, text

from ..models import Contract
from .contract_lifecycle_types import Command, Confirmation, DraftCreate, DraftEdit, RenewalData, RevisionCommand

TABLES = ("contract_lifecycle_drafts", "contract_lifecycle_commands")
FINAL = frozenset({"confirmed", "pending_effective", "completed", "superseded"})


class JournalValidationError(ValueError):
    pass


def _hash(value) -> str:
    content = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _etag(identifier: str, updated_at) -> str:
    stamp = datetime.fromisoformat(updated_at.replace("Z", "+00:00")) if isinstance(updated_at, str) else updated_at
    stamp = stamp.replace(tzinfo=timezone.utc) if stamp.tzinfo is None else stamp.astimezone(timezone.utc)
    return f'"immo-v1:contracts:{quote(identifier, safe="")}:{stamp.isoformat(timespec="microseconds").replace("+00:00", "Z")}"'


def _check_etag(value, identifier: str) -> datetime:
    prefix = f'"immo-v1:contracts:{quote(identifier, safe="")}:'
    if not isinstance(value, str) or not value.startswith(prefix) or not value.endswith('"'):
        raise ValueError
    stamp = value[len(prefix):-1]
    if _etag(identifier, stamp) != value:
        raise ValueError
    return datetime.fromisoformat(stamp.replace("Z", "+00:00"))


def validate_draft_evidence(row) -> None:
    """Shared online/offline typed identity, review and accepted-result checks."""
    try:
        UUID(row.id)
        UUID(row.revision)
        _check_etag(row.source_contract_etag, row.contract_id)
        data = DraftCreate(idempotency_key=row.create_key, expected_contract_etag=row.source_contract_etag,
                           data=row.data).data
        if row.state not in FINAL | {"draft", "reviewed"}:
            raise ValueError
        if row.state == "draft":
            if row.review is not None or row.review_hash is not None or row.supersedes_draft_id is not None:
                raise ValueError
        else:
            if not isinstance(row.review, dict) or _hash(row.review) != row.review_hash:
                raise ValueError
            source = row.review["source_contract"]
            if not isinstance(source, dict) or not {"id", "created_at", "updated_at"} <= source.keys():
                raise ValueError
            contract = Contract.model_validate(source)
            if (contract.id, contract.property_id, contract.unit_id, contract.tenant_id) != (
                    row.contract_id, row.property_id, row.unit_id, row.tenant_id):
                raise ValueError
            if _etag(contract.id, contract.updated_at) != row.source_contract_etag:
                raise ValueError
            if row.review["source_contract_etag"] != row.source_contract_etag or row.review["data"] != data.model_dump(mode="json"):
                raise ValueError
            previous = row.review.get("supersedes")
            if row.supersedes_draft_id is not None:
                if not isinstance(previous, dict) or previous["id"] != row.supersedes_draft_id or isinstance(data, RenewalData):
                    raise ValueError
                UUID(row.supersedes_draft_id)
                previous_end = date.fromisoformat(previous["termination_end_date"])
                if previous_end != contract.end_date or data.termination_end_date >= previous_end:
                    raise ValueError
                previous_hash = previous["review_hash"]
                if not isinstance(previous_hash, str) or len(previous_hash) != 64 or any(c not in "0123456789abcdef" for c in previous_hash):
                    raise ValueError
            elif previous is not None:
                raise ValueError
        if row.state in FINAL:
            if not row.applied_contract_etag or (row.successor_contract_id is not None) != isinstance(data, RenewalData):
                raise ValueError
            _check_etag(row.applied_contract_etag, row.contract_id)
            if isinstance(data, RenewalData) != (row.state == "confirmed"):
                raise ValueError
        elif row.applied_contract_etag is not None or row.successor_contract_id is not None:
            raise ValueError
        if row.finalized_contract_etag is not None and row.state != "completed":
            raise ValueError
        if row.finalized_contract_etag is not None:
            if _check_etag(row.finalized_contract_etag, row.contract_id) <= _check_etag(row.applied_contract_etag, row.contract_id):
                raise ValueError
        if (row.superseded_by_draft_id is not None) != (row.state == "superseded"):
            raise ValueError
        if row.superseded_by_draft_id is not None:
            UUID(row.superseded_by_draft_id)
        if row.id in {row.supersedes_draft_id, row.superseded_by_draft_id}:
            raise ValueError
    except (ValueError, TypeError, KeyError, AttributeError):
        raise JournalValidationError("Contract lifecycle draft evidence is invalid") from None


def validate_supersession_evidence(row, previous) -> None:
    """Same-subject references, immutable predecessor proof and strict direction.

    Earlier dates strictly decrease along every accepted edge. This proves
    acyclicity without materializing an installation's complete history.
    Open reviews may legitimately become stale after another confirmation.
    """
    try:
        validate_draft_evidence(previous)
        keys = ("contract_id", "portfolio_id", "property_id", "unit_id", "tenant_id")
        if row.supersedes_draft_id != previous.id or any(getattr(row, key) != getattr(previous, key) for key in keys):
            raise ValueError
        reviewed = row.review["supersedes"]
        if reviewed != {"id": previous.id, "termination_end_date": previous.data["termination_end_date"],
                         "review_hash": previous.review_hash}:
            raise ValueError
        if row.data["termination_end_date"] >= previous.data["termination_end_date"]:
            raise ValueError
        if row.state in FINAL:
            if previous.state != "superseded" or previous.superseded_by_draft_id != row.id:
                raise ValueError
            old_applied = _check_etag(previous.applied_contract_etag, previous.contract_id)
            if (_check_etag(row.source_contract_etag, row.contract_id) < old_applied
                    or _check_etag(row.applied_contract_etag, row.contract_id) <= old_applied):
                raise ValueError
    except (ValueError, TypeError, KeyError, AttributeError):
        raise JournalValidationError("Contract lifecycle supersession evidence is invalid") from None


def validate_command_evidence(command, draft) -> None:
    try:
        UUID(command.id)
        classes: dict[str, type[Command]] = {"create": DraftCreate, "edit": DraftEdit, "review": RevisionCommand,
                                           "confirm": Confirmation, "finalize": Confirmation}
        cls = classes[command.operation]
        request = cls.model_validate(command.request)
        if request.idempotency_key != command.command_key or _hash({"operation": command.operation,
                "payload": request.model_dump(mode="json")}) != command.request_hash:
            raise ValueError
        result = command.result
        bindings = {"id": draft.id, "contract_id": draft.contract_id, "portfolio_id": draft.portfolio_id,
                    "property_id": draft.property_id, "unit_id": draft.unit_id, "tenant_id": draft.tenant_id,
                    "actor_id": draft.actor_id}
        if not isinstance(result, dict) or any(result.get(key) != value for key, value in bindings.items()):
            raise ValueError
        if command.contract_id != draft.contract_id or command.portfolio_id != draft.portfolio_id or command.draft_id != draft.id:
            raise ValueError
        if command.operation != "finalize" and command.actor_id != draft.actor_id:
            raise ValueError
        validate_draft_evidence(SimpleNamespace(**{**result, "create_key": draft.create_key}))
        expected = _check_etag(request.expected_contract_etag, draft.contract_id)
        if command.operation != "finalize" and result["source_contract_etag"] != request.expected_contract_etag:
            raise ValueError
        if isinstance(request, (DraftCreate, DraftEdit)) and result["data"] != request.data.model_dump(mode="json"):
            raise ValueError
        if command.operation in {"create", "edit"} and result["state"] != "draft":
            raise ValueError
        if command.operation == "review" and result["state"] != "reviewed":
            raise ValueError
        if command.operation in {"confirm", "finalize"}:
            if not isinstance(request, Confirmation):
                raise ValueError
            if result["review_hash"] != request.reviewed_hash or result["review_hash"] != draft.review_hash or result["data"] != draft.data:
                raise ValueError
            if result["state"] not in {"confirmed", "pending_effective", "completed"} or (command.operation == "finalize" and result["state"] != "completed"):
                raise ValueError
            applied = _check_etag(result["applied_contract_etag"], draft.contract_id)
            if command.operation == "confirm" and (applied < expected or result["finalized_contract_etag"] is not None):
                raise ValueError
            if command.operation == "finalize" and (result["finalized_contract_etag"] is None
                    or _check_etag(result["finalized_contract_etag"], draft.contract_id) <= expected):
                raise ValueError
    except (ValueError, TypeError, KeyError, AttributeError):
        raise JournalValidationError("Contract lifecycle command evidence is invalid") from None


def _rows(connection, sql: str, params=None):
    """Bounded page fetching; connection belongs to the offline caller."""
    if isinstance(connection, sqlite3.Connection):
        result = connection.execute(sql, params or {})
        names = [field[0] for field in result.description]
        with closing(result):
            while page := result.fetchmany(100):
                for row in page:
                    yield dict(zip(names, row, strict=True))
    else:
        result = connection.execute(text(sql).execution_options(stream_results=True), params or {})
        with closing(result):
            while page := result.fetchmany(100):
                for row in page:
                    yield dict(row._mapping)


def _one(connection, sql: str, params=None):
    with closing(_rows(connection, sql, params)) as records:
        return next(records, None)


def _object(values: Mapping, json_fields):
    record = dict(values)
    for key in json_fields:
        if isinstance(record.get(key), str):
            try:
                record[key] = json.loads(record[key])
            except ValueError:
                raise JournalValidationError("Contract lifecycle JSON is invalid") from None
    return SimpleNamespace(**record)


def validate_lifecycle_journal(connection) -> bool:
    """Verify the entire offline journal before session invalidation/publication.

    Returns False for a fully pre-z1 archive; a partial pair always fails.
    This never alters immutable snapshots or current contract values.
    """
    names = ({row["name"] for row in _rows(connection, "SELECT name FROM sqlite_master WHERE type='table'")}
             if isinstance(connection, sqlite3.Connection) else set(inspect(connection).get_table_names()))
    if not names & set(TABLES):
        return False
    if not set(TABLES) <= names:
        raise JournalValidationError("Incomplete contract lifecycle journal schema")
    try:
        for values in _rows(connection, "SELECT * FROM contract_lifecycle_drafts ORDER BY id"):
            row = _object(values, ("data", "review"))
            validate_draft_evidence(row)
            current = _one(connection, "SELECT c.property_id,c.unit_id,c.tenant_id,p.portfolio_id "
                "FROM contracts c JOIN properties p ON p.id=c.property_id JOIN units u ON u.id=c.unit_id "
                "AND u.property_id=p.id JOIN tenants t ON t.id=c.tenant_id WHERE c.id=:id", {"id": row.contract_id})
            if current is None or any(current[key] != getattr(row, key) for key in current):
                raise JournalValidationError("Contract lifecycle subject binding is invalid")
            if row.supersedes_draft_id is not None:
                values = _one(connection, "SELECT * FROM contract_lifecycle_drafts WHERE id=:id",
                              {"id": row.supersedes_draft_id})
                if values is None:
                    raise JournalValidationError("Contract lifecycle supersession is orphaned")
                validate_supersession_evidence(row, _object(values, ("data", "review")))
            if row.superseded_by_draft_id is not None:
                values = _one(connection, "SELECT * FROM contract_lifecycle_drafts WHERE id=:id",
                              {"id": row.superseded_by_draft_id})
                if values is None:
                    raise JournalValidationError("Contract lifecycle supersession is orphaned")
                following = _object(values, ("data", "review"))
                validate_draft_evidence(following)
                if following.state not in FINAL:
                    raise JournalValidationError("Contract lifecycle supersession is not confirmed")
                validate_supersession_evidence(following, row)
            if row.state in {"pending_effective", "completed"}:
                actual = _one(connection, "SELECT end_date,status FROM contracts WHERE id=:id", {"id": row.contract_id})
                end = actual["end_date"]
                end = end.isoformat() if isinstance(end, date) else end
                if end != row.data["termination_end_date"] or actual["status"] != (
                        "active" if row.state == "pending_effective" else "terminated"):
                    raise JournalValidationError("Contract lifecycle accepted end or state contradicts its contract")
                another = _one(connection, "SELECT 1 FROM contract_lifecycle_drafts WHERE contract_id=:contract "
                    "AND state IN ('pending_effective','completed') AND id<>:id LIMIT 1",
                    {"contract": row.contract_id, "id": row.id})
                if another is not None:
                    raise JournalValidationError("Contract lifecycle has multiple current termination confirmations")
            if row.successor_contract_id is not None:
                successor = _one(connection, "SELECT property_id,unit_id,tenant_id FROM contracts WHERE id=:id",
                                 {"id": row.successor_contract_id})
                if successor is None or any(successor[key] != getattr(row, key) for key in successor):
                    raise JournalValidationError("Contract lifecycle successor binding is invalid")
            counts = {"create": 0, "confirm": 0, "finalize": 0}
            for values in _rows(connection, "SELECT * FROM contract_lifecycle_commands WHERE draft_id=:id ORDER BY created_at,id", {"id": row.id}):
                command = _object(values, ("request", "result"))
                validate_command_evidence(command, row)
                if command.operation in counts:
                    counts[command.operation] += 1
                if command.operation == "create" and (command.command_key != row.create_key or command.request_hash != row.create_hash):
                    raise JournalValidationError("Contract lifecycle creation evidence is invalid")
            if counts["create"] != 1 or counts["confirm"] != int(row.state in FINAL) or counts["finalize"] != int(row.finalized_contract_etag is not None):
                raise JournalValidationError("Contract lifecycle confirmation history is incomplete")
        orphan = _one(connection, "SELECT 1 FROM contract_lifecycle_commands c LEFT JOIN contract_lifecycle_drafts d "
                                  "ON d.id=c.draft_id WHERE d.id IS NULL LIMIT 1")
        if orphan is not None:
            raise JournalValidationError("Contract lifecycle command is orphaned")
    except JournalValidationError:
        raise
    except (ValueError, TypeError, KeyError, AttributeError):
        raise JournalValidationError("Contract lifecycle journal is invalid") from None
    return True
