"""Synthetic real wizard publication, complete private exports and retained evidence."""

import base64
import hashlib
import json
import re
from copy import deepcopy
from datetime import date, datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi import Depends, FastAPI, HTTPException
from fastapi.testclient import TestClient

from backend import auth, dependencies
from backend.db.contract_wizard_models import ContractAttachmentChunkORM, ContractDraftORM, ContractTemplateORM
from backend.models import ContractCreate, DocumentCreate, TenantCreate
from backend.routers import admin
from backend.services import contract_wizard as wizard
from backend.services.contract_wizard_types import DraftCreate, DraftEdit, SignatureCreate, TemplateCreate
from backend.services.portfolio_http import PortfolioScopeMiddleware
from backend.services.portfolio_scope import scope_context, scope_from_user
from backend.services.tenant_data_graph import TenantExportError
from backend.services.tenant_privacy import (
    PrivacyConflict,
    anonymize_tenant_profile,
    export_tenant_metadata,
    prepare_tenant_export,
    preview_tenant_anonymization,
)
from backend.storage import ValidationError
from backend.tests.test_contract_wizard_workflow import active as wizard_store
from backend.tests.test_contract_wizard_workflow import command, data, prepare, publish

active = wizard_store


def test_bounded_pdf_driver_buffers_preserve_complete_original_bytes_and_digest():
    from backend.services.tenant_wizard_graph import BLOCK_SIZE, verified_blocks

    original = b"%PDF-" + bytes(range(256)) * 410
    buffers = iter(memoryview(original[offset:offset + BLOCK_SIZE]) for offset in range(0, len(original), BLOCK_SIZE))
    driver = SimpleNamespace(db=SimpleNamespace(scalar=lambda _query: next(buffers)))
    manifest = {"kind": "reviewed_pdf", "draft_id": "synthetic-draft", "portfolio_id": "synthetic-portfolio",
                "size_bytes": len(original), "sha256": hashlib.sha256(original).hexdigest()}
    assert b"".join(verified_blocks(driver, manifest)) == original


@pytest.mark.parametrize("invalid", [None, "not binary", memoryview(b"x" * (65536 + 1))])
def test_invalid_driver_buffer_is_refused_before_export_success(invalid):
    from backend.services.tenant_wizard_graph import verified_blocks

    driver = SimpleNamespace(db=SimpleNamespace(scalar=lambda _query: invalid))
    manifest = {"kind": "reviewed_pdf", "draft_id": "synthetic-draft", "portfolio_id": "synthetic-portfolio",
                "size_bytes": 10, "sha256": hashlib.sha256(b"%PDF-hello").hexdigest()}
    with pytest.raises(TenantExportError, match="PDF block"):
        list(verified_blocks(driver, manifest))


def completed(box, *, existing=False):
    contents = bytes(range(256)) * 1300
    (box.storage.base_dir / "original.bin").write_bytes(contents)
    source = box.store.create_document(DocumentCreate(property_id=box.property.id,
        title="Own original personal evidence", file_url="/uploads/original.bin"))
    template = wizard.create_template(box.store, TemplateCreate(idempotency_key="own-template",
        portfolio_id=box.p.id, title="Own personal template", body="Own explicitly reviewed template Ä €"), "actor")
    changes = dict(template_id=template["id"], terms="", attachment_ids=[source.id])
    if existing:
        changes.update(tenant_id=box.tenant.id, new_tenant=None)
    row = prepare(box, **changes)
    row = wizard.publish_draft(box.store, row["id"], publish(row), "actor")
    row = wizard.record_signature(box.store, row["id"], SignatureCreate(**command(row, "signature").model_dump(),
        confirmed=True, signed_date=date(2026, 10, 1), tenant_signer="Own recorded tenant signer",
        landlord_signer="Own landlord signer", reference="Own paper record", note="Own signature note"), "actor")
    tenant_id = box.store.get_contract(row["contract_id"]).tenant_id
    return row, tenant_id, contents, source, template


