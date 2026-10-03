"""Native-slot runtime tests: importing the service loads auth/global Settings.

These are deliberately not pure/no-runtime tests. No positive write authority is
fabricated; a future actual Root unit needs a separate composed acceptance suite.
"""

import sys
from contextlib import nullcontext
from datetime import datetime
from types import ModuleType, SimpleNamespace

import pytest
from fastapi import HTTPException

from backend.db.teha_receive_schema import TehaReceiveSchemaError
from backend.services.providers import teha_receive_commands as commands
from backend.services.providers.teha_command_types import (
    ConfirmMapping,
    DocumentImportData,
    ImportDocument,
    ImportTechnicalOrder,
    MappingSelection,
    MappingTarget,
    OpaqueIdentity,
    PreviewImport,
    TaskImportData,
)
from backend.services.providers.teha_import_validation import (
    build_document_manifest,
    mapping_reference,
)
from backend.services.providers.teha_receive_contract import ExternalIdentity


def bomb(*_args, **_kwargs):
    raise AssertionError("write reached auth, Session, business writer or DML")


def actor_only_module(monkeypatch):
    module = ModuleType("backend.services.commit_authority")

    class CommitAuthority:
        def __init__(self):
            self.actor_id = "actor-a"

    def validate_commit_authority(_authority, _actor_id):
        raise AssertionError("actor-only validator must never be consulted")

    CommitAuthority.__module__ = module.__name__
    validate_commit_authority.__module__ = module.__name__
    module.CommitAuthority = CommitAuthority
    module.validate_commit_authority = validate_commit_authority
    monkeypatch.setitem(sys.modules, module.__name__, module)
    return CommitAuthority()


@pytest.mark.parametrize("forgery", ["actor_only", "notification", "boolean", "missing"])
def test_write_work_always_fails_before_auth_bind_session_writer_and_body(monkeypatch, forgery):
    actor_only = actor_only_module(monkeypatch)
    authorities = {
        "actor_only": actor_only,
        "notification": SimpleNamespace(actor_id="actor-a", notification_id="notification-a"),
        "boolean": True, "missing": None,
    }
    monkeypatch.setattr(commands, "_identity", bomb)
    monkeypatch.setattr(commands, "require_fresh_request_authority", bomb)
    monkeypatch.setattr(commands, "Session", bomb)
    monkeypatch.setattr(commands, "begin_writer", bomb)
    store = SimpleNamespace(db=SimpleNamespace(get_bind=bomb))
    with pytest.raises(HTTPException) as failure:
        with commands._work(store, "actor-a", write=True, commit_authority=authorities[forgery]):
            bomb()
    assert failure.value.status_code == 503
    assert failure.value.detail["code"] == "teha_write_unit_unavailable"


def preview_payload(source_kind="document"):
    kind, parts = ("document", {"lieg_nr": "L-41", "reference": "REF-1"}) if source_kind == "document" else ("technical_order", {"termin_id": 9001})
    identity = OpaqueIdentity(kind=kind, parts=parts)
    return PreviewImport(
        connection_key="connection-a", portfolio_id="portfolio-a",
        source_kind=source_kind, source_history_run_id="source-history-a",
        content_history_run_id="content-history-a" if source_kind == "document" else None,
        identity=identity, external_identity_hash=commands._opaque(identity).token,
        source_sha256="1" * 64,
        mapping=MappingSelection(mapping_id="mapping-a", expected_revision="2" * 64, expected_generation=1),
        document=DocumentImportData(title="Synthetic", document_type="invoice") if source_kind == "document" else None,
        task=TaskImportData(title="Synthetic") if source_kind == "technical_order" else None,
    )


