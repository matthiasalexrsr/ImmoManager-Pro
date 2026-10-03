"""Pure TEHA transaction-boundary gates; no database or provider access."""

from __future__ import annotations

import sys
from types import ModuleType, SimpleNamespace

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from backend.services.providers import teha_receive_commands as commands
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


ROOT_AUTHORITY_MODULE = "backend.services.commit_authority"


def _root_authority(monkeypatch, result=None):
    module = ModuleType(ROOT_AUTHORITY_MODULE)

    class CommitAuthority:
        def __init__(self, actor_id: str):
            self.actor_id = actor_id

    CommitAuthority.__module__ = ROOT_AUTHORITY_MODULE

    def validate_commit_authority(authority, actor_id):
        if authority.actor_id != actor_id:
            raise HTTPException(401, "synthetic authority mismatch")
        return result

    validate_commit_authority.__module__ = ROOT_AUTHORITY_MODULE
    module.CommitAuthority = CommitAuthority
    module.validate_commit_authority = validate_commit_authority
    monkeypatch.setitem(sys.modules, ROOT_AUTHORITY_MODULE, module)
    return CommitAuthority


def test_missing_root_commit_authority_contract_fails_before_any_loose_fallback(monkeypatch):
    monkeypatch.delitem(sys.modules, ROOT_AUTHORITY_MODULE, raising=False)
    with pytest.raises(HTTPException) as failure:
        commands._require_root_commit_authority(None, "actor")
    assert failure.value.status_code == 503


def test_root_commit_authority_rejects_bool_lambda_and_duck_types(monkeypatch):
    CommitAuthority = _root_authority(monkeypatch)
    assert commands._require_root_commit_authority(CommitAuthority("actor"), "actor") is None
    for forged in (
        True,
        False,
        lambda: True,
        SimpleNamespace(actor_id="actor", authorized=True),
    ):
        with pytest.raises(HTTPException) as failure:
            commands._require_root_commit_authority(forged, "actor")
        assert failure.value.status_code == 503


def test_root_commit_authority_rejects_boolean_validator_result(monkeypatch):
    CommitAuthority = _root_authority(monkeypatch, result=True)
    with pytest.raises(HTTPException) as failure:
        commands._require_root_commit_authority(CommitAuthority("actor"), "actor")
    assert failure.value.status_code == 503


def test_write_work_fails_503_before_session_writer_or_dml_without_root_authority(monkeypatch):
    monkeypatch.delitem(sys.modules, ROOT_AUTHORITY_MODULE, raising=False)
    touched = {"bind": False, "fresh": 0}

    class BombDB:
        def get_bind(self):
            touched["bind"] = True
            raise AssertionError("DB/session boundary must not be reached")

    fake_store = SimpleNamespace(db=BombDB())
    fake_scope = SimpleNamespace(
        user_id="actor",
        role="verwalter",
        unrestricted=True,
        portfolio_ids=(),
    )
    monkeypatch.setattr(
        commands,
        "_identity",
        lambda actor_id, write_kind=None: (
            {
                "id": actor_id,
                "role": "verwalter",
                "is_active": True,
            },
            fake_scope,
        ),
    )

    def fresh(actor_id):
        touched["fresh"] += 1
        raise AssertionError("fresh SID fence is supplemental, not commit authority")

    monkeypatch.setattr(commands, "require_fresh_request_authority", fresh)

    with pytest.raises(HTTPException) as failure:
        with commands._work(
            fake_store,
            "actor",
            write=True,
            write_kind="document",
            commit_authority=None,
        ):
            raise AssertionError("write body must not be entered")

    assert failure.value.status_code == 503
    assert touched == {"bind": False, "fresh": 0}
