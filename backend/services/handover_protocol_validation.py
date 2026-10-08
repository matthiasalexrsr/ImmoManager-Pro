"""Pure validation of a finalized handover protocol's archived evidence.

The archived original of a handover protocol carries, next to the PDF, the
reviewed facts the PDF was rendered from (metadata `handover-protocol/1`). This
module checks that evidence against the generic version manifest; it runs on
live reads, on snapshot imports and on backup verification
(document_version_validation.validate_feature_snapshot).
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from .housing_confirmation_validation import digest

DOC_TYPE = "handover_protocol"
VIRTUAL_PREFIX = "handover-protocols/"
SCHEMA_VERSION = "handover-protocol/1"
PDF_FORMAT_VERSION = "handover-protocol-pdf/1"
_HASH = re.compile(r"^[a-f0-9]{64}$")
EXTENSION_KEYS = frozenset({"schema_version", "review", "review_hash", "request_sha256", "actor_id",
                            "idempotency_key", "protocol_id", "confirmed_content", "confirmed_signatures"})
REVIEW_KEYS = frozenset({"format_version", "protocol", "rooms", "defects", "keys", "meter_readings", "photos",
                         "source", "correction_of", "pdf_sha256"})
SOURCE_KEYS = frozenset({"portfolio", "property", "unit", "contract", "tenant", "etags"})


class HandoverValidationError(ValueError):
    pass


def _value(row: Any, name: str):
    return row.get(name) if isinstance(row, Mapping) else getattr(row, name, None)


def document_id_for(actor_id: str, command_key: str) -> str:
    """The same actor and command key always name the same document (safe retry)."""
    return str(uuid5(NAMESPACE_URL, f"immo-manager:handover-protocol:v1:{actor_id}:{command_key}"))


def finalize_request_hash(protocol_id: str, payload: Mapping[str, Any]) -> str:
    return digest({"operation": "finalize_handover_protocol", "protocol_id": protocol_id, "payload": dict(payload)})


def validate_handover_snapshot(row: Any, snapshot: Mapping[str, Any]) -> dict:
    """The extension of a handover protocol original, checked; {} for other documents."""
    if snapshot.get("document_type") != DOC_TYPE:
        return {}
    extension = snapshot.get("handover_protocol")
    if not isinstance(extension, dict) or set(extension) != EXTENSION_KEYS:
        raise HandoverValidationError("invalid handover protocol evidence shape")
    if extension["schema_version"] != SCHEMA_VERSION:
        raise HandoverValidationError("unsupported handover protocol schema")
    if (extension["actor_id"] != _value(row, "actor_id") or extension["request_sha256"] != _value(row, "request_sha256")
            or not isinstance(extension["review_hash"], str) or not _HASH.fullmatch(extension["review_hash"])
            or extension["confirmed_content"] is not True or extension["confirmed_signatures"] is not True):
        raise HandoverValidationError("invalid handover protocol finalization proof")
    review = extension["review"]
    if not isinstance(review, dict) or set(review) != REVIEW_KEYS:
        raise HandoverValidationError("invalid handover protocol review")
    if review["format_version"] != PDF_FORMAT_VERSION:
        raise HandoverValidationError("unsupported handover protocol PDF format")
    if review["pdf_sha256"] != _value(row, "sha256") or digest(review) != extension["review_hash"]:
        raise HandoverValidationError("handover protocol review hash mismatch")
    protocol = review["protocol"]
    if not isinstance(protocol, dict) or protocol.get("id") != extension["protocol_id"]:
        raise HandoverValidationError("handover protocol identity mismatch")
    if protocol.get("protocol_type") not in ("move_in", "move_out") or not isinstance(protocol.get("protocol_date"), str):
        raise HandoverValidationError("invalid handover protocol header")
    for name in ("rooms", "defects", "keys", "meter_readings", "photos"):
        parts = review[name]
        if not isinstance(parts, list) or not all(isinstance(part, dict) and isinstance(part.get("id"), str)
                                                  for part in parts):
            raise HandoverValidationError("invalid handover protocol parts")
    for photo in review["photos"]:
        if not isinstance(photo.get("sha256"), str) or not _HASH.fullmatch(photo["sha256"]):
            raise HandoverValidationError("invalid handover protocol photo")
    source = review["source"]
    if not isinstance(source, dict) or set(source) != SOURCE_KEYS or not all(
            isinstance(source[name], dict) for name in SOURCE_KEYS):
        raise HandoverValidationError("invalid handover protocol source snapshot")
    expected = {"portfolio": _value(row, "portfolio_id"), "property": _value(row, "property_id"),
                "unit": _value(row, "unit_id"), "contract": _value(row, "contract_id"),
                "tenant": _value(row, "tenant_id")}
    if any(source[name].get("id") != identifier for name, identifier in expected.items()):
        raise HandoverValidationError("handover protocol source identity mismatch")
    contract = source["contract"]
    if (contract.get("property_id") != expected["property"] or contract.get("unit_id") != expected["unit"]
            or contract.get("tenant_id") != expected["tenant"]
            or source["unit"].get("property_id") != expected["property"]
            or source["property"].get("portfolio_id") != expected["portfolio"]):
        raise HandoverValidationError("handover protocol source relationship mismatch")
    correction = review["correction_of"]
    if correction is not None and (not isinstance(correction, dict) or not all(
            isinstance(correction.get(name), str) for name in ("protocol_id", "document_id", "version_id"))):
        raise HandoverValidationError("invalid handover protocol correction reference")

    document_id = _value(row, "document_id")
    key, actor_id = extension["idempotency_key"], extension["actor_id"]
    if (not isinstance(key, str) or not 1 <= len(key) <= 100 or not isinstance(actor_id, str) or not actor_id
            or document_id != document_id_for(actor_id, key)
            or _value(row, "idempotency_key") != "generated-" + document_id):
        raise HandoverValidationError("handover protocol command identity mismatch")
    if (snapshot.get("id") != document_id or snapshot.get("contract_id") != expected["contract"]
            or snapshot.get("property_id") != expected["property"] or snapshot.get("unit_id") != expected["unit"]
            or snapshot.get("file_url") != f"/uploads/{VIRTUAL_PREFIX}{document_id}.pdf"
            or snapshot.get("document_date") != protocol["protocol_date"]):
        raise HandoverValidationError("handover protocol document binding mismatch")
    payload = {"idempotency_key": key, "review_hash": extension["review_hash"], "confirmed_content": True,
               "confirmed_signatures": True}
    if finalize_request_hash(extension["protocol_id"], payload) != extension["request_sha256"]:
        raise HandoverValidationError("handover protocol request hash mismatch")
    return extension
