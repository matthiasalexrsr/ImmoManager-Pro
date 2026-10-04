"""Retained manifest checks without service/auth/settings or backend conftest.

Prepared source only. Run this separately with --noconftest; runtime boundary
tests belong to backend/tests/test_teha_runtime_boundaries.py instead.
"""

from copy import deepcopy
from types import SimpleNamespace

import pytest

from backend.services.providers.teha_command_types import DocumentImportData
from backend.services.providers.teha_import_projection import document_projection
from backend.services.providers.teha_import_validation import (
    TehaImportEvidenceError,
    build_document_manifest,
    mapping_reference,
    validate_document_manifest,
)
from backend.services.providers.teha_receive_contract import (
    ExternalIdentity,
    ObservedEvidence,
    PreviewDecision,
    digest,
)


def evidence(kind="property", document_type="provider_unknown_classification"):
    identities = {
        "property": {"object_id": 41},
        "period": {"object_id": 41, "period_number": 7},
        "unit": {"lieg_nr": "L-41", "unit_id": 501},
        "user": {"termin_id": 9001, "user_id": 601},
        "technical_order": {"termin_id": 9001},
    }
    target_fields = {
        "property": "internal_property_id", "period": "billing_period_id",
        "unit": "unit_id", "user": "tenant_id", "technical_order": "task_id",
    }
    target_ids = {
        "property": "property-a", "period": "period-a", "unit": "unit-a",
        "user": "tenant-a", "technical_order": "task-a",
    }
    identity = ExternalIdentity.create(kind, **identities[kind])
    mapping = SimpleNamespace(
        id="mapping-a", portfolio_id="portfolio-a", connection_key="connection-a",
        kind=kind, external_identity_hash=identity.token,
        external_identity_json=identity.private_value(), generation=1,
        revision="1" * 64, source_history_run_id="mapping-history-a",
        source_sha256="2" * 64, internal_property_id=None,
        billing_period_id=None, unit_id=None, tenant_id=None, task_id=None,
    )
    setattr(mapping, target_fields[kind], target_ids[kind])
    _, mapping_sha = mapping_reference(mapping)
    context = {
        "portfolio_id": "portfolio-a", "property_id": None, "unit_id": None,
        "tenant_id": None, "billing_period_id": None,
    }
    binding = {
        "portfolio_id": "portfolio-a", "property_id": "property-a", "unit_id": None,
        "tenant_id": None, "contract_id": None,
    }
    if kind in {"property", "period", "unit", "technical_order"}:
        context["property_id"] = binding["property_id"] = "property-a"
    if kind == "period":
        context["billing_period_id"] = "period-a"
    if kind == "unit":
        context["unit_id"] = binding["unit_id"] = "unit-a"
    if kind == "user":
        context["tenant_id"] = binding["tenant_id"] = "tenant-a"
        binding["contract_id"] = "contract-a"
    receipt = SimpleNamespace(
        id="receipt-a", portfolio_id="portfolio-a", connection_key="connection-a",
        imported_by="actor-a", command_sha256="3" * 64,
        source_history_run_id="document-history-a", external_identity_hash="4" * 64,
        source_sha256="5" * 64, content_sha256="6" * 64, mapping_generation=1,
        mapping_id=mapping.id, mapping_sha256=mapping_sha,
        document_id="document-a", document_version_id="version-a",
    )
    version = SimpleNamespace(
        id="version-a", document_id="document-a", sha256="6" * 64, **binding,
    )
    manifest = build_document_manifest(
        receipt_id=receipt.id, actor_id=receipt.imported_by,
        command_sha256=receipt.command_sha256, connection_key=receipt.connection_key,
        source_history_run_id=receipt.source_history_run_id,
        content_history_run_id="content-history-a",
        external_identity_hash=receipt.external_identity_hash,
        source_sha256=receipt.source_sha256, content_sha256=receipt.content_sha256,
        mapping_id=mapping.id, mapping_generation=1, mapping_sha256=mapping_sha,
        local_binding=binding, mapping_target_binding=context, document_type=document_type,
    )
    snapshot = {"document_type": document_type, "teha_import": manifest}
    return mapping, receipt, version, snapshot, context


def validate(values):
    mapping, receipt, version, snapshot, context = values
    return validate_document_manifest(
        version, receipt, snapshot, mapping=mapping, mapping_target_binding=context,
    )


@pytest.mark.parametrize("kind", ["property", "period", "unit", "user"])
def test_exact_kind_specific_original_binding_is_retained(kind):
    values = evidence(kind)
    assert validate(values)["mapping_id"] == values[0].id