def test_complete_download_preserves_pdf_original_signers_commands_and_template_after_source_loss(active):
    row, tenant_id, original, source, template = completed(active)
    pdf = wizard.read_pdf(active.store, row["id"], "actor")
    active.store.delete_document(source.id)
    (active.storage.base_dir / "original.bin").unlink()
    compiled, _ = prepare_tenant_export(active.store, tenant_id, parent=active.tmp)
    path = compiled.path
    try:
        result = json.loads(path.read_bytes())
        assert result["tenant"]["id"] == tenant_id and result["schema_version"] == "tenant-data-graph/3"
        assert [item["id"] for item in result["contract_wizard_drafts"]] == [row["id"]]
        assert result["contract_template_versions"][0]["id"] == template["id"]
        assert result["contract_template_versions"][0]["body"] == "Own explicitly reviewed template Ä €"
        assert result["contract_signature_evidence"][0]["note"] == "Own signature note"
        assert {item["result"]["state"] for item in result["contract_wizard_commands"]} == {"reviewed", "committed", "signed"}
        recovered = {}
        manifests = {item["id"]: item for item in result["contract_wizard_files"]}
        for item in result["wizard_file_contents"]:
            blocks = item["blocks"]
            assert [block["position"] for block in blocks] == list(range(len(blocks)))
            payload = b"".join(base64.b64decode(block["data_base64"], validate=True) for block in blocks)
            manifest = manifests[item["id"]]
            assert len(payload) == manifest["size_bytes"]
            assert hashlib.sha256(payload).hexdigest() == manifest["sha256"]
            assert all(len(base64.b64decode(block["data_base64"])) <= 65536 for block in blocks)
            recovered[manifest["kind"]] = payload
        assert recovered == {"reviewed_pdf": pdf, "frozen_attachment": original}
        assert hashlib.sha256(path.read_bytes()).hexdigest() == compiled.manifest["sha256"]
        assert result["contract_attachment_evidence"][0]["source_document_id"] == source.id
        assert "file_url" not in result["contract_attachment_evidence"][0]["metadata_snapshot"]
    finally:
        compiled.close()
    assert not path.exists() and not path.parent.exists()


def test_existing_tenant_review_without_contract_is_exported_and_historical_party_switch_never_leaks(active):
    own = active.tenant
    with scope_context(scope_from_user(active.users["actor"])):
        other = active.store.create_tenant(TenantCreate(full_name="FOREIGN PARTY MUST NOT LEAK"))
    row = prepare(active, tenant_id=own.id, new_tenant=None)
    reviewed = deepcopy(row)
    row = wizard.edit_draft(active.store, row["id"], DraftEdit(**command(row, "change-party").model_dump(),
        data=data(active, tenant_id=other.id, new_tenant=None, landlord_name="FOREIGN CURRENT CONTENT")), "actor")
    graph = export_tenant_metadata(active.store, own.id)
    assert graph["contracts"] == []
    assert graph["contract_wizard_drafts"][0]["data"] is None
    assert not graph["contract_wizard_drafts"][0]["current_subject_included"]
    assert graph["contract_wizard_commands"][0]["result"]["review"] == reviewed["review"]
    assert "FOREIGN" not in json.dumps(graph)
    assert graph["contract_wizard_files"] == []  # Superseded draft PDF is not stored.
    with pytest.raises(ValidationError, match="Vertrags"):
        active.store.delete_tenant(own.id)
    assert active.store.get_tenant(own.id).full_name == own.full_name


