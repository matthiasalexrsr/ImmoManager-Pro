"""Shared identity policy used by live readers and offline recovery."""
from types import SimpleNamespace

import pytest

from backend.services.document_version_validation import (
    ManifestValidationError,
    validate_manifest_identity,
)


def manifest():
    return dict(document_id="reviewed-document", property_id="property", unit_id="unit", contract_id="contract",
                number=1, size_bytes=0, sha256="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
                operation="archive_original", predecessor_id=None, restored_from_id=None)


def snapshot():
    return dict(id="reviewed-document", property_id=None, unit_id=None, contract_id="contract")


@pytest.mark.parametrize("objects", [False, True])
def test_nullable_historical_subjects_match_resolved_manifest(objects):
    row = manifest()
    validate_manifest_identity(SimpleNamespace(**row) if objects else row, snapshot())


@pytest.mark.parametrize("changes", [
    {"number": True}, {"number": 0}, {"size_bytes": False}, {"size_bytes": -1},
    {"sha256": "A" * 64}, {"operation": "upload"}, {"predecessor_id": "foreign"},
    {"restored_from_id": ""}, {"restored_from_id": 0}, {"number": 2, "operation": "upload", "predecessor_id": ""},
    {"number": 2, "operation": "restore", "predecessor_id": "previous", "restored_from_id": ""},
    {"number": 2, "operation": "restore", "predecessor_id": "previous", "restored_from_id": None},
])
def test_invalid_manifest_fields_are_rejected(changes):
    with pytest.raises(ManifestValidationError):
        validate_manifest_identity({**manifest(), **changes}, snapshot())


@pytest.mark.parametrize("changes", [
    {"id": "unrelated"}, {"contract_id": None}, {"property_id": "foreign"}, {"unit_id": "foreign"},
])
def test_nonnullable_snapshot_identity_must_match_exactly(changes):
    with pytest.raises(ManifestValidationError):
        validate_manifest_identity(manifest(), {**snapshot(), **changes})


def test_restore_manifest_requires_both_explicit_links():
    validate_manifest_identity({**manifest(), "number": 3, "operation": "restore",
                                "predecessor_id": "previous", "restored_from_id": "original"}, snapshot())
