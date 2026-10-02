"""Independent privacy review: complete journals, fresh scope and real bytes."""

import asyncio
import base64
import hashlib
import json
from datetime import date
from io import BytesIO
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, update
from sqlalchemy.orm import Session, scoped_session, sessionmaker

from backend import auth, dependencies
from backend.db.document_version_models import DocumentVersionChunkORM, DocumentVersionORM
from backend.middleware import DBSessionMiddleware
from backend.models import ContractCreate, DocumentCreate, TenantCreate, UnitCreate
from backend.repositories.sql_store import SQLAlchemyStore
from backend.routers import admin
from backend.routers.datev import download_chunks
from backend.routing import build_api_v1
from backend.services import document_versions as versions
from backend.services import tenant_document_versions
from backend.services.document_version_types import OriginalCommand, RestoreCommand
from backend.services.portfolio_http import PortfolioScopeMiddleware
from backend.services.portfolio_scope import AccessScope, scope_context, scope_from_user
from backend.services.tenant_data_graph import TenantExportError
from backend.services.tenant_privacy import (
    PrivacyConflict,
    anonymize_tenant_profile,
    prepare_tenant_export,
    preview_tenant_anonymization,
)
from backend.tests import test_document_versions as version_fixtures
from backend.tests.test_tenant_document_versions import archive_document, archived_subject

active = version_fixtures.active


def test_sql_nullable_historical_portfolio_cannot_hide_an_authorized_document_journal():
    # A bounded actual SQLite truth-table proof for a damaged historical schema;
    # current production NOT NULL constraints are not relaxed by the service.
    engine = create_engine("sqlite://")
    try:
        with engine.begin() as connection, Session(bind=connection) as db:
            connection.exec_driver_sql("CREATE TABLE document_versions (document_id TEXT NOT NULL, portfolio_id TEXT, tenant_id TEXT)")
            connection.exec_driver_sql("INSERT INTO document_versions VALUES ('separate-hidden-document', NULL, 'subject')")
            with scope_context(AccessScope("actor", "verwalter", False, ("own-portfolio",))):
                tenant_document_versions._require_complete_document_scope(SimpleNamespace(db=db), {"authorized-document"})
                with pytest.raises(HTTPException) as denied:
                    tenant_document_versions.require_complete_subject_scope(SimpleNamespace(db=db), "subject")
                assert denied.value.status_code == 403
                connection.exec_driver_sql("INSERT INTO document_versions VALUES ('authorized-document', NULL, 'subject')")
                with pytest.raises(TenantExportError):
                    tenant_document_versions._require_complete_document_scope(SimpleNamespace(db=db), {"authorized-document"})
    finally:
        engine.dispose()


def corrupt_version(box, version_id, **changes):
    """Synthetic damage only, including the actual append-only SQLite guard."""
    if box.engine is None:
        for name, value in changes.items():
            setattr(box.store.document_versions[version_id], name, value)
    else:
        with box.engine.begin() as connection:
            connection.exec_driver_sql("DROP TRIGGER immo_document_versions_update")
            connection.execute(update(DocumentVersionORM).where(
                DocumentVersionORM.id == version_id).values(**changes))
        box.db.expire_all()


def test_selected_scope_never_silently_truncates_a_visible_document_journal(active):
    tenant, _contract, _original = archived_subject(active)
    tail = versions.publish(active.store, active.document.id, version_fixtures.command(active),
        "actor", source=BytesIO(b"Second private original"), upload_name="second.txt")
    corrupt_version(active, tail["id"], portfolio_id=active.foreign.id)
    before = {item.name for item in active.tmp.iterdir()}
    with scope_context(scope_from_user(active.users["actor"])):
        with pytest.raises(TenantExportError):
            prepare_tenant_export(active.store, tenant.id, parent=active.tmp)
    assert {item.name for item in active.tmp.iterdir()} == before