def test_profile_anonymization_names_retained_wizard_pii_and_preserves_exact_immutable_bytes(active):
    row, tenant_id, _, _, _ = completed(active, existing=True)
    before = export_tenant_metadata(active.store, tenant_id)
    pdf = wizard.read_pdf(active.store, row["id"], "actor")
    preview = preview_tenant_anonymization(active.store, tenant_id)
    assert preview["scope"] == "tenant_profile_only"
    assert preview["retained_personal_evidence"]["contract_wizard_commands"]["count"] == 3
    assert "nicht anonymisiert" in preview["note"]
    result = anonymize_tenant_profile(active.store, tenant_id, plan_hash=preview["plan_hash"], confirm_tenant_id=tenant_id)
    assert result["status"] == "profile_anonymized"
    assert result["retained_personal_evidence"] == preview["retained_personal_evidence"]
    after = export_tenant_metadata(active.store, tenant_id)
    assert active.store.get_tenant(tenant_id).full_name == "Anonymisiert-" + tenant_id
    for collection in ("contract_wizard_drafts", "contract_wizard_commands", "contract_template_versions",
                       "contract_signature_evidence", "contract_attachment_evidence", "contract_wizard_files"):
        assert before[collection] == after[collection]
    assert wizard.read_pdf(active.store, row["id"], "actor") == pdf


def test_added_signature_invalidates_anonymization_review_before_any_profile_change(active):
    row = prepare(active, tenant_id=active.tenant.id, new_tenant=None)
    row = wizard.publish_draft(active.store, row["id"], publish(row), "actor")
    preview = preview_tenant_anonymization(active.store, active.tenant.id)
    wizard.record_signature(active.store, row["id"], SignatureCreate(**command(row, "new-signature").model_dump(),
        confirmed=True, signed_date=date(2026, 10, 1), tenant_signer="Own signer", landlord_signer="Landlord",
        reference="New factual evidence"), "actor")
    with pytest.raises(PrivacyConflict, match="Datenstand"):
        anonymize_tenant_profile(active.store, active.tenant.id, plan_hash=preview["plan_hash"], confirm_tenant_id=active.tenant.id)
    assert active.store.get_tenant(active.tenant.id).full_name == active.tenant.full_name


@pytest.mark.parametrize("damage", ["pdf", "review", "original", "missing_pdf_hash", "template"])
def test_corrupt_immutable_sources_never_publish_partial_export_and_cleanup_private_workspace(active, damage):
    row, tenant_id, _, _, _ = completed(active)
    if active.engine:
        active.store.db.rollback()
        with active.engine.begin() as connection:
            if damage == "original":
                connection.exec_driver_sql("DROP TRIGGER immo_contract_attachment_chunks_keep_update")
                connection.execute(ContractAttachmentChunkORM.__table__.update().values(data=b"corrupt"))
            elif damage == "template":
                connection.exec_driver_sql("DROP TRIGGER immo_contract_template_versions_keep_update")
                connection.execute(ContractTemplateORM.__table__.update().values(body="Corrupted unrelated personal contents"))
            else:
                connection.exec_driver_sql("DROP TRIGGER immo_contract_wizard_drafts_keep_update")
                values = ({"pdf": b"%PDF-corrupt"} if damage == "pdf" else
                          {"pdf_sha256": None} if damage == "missing_pdf_hash" else {"review_hash": "f" * 64})
                connection.execute(ContractDraftORM.__table__.update().where(ContractDraftORM.id == row["id"]).values(**values))
    else:
        if damage == "original":
            next(iter(active.store.__dict__[ContractAttachmentChunkORM.__tablename__].values())).data = b"corrupt"
        elif damage == "template":
            next(iter(active.store.__dict__[ContractTemplateORM.__tablename__].values())).body = "Corrupted unrelated personal contents"
        else:
            record = active.store.__dict__[ContractDraftORM.__tablename__][row["id"]]
            field, value = ({"pdf": ("pdf", b"%PDF-corrupt"), "missing_pdf_hash": ("pdf_sha256", None),
                            "review": ("review_hash", "f" * 64)})[damage]
            setattr(record, field, value)
    with pytest.raises(TenantExportError):
        prepare_tenant_export(active.store, tenant_id, parent=active.tmp)
    assert not list(active.tmp.glob("immomanager-server-*"))