@pytest.mark.parametrize("operation", ["mapping", "document", "technical_order"])
def test_each_public_write_rejects_actor_only_authority_before_business_access(monkeypatch, operation):
    authority = actor_only_module(monkeypatch)
    monkeypatch.setattr(commands, "_identity", bomb)
    monkeypatch.setattr(commands, "Session", bomb)
    monkeypatch.setattr(commands, "begin_writer", bomb)
    monkeypatch.setattr(commands, "_verified_source", bomb)
    store = SimpleNamespace(db=SimpleNamespace(get_bind=bomb))
    with pytest.raises(HTTPException) as failure:
        if operation == "mapping":
            identity = OpaqueIdentity(kind="property", parts={"object_id": 41})
            payload = ConfirmMapping(
                idempotency_key="mapping-command-a", connection_key="connection-a",
                portfolio_id="portfolio-a", identity=identity,
                external_identity_hash=commands._opaque(identity).token,
                source_history_run_id="source-history-a", source_sha256="1" * 64,
                expected_previous_revision="new",
                target=MappingTarget(target_id="property-a", expected_target_etag="etag-a"),
            )
            commands.confirm_mapping(store, payload, "actor-a", commit_authority=authority)
        elif operation == "document":
            payload = ImportDocument(
                idempotency_key="document-command-a", preview=preview_payload(),
                preview_hash="3" * 64, content_history_run_id="content-history-a",
            )
            commands.import_document(store, payload, b"%PDF-synthetic", "actor-a", commit_authority=authority)
        else:
            payload = ImportTechnicalOrder(
                idempotency_key="task-command-a", preview=preview_payload("technical_order"),
                preview_hash="3" * 64,
            )
            commands.import_technical_order(store, payload, "actor-a", commit_authority=authority)
    assert failure.value.status_code == 503
    assert failure.value.detail["code"] == "teha_write_unit_unavailable"


@pytest.mark.parametrize("entry", ["read", "preview", "download"])
@pytest.mark.parametrize("schema_result", ["absent", "invalid"])
def test_read_preview_download_schema_failure_is_maintenance_503(monkeypatch, entry, schema_result):
    events = []

    class ReadSession:
        def connection(self):
            return object()

        def rollback(self):
            events.append("rollback")

        def close(self):
            events.append("close")

    def schema(_connection):
        if schema_result == "invalid":
            raise TehaReceiveSchemaError("synthetic old/partial development schema")
        return False

    monkeypatch.setattr(commands, "_identity", lambda *_args, **_kwargs: ({}, object()))
    monkeypatch.setattr(commands, "require_fresh_request_authority", lambda _actor: None)
    monkeypatch.setattr(commands, "scope_context", lambda _scope: nullcontext())
    monkeypatch.setattr(commands, "Session", lambda *_args, **_kwargs: ReadSession())
    monkeypatch.setattr(commands, "SQLAlchemyStore", lambda _db: object())
    monkeypatch.setattr(commands, "validate_teha_receive_schema", schema)
    monkeypatch.setattr(commands, "begin_writer", bomb)
    monkeypatch.setattr(commands, "_verified_source", lambda *_args, **_kwargs: ({}, {}))
    monkeypatch.setattr(commands, "_preview", bomb)
    monkeypatch.setattr(commands.document_versions, "prepare_download", bomb)
    store = SimpleNamespace(db=SimpleNamespace(get_bind=lambda: object()))
    with pytest.raises(HTTPException) as failure:
        if entry == "read":
            with commands._work(store, "actor-a"):
                bomb()
        elif entry == "preview":
            commands.preview_import(store, preview_payload(), "actor-a")
        else:
            commands.prepare_document_download(store, "receipt-a", "actor-a")
    assert failure.value.status_code == 503
    assert failure.value.detail["code"] == "teha_l2_schema_requires_maintenance"
    assert failure.value.detail["maintenance_path"] == "docs/TEHA_L2_MAINTENANCE_20261004.md"
    assert events == ["rollback", "close"]


@pytest.mark.parametrize("kind", ["property", "period", "unit", "user"])
def test_target_binding_reads_current_kind_specific_parent_or_tenant_grant(kind):
    stamp = datetime(2026, 10, 4)
    portfolio = SimpleNamespace(id="portfolio-a")
    prop = SimpleNamespace(id="property-a", portfolio_id="portfolio-a", updated_at=stamp)
    targets = {
        "property": prop,
        "period": SimpleNamespace(id="period-a", property_id=prop.id, updated_at=stamp),
        "unit": SimpleNamespace(id="unit-a", property_id=prop.id, updated_at=stamp),
        "user": SimpleNamespace(id="tenant-a", updated_at=stamp),
    }
    results = {
        "property": [portfolio, prop],
        "period": [portfolio, prop.id, prop, targets["period"]],
        "unit": [portfolio, prop.id, prop, targets["unit"]],
        "user": [portfolio, object(), targets["user"]],
    }
    values = iter(results[kind])
    unit = SimpleNamespace(db=SimpleNamespace(scalar=lambda _statement: next(values)))
    row, _etag, context = commands._target_binding(unit, kind, targets[kind].id, portfolio.id, lock=False)
    assert row.id == targets[kind].id
    assert context["portfolio_id"] == portfolio.id
    key = {"property": "property_id", "period": "billing_period_id", "unit": "unit_id", "user": "tenant_id"}[kind]
    assert context[key] == row.id
    if kind in {"period", "unit"}:
        assert context["property_id"] == prop.id