@pytest.mark.parametrize("operation", ["history", "source_preview", "archive", "upload"])
def test_normal_version_apis_reject_hidden_corruption_before_business_dml(active, operation):
    _tenant, _contract, original = archived_subject(active)
    request = version_fixtures.command(active, "must-not-publish")
    if operation == "archive":
        damaged = original
    else:
        damaged = versions.publish(active.store, active.document.id, version_fixtures.command(active),
            "actor", source=BytesIO(b"Second private version"), upload_name="second.txt")
    corrupt_version(active, damaged["id"], portfolio_id=active.foreign.id)
    statements = []
    before_versions = len(active.store.document_versions) if active.engine is None else None

    def observe(_connection, _cursor, sql, _parameters, _context, _many):
        if sql.lstrip().upper().startswith(("INSERT", "UPDATE", "DELETE")):
            statements.append(sql)

    if active.engine is not None:
        event.listen(active.engine, "before_cursor_execute", observe)
    try:
        with scope_context(scope_from_user(active.users["actor"])), pytest.raises(HTTPException) as denied:
            if operation == "history":
                versions.history(active.store, active.document.id, "actor")
            elif operation == "source_preview":
                versions.source_preview(active.store, active.document.id, "actor")
            elif operation == "archive":
                archive_request = OriginalCommand(**{**request.model_dump(), "expected_head_id": None},
                    expected_sha256=hashlib.sha256(active.content).hexdigest())
                versions.publish(active.store, active.document.id, archive_request, "actor")
            else:
                versions.publish(active.store, active.document.id, request, "actor",
                    source=BytesIO(b"Must never publish"), upload_name="pending.txt")
        assert denied.value.status_code == 503
        assert not statements
        if active.engine is None:
            assert len(active.store.document_versions) == before_versions
    finally:
        if active.engine is not None:
            event.remove(active.engine, "before_cursor_execute", observe)


def test_complete_api_enforces_current_roles_scope_and_preserves_all_profile_evidence(active, monkeypatch):
    tenant, _contract, rows, _originals = complete_chain(active)
    active.storage.delete("documents/original.txt")
    registry = None
    store = active.store
    if active.engine is not None:
        registry = scoped_session(sessionmaker(bind=active.engine), scopefunc=dependencies.session_scope_key)
        store = SQLAlchemyStore(registry)
    monkeypatch.setattr(dependencies, "_scoped_session", registry)
    monkeypatch.setattr(dependencies, "store", store)
    monkeypatch.setattr(admin, "store", store)
    monkeypatch.setattr(auth, "_user_store", auth.InMemoryUserStore())
    monkeypatch.setattr(auth, "_auth_session_factory", None)
    monkeypatch.setattr(auth, "get_user_by_id", auth._user_store.get_by_id)
    owner = auth.register_user("privacy-owner", "owner@example.test", "Owner", "StrongPass123!", "eigentuemer")
    manager = auth.register_user("privacy-manager", "manager@example.test", "Manager", "StrongPass123!", "verwalter")
    reader = auth.register_user("privacy-reader", "reader@example.test", "Reader", "StrongPass123!", "readonly")
    selected = auth.register_user("privacy-selected", "selected@example.test", "Selected", "StrongPass123!", "verwalter",
        portfolio_access="selected", portfolio_ids=[active.p.id])

    def headers(user):
        return {"Authorization": "Bearer " + auth.create_access_token(user.id)}

    app = FastAPI()
    app.include_router(build_api_v1())
    root = "/api/v1/admin/dsgvo/tenant/" + tenant.id
    try:
        with TestClient(DBSessionMiddleware(PortfolioScopeMiddleware(app))) as client:
            assert client.get(root + "/export").status_code == 401
            assert client.get(root + "/export", headers=headers(reader)).status_code == 403
            # Installation administration currently requires all portfolios;
            # the helper's exact subject scope never overrides that HTTP rule.
            selected_headers = headers(selected)
            assert client.get(root + "/export", headers=selected_headers).status_code == 403
            owner_headers = headers(owner)
            manager_headers = headers(manager)
            response = client.get(root + "/export", headers=manager_headers)
            assert response.status_code == 200, response.text
            assert [row["id"] for row in response.json()["document_versions"]] == [row["id"] for row in rows]
            assert int(response.headers["content-length"]) == len(response.content)
            assert response.headers["x-content-sha256"] == hashlib.sha256(response.content).hexdigest()
            assert response.headers["cache-control"] == "private, no-store"
            auth.update_user(manager.id, {"role": "readonly"}, actor_id=owner.id)
            assert client.get(root + "/export", headers=manager_headers).status_code == 403
            auth.update_user(selected.id, {"portfolio_access": "all", "portfolio_ids": []}, actor_id=owner.id)
            assert client.get(root + "/export", headers=selected_headers).status_code == 200
            auth.update_user(selected.id, {"portfolio_access": "selected", "portfolio_ids": []}, actor_id=owner.id)
            assert client.get(root + "/export", headers=selected_headers).status_code == 403
            preview = client.get(root + "/anonymization-preview", headers=owner_headers)
            assert preview.status_code == 200, preview.text
            assert preview.json()["retained_personal_evidence"]["document_versions"]["count"] == 3
            body = {"plan_hash": preview.json()["plan_hash"], "confirm_tenant_id": tenant.id}
            assert client.post(root + "/anonymize", headers=headers(reader), json=body).status_code == 403
            saved = client.post(root + "/anonymize", headers=owner_headers, json=body)
            assert saved.status_code == 200, saved.text
            assert saved.json()["scope"] == "tenant_profile_only"
            assert saved.json()["retained_personal_evidence"]["document_versions"]["count"] == 3
            retained = client.get(root + "/export", headers=owner_headers).json()
            assert retained["tenant"]["full_name"] == "Anonymisiert-" + tenant.id
            assert [row["id"] for row in retained["document_versions"]] == [row["id"] for row in rows]
            assert len(retained["document_version_contents"]) == 3
    finally:
        if registry is not None:
            registry.remove()