def test_revoked_scope_during_output_refuses_success_and_cleans_up(active, monkeypatch):
    _, tenant_id, _, _, _ = completed(active, existing=True)
    from backend.services import tenant_wizard_graph
    original = tenant_wizard_graph.verified_blocks
    def revoked(store, manifest):
        for block in original(store, manifest):
            yield block
            active.users["actor"]["portfolio_ids"] = []
    monkeypatch.setattr(tenant_wizard_graph, "verified_blocks", revoked)
    with scope_context(scope_from_user(active.users["actor"])), pytest.raises(HTTPException) as denied:
        prepare_tenant_export(active.store, tenant_id, parent=active.tmp)
    assert denied.value.status_code == 403
    assert not list(active.tmp.glob("immomanager-server-*"))


def test_sql_download_reads_binary_substrings_instead_of_full_pdf_values(active):
    if not active.engine:
        pytest.skip("SQL BLOB read regression")
    _, tenant_id, _, _, _ = completed(active)
    from sqlalchemy import event
    statements = []
    def observe(_connection, _cursor, statement, _parameters, _context, _many):
        if "contract_wizard_drafts" in statement and statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement)
    event.listen(active.engine, "before_cursor_execute", observe)
    try:
        compiled, _ = prepare_tenant_export(active.store, tenant_id, parent=active.tmp)
        compiled.close()
    finally:
        event.remove(active.engine, "before_cursor_execute", observe)
    assert any("substr(" in statement.lower() for statement in statements)
    assert all("WHERE" in statement.upper() for statement in statements)
    assert not any(re.search(r"(?:SELECT|,)\s*contract_wizard_drafts\.pdf\s*(?:,|FROM)", statement)
                   for statement in statements)


def test_hidden_shared_subject_references_block_profile_changes_without_exporting_foreign_portfolio(active):
    row = prepare(active, tenant_id=active.tenant.id, new_tenant=None)
    active.users["actor"]["portfolio_ids"] = [active.p.id, active.foreign.id]
    hidden_data = data(active, tenant_id=active.tenant.id, new_tenant=None,
        property_id=active.other.id, unit_id=active.other_unit.id,
        contract_number="Hidden-portfolio-draft", terms="HIDDEN PORTFOLIO PII MUST NOT LEAK")
    wizard.create_draft(active.store, DraftCreate(idempotency_key="hidden-draft", data=hidden_data), "actor")
    unrestricted = preview_tenant_anonymization(active.store, active.tenant.id)
    active.users["actor"]["portfolio_ids"] = [active.p.id]
    with scope_context(scope_from_user(active.users["actor"])):
        graph = export_tenant_metadata(active.store, active.tenant.id)
        assert [item["id"] for item in graph["contract_wizard_drafts"]] == [row["id"]]
        assert "HIDDEN PORTFOLIO" not in json.dumps(graph)
        with pytest.raises(HTTPException) as preview_denied:
            preview_tenant_anonymization(active.store, active.tenant.id)
        assert preview_denied.value.status_code == 403
        with pytest.raises(HTTPException) as mutation_denied:
            anonymize_tenant_profile(active.store, active.tenant.id,
                plan_hash=unrestricted["plan_hash"], confirm_tenant_id=active.tenant.id)
        assert mutation_denied.value.status_code == 403
    assert active.store.get_tenant(active.tenant.id).full_name == active.tenant.full_name


