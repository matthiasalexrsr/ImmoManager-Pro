"""Pure TEHA transaction-boundary gates; no database or provider access."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from backend.services.providers.teha_command_types import OpaqueIdentity
from backend.services.providers.teha_import_validation import (
    TehaImportEvidenceError,
    build_document_manifest,
    mapping_reference,
    validate_document_manifest,
)
from backend.services.providers.teha_receive_contract import ExternalIdentity


def test_opaque_identity_accepts_only_exact_nonsecret_components():
    value = OpaqueIdentity(
        kind="document",
        parts={"lieg_nr": "L-41", "reference": "REF-1"},
    )
    assert value.parts == {"lieg_nr": "L-41", "reference": "REF-1"}

    for parts in (
        {"lieg_nr": "L-41"},
        {"lieg_nr": "L-41", "reference": "REF-1", "email": "x@example.invalid"},
        {"lieg_nr": "L-41", "reference": "REF-1", "password": "secret"},
    ):
        with pytest.raises(ValidationError):
            OpaqueIdentity(kind="document", parts=parts)

    with pytest.raises(ValidationError):
        OpaqueIdentity(kind="property", parts={"object_id": True})


def _evidence():
    mapping_identity = ExternalIdentity.create("property", object_id=41)
    mapping = SimpleNamespace(
        id="mapping-1",
        portfolio_id="portfolio-1",
        connection_key="connection-1",
        kind="property",
        external_identity_hash=mapping_identity.token,
        external_identity_json=mapping_identity.private_value(),
        generation=2,
        revision="1" * 64,
        internal_property_id="property-1",
        billing_period_id=None,
        unit_id=None,
        tenant_id=None,
        task_id=None,
        source_history_run_id="mapping-run",
        source_sha256="2" * 64,
    )
    _, mapping_sha = mapping_reference(mapping)
    receipt = SimpleNamespace(
        id="receipt-1",
        imported_by="actor",
        command_sha256="3" * 64,
        connection_key="connection-1",
        source_history_run_id="source-run",
        external_identity_hash="4" * 64,
        source_sha256="5" * 64,
        content_sha256="6" * 64,
        mapping_generation=mapping.generation,
        document_id="document-1",
        document_version_id="version-1",
    )
    version = SimpleNamespace(
        id="version-1",
        document_id="document-1",
        portfolio_id="portfolio-1",
        property_id="property-1",
        unit_id=None,
        contract_id=None,
        tenant_id=None,
        sha256="6" * 64,
    )
    manifest = build_document_manifest(
        receipt_id=receipt.id,
        actor_id=receipt.imported_by,
        command_sha256=receipt.command_sha256,
        connection_key=receipt.connection_key,
        source_history_run_id=receipt.source_history_run_id,
        content_history_run_id="content-run",
        external_identity_hash=receipt.external_identity_hash,
        source_sha256=receipt.source_sha256,
        content_sha256=receipt.content_sha256,
        mapping_id=mapping.id,
        mapping_generation=mapping.generation,
        mapping_sha256=mapping_sha,
        local_binding={
            "portfolio_id": "portfolio-1",
            "property_id": "property-1",
            "unit_id": None,
            "contract_id": None,
            "tenant_id": None,
        },
    )
    return mapping, receipt, version, manifest, mapping_sha


def test_document_manifest_binds_existing_receipt_to_exact_immutable_mapping():
    mapping, receipt, version, manifest, mapping_sha = _evidence()

    assert (
        validate_document_manifest(
            version,
            receipt,
            {"teha_import": manifest},
            mapping=mapping,
        )["mapping_sha256"]
        == mapping_sha
    )

    mapping.revision = "9" * 64
    with pytest.raises(TehaImportEvidenceError):
        validate_document_manifest(
            version,
            receipt,
            {"teha_import": manifest},
            mapping=mapping,
        )


def test_document_manifest_rejects_receipt_source_drift():
    mapping, receipt, version, manifest, _ = _evidence()
    receipt.source_sha256 = "8" * 64

    with pytest.raises(TehaImportEvidenceError):
        validate_document_manifest(
            version,
            receipt,
            {"teha_import": manifest},
            mapping=mapping,
        )