def test_memory_profile_cas_preserves_a_concurrent_document_journal_change(active, monkeypatch):
    if active.engine is not None:
        pytest.skip("Native Memory CAS regression")
    tenant, _contract, original = archived_subject(active)
    previous_profile = active.store.get_tenant(tenant.id).model_dump()
    plan = preview_tenant_anonymization(active.store, tenant.id)
    original_patch = type(active.store)._patch_entity

    def edited_while_staging(store, kind, entity_id, payload):
        result = original_patch(store, kind, entity_id, payload)
        if kind == "tenant" and store is not active.store:
            active.store.document_versions[original["id"]].comment = "Concurrent actual journal change"
        return result

    monkeypatch.setattr(type(active.store), "_patch_entity", edited_while_staging)
    with pytest.raises(PrivacyConflict, match="während"):
        anonymize_tenant_profile(active.store, tenant.id,
            plan_hash=plan["plan_hash"], confirm_tenant_id=tenant.id)
    assert active.store.get_tenant(tenant.id).model_dump() == previous_profile
    assert active.store.document_versions[original["id"]].comment == "Concurrent actual journal change"


def complete_chain(box):
    tenant, contract, original = archived_subject(box, contract_only=True)
    current_bytes = b"Second reviewed private version\n" * 3500
    current = versions.publish(box.store, box.document.id, version_fixtures.command(box),
        "actor", source=BytesIO(current_bytes), upload_name="second.txt")
    restored = versions.publish(box.store, box.document.id,
        RestoreCommand(**version_fixtures.command(box, "restore").model_dump(), source_version_id=original["id"]),
        "actor", restore=True)
    return tenant, contract, (original, current, restored), (box.content, current_bytes, box.content)


def test_source_gone_export_contains_every_link_and_original_of_contract_only_chain(active):
    tenant, contract, rows, originals = complete_chain(active)
    active.storage.delete("documents/original.txt")
    with scope_context(scope_from_user(active.users["actor"])):
        compiled, _ = prepare_tenant_export(active.store, tenant.id, parent=active.tmp)
    try:
        payload = json.loads(compiled.path.read_bytes())
        assert [row["id"] for row in payload["document_versions"]] == [row["id"] for row in rows]
        assert [row["predecessor_id"] for row in payload["document_versions"]] == [None, rows[0]["id"], rows[1]["id"]]
        assert payload["document_versions"][2]["restored_from_id"] == rows[0]["id"]
        for value, manifest, contents, original in zip(payload["document_versions"],
                payload["document_version_files"], payload["document_version_contents"], originals, strict=True):
            assert value["contract_id"] == contract.id
            assert value["property_id"] == active.prop.id and value["unit_id"] == active.unit.id
            assert "file_url" not in value["metadata_snapshot"] and "download_url" not in value
            assert manifest["id"] == contents["id"] == "document-version:" + value["id"]
            blocks = [base64.b64decode(block["data_base64"], validate=True) for block in contents["blocks"]]
            assert [block["position"] for block in contents["blocks"]] == list(range(len(blocks)))
            assert all(0 < len(block) <= 65536 for block in blocks)
            assert b"".join(blocks) == original
            assert manifest["size_bytes"] == len(original)
            assert manifest["sha256"] == hashlib.sha256(original).hexdigest()
        payload["document_versions"][0]["metadata_snapshot"]["title"] = "Detached caller change"
        assert versions.history(active.store, active.document.id, "actor")["items"][-1]["metadata_snapshot"]["title"] == "Synthetic original"
    finally:
        workspace = compiled.path.parent
        compiled.close()
    assert not workspace.exists()