@pytest.mark.parametrize("new_party", [True, False])
def test_foreign_contract_attachment_is_rejected_before_creating_draft_or_freezing_evidence(active, new_party):
    with scope_context(scope_from_user(active.users["actor"])):
        foreign = active.store.create_tenant(TenantCreate(full_name="Foreign source owner"))
        contract = active.store.create_contract(ContractCreate(contract_number="Foreign-source-contract",
            property_id=active.property.id, unit_id=active.unit.id, tenant_id=foreign.id,
            start_date=date(2025, 1, 1), status="draft"))
    # Administrative fixture setup only; no external bytes are fetched.
    document = active.store.create_document(DocumentCreate(contract_id=contract.id,
        property_id=active.property.id, unit_id=active.unit.id, title="Foreign personal document",
        file_url="https://example.invalid/no-fetch"))
    changes = {} if new_party else {"tenant_id": active.tenant.id, "new_tenant": None}
    with pytest.raises(ValidationError, match="anderen Mieter"):
        prepare(active, attachment_ids=[document.id], metadata_only_attachment_ids=[document.id], **changes)
    assert wizard.list_drafts(active.store, "actor")["items"] == []


def test_http_download_is_complete_private_authenticated_and_readonly_cannot_anonymize(active, monkeypatch):
    _, tenant_id, original, _, _ = completed(active)
    monkeypatch.setattr(auth, "_user_store", auth.InMemoryUserStore())
    monkeypatch.setattr(auth, "_auth_session_factory", None)
    monkeypatch.setattr(auth, "get_user_by_id", auth._user_store.get_by_id)
    monkeypatch.setattr(dependencies, "store", active.store)
    monkeypatch.setattr(admin, "store", active.store)
    owner = auth.register_user("privacy-owner", "owner@example.test", "Own owner", "Strong123", "eigentuemer")
    reader = auth.register_user("privacy-reader", "reader@example.test", "Reader", "Strong123", "readonly")
    headers = {"Authorization": "Bearer " + auth.create_access_token(owner.id)}
    readonly = {"Authorization": "Bearer " + auth.create_access_token(reader.id)}
    app = FastAPI()
    app.include_router(admin.router, prefix="/api/v1", dependencies=[Depends(auth.require_role("eigentuemer", "verwalter"))])
    root = "/api/v1/admin/dsgvo/tenant/" + tenant_id
    with TestClient(PortfolioScopeMiddleware(app)) as client:
        assert client.get(root + "/export").status_code == 401
        assert client.get(root + "/export", headers=readonly).status_code == 403
        response = client.get(root + "/export", headers=headers)
        assert response.status_code == 200, response.text
        assert response.headers["cache-control"] == "private, no-store"
        assert response.headers["content-type"].startswith("application/json")
        assert response.headers["x-content-sha256"] == hashlib.sha256(response.content).hexdigest()
        assert int(response.headers["content-length"]) == len(response.content)
        result = response.json()
        attachment = next(item for item in result["wizard_file_contents"] if item["id"].startswith("wizard-attachment:"))
        assert b"".join(base64.b64decode(block["data_base64"]) for block in attachment["blocks"]) == original
        preview = client.get(root + "/anonymization-preview", headers=headers).json()
        body = {"plan_hash": preview["plan_hash"], "confirm_tenant_id": tenant_id}
        assert client.post(root + "/anonymize", headers=readonly, json=body).status_code == 403
        saved = client.post(root + "/anonymize", headers=headers, json=body)
        assert saved.status_code == 200, saved.text
        assert saved.json()["retained_personal_evidence"]["contract_signature_evidence"]["count"] == 1


def private_editor_fixture(box, tenant_id, *, revision="private-one", foreign=False):
    from sqlalchemy import Column, DateTime, MetaData, String, Table, Text
    now = datetime(2026, 10, 1)
    row = {"id": "opaque-private-key-" + str(foreign), "user_id": "OTHER PRIVATE USER",
        "collection": "tenants", "entity_id": tenant_id, "form_key": "edit",
        "scope_hash": "synthetic-scope", "revision": revision,
        "payload": "FOREIGN ENCRYPTED WORK MUST NOT LEAK", "updated_at": now,
        "expires_at": now + timedelta(days=7)}
    if box.engine:
        table = Table("form_drafts", MetaData(), Column("id", String, primary_key=True),
            *[Column(key, DateTime if key in {"updated_at", "expires_at"} else Text)
              for key in row if key != "id"])
        box.store.db.rollback()
        with box.engine.begin() as connection:
            table.create(connection, checkfirst=True)
            connection.execute(table.insert().values(**row))
    else:
        box.store.__dict__.setdefault("_form_drafts", {})[row["id"]] = row
    return row


