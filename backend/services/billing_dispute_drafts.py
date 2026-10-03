"""Authorised private command envelopes; never execute a journal command.

The common draft core owns encryption, owner/grant binding and tab CAS. This
policy validates references inside its four scalar fields. In particular an
old, reviewed expected revision survives a lost successful response unchanged.
"""

import json
import re
from datetime import date

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, ValidationError

from ..db.billing_dispute_models import BillingDisputeEventORM as Event
from ..storage import NotFoundError
from . import billing_disputes as journal
from .billing_dispute_types import AppendDisputeEvent, OpenDispute
from .billing_dispute_validation import DisputeIntegrityError, digest, payload
from .billing_settlement import IMMUTABLE
from .billing_statement_parties import StatementPartyIntegrityError

COLLECTION = "billing/disputes"


class DisputeDraftValues(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    period_id: str
    case_id: str
    command_json: str
    review_json: str


def _invalid():
    return HTTPException(422, "Der Widerspruchsentwurf besitzt ungültige Felder oder eine widersprüchliche Zuordnung.")


def validate_identity(identity):
    if identity.entity_id is not None or not re.fullmatch(r"(?:open|event):[A-Za-z0-9_.:-]+", identity.form_key):
        raise _invalid()


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise _invalid()
        result[key] = value
    return result


def _constant(_value):
    raise _invalid()


def _json(value):
    try:
        result = json.loads(value, object_pairs_hook=_pairs, parse_constant=_constant)
    except (ValueError, TypeError, RecursionError):
        raise _invalid() from None
    if not isinstance(result, dict):
        raise _invalid()
    return result


def _identifier(value):
    return isinstance(value, str) and bool(re.fullmatch(r"[A-Za-z0-9_.:-]{1,100}", value))


def _command(value, opening):
    model = OpenDispute if opening else AppendDisputeEvent
    if not set(value) <= set(model.model_fields):
        raise _invalid()
    if not isinstance(value.get("idempotency_key"), str) or not 1 <= len(value["idempotency_key"]) <= 200 or not value["idempotency_key"].strip():
        raise _invalid()
    for key in ("reason", "received_on", "observed_on"):
        if key in value and not isinstance(value[key], str):
            raise _invalid()
    for key in ("expected_snapshot_hash", "preview_hash"):
        if value.get(key) is not None and not re.fullmatch(r"[0-9a-f]{64}", str(value[key])):
            raise _invalid()
    for key in ("expected_revision", "expected_statement_revision"):
        if value.get(key) is not None and (type(value[key]) is not int or value[key] < 1):
            raise _invalid()
    for key in ("period_id", "statement_id", "corrects_event_id", "correction_statement_id"):
        if value.get(key) is not None and not _identifier(value[key]):
            raise _invalid()
    evidence = value.get("evidence_version_ids", [])
    if not isinstance(evidence, list) or any(not _identifier(item) for item in evidence) or len(set(evidence)) != len(evidence):
        raise _invalid()
    if opening:
        if type(value.get("expected_case_revision", 0)) is not int or value.get("expected_case_revision", 0) != 0:
            raise _invalid()
        if value.get("case_kind", "tenant_statement") not in {"tenant_statement", "property_review"}:
            raise _invalid()
        positions = value.get("line_item_refs", [])
        if not isinstance(positions, list) or any(type(index) is not int or index < 0 for index in positions) or len(set(positions)) != len(positions):
            raise _invalid()
        if value.get("case_kind") == "property_review" and (value.get("statement_id") is not None or value.get("expected_statement_revision") is not None or positions):
            raise _invalid()
    elif (type(value.get("expected_revision")) is not int or value["expected_revision"] < 1
            or value.get("kind") not in {"note", "in_review", "correction", "withdrawn", "closed", "reopened", "correction_link"}):
        raise _invalid()
    return model


def _opening_binding(store, period, command):
    # Actual reference proof uses today's immutable original, while the user's
    # expected values remain exactly as entered in the encrypted draft.
    selected = command.get("statement_id")
    if command.get("case_kind", "tenant_statement") == "tenant_statement":
        if selected is None:
            return {"portfolio_id": store.get_property(period.property_id).portfolio_id,
                    "property_id": period.property_id, "tenant_id": None, "contract_id": None, "unit_id": None}
        statement = store.get_utility_statement(selected)
        verified = {**command, "expected_statement_revision": statement.revision, "expected_snapshot_hash": statement.snapshot_hash}
    else:
        original = {"period_id": period.id, "revision": period.revision_number, "owner_cost_share": period.owner_cost_share}
        verified = {**command, "expected_snapshot_hash": digest(original)}
    verified.update(reason="Private reference verification", received_on=date.today().isoformat(), preview_hash=None)
    return journal._original(store, period, OpenDispute.model_validate(verified))


def _references(store, case, command, binding):
    versions = [journal._evidence_version(store, binding, identifier) for identifier in command.get("evidence_version_ids", [])]
    correction = None
    if case is not None:
        target_id = command.get("corrects_event_id")
        if target_id:
            target = next(iter(journal._rows(store, Event, id=target_id, case_id=case.id)), None)
            if target is None:
                raise HTTPException(404, "Das zu berichtigende Originalereignis ist nicht mehr zugänglich.")
            journal._verified(store, case, target)
        if command.get("correction_statement_id"):
            reference = AppendDisputeEvent(expected_revision=case.revision, kind="correction_link",
                reason="Private reference verification", observed_on=date.today(),
                idempotency_key="draft-reference-verification", correction_statement_id=command["correction_statement_id"])
            correction = journal._append_preview(store, case, reference)["correction"]
    return [journal._evidence_manifest(version) for version in versions], correction


def _historical_head(store, case, revision):
    previous = None
    state = None
    rows = journal._rows(store, Event, case_id=case.id)
    try:
        for row in rows:
            if row.revision != (previous.revision + 1 if previous is not None else 1) or row.previous_hash != (previous.content_hash if previous is not None else None):
                raise DisputeIntegrityError("Die Ereigniskette des Widerspruchsentwurfs ist beschädigt.")
            journal._verified(store, case, row)
            state = journal.event_state(state, row.kind)
            previous = row
            if row.revision == revision:
                return row, state
    finally:
        close = getattr(rows, "close", None)
        if close is not None:
            close()
    raise _invalid()


def _review(store, case, command, model, review, binding, evidence, correction):
    complete = model.model_validate(command)
    if complete.preview_hash is None:
        raise _invalid()
    if case is None:
        if complete.expected_snapshot_hash != binding.get("snapshot_hash") or complete.expected_statement_revision != binding.get("statement_revision"):
            raise _invalid()
        expected = journal._preview(complete, binding, evidence)
    else:
        # Reconstruct the real former head without materialising the history or
        # rebasing onto a later event. Reuse the actual native preview encoder:
        # its date hashing/JSON projection is part of the established contract.
        previous, state = _historical_head(store, case, complete.expected_revision)
        old_binding = {**binding, "revision": complete.expected_revision, "state": state}
        expected = journal._preview(complete, old_binding, evidence, state=state,
                                    previous_hash=previous.content_hash, correction=correction)
    if review != expected or complete.preview_hash != expected["preview_hash"]:
        raise _invalid()
    # Validate real immutable file bytes as well as manifest identity for a
    # reviewed command. Editing does not repeatedly download/materialise them.
    if journal._evidence(store, binding, complete.evidence_version_ids) != evidence:
        raise _invalid()


def _envelope(store, identity, values, *, pending=False):
    envelope = DisputeDraftValues.model_validate(values)
    opening = identity.form_key.startswith("open:")
    if not _identifier(envelope.period_id) or opening != (envelope.case_id == ""):
        raise _invalid()
    if identity.form_key != ("open:" + envelope.period_id if opening else "event:" + envelope.case_id):
        raise _invalid()
    period = store.get_billing_period(envelope.period_id)
    store.get_portfolio(store.get_property(period.property_id).portfolio_id)
    if period.status not in IMMUTABLE:
        raise HTTPException(409, "Die Abrechnung ist nicht mehr als finalisiertes Original verfügbar.")
    case = None if opening else journal._case(store, envelope.case_id)
    if case is not None and case.period_id != period.id:
        raise _invalid()
    command = _json(envelope.command_json)
    model = _command(command, opening)
    if opening and command.get("period_id") != period.id:
        raise _invalid()
    binding = _opening_binding(store, period, command) if opening else payload(case)
    evidence, correction = _references(store, case, command, binding)
    if envelope.review_json:
        _review(store, case, command, model, _json(envelope.review_json), binding, evidence, correction)
    elif pending or command.get("preview_hash") is not None:
        raise _invalid()


def validate_resources(store, identity, value):
    validate_identity(identity)
    try:
        _envelope(store, identity, value.get("values", {}), pending=value.get("submission_pending", False))
        _envelope(store, identity, value.get("original_values", {}))
    except ValidationError:
        raise _invalid() from None
    except NotFoundError:
        raise HTTPException(404, "Eine Referenz des Widerspruchsentwurfs ist nicht mehr zugänglich.") from None
    except (DisputeIntegrityError, StatementPartyIntegrityError):
        raise HTTPException(503, "Das referenzierte Original kann nicht sicher geprüft werden. Originalbestand und Wiederherstellung prüfen.") from None
