"""Offline, bounded correspondence evidence checks. No auth or store imports."""

import sqlite3
import time
from copy import deepcopy
from datetime import date, datetime, timezone
from types import SimpleNamespace
from typing import Any
from uuid import UUID

from sqlalchemy import inspect
from sqlalchemy.exc import SQLAlchemyError

from ..models import Contract
from .contract_correspondence_types import (
    ApproveLetter,
    CreateLetter,
    EditLetter,
    LetterData,
    ManualEvent,
    RevisionCommand,
)
from .contract_lifecycle_validation import (
    _check_etag,
    _etag,
    _hash,
    _object,
    _one,
    _rows,
    validate_command_evidence,
)
from .document_version_validation import verify_document_versions
from .recovery_archive import RecoveryError

TABLES = ("contract_correspondence_drafts", "contract_correspondence_commands", "contract_correspondence_events")
BINDING = ("portfolio_id", "contract_id", "property_id", "unit_id", "tenant_id")


class EvidenceError(ValueError):
    pass


def validate_draft(row):
    try:
        UUID(row.id)
        UUID(row.revision)
        _check_etag(row.source_contract_etag, row.contract_id)
        data = LetterData.model_validate(row.data)
        day = date.fromisoformat(row.deadline_date) if isinstance(row.deadline_date, str) else row.deadline_date
        if day != data.deadline_date or row.state not in {"draft", "reviewed", "approved"}:
            raise ValueError
        if row.state == "draft":
            if row.review is not None or row.review_hash is not None:
                raise ValueError
        else:
            review = row.review
            if not isinstance(review, dict) or _hash(review) != row.review_hash or review["data"] != row.data:
                raise ValueError
            contract = Contract.model_validate(review["source_contract"])
            if (contract.id, contract.property_id, contract.unit_id, contract.tenant_id) != (
                    row.contract_id, row.property_id, row.unit_id, row.tenant_id):
                raise ValueError
            if review["source_contract_etag"] != row.source_contract_etag or review["source_context"]["portfolio_id"] != row.portfolio_id:
                raise ValueError
            if _etag(contract.id, contract.updated_at) != row.source_contract_etag:
                raise ValueError
            _check_etag(review["source_contract_etag"], row.contract_id)
            # The immutable original bytes, not a future ReportLab release,
            # are authoritative. Offline verification checks this bound SHA
            # against the complete archived original below.
            checksum = review["pdf_sha256"]
            if not isinstance(checksum, str) or len(checksum) != 64 or any(char not in "0123456789abcdef" for char in checksum):
                raise ValueError
            if not isinstance(review["rendered_body"], str) or not review["rendered_body"].strip():
                raise ValueError
            if (data.template_id is None) != (review["template"] is None) or (data.lifecycle_command_id is None) != (review["lifecycle"] is None):
                raise ValueError
            if data.template_id and review["template"]["id"] != data.template_id:
                raise ValueError
            if data.lifecycle_command_id and review["lifecycle"]["command_id"] != data.lifecycle_command_id:
                raise ValueError
        if row.state == "approved":
            if not row.document_id or not row.document_version_id or row.approved_at is None:
                raise ValueError
        elif row.document_id is not None or row.document_version_id is not None or row.approved_at is not None:
            raise ValueError
    except (ValueError, TypeError, KeyError, AttributeError):
        raise EvidenceError("Contract correspondence draft evidence is invalid") from None


def validate_event(event, draft, dispatch=None):
    try:
        UUID(event.id)
        data = ManualEvent.model_validate(event.data)
        if draft.state != "approved" or any(getattr(event, key) != getattr(draft, key) for key in ("contract_id", "portfolio_id")) or event.draft_id != draft.id:
            raise ValueError
        if event.document_version_id != draft.document_version_id or event.review_hash != draft.review_hash:
            raise ValueError
        if type(event.event_revision) is not int or event.event_revision != data.expected_event_revision + 1:
            raise ValueError
        if data.expected_revision != draft.revision:
            raise ValueError
        if data.event_date < date.fromisoformat(draft.data["letter_date"]):
            raise ValueError
        if data.kind == "received":
            if dispatch is None or dispatch.id != data.dispatch_event_id or dispatch.draft_id != draft.id or dispatch.portfolio_id != draft.portfolio_id:
                raise ValueError
            sent = ManualEvent.model_validate(dispatch.data)
            if sent.kind != "dispatched" or data.event_date < sent.event_date or dispatch.event_revision >= event.event_revision:
                raise ValueError
    except (ValueError, TypeError, KeyError, AttributeError):
        raise EvidenceError("Contract correspondence event evidence is invalid") from None


def event_public(event):
    stamp = datetime.fromisoformat(event.created_at) if isinstance(event.created_at, str) else event.created_at
    return {"id": event.id, "event_revision": event.event_revision, "data": deepcopy(event.data),
        "actor_id": event.actor_id, "created_at": stamp.replace(tzinfo=timezone.utc).isoformat(), "policy": "manual_observation_only"}


