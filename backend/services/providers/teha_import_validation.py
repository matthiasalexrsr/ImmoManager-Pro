"""Pure retained-evidence checks for locally imported TEHA originals."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from ...db.teha_receive_schema import validate_identity_binding
from .teha_receive_contract import digest

SCHEMA_VERSION = "teha-import/2"
_SHA = re.compile(r"^[a-f0-9]{64}$")
_TARGET_FIELD = {
    "property": "internal_property_id",
    "period": "billing_period_id",
    "unit": "unit_id",
    "user": "tenant_id",
    "technical_order": "task_id",
}
_MAPPING_BINDING_FIELDS = {
    "portfolio_id", "property_id", "unit_id", "tenant_id", "billing_period_id",
}


class TehaImportEvidenceError(ValueError):
    pass


def _field(value: Any, name: str):
    return value.get(name) if isinstance(value, Mapping) else getattr(value, name, None)


def _sha(value: Any) -> str:
    if not isinstance(value, str) or not _SHA.fullmatch(value):
        raise TehaImportEvidenceError("invalid TEHA evidence digest")
    return value


def mapping_reference(row: Any) -> tuple[dict[str, Any], str]:
    """Canonical immutable mapping reference. Raw provider data is never included."""
    kind = _field(row, "kind")
    target_field = _TARGET_FIELD.get(kind)
    targets = {name: _field(row, name) for name in _TARGET_FIELD.values()}
    if target_field is None or any(value is not None for name, value in targets.items() if name != target_field):
        raise TehaImportEvidenceError("invalid kind-specific mapping target")
    target = targets[target_field]
    if not isinstance(target, str) or not target:
        raise TehaImportEvidenceError("missing mapping target")
    identity = validate_identity_binding(
        kind,
        _field(row, "external_identity_json"),
        _field(row, "external_identity_hash"),
    )
    value = {
        "id": _field(row, "id"),
        "portfolio_id": _field(row, "portfolio_id"),
        "connection_key": _field(row, "connection_key"),
        "kind": kind,
        "external_identity_hash": _sha(_field(row, "external_identity_hash")),
        "external_identity": identity,
        "generation": _field(row, "generation"),
        "revision": _sha(_field(row, "revision")),
        "target_id": target,
        "source_history_run_id": _field(row, "source_history_run_id"),
        "source_sha256": _sha(_field(row, "source_sha256")),
    }
    if (
        not isinstance(value["id"], str)
        or not value["id"]
        or not isinstance(value["portfolio_id"], str)
        or not value["portfolio_id"]
        or not isinstance(value["connection_key"], str)
        or not value["connection_key"]
        or type(value["generation"]) is not int
        or value["generation"] < 1
        or not isinstance(value["source_history_run_id"], str)
        or not value["source_history_run_id"]
    ):
        raise TehaImportEvidenceError("invalid mapping reference")
    return value, digest(value)


def build_document_manifest(
    *,
    receipt_id: str,
    actor_id: str,
    command_sha256: str,
    connection_key: str,
    source_history_run_id: str,
    content_history_run_id: str,
    external_identity_hash: str,
    source_sha256: str,
    content_sha256: str,
    mapping_id: str,
    mapping_generation: int,
    mapping_sha256: str,
    local_binding: Mapping[str, Any],
    mapping_target_binding: Mapping[str, Any],
    document_type: str,
) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "receipt_id": receipt_id,
        "actor_id": actor_id,
        "command_sha256": _sha(command_sha256),
        "connection_key": connection_key,
        "source_history_run_id": source_history_run_id,
        "content_history_run_id": content_history_run_id,
        "external_identity_hash": _sha(external_identity_hash),
        "source_sha256": _sha(source_sha256),
        "content_sha256": _sha(content_sha256),
        "mapping_id": mapping_id,
        "mapping_generation": mapping_generation,
        "mapping_sha256": _sha(mapping_sha256),
        "mapping_target_binding": dict(mapping_target_binding),
        "document_type": document_type,
        "local_binding": {
            name: local_binding.get(name)
            for name in (
                "portfolio_id",
                "property_id",
                "unit_id",
                "contract_id",
                "tenant_id",
            )
        },
    }


def _validate_mapping_original_binding(reference, binding, mapping_binding) -> None:
    """Bind an original to a freshly checked kind-specific mapping parent context.

    Runtime callers read current parents/grants; an offline recovery caller must
    derive the same context from the selected image, never a runtime store.
    """
    if not isinstance(mapping_binding, Mapping) or set(mapping_binding) != _MAPPING_BINDING_FIELDS:
        raise TehaImportEvidenceError("invalid mapping target binding")
    if reference["portfolio_id"] != binding["portfolio_id"] or mapping_binding["portfolio_id"] != binding["portfolio_id"]:
        raise TehaImportEvidenceError("mapping/original portfolio mismatch")
    kind, target = reference["kind"], reference["target_id"]
    contexts = {
        "property": {"portfolio_id", "property_id"},
        "period": {"portfolio_id", "property_id", "billing_period_id"},
        "unit": {"portfolio_id", "property_id", "unit_id"},
        "user": {"portfolio_id", "tenant_id"},
    }
    if kind not in contexts:
        raise TehaImportEvidenceError("mapping target/original binding mismatch")
    relevant = contexts[kind]
    if any(value is not None for name, value in mapping_binding.items() if name not in relevant):
        raise TehaImportEvidenceError("invalid kind-specific mapping parent context")
    if kind == "property":
        valid = mapping_binding["property_id"] == target and binding["property_id"] == target
    elif kind == "period":
        valid = (
            mapping_binding["billing_period_id"] == target
            and isinstance(mapping_binding["property_id"], str)
            and bool(mapping_binding["property_id"])
            and binding["property_id"] == mapping_binding["property_id"]
        )
    elif kind == "unit":
        valid = (
            mapping_binding["unit_id"] == target and binding["unit_id"] == target
            and isinstance(mapping_binding["property_id"], str)
            and bool(mapping_binding["property_id"])
            and binding["property_id"] == mapping_binding["property_id"]
        )
    elif kind == "user":
        valid = mapping_binding["tenant_id"] == target and binding["tenant_id"] == target
    else:
        valid = False
    if not valid:
        raise TehaImportEvidenceError("mapping target/original binding mismatch")


def validate_document_manifest(
    version: Any,
    receipt: Any,
    snapshot: Mapping[str, Any],
    *,
    mapping: Any,
    mapping_target_binding: Mapping[str, Any],
) -> dict[str, Any]:
    extension = snapshot.get("teha_import") if isinstance(snapshot, Mapping) else None
    if not isinstance(extension, dict) or set(extension) != {
        "schema_version",
        "receipt_id",
        "actor_id",
        "command_sha256",
        "connection_key",
        "source_history_run_id",
        "content_history_run_id",
        "external_identity_hash",
        "source_sha256",
        "content_sha256",
        "mapping_id",
        "mapping_generation",
        "mapping_sha256",
        "mapping_target_binding",
        "document_type",
        "local_binding",
    }:
        raise TehaImportEvidenceError("invalid TEHA document evidence shape")
    if extension["schema_version"] != SCHEMA_VERSION:
        raise TehaImportEvidenceError("unsupported TEHA document evidence schema")
    binding = extension["local_binding"]
    if not isinstance(binding, dict) or set(binding) != {
        "portfolio_id",
        "property_id",
        "unit_id",
        "contract_id",
        "tenant_id",
    }:
        raise TehaImportEvidenceError("invalid TEHA local binding")
    expected = {
        "receipt_id": _field(receipt, "id"),
        "actor_id": _field(receipt, "imported_by"),
        "command_sha256": _field(receipt, "command_sha256"),
        "connection_key": _field(receipt, "connection_key"),
        "source_history_run_id": _field(receipt, "source_history_run_id"),
        "external_identity_hash": _field(receipt, "external_identity_hash"),
        "source_sha256": _field(receipt, "source_sha256"),
        "content_sha256": _field(receipt, "content_sha256"),
        "mapping_generation": _field(receipt, "mapping_generation"),
        "mapping_id": _field(receipt, "mapping_id"),
        "mapping_sha256": _field(receipt, "mapping_sha256"),
    }
    if any(extension[name] != value for name, value in expected.items()):
        raise TehaImportEvidenceError("TEHA receipt/manifest mismatch")
    mapping_value, mapping_sha256 = mapping_reference(mapping)
    if (
        extension["mapping_id"] != mapping_value["id"]
        or extension["mapping_generation"] != mapping_value["generation"]
        or extension["mapping_sha256"] != mapping_sha256
        or mapping_value["connection_key"] != _field(receipt, "connection_key")
        or mapping_value["portfolio_id"] != _field(receipt, "portfolio_id")
        or binding["portfolio_id"] != _field(receipt, "portfolio_id")
    ):
        raise TehaImportEvidenceError("TEHA mapping/manifest mismatch")
    if extension["mapping_target_binding"] != dict(mapping_target_binding):
        raise TehaImportEvidenceError("TEHA mapping parent context changed")
    _validate_mapping_original_binding(mapping_value, binding, mapping_target_binding)
    classification = extension["document_type"]
    if not isinstance(classification, str) or not classification.strip() or classification != snapshot.get("document_type"):
        raise TehaImportEvidenceError("TEHA original classification mismatch")
    for name in (
        "command_sha256",
        "external_identity_hash",
        "source_sha256",
        "content_sha256",
        "mapping_sha256",
    ):
        _sha(extension[name])
    if (
        binding["portfolio_id"] != _field(version, "portfolio_id")
        or binding["property_id"] != _field(version, "property_id")
        or binding["unit_id"] != _field(version, "unit_id")
        or binding["contract_id"] != _field(version, "contract_id")
        or binding["tenant_id"] != _field(version, "tenant_id")
        or extension["content_sha256"] != _field(version, "sha256")
        or _field(receipt, "document_id") != _field(version, "document_id")
        or _field(receipt, "document_version_id") != _field(version, "id")
    ):
        raise TehaImportEvidenceError("TEHA original binding mismatch")
    if not isinstance(extension["content_history_run_id"], str) or not extension["content_history_run_id"]:
        raise TehaImportEvidenceError("missing content history reference")
    return extension