@pytest.mark.parametrize("kind", ["period", "unit"])
def test_reparented_target_is_denied_before_original_verification(kind):
    values = iter([
        SimpleNamespace(id="portfolio-a"), "property-a",
        SimpleNamespace(id="property-a", portfolio_id="portfolio-a"),
        SimpleNamespace(id="target-a", property_id="property-b"),
    ])
    unit = SimpleNamespace(db=SimpleNamespace(scalar=lambda _statement: next(values)))
    with pytest.raises(HTTPException) as failure:
        commands._target_binding(unit, kind, "target-a", "portfolio-a", lock=False)
    assert failure.value.status_code == 404


def test_removed_tenant_portfolio_grant_is_denied():
    values = iter([SimpleNamespace(id="portfolio-a"), None, SimpleNamespace(id="tenant-a")])
    unit = SimpleNamespace(db=SimpleNamespace(scalar=lambda _statement: next(values)))
    with pytest.raises(HTTPException) as failure:
        commands._target_binding(unit, "user", "tenant-a", "portfolio-a", lock=False)
    assert failure.value.status_code == 404


@pytest.mark.parametrize("classification", ["invoice", "future-unknown:" + "x" * 160])
def test_receipt_read_uses_original_classification_and_verifies_all_bytes(monkeypatch, classification):
    identity = ExternalIdentity.create("property", object_id=41)
    mapping = SimpleNamespace(
        id="mapping-a", portfolio_id="portfolio-a", connection_key="connection-a",
        kind="property", internal_property_id="property-a", billing_period_id=None,
        unit_id=None, tenant_id=None, task_id=None, generation=1, revision="1" * 64,
        external_identity_hash=identity.token, external_identity_json=identity.private_value(),
        source_history_run_id="mapping-history-a", source_sha256="2" * 64,
    )
    _, mapping_sha = mapping_reference(mapping)
    binding = {"portfolio_id": "portfolio-a", "property_id": "property-a", "unit_id": None, "tenant_id": None, "contract_id": None}
    context = {key: value for key, value in binding.items() if key != "contract_id"}
    context["billing_period_id"] = None
    receipt = SimpleNamespace(
        id="receipt-a", source_kind="document", imported_by="actor-a", portfolio_id="portfolio-a",
        connection_key="connection-a", mapping_id="mapping-a", mapping_sha256=mapping_sha,
        mapping_generation=1, command_sha256="3" * 64, source_history_run_id="source-history-a",
        external_identity_hash="4" * 64, source_sha256="5" * 64, content_sha256="6" * 64,
        document_id="document-a", document_version_id="version-a",
    )
    extension = build_document_manifest(
        receipt_id=receipt.id, actor_id=receipt.imported_by, command_sha256=receipt.command_sha256,
        connection_key=receipt.connection_key, source_history_run_id=receipt.source_history_run_id,
        content_history_run_id="content-history-a", external_identity_hash=receipt.external_identity_hash,
        source_sha256=receipt.source_sha256, content_sha256=receipt.content_sha256,
        mapping_id=mapping.id, mapping_generation=1, mapping_sha256=mapping_sha,
        local_binding=binding, mapping_target_binding=context, document_type=classification,
    )
    version = SimpleNamespace(
        id="version-a", document_id="document-a", sha256=receipt.content_sha256,
        metadata_snapshot={"teha_import": extension, "document_type": classification}, **binding,
    )
    observed = []

    def target_binding(_unit, kind, target, portfolio, *, lock):
        observed.append((kind, target, portfolio, lock))
        return object(), "etag-a", context

    def blocks(_store, selected_version):
        assert selected_version is version
        yield b"synthetic first block"
        observed.append("all immutable blocks verified")

    monkeypatch.setattr(commands, "_target_binding", target_binding)
    # Current document categorization is editable; the immutable original
    # classification remains evidence. It must never be replaced by live text.
    monkeypatch.setattr(commands.document_versions, "_document", lambda *_args: (SimpleNamespace(document_type="later-local-category"), binding))
    monkeypatch.setattr(commands.document_versions, "_authorized_version", lambda *_args: version)
    monkeypatch.setattr(commands.document_versions, "verified_blocks", blocks)
    unit = SimpleNamespace(store=object(), db=object())
    commands._verify_receipt_target(unit, receipt, mapping_row=mapping)
    assert observed == [("property", "property-a", "portfolio-a", False), "all immutable blocks verified"]
