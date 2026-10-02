"""Real version bytes, tenant boundaries and profile-only retention."""

import base64
import hashlib
import json
from datetime import date

import pytest
from sqlalchemy import update

from backend.db.document_version_models import DocumentVersionChunkORM
from backend.models import ContractCreate, DocumentCreate, DocumentPatch, TenantCreate
from backend.services import document_versions as versions
from backend.services.document_version_types import OriginalCommand
from backend.services.tenant_data_graph import TenantExportError
from backend.services.tenant_privacy import (
    anonymize_tenant_profile,
    export_tenant_metadata,
    prepare_tenant_export,
    preview_tenant_anonymization,
)
from backend.tests import test_document_versions as version_fixtures

active = version_fixtures.active


def archived_subject(box, *, contract_only=False, name="Explicit own tenant"):
    tenant = box.store.create_tenant(TenantCreate(full_name=name))
    contract = box.store.create_contract(ContractCreate(contract_number="SYN-" + tenant.id,
        property_id=box.prop.id, unit_id=box.unit.id, tenant_id=tenant.id,
        start_date=date(2024, 1, 1), end_date=date(2025, 12, 31), status="terminated"))
    patch = DocumentPatch(contract_id=contract.id, property_id=None if contract_only else box.prop.id,
                          unit_id=None if contract_only else box.unit.id)
    box.document = box.store._patch_entity("document", box.document.id, patch)
    receipt, _ = version_fixtures.archive(box)
    return tenant, contract, receipt


def archive_document(box, document, key):
    preview = versions.source_preview(box.store, document.id, "actor")
    request = OriginalCommand(idempotency_key=key, expected_document_etag=preview["document_etag"],
        expected_head_id=None, expected_sha256=preview["sha256"], comment="Other explicit source", confirmed=True)
    return versions.publish(box.store, document.id, request, "actor")


@pytest.mark.parametrize("contract_only", [False, True])
def test_complete_private_tenant_export_recovers_exact_original_after_source_loss(active, contract_only):
    tenant, _contract, original = archived_subject(active, contract_only=contract_only)
    same_name = active.store.create_tenant(TenantCreate(full_name=tenant.full_name))
    foreign_contract = active.store.create_contract(ContractCreate(contract_number="FOREIGN-" + same_name.id,
        property_id=active.prop.id, unit_id=active.unit.id, tenant_id=same_name.id,
        start_date=date(2020, 1, 1), end_date=date(2021, 12, 31), status="terminated"))
    foreign = active.store.create_document(DocumentCreate(title="Foreign private document",
        contract_id=foreign_contract.id, file_url=active.document.file_url))
    foreign_receipt = archive_document(active, foreign, "foreign-original")
    shared = active.store.create_document(DocumentCreate(title="Shared property original",
        property_id=active.prop.id, file_url=active.document.file_url))
    shared_receipt = archive_document(active, shared, "shared-original")
    active.storage.delete("documents/original.txt")
    before = {item.name for item in active.tmp.iterdir()}
    compiled, _ = prepare_tenant_export(active.store, tenant.id, parent=active.tmp)
    try:
        payload = json.loads(compiled.path.read_bytes())
        assert payload["schema_version"] == "tenant-data-graph/4"
        assert [row["id"] for row in payload["document_versions"]] == [original["id"]]
        assert "file_url" not in payload["document_versions"][0]["metadata_snapshot"]
        assert foreign_receipt["id"] not in compiled.path.read_text(encoding="utf-8")
        assert shared_receipt["id"] not in compiled.path.read_text(encoding="utf-8")
        manifest = payload["document_version_files"][0]
        contents = payload["document_version_contents"][0]
        assert manifest["id"] == contents["id"] == "document-version:" + original["id"]
        blocks = contents["blocks"]
        assert [block["position"] for block in blocks] == list(range(len(blocks)))
        decoded = [base64.b64decode(block["data_base64"], validate=True) for block in blocks]
        assert all(0 < len(block) <= 65536 for block in decoded)
        assert b"".join(decoded) == active.content
        assert hashlib.sha256(active.content).hexdigest() == manifest["sha256"]
        assert len(active.content) == manifest["size_bytes"]
        assert hashlib.sha256(compiled.path.read_bytes()).hexdigest() == compiled.manifest["sha256"]
    finally:
        workspace = compiled.path.parent
        compiled.close()
    assert not workspace.exists()
    assert {item.name for item in active.tmp.iterdir()} == before


def test_profile_anonymization_preserves_real_document_history_and_bytes(active):
    tenant, _contract, original = archived_subject(active)
    plan = preview_tenant_anonymization(active.store, tenant.id)
    assert plan["retained_personal_evidence"]["document_versions"]["count"] == 1
    result = anonymize_tenant_profile(active.store, tenant.id, plan_hash=plan["plan_hash"], confirm_tenant_id=tenant.id)
    assert result["status"] == "profile_anonymized"
    current = active.store.get_tenant(tenant.id)
    assert current.full_name == "Anonymisiert-" + tenant.id
    graph = export_tenant_metadata(active.store, tenant.id)
    assert graph["document_versions"][0]["id"] == original["id"]
    assert version_fixtures.downloaded(active, original) == active.content


def test_corrupt_archived_bytes_fail_before_export_release_and_clean_private_workspace(active):
    tenant, _contract, original = archived_subject(active)
    if active.engine is None:
        row = active.store.document_version_chunks[(original["id"], 0)]
        row.data = b"!" + bytes(row.data)[1:]
    else:
        with active.engine.begin() as db:
            db.exec_driver_sql("DROP TRIGGER immo_document_version_chunks_update")
            db.execute(update(DocumentVersionChunkORM).where(DocumentVersionChunkORM.version_id == original["id"],
                DocumentVersionChunkORM.position == 0).values(data=b"!" + active.content[:65536][1:]))
        active.db.expire_all()
    before = {item.name for item in active.tmp.iterdir()}
    with pytest.raises(TenantExportError, match="document bytes"):
        prepare_tenant_export(active.store, tenant.id, parent=active.tmp)
    assert {item.name for item in active.tmp.iterdir()} == before