def draft_public(found, persistent):
    def stamp(value):
        value = datetime.fromisoformat(value) if isinstance(value, str) else value
        return value.replace(tzinfo=timezone.utc).isoformat()
    return {key: deepcopy(getattr(found, key)) for key in ("id", "contract_id", "portfolio_id", "property_id", "unit_id", "tenant_id",
        "actor_id", "revision", "state", "data", "source_contract_etag", "review", "review_hash", "document_id", "document_version_id")} | {
        "created_at": stamp(found.created_at), "approved_at": stamp(found.approved_at) if found.approved_at else None,
        "persistent": persistent, "delivery_policy": "manual_observation_only",
        "download_url": f"/documents/{found.document_id}/versions/{found.document_version_id}/download" if found.document_id else None}


def validate_event_response(command, event):
    """Exact replay must describe the very same immutable observation."""
    try:
        if event is None or (event.id, event.draft_id, event.contract_id, event.portfolio_id, event.actor_id) != (
                command.result["event"]["id"], command.draft_id, command.contract_id, command.portfolio_id, command.actor_id):
            raise ValueError
        if event.data != command.request or command.result["event"] != event_public(event):
            raise ValueError
    except (ValueError, TypeError, KeyError, AttributeError):
        raise EvidenceError("Contract correspondence manual response is not backed by its event") from None


def validate_review_binding(draft, *, expected_revision, review_revision, review_hash):
    """Metadata-only proof for an already authorized current review subject.

    Callers must select exactly one review command for this draft/actor/subject.
    No private draft text is required by this binding check.
    """
    try:
        UUID(expected_revision)
        if draft.state not in {"reviewed", "approved"} or review_revision != expected_revision or review_hash != draft.review_hash:
            raise ValueError
    except (ValueError, TypeError, AttributeError):
        raise EvidenceError("Contract correspondence current review binding is invalid") from None


def validate_command(command, draft):
    try:
        UUID(command.id)
        cls: Any = {"create": CreateLetter, "edit": EditLetter, "review": RevisionCommand, "approve": ApproveLetter, "event": ManualEvent}[command.operation]
        request = cls.model_validate(command.request)
        if request.idempotency_key != command.command_key or _hash({"operation": command.operation, "payload": request.model_dump(mode="json")}) != command.request_hash:
            raise ValueError
        result = command.result
        if any(result[key] != getattr(draft, key) for key in BINDING + ("id", "actor_id")):
            raise ValueError
        if (command.draft_id, command.contract_id, command.portfolio_id) != (draft.id, draft.contract_id, draft.portfolio_id):
            raise ValueError
        if command.operation != "event" and command.actor_id != draft.actor_id:
            raise ValueError
        earlier = SimpleNamespace(**{**result, "deadline_date": result["data"]["deadline_date"]})
        validate_draft(earlier)
        if command.operation != "event" and request.expected_contract_etag != result["source_contract_etag"]:
            raise ValueError
        if command.operation == "create" and (command.command_key != draft.create_key or command.request_hash != draft.create_hash or result["state"] != "draft" or
                request.data.model_dump(mode="json") != result["data"]):
            raise ValueError
        if command.operation == "edit" and (request.data.model_dump(mode="json") != result["data"] or result["state"] != "draft"):
            raise ValueError
        if command.operation == "review" and result["state"] != "reviewed":
            raise ValueError
        if command.operation == "approve" and (not request.confirmed or result["state"] != "approved" or result["revision"] != draft.revision or
                request.reviewed_hash != draft.review_hash or result["review_hash"] != draft.review_hash or result["document_version_id"] != draft.document_version_id):
            raise ValueError
        if command.operation == "event" and result["state"] != "approved":
            raise ValueError
        if command.operation in {"approve", "event"}:
            if type(result["persistent"]) is not bool or {key: value for key, value in result.items() if key != "event"} != draft_public(draft, result["persistent"]):
                raise ValueError
    except (ValueError, TypeError, KeyError, AttributeError):
        raise EvidenceError("Contract correspondence command evidence is invalid") from None


