"""Checks of an archived maintenance protocol that need no running application.

The manifest of a protocol's original carries the protocol's content and its hash;
the hash must match the content and the archiving account, so a restore check
(document_version_validation.verify_document_versions) proves the protocol as well.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from typing import Any

SCHEMA_VERSION = "maintenance-protocol/1"
DOC_TYPE = "maintenance_protocol"
_HASH = re.compile(r"[a-f0-9]{64}")
_KEYS = {"schema_version", "content", "content_sha256", "actor_id", "idempotency_key"}


class MaintenanceProtocolValidationError(ValueError):
    """The archived protocol evidence is inconsistent."""


def content_digest(content: Any) -> str:
    text = json.dumps(content, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(text.encode()).hexdigest()


def _value(row: Any, name: str) -> Any:
    return row.get(name) if isinstance(row, Mapping) else getattr(row, name, None)


def validate_maintenance_protocol_snapshot(row: Any, snapshot: Mapping[str, Any]) -> None:
    if snapshot.get("document_type") != DOC_TYPE:
        return
    extension = snapshot.get("maintenance_protocol")
    if not isinstance(extension, dict) or set(extension) != _KEYS:
        raise MaintenanceProtocolValidationError("invalid maintenance protocol evidence shape")
    content = extension["content"]
    if (extension["schema_version"] != SCHEMA_VERSION or not isinstance(content, dict)
            or content.get("format") != SCHEMA_VERSION
            or not isinstance(extension["content_sha256"], str) or not _HASH.fullmatch(extension["content_sha256"])
            or content_digest(content) != extension["content_sha256"]
            or extension["actor_id"] != _value(row, "actor_id")):
        raise MaintenanceProtocolValidationError("maintenance protocol evidence does not match")