def test_distinct_hidden_subject_document_never_expands_export_or_permits_profile_edit(active):
    tenant, _contract, original = archived_subject(active)
    foreign_unit = active.store.create_unit(UnitCreate(property_id=active.other.id, label="Hidden", unit_type="apartment"))
    hidden_contract = active.store.create_contract(ContractCreate(contract_number="Hidden-subject-contract",
        property_id=active.other.id, unit_id=foreign_unit.id, tenant_id=tenant.id,
        start_date=date(2020, 1, 1), end_date=date(2021, 12, 31), status="terminated"))
    hidden = active.store.create_document(DocumentCreate(title="HIDDEN ORIGINAL MUST NOT LEAK",
        contract_id=hidden_contract.id, file_url="/uploads/documents/original.txt"))
    active.users["actor"]["portfolio_ids"] = [active.p.id, active.foreign.id]
    hidden_receipt = archive_document(active, hidden, "hidden-original")
    full_plan = preview_tenant_anonymization(active.store, tenant.id)
    active.users["actor"]["portfolio_ids"] = [active.p.id]
    with scope_context(scope_from_user(active.users["actor"])):
        compiled, _ = prepare_tenant_export(active.store, tenant.id, parent=active.tmp)
        try:
            payload = json.loads(compiled.path.read_bytes())
            assert [row["id"] for row in payload["document_versions"]] == [original["id"]]
            assert hidden_receipt["id"] not in compiled.path.read_text(encoding="utf-8")
            assert "HIDDEN ORIGINAL" not in json.dumps(payload)
            assert [row["id"] for row in payload["contracts"]] == [active.document.contract_id]
        finally:
            compiled.close()
        with pytest.raises(HTTPException) as preview_denied:
            preview_tenant_anonymization(active.store, tenant.id)
        assert preview_denied.value.status_code == 403
        with pytest.raises(HTTPException) as mutation_denied:
            anonymize_tenant_profile(active.store, tenant.id,
                plan_hash=full_plan["plan_hash"], confirm_tenant_id=tenant.id)
        assert mutation_denied.value.status_code == 403
    assert active.store.get_tenant(tenant.id).full_name == tenant.full_name


@pytest.mark.parametrize("damage", ["gap", "predecessor", "restore_source", "tenant"])
def test_corrupt_chain_or_party_aborts_complete_private_output(active, damage):
    tenant, _contract, rows, _originals = complete_chain(active)
    if damage == "gap":
        corrupt_version(active, rows[2]["id"], number=4)
    elif damage == "predecessor":
        corrupt_version(active, rows[1]["id"], predecessor_id=rows[1]["id"])
    elif damage == "restore_source":
        corrupt_version(active, rows[2]["id"], restored_from_id=rows[1]["id"])
    else:
        foreign = active.store.create_tenant(TenantCreate(full_name="Different explicit party"))
        corrupt_version(active, rows[2]["id"], tenant_id=foreign.id)
    before = {item.name for item in active.tmp.iterdir()}
    with scope_context(scope_from_user(active.users["actor"])), pytest.raises(TenantExportError):
        prepare_tenant_export(active.store, tenant.id, parent=active.tmp)
    assert {item.name for item in active.tmp.iterdir()} == before