def validate_correspondence_journal(connection, *, deadline=None):
    names = ({value["name"] for value in _rows(connection, "SELECT name FROM sqlite_master WHERE type='table'")}
             if isinstance(connection, sqlite3.Connection) else set(inspect(connection).get_table_names()))
    if not set(TABLES) & names:
        return False
    if not set(TABLES) <= names:
        raise EvidenceError("Incomplete contract correspondence journal")
    def remaining():
        if deadline is not None and time.monotonic() >= deadline:
            raise EvidenceError("Contract correspondence verification deadline exceeded")
    verified_documents = False
    try:
        for values in _rows(connection, "SELECT * FROM contract_correspondence_drafts ORDER BY id"):
            remaining()
            draft = _object(values, ("data", "review"))
            validate_draft(draft)
            current = _one(connection, "SELECT c.property_id,c.unit_id,c.tenant_id,p.portfolio_id FROM contracts c "
                "JOIN properties p ON p.id=c.property_id JOIN units u ON u.id=c.unit_id AND u.property_id=p.id "
                "JOIN tenants t ON t.id=c.tenant_id WHERE c.id=:id", {"id": draft.contract_id})
            if current is None or any(current[key] != getattr(draft, key) for key in current):
                raise EvidenceError("Contract correspondence subject binding is invalid")
            counts = {"create": 0, "approve": 0, "event": 0}
            # Causal revision identity, not wall-clock order, binds approval to
            # the exact private review that preceded it. Stream all candidates
            # without retaining a dictionary of the letter's entire history.
            approval = _one(connection, "SELECT request FROM contract_correspondence_commands WHERE draft_id=:id AND operation='approve'", {"id": draft.id})
            reviewed_revision = (_object(approval, ("request",)).request["expected_revision"] if approval else
                draft.revision if draft.state == "reviewed" else None)
            matching_review = 0
            for values in _rows(connection, "SELECT * FROM contract_correspondence_commands WHERE draft_id=:id ORDER BY created_at,id", {"id": draft.id}):
                remaining()
                command = _object(values, ("request", "result"))
                validate_command(command, draft)
                if command.operation in counts:
                    counts[command.operation] += 1
                if command.operation == "review" and command.result["revision"] == reviewed_revision:
                    validate_review_binding(draft, expected_revision=reviewed_revision,
                        review_revision=command.result["revision"], review_hash=command.result["review_hash"])
                    matching_review += 1
                if command.operation == "event":
                    event = _one(connection, "SELECT * FROM contract_correspondence_events WHERE id=:id AND draft_id=:draft", {"id": command.result["event"]["id"], "draft": draft.id})
                    validate_event_response(command, _object(event, ("data",)) if event else None)
            if counts["create"] != 1 or counts["approve"] != int(draft.state == "approved"):
                raise EvidenceError("Contract correspondence approval history is incomplete")
            if draft.state in {"reviewed", "approved"} and matching_review != 1:
                raise EvidenceError("Contract correspondence current review history is incomplete")
            if draft.review is not None:
                linked = draft.review["lifecycle"]
                if linked:
                    command = _one(connection, "SELECT * FROM contract_lifecycle_commands WHERE id=:id", {"id": linked["command_id"]})
                    parent = _one(connection, "SELECT * FROM contract_lifecycle_drafts WHERE id=:id", {"id": linked["draft_id"]})
                    if command is None or parent is None:
                        raise EvidenceError("Contract correspondence lifecycle evidence is orphaned")
                    command, parent = _object(command, ("request", "result")), _object(parent, ("data", "review"))
                    validate_command_evidence(command, parent)
                    if command.contract_id != draft.contract_id or command.portfolio_id != draft.portfolio_id or command.operation not in {"confirm", "finalize"} or parent.review_hash != linked["review_hash"] or _hash(command.result) != linked["result_hash"]:
                        raise EvidenceError("Contract correspondence lifecycle evidence is invalid")
                template = draft.review["template"]
                if template:
                    value = _one(connection, "SELECT id,portfolio_id,root_id,version,title,body FROM contract_template_versions WHERE id=:id", {"id": template["id"]})
                    if value is None or value["portfolio_id"] != draft.portfolio_id or {key: value[key] for key in ("id", "root_id", "version", "title")} | {"body_sha256": _hash(value["body"])} != template:
                        raise EvidenceError("Contract correspondence template evidence is invalid")
            if draft.state == "approved":
                if not verified_documents:
                    verify_document_versions(connection, deadline=deadline)
                    verified_documents = True
                version = _one(connection, "SELECT document_id,portfolio_id,property_id,unit_id,contract_id,tenant_id,number,operation,sha256 FROM document_versions WHERE id=:id", {"id": draft.document_version_id})
                if version is None or version["document_id"] != draft.document_id or any(version[key] != getattr(draft, key) for key in BINDING) or version["number"] != 1 or version["operation"] != "archive_original" or version["sha256"] != draft.review["pdf_sha256"]:
                    raise EvidenceError("Contract correspondence approved original is invalid")
            position = 0
            for values in _rows(connection, "SELECT * FROM contract_correspondence_events WHERE draft_id=:id ORDER BY event_revision", {"id": draft.id}):
                remaining()
                event = _object(values, ("data",))
                sent = _one(connection, "SELECT * FROM contract_correspondence_events WHERE id=:id", {"id": event.data["dispatch_event_id"]}) if event.data["dispatch_event_id"] else None
                validate_event(event, draft, _object(sent, ("data",)) if sent else None)
                position += 1
                if event.event_revision != position:
                    raise EvidenceError("Contract correspondence event chain is incomplete")
            if position != counts["event"]:
                raise EvidenceError("Contract correspondence event commands are incomplete")
        for table in TABLES[1:]:
            if _one(connection, f"SELECT 1 FROM {table} c LEFT JOIN {TABLES[0]} d ON c.draft_id=d.id WHERE d.id IS NULL LIMIT 1"):
                raise EvidenceError("Contract correspondence journal is orphaned")
    except EvidenceError:
        raise
    except (ValueError, TypeError, KeyError, AttributeError, sqlite3.Error, SQLAlchemyError, RecoveryError):
        raise EvidenceError("Contract correspondence journal is invalid") from None
    return True