def test_private_editors_remain_opaque_but_revision_changes_invalidate_review_and_block_normal_delete(active):
    tenant_id = active.tenant.id
    row = private_editor_fixture(active, tenant_id)
    other = active.store.create_tenant(TenantCreate(full_name="Foreign draft subject"))
    private_editor_fixture(active, other.id, foreign=True)
    graph = export_tenant_metadata(active.store, tenant_id)
    assert graph["scope"]["private_form_drafts"]["count"] == 1
    assert "OTHER PRIVATE USER" not in json.dumps(graph)
    assert "FOREIGN ENCRYPTED WORK" not in json.dumps(graph)
    assert "opaque-private-key" not in json.dumps(graph)
    preview = preview_tenant_anonymization(active.store, tenant_id)
    assert preview["retained_personal_evidence"]["private_form_drafts"]["contents_exported"] is False
    with pytest.raises(ValidationError, match="Private Formularentwürfe"):
        active.store.delete_tenant(tenant_id)
    if active.engine:
        from sqlalchemy import MetaData, Table
        active.store.db.rollback()
        with active.engine.begin() as connection:
            table = Table("form_drafts", MetaData(), autoload_with=connection)
            connection.execute(table.update().where(table.c.id == row["id"]).values(revision="new-private-revision"))
    else:
        row["revision"] = "new-private-revision"
    with pytest.raises(PrivacyConflict, match="Datenstand"):
        anonymize_tenant_profile(active.store, tenant_id, plan_hash=preview["plan_hash"], confirm_tenant_id=tenant_id)
    fresh = preview_tenant_anonymization(active.store, tenant_id)
    result = anonymize_tenant_profile(active.store, tenant_id, plan_hash=fresh["plan_hash"], confirm_tenant_id=tenant_id)
    assert result["retained_personal_evidence"]["private_form_drafts"]["count"] == 1
    assert active.store.get_tenant(tenant_id).full_name == "Anonymisiert-" + tenant_id


def test_own_contract_attachment_remains_reviewable_and_unrelated_identical_prospect_never_leaks(active):
    contract = active.store.create_contract(ContractCreate(contract_number="Own-source",
        property_id=active.property.id, unit_id=active.unit.id, tenant_id=active.tenant.id,
        start_date=date(2025, 1, 1), status="draft"))
    document = active.store.create_document(DocumentCreate(contract_id=contract.id,
        property_id=active.property.id, unit_id=active.unit.id, title="Own party source",
        file_url="https://example.invalid/metadata-only"))
    own = prepare(active, tenant_id=active.tenant.id, new_tenant=None,
        attachment_ids=[document.id], metadata_only_attachment_ids=[document.id])
    # Equal prospect names are not a tenant binding. No broad PII/name search.
    wizard.create_draft(active.store, DraftCreate(idempotency_key="unbound-prospect",
        data=data(active, new_tenant={"full_name": active.tenant.full_name}, terms="UNBOUND PRIVATE PROSPECT")), "actor")
    graph = export_tenant_metadata(active.store, active.tenant.id)
    assert [row["id"] for row in graph["contract_wizard_drafts"]] == [own["id"]]
    assert "UNBOUND PRIVATE PROSPECT" not in json.dumps(graph)