@pytest.mark.parametrize("changed", ["role", "grants", "inactive"])
def test_revoked_identity_during_private_compilation_cleans_before_release(active, monkeypatch, changed):
    tenant, _contract, _original = archived_subject(active)
    original_blocks = tenant_document_versions.verified_blocks

    def revoked(store, manifest):
        for block in original_blocks(store, manifest):
            yield block
            active.users["actor"].update({"role": "readonly"} if changed == "role" else
                {"portfolio_ids": []} if changed == "grants" else {"is_active": False})

    monkeypatch.setattr(tenant_document_versions, "verified_blocks", revoked)
    before = {item.name for item in active.tmp.iterdir()}
    with scope_context(scope_from_user(active.users["actor"])), pytest.raises(HTTPException) as denied:
        prepare_tenant_export(active.store, tenant.id, parent=active.tmp)
    assert denied.value.status_code == 403
    assert {item.name for item in active.tmp.iterdir()} == before


def test_grant_revocation_after_preparation_yields_no_first_byte_and_removes_private_output(active):
    tenant, _contract, _original = archived_subject(active)
    captured = scope_from_user(active.users["actor"])
    with scope_context(captured):
        compiled, _ = prepare_tenant_export(active.store, tenant.id, parent=active.tmp)
    workspace = compiled.path.parent
    active.users["actor"]["portfolio_ids"] = []

    async def attempt():
        iterator = download_chunks(compiled, captured)
        try:
            with pytest.raises(HTTPException) as denied:
                await anext(iterator)
            assert denied.value.status_code == 403
        finally:
            await iterator.aclose()

    asyncio.run(attempt())
    assert not workspace.exists()


def test_sql_privacy_originals_are_size_guarded_before_dbapi_materialization(active):
    if active.engine is None:
        pytest.skip("Real SQLite DBAPI statement proof")
    tenant, _contract, _original = archived_subject(active)
    statements = []

    def observe(_connection, _cursor, statement, _parameters, _context, _many):
        if "document_version_chunks" in statement and statement.lstrip().upper().startswith("SELECT"):
            statements.append(statement.lower())

    event.listen(active.engine, "before_cursor_execute", observe)
    try:
        compiled, _ = prepare_tenant_export(active.store, tenant.id, parent=active.tmp)
        compiled.close()
    finally:
        event.remove(active.engine, "before_cursor_execute", observe)
    binary_reads = [sql for sql in statements if "document_version_chunks.data" in sql]
    assert binary_reads and all("case when" in sql and "length(" in sql and "where" in sql for sql in binary_reads)
    assert all("document_version_chunks.data" not in sql.split("case when", 1)[0] for sql in binary_reads)


@pytest.mark.parametrize("operation", ["tenant_export", "individual_download"])
def test_foreign_extra_chunk_of_empty_original_is_not_hidden_by_scoped_sql(active, operation):
    active.content = b""
    active.storage.save("documents/original.txt", BytesIO(active.content))
    tenant, _contract, original = archived_subject(active)
    # Empty originals remain valid evidence; the integrity check must only
    # reject the contradictory extra block that is injected afterwards.
    with scope_context(scope_from_user(active.users["actor"])):
        compiled, _ = prepare_tenant_export(active.store, tenant.id, parent=active.tmp)
        try:
            assert json.loads(compiled.path.read_bytes())["document_version_contents"][0]["blocks"] == []
        finally:
            compiled.close()
        downloaded, _ = versions.prepare_download(active.store, active.document.id, original["id"], "actor", parent=active.tmp)
        try:
            assert downloaded.path.read_bytes() == b""
        finally:
            downloaded.close()
    chunk = dict(version_id=original["id"], portfolio_id=active.foreign.id, position=0, data=b"Foreign corrupt extra block")
    if active.engine is None:
        active.store.document_version_chunks[(original["id"], 0)] = DocumentVersionChunkORM(**chunk)
    else:
        with active.engine.begin() as connection:
            connection.execute(DocumentVersionChunkORM.__table__.insert().values(**chunk))
        active.db.expire_all()
    before = {item.name for item in active.tmp.iterdir()}
    with scope_context(scope_from_user(active.users["actor"])):
        if operation == "tenant_export":
            with pytest.raises(TenantExportError):
                prepare_tenant_export(active.store, tenant.id, parent=active.tmp)
        else:
            with pytest.raises(HTTPException) as denied:
                versions.prepare_download(active.store, active.document.id, original["id"], "actor", parent=active.tmp)
            assert denied.value.status_code == 503
    assert {item.name for item in active.tmp.iterdir()} == before