@pytest.mark.parametrize("kind", ["property", "period", "unit", "user"])
def test_another_original_target_in_the_same_portfolio_is_rejected(kind):
    values = evidence(kind)
    binding_key = "tenant_id" if kind == "user" else "unit_id" if kind == "unit" else "property_id"
    # The original and its own immutable local binding agree; only the exact
    # mapping target differs. Portfolio-only verification would accept this.
    setattr(values[2], binding_key, "another-target")
    values[3]["teha_import"]["local_binding"][binding_key] = "another-target"
    with pytest.raises(TehaImportEvidenceError, match="mapping target/original"):
        validate(values)


@pytest.mark.parametrize(
    ("field", "changed"),
    [("connection_key", "connection-b"), ("portfolio_id", "portfolio-b"),
     ("mapping_id", "mapping-b"), ("mapping_sha256", "7" * 64),
     ("mapping_generation", 2), ("source_sha256", "8" * 64)],
)
def test_receipt_namespace_and_exact_mapping_reference_cannot_drift(field, changed):
    values = evidence()
    setattr(values[1], field, changed)
    with pytest.raises(TehaImportEvidenceError):
        validate(values)


@pytest.mark.parametrize(
    ("field", "changed"),
    [("connection_key", "connection-b"), ("mapping_id", "mapping-b"),
     ("mapping_sha256", "7" * 64), ("mapping_generation", 2)],
)
def test_matching_receipt_and_extension_still_require_the_actual_mapping(field, changed):
    values = evidence()
    setattr(values[1], field, changed)
    values[3]["teha_import"][field] = changed
    with pytest.raises(TehaImportEvidenceError, match="mapping/manifest"):
        validate(values)


def test_receipt_and_original_cannot_move_together_to_another_mapping_portfolio():
    values = evidence()
    values[1].portfolio_id = values[2].portfolio_id = "portfolio-b"
    values[3]["teha_import"]["local_binding"]["portfolio_id"] = "portfolio-b"
    values[3]["teha_import"]["mapping_target_binding"]["portfolio_id"] = "portfolio-b"
    values[4]["portfolio_id"] = "portfolio-b"
    with pytest.raises(TehaImportEvidenceError, match="mapping/manifest"):
        validate(values)


@pytest.mark.parametrize("kind", ["period", "unit"])
def test_current_mapping_parent_change_is_rejected(kind):
    values = evidence(kind)
    values[4]["property_id"] = "reparented-property"
    with pytest.raises(TehaImportEvidenceError, match="parent context changed"):
        validate(values)


def test_mapping_kind_cannot_hide_a_second_target():
    mapping, *_ = evidence()
    mapping.unit_id = "another-unit"
    with pytest.raises(TehaImportEvidenceError, match="kind-specific"):
        mapping_reference(mapping)


def test_technical_order_mapping_cannot_claim_a_document_original():
    with pytest.raises(TehaImportEvidenceError, match="mapping target/original"):
        validate(evidence("technical_order"))


def test_unknown_long_classification_is_preserved_without_an_invented_enum_or_limit():
    classification = "  future-provider-classification:" + "x" * 160 + "  "
    assert DocumentImportData(title="Synthetic", document_type=classification).document_type == classification
    identity = ExternalIdentity.create("document", lieg_nr="L-41", reference="REF-1")
    observed = ObservedEvidence(
        "source-history-a", identity, {}, digest({}), (),
        content_sha256="6" * 64, content_size=14,
    )
    decision = PreviewDecision("new", identity.token, observed.source_sha256, "7" * 64, "6" * 64, ())
    projected = document_projection(
        observed, decision, property_id="property-a", title="Synthetic",
        document_type=classification,
    )
    assert projected.document.document_type == classification
    assert validate(evidence(document_type=classification))["document_type"] == classification


def test_classification_is_proven_by_the_immutable_original_snapshot():
    values = evidence(document_type="invoice")
    changed = deepcopy(values[3])
    changed["document_type"] = "another-classification"
    with pytest.raises(TehaImportEvidenceError, match="classification"):
        validate_document_manifest(
            values[2], values[1], changed, mapping=values[0],
            mapping_target_binding=values[4],
        )


def test_old_development_manifest_requires_explicit_maintenance():
    values = evidence()
    values[3]["teha_import"]["schema_version"] = "teha-import/1"
    with pytest.raises(TehaImportEvidenceError, match="unsupported"):
        validate(values)