def test_preexisting_foreign_contract_in_immutable_attachment_snapshot_fails_closed(active):
    row, tenant_id, _, _, _ = completed(active)
    foreign = active.store.create_tenant(TenantCreate(full_name="Historic foreign party"))
    contract = active.store.create_contract(ContractCreate(contract_number="Historic foreign source",
        property_id=active.property.id, unit_id=active.unit.id, tenant_id=foreign.id,
        start_date=date(2025, 1, 1), status="draft"))
    # Explicit synthetic corrupted historical evidence, never through the API.
    review = deepcopy(row["review"])
    review["attachments"][0]["contract_id"] = contract.id
    if active.engine:
        active.store.db.rollback()
        with active.engine.begin() as connection:
            connection.exec_driver_sql("DROP TRIGGER immo_contract_wizard_drafts_keep_update")
            connection.execute(ContractDraftORM.__table__.update().where(ContractDraftORM.id == row["id"])
                .values(review=review, review_hash=wizard.digest(review)))
    else:
        stored = active.store.__dict__[ContractDraftORM.__tablename__][row["id"]]
        stored.review, stored.review_hash = review, wizard.digest(review)
    with pytest.raises(TenantExportError, match="another tenant"):
        prepare_tenant_export(active.store, tenant_id, parent=active.tmp)
    assert not list(active.tmp.glob("immomanager-server-*"))


@pytest.mark.parametrize("fail_on_body", [False, True])
def test_actual_private_tenant_response_cleans_owned_output_when_headers_or_body_disconnect(active, monkeypatch, fail_on_body):
    import anyio
    from starlette.requests import ClientDisconnect
    _, tenant_id, _, _, _ = completed(active)
    monkeypatch.setattr(admin, "store", active.store)
    response = admin.dsgvo_export_tenant_data(tenant_id)
    directory = response.compiled.path.parent
    async def disconnected():
        async def send(message):
            if message["type"] == ("http.response.body" if fail_on_body else "http.response.start"):
                assert directory.exists()
                raise OSError("Synthetic closed connection")
        async def receive():
            return {"type": "http.disconnect"}
        await response({"type": "http", "asgi": {"spec_version": "2.4"}}, receive, send)
    with pytest.raises((OSError, ClientDisconnect)):
        anyio.run(disconnected)
    assert not directory.exists()


def test_selected_scope_cannot_export_a_foreign_tenant_or_expand_foreign_journals(active):
    from backend.services.tenant_data_graph import TenantNotFoundError
    other = active.store.create_tenant(TenantCreate(full_name="FOREIGN PORTFOLIO PARTY"))
    active.store.create_contract(ContractCreate(contract_number="Foreign portfolio contract",
        property_id=active.other.id, unit_id=active.other_unit.id, tenant_id=other.id,
        start_date=date(2025, 1, 1), status="draft"))
    with scope_context(scope_from_user(active.users["actor"])):
        with pytest.raises(TenantNotFoundError):
            prepare_tenant_export(active.store, other.id, parent=active.tmp)
    assert not list(active.tmp.glob("immomanager-server-*"))


