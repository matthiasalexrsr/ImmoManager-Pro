"""Pure validation of a finalized dunning letter's archived evidence.

The archived original of a dunning letter carries, next to the PDF, the reviewed
content the PDF was rendered from (metadata `dunning-letter/1`): the claims with
their amounts and receivables, fee and interest. This module checks that evidence
against the generic version manifest; it runs on live reads, snapshot imports and
backup verification (document_version_validation.validate_feature_snapshot).
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from ..domain.dunning_process import digest

DOC_TYPE = "dunning_letter"
VIRTUAL_PREFIX = "dunning-letters/"
SCHEMA_VERSION = "dunning-letter/1"
PDF_FORMAT_VERSION = "dunning-letter-pdf/1"
_HASH = re.compile(r"^[a-f0-9]{64}$")
EXTENSION_KEYS = frozenset({"schema_version", "content", "draft_hash", "request_sha256", "actor_id", "command_key",
                            "letter_id", "case_id", "reference", "stage", "claim_keys", "receivable_ids",
                            "charge_receivable_ids", "confirmed"})


class DunningLetterValidationError(ValueError):
    pass


def _value(row: Any, name: str):
    return row.get(name) if isinstance(row, Mapping) else getattr(row, name, None)


def document_id_for(actor_id: str, command_key: str) -> str:
    """The same actor and command key always name the same document (safe retry)."""
    return str(uuid5(NAMESPACE_URL, f"immo-manager:dunning-letter:v1:{actor_id}:{command_key}"))


def finalize_request_hash(letter_id: str, payload: Mapping[str, Any]) -> str:
    return digest({"operation": "finalize_dunning_letter", "letter_id": letter_id, "payload": dict(payload)})


def validate_dunning_letter_snapshot(row: Any, snapshot: Mapping[str, Any]) -> dict:
    """The extension of a dunning letter original, checked; {} for other documents."""
    if snapshot.get("document_type") != DOC_TYPE:
        return {}
    extension = snapshot.get("dunning_letter")
    if not isinstance(extension, dict) or set(extension) != EXTENSION_KEYS:
        raise DunningLetterValidationError("invalid dunning letter evidence shape")
    if extension["schema_version"] != SCHEMA_VERSION or extension["confirmed"] is not True:
        raise DunningLetterValidationError("unsupported dunning letter schema")
    content = extension["content"]
    if (extension["actor_id"] != _value(row, "actor_id") or extension["request_sha256"] != _value(row, "request_sha256")
            or not isinstance(extension["draft_hash"], str) or not _HASH.fullmatch(extension["draft_hash"])
            or not isinstance(content, dict) or digest(content) != extension["draft_hash"]
            or content.get("format_version") != PDF_FORMAT_VERSION
            or content.get("reference") != extension["reference"] or content.get("stage") != extension["stage"]):
        raise DunningLetterValidationError("invalid dunning letter proof")
    document_id = _value(row, "document_id")
    if (document_id != document_id_for(extension["actor_id"], extension["command_key"])
            or snapshot.get("file_url") != f"/uploads/{VIRTUAL_PREFIX}{document_id}.pdf"
            or content.get("contract", {}).get("id") != _value(row, "contract_id")):
        raise DunningLetterValidationError("dunning letter bound to another document")
    keys = [line.get("key") for line in [*content.get("lines", []), *content.get("earlier_charges", [])]]
    if keys != extension["claim_keys"]:
        raise DunningLetterValidationError("dunning letter claims do not match")
    return extension