def test_sqlite_private_draft_writer_and_normal_tenant_delete_never_leave_an_orphan(active):
    if not active.engine:
        pytest.skip("Independent SQLite writer transactions")
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event, current_thread

    from sqlalchemy import MetaData, Table, event
    from sqlalchemy.orm import Session

    from backend.repositories.sql_store import SQLAlchemyStore
    row = private_editor_fixture(active, active.tenant.id)
    active.store.db.rollback()
    with active.engine.begin() as connection:
        table = Table("form_drafts", MetaData(), autoload_with=connection)
        connection.execute(table.delete())
    locked, finish_writer, committed = Event(), Event(), Event()
    def write():
        with active.engine.connect() as connection:
            connection.exec_driver_sql("BEGIN IMMEDIATE")
            locked.set()
            assert finish_writer.wait(10)
            connection.execute(table.insert().values(**row))
            connection.commit()
        committed.set()
    def delete():
        with Session(active.engine) as db:
            SQLAlchemyStore(db).delete_tenant(active.tenant.id)
    def release_before_write(_connection, _cursor, statement, _parameters, _context, _many):
        if current_thread().name.startswith("tenant-delete") and statement.upper().startswith("BEGIN IMMEDIATE"):
            finish_writer.set()
    def release_after_old_check(_connection, _cursor, statement, _parameters, _context, _many):
        # Also makes the pre-fix race reproducible: an unlocked empty retention
        # SELECT must not authorize deletion after a competing draft commits.
        if (current_thread().name.startswith("tenant-delete") and "FROM form_drafts" in statement
                and "WHERE" in statement and statement.lstrip().upper().startswith("SELECT")):
            finish_writer.set()
            assert committed.wait(10)
    event.listen(active.engine, "before_cursor_execute", release_before_write)
    event.listen(active.engine, "after_cursor_execute", release_after_old_check)
    try:
        with ThreadPoolExecutor(max_workers=1, thread_name_prefix="draft-writer") as writer_pool:
            writer = writer_pool.submit(write)
            assert locked.wait(10)
            try:
                with ThreadPoolExecutor(max_workers=1, thread_name_prefix="tenant-delete") as delete_pool:
                    deleted = delete_pool.submit(delete)
                    with pytest.raises(ValidationError, match="Private Formularentwürfe"):
                        deleted.result(timeout=15)
                writer.result(timeout=10)
            finally:
                finish_writer.set()
    finally:
        finish_writer.set()
        event.remove(active.engine, "before_cursor_execute", release_before_write)
        event.remove(active.engine, "after_cursor_execute", release_after_old_check)
    assert active.store.get_tenant(active.tenant.id).full_name == active.tenant.full_name
    with active.engine.connect() as connection:
        assert connection.execute(table.select().where(table.c.entity_id == active.tenant.id)).first() is not None


def test_memory_private_writer_and_fresh_scoped_snapshot_share_one_lock_order(active, monkeypatch):
    if active.engine:
        pytest.skip("Native memory account/financial locks")
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event, current_thread

    from backend.services import portfolio_scope, tenant_privacy
    from backend.services.payments import _memory_lock
    account_store = auth.InMemoryUserStore()
    account_store.create({**active.users["actor"], "username": "synthetic-memory-actor", "email": "actor@example.test"})
    monkeypatch.setattr(auth, "_user_store", account_store)
    monkeypatch.setattr(auth, "get_user_by_id", account_store.get_by_id)
    initial, allow_read, copying = Event(), Event(), Event()
    original_refresh, original_copy = portfolio_scope.refresh_scope, tenant_privacy._memory_copy
    def pause_after_initial_refresh(captured):
        result = original_refresh(captured)
        if current_thread().name.startswith("privacy-reader") and not initial.is_set():
            initial.set()
            assert allow_read.wait(5)
        return result
    def copy_started(store):
        copying.set()
        return original_copy(store)
    monkeypatch.setattr(portfolio_scope, "refresh_scope", pause_after_initial_refresh)
    monkeypatch.setattr(tenant_privacy, "_memory_copy", copy_started)
    def read():
        with scope_context(scope_from_user(active.users["actor"])):
            with tenant_privacy._read_snapshot(active.store) as snapshot:
                assert auth.get_user_by_id("actor")["is_active"]
                return bool(snapshot.__dict__.get("_form_drafts"))
    def write():
        assert initial.wait(5)
        with account_store._lock:
            allow_read.set()
            copying.wait(.25)
            acquired = _memory_lock.acquire(timeout=2)
            try:
                if acquired:
                    active.store.__dict__["_form_drafts"] = {"synthetic": {"opaque": "private work"}}
                return acquired
            finally:
                if acquired:
                    _memory_lock.release()
    with ThreadPoolExecutor(max_workers=1, thread_name_prefix="privacy-reader") as readers:
        reading = readers.submit(read)
        try:
            with ThreadPoolExecutor(max_workers=1, thread_name_prefix="private-writer") as writers:
                assert writers.submit(write).result(timeout=10)
            assert reading.result(timeout=10)
        finally:
            allow_read.set()
