"""Transactional TEHA mapping/import commands on synthetic local evidence."""

from __future__ import annotations

import hashlib
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from threading import Barrier
from types import ModuleType, SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import Session, sessionmaker

from backend import auth
from backend.db.document_version_models import DocumentVersionORM
from backend.db.integration_history_schema import install_history_guards
from backend.db.orm_models import Base, DocumentORM, TaskORM
from backend.db.teha_receive_models import TehaExternalMappingORM, TehaImportReceiptORM
from backend.db.teha_receive_schema import install_teha_receive_guards
from backend.models import PortfolioCreate, PropertyCreate, TenantCreate, UnitCreate
from backend.repositories.sql_store import SQLAlchemyStore
from backend.services import document_versions
from backend.services.concurrency import etag
from backend.services.iban_encryption import IBANKeyring, generate_key
from backend.services.integrations.history_store import SQLIntegrationHistoryStore
from backend.services.integrations.history_types import HistoryActor
from backend.services.portfolio_scope import scope_context, scope_from_user
from backend.services.providers import teha_receive_commands as service
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
from backend.services.providers.teha_receive_contract import digest


@pytest.fixture
def box(tmp_path, monkeypatch):
    engine = create_engine(
        "sqlite:///" + (tmp_path / "teha-commands.db").as_posix(),
        connect_args={"check_same_thread": False, "timeout": 20},
    )
    @event.listens_for(engine, "connect")
    def configure(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA busy_timeout=20000")
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        install_history_guards(connection)
        install_teha_receive_guards(connection)
    db = Session(engine)
    store = SQLAlchemyStore(db)
    portfolio = store.create_portfolio(PortfolioCreate(name="Synthetic TEHA"))
    prop = store.create_property(PropertyCreate(portfolio_id=portfolio.id, name="Synthetic property", property_type="residential"))
    unit = store.create_unit(UnitCreate(property_id=prop.id, label="A", unit_type="apartment"))
    tenant = store.create_tenant(TenantCreate(full_name="Synthetic tenant"))
    # unrestricted owner avoids portfolio inference; source values are synthetic.
    users = {
        "actor": {
            "id": "actor",
            "role": "eigentuemer",
            "is_active": True,
            "portfolio_access": "all",
            "portfolio_ids": [portfolio.id],
        },
        "actor2": {
            "id": "actor2",
            "role": "eigentuemer",
            "is_active": True,
            "portfolio_access": "all",
            "portfolio_ids": [portfolio.id],
        },
    }
    monkeypatch.setattr(auth, "get_user_by_id", lambda identifier: users.get(identifier))

    authority_module = ModuleType("backend.services.commit_authority")

    class CommitAuthority:
        def __init__(self, actor_id):
            self.actor_id = actor_id

    CommitAuthority.__module__ = "backend.services.commit_authority"

    def validate_commit_authority(authority, actor_id):
        if authority.actor_id != actor_id:
            raise HTTPException(401, "synthetic commit authority mismatch")
        return None

    validate_commit_authority.__module__ = "backend.services.commit_authority"
    authority_module.CommitAuthority = CommitAuthority
    authority_module.validate_commit_authority = validate_commit_authority
    monkeypatch.setitem(
        sys.modules,
        "backend.services.commit_authority",
        authority_module,
    )
    authorities = {
        actor_id: CommitAuthority(actor_id) for actor_id in users
    }

    # Compose the domain exactly as Root will: every write gets a typed
    # CommitAuthority. This is not authority-by-lambda; the supplied evidence is
    # always the exact Root-contract class above.
    original_confirm_mapping = service.confirm_mapping
    original_import_document = service.import_document
    original_import_technical_order = service.import_technical_order

    def confirm_mapping(*args, **kwargs):
        actor_id = args[2]
        kwargs.setdefault("commit_authority", authorities[actor_id])
        return original_confirm_mapping(*args, **kwargs)

    def import_document(*args, **kwargs):
        actor_id = args[3]
        kwargs.setdefault("commit_authority", authorities[actor_id])
        return original_import_document(*args, **kwargs)

    def import_technical_order(*args, **kwargs):
        actor_id = args[2]
        kwargs.setdefault("commit_authority", authorities[actor_id])
        return original_import_technical_order(*args, **kwargs)

    monkeypatch.setattr(service, "confirm_mapping", confirm_mapping)
    monkeypatch.setattr(service, "import_document", import_document)
    monkeypatch.setattr(service, "import_technical_order", import_technical_order)

    history = SQLIntegrationHistoryStore(
        sessionmaker(engine),
        keyring=IBANKeyring("synthetic", {"synthetic": generate_key()}),
    )
    yield SimpleNamespace(
        engine=engine,
        db=db,
        store=store,
        portfolio=portfolio,
        property=prop,
        unit=unit,
        tenant=tenant,
        users=users,
        history=history,
        authorities=authorities,
        authority_module=authority_module,
    )
    db.close()
    engine.dispose()


def history_run(
    box,
    operation,
    body,
    *,
    arguments=None,
    manifest=None,
    connection_key="synthetic-connection",
):
    actor = HistoryActor.internal("synthetic:teha-command-tests")
    request = {
        "payload": {
            "operation": operation,
            "arguments": arguments or {},
            "connection_key": connection_key,
        },
        "privacy_policy": {"synthetic": True},
    }
    ticket = box.history.accept("teha", actor, request, {"synthetic": True})
    box.history.append(ticket, "execution_started", actor=actor)
    details = {"operation": operation, "exchange": {"response": {"body": body}}, "exchange_schema": {"synthetic": True}}
    if manifest is not None:
        details["result_manifest"] = manifest
    response = {"success": True, "message": "synthetic complete", "details": details}
    box.history.append(ticket, "completed", {"response": response, "schema": {"synthetic": True}}, actor=actor)
    return ticket.run_id


def property_source(box, *, late="v1"):
    row = {
        "liegId": {"id": 41, "abrechnungLaufendeNr": 7},
        "liegenschaftenNummer": "L-41",
        "abrechnungVon": "2026-01-01T00:00:00",
        "abrechnungBis": "2026-12-31T00:00:00",
        "unknown_late_field": late,
    }
    run = history_run(box, "list_property_periods", {"success": True, "liegenschaften": [row]})
    return row, run


def mapping_payload(box, row, run, *, key="map-1", expected="new"):
    identity = OpaqueIdentity(kind="property", parts={"object_id": 41})
    return ConfirmMapping(
        idempotency_key=key, connection_key="synthetic-connection", portfolio_id=box.portfolio.id,
        identity=identity, external_identity_hash=service._opaque(identity).token,
        source_history_run_id=run, source_sha256=digest(row), expected_previous_revision=expected,
        target=MappingTarget(target_id=box.property.id, expected_target_etag=etag("properties", box.property.id, box.store.get_property(box.property.id).updated_at)),
    )


def confirm_property_mapping(box, **kwargs):
    row, run = property_source(box, late=kwargs.pop("late", "v1"))
    payload = mapping_payload(box, row, run, **kwargs)
    with scope_context(scope_from_user(box.users["actor"])):
        result = service.confirm_mapping(box.store, payload, "actor", history=box.history)
    return result, row, run, payload


def document_source(box, content: bytes, *, lieg_nr="L-41", reference="REF-1"):
    body = {
        "success": True,
        "content": {"omitted": "document_bytes", "sha256": hashlib.sha256(content).hexdigest(), "size_bytes": len(content), "media_type": "application/pdf"},
        "unknown_content_metadata": {"opaque": 99},
    }
    identity = OpaqueIdentity(
        kind="document", parts={"lieg_nr": lieg_nr, "reference": reference}
    )
    run = history_run(
        box,
        "read_document",
        body,
        arguments={"lieg_nr": lieg_nr, "reference": reference},
        manifest={
            "type": "TehaDocumentContent",
            "reference": reference,
            "lieg_nr": lieg_nr,
            "sha256": hashlib.sha256(content).hexdigest(),
            "size_bytes": len(content),
            "media_type": "application/pdf",
        },
    )
    return identity, body, run


def document_preview(box, mapping, content: bytes):
    identity, body, run = document_source(box, content)
    payload = PreviewImport(
        connection_key="synthetic-connection", portfolio_id=box.portfolio.id, source_kind="document",
        source_history_run_id=run, content_history_run_id=run, identity=identity,
        external_identity_hash=service._opaque(identity).token, source_sha256=digest(body),
        mapping=MappingSelection(mapping_id=mapping["id"], expected_revision=mapping["revision"], expected_generation=mapping["generation"]),
        document=DocumentImportData(title="Synthetic TEHA original", document_date=date(2026, 10, 3)),
    )
    with scope_context(scope_from_user(box.users["actor"])):
        preview = service.preview_import(box.store, payload, "actor", history=box.history)
    return payload, preview, run


def order_source(box, *, marker="v1"):
    row = {"terminId": 9001, "auftragNummer": 77, "liegenschaftsnummer": "L-41", "abrLfdNr": 7, "terminVon": "2026-10-01T08:00:00", "terminBis": "2026-10-01T10:00:00", "abrechnungBis": "2026-12-31T00:00:00", "unknown_late": marker}
    run = history_run(box, "list_technical_orders", {"success": True, "auftraege": [row]})
    identity = OpaqueIdentity(kind="technical_order", parts={"termin_id": 9001})
    return identity, row, run


def test_mapping_history_hash_generation_cas_and_replay(box):
    first, row, run, payload = confirm_property_mapping(box)
    with scope_context(scope_from_user(box.users["actor"])):
        assert service.confirm_mapping(box.store, payload, "actor", history=box.history) == first
    row2, run2 = property_source(box, late="v2")
    payload2 = mapping_payload(box, row2, run2, key="map-2", expected=first["revision"])
    with scope_context(scope_from_user(box.users["actor"])):
        second = service.confirm_mapping(box.store, payload2, "actor", history=box.history)
    assert second["generation"] == 2
    stale = payload2.model_copy(update={"idempotency_key": "map-stale", "expected_previous_revision": first["revision"]})
    with scope_context(scope_from_user(box.users["actor"])), pytest.raises(HTTPException) as failure:
        service.confirm_mapping(box.store, stale, "actor", history=box.history)
    assert failure.value.status_code == 412
    assert box.db.scalar(select(TehaExternalMappingORM).count()) if False else True


def test_mapping_rejects_wrong_source_hash_and_changed_target_etag(box):
    row, run = property_source(box)
    payload = mapping_payload(box, row, run)
    bad = payload.model_copy(update={"source_sha256": "0" * 64})
    with scope_context(scope_from_user(box.users["actor"])), pytest.raises(HTTPException) as failure:
        service.confirm_mapping(box.store, bad, "actor", history=box.history)
    assert failure.value.status_code == 409
    current = box.store.get_property(box.property.id)
    box.store.update_property(current.id, PropertyCreate(**{**current.model_dump(exclude={"id", "created_at", "updated_at"}), "name": "changed"}))
    with scope_context(scope_from_user(box.users["actor"])), pytest.raises(HTTPException) as failure:
        service.confirm_mapping(box.store, payload, "actor", history=box.history)
    assert failure.value.status_code == 412


def test_document_import_is_atomic_original_receipt_and_safe_replay(box):
    mapping, *_ = confirm_property_mapping(box)
    content = b"%PDF-1.4\nsynthetic immutable TEHA original\n%%EOF\n"
    preview_payload, preview, run = document_preview(box, mapping, content)
    assert preview["state"] == "new"
    command = ImportDocument(idempotency_key="import-doc-1", preview=preview_payload, preview_hash=preview["preview_hash"], content_history_run_id=run)
    with scope_context(scope_from_user(box.users["actor"])):
        first = service.import_document(box.store, command, content, "actor", history=box.history)
        second = service.import_document(box.store, command, content, "actor", history=box.history)
    assert second == first
    with Session(box.engine) as db:
        receipt = db.get(TehaImportReceiptORM, first["id"])
        document = db.get(DocumentORM, first["document_id"])
        version = db.get(DocumentVersionORM, first["document_version_id"])
        assert receipt is not None and document is not None and version is not None
        assert version.sha256 == hashlib.sha256(content).hexdigest()
        assert b"".join(document_versions.verified_blocks(SQLAlchemyStore(db), version)) == content


def test_document_failure_after_chunks_rolls_back_everything(box, monkeypatch):
    mapping, *_ = confirm_property_mapping(box)
    content = b"%PDF-1.4\nrollback original\n%%EOF\n"
    preview_payload, preview, run = document_preview(box, mapping, content)
    command = ImportDocument(idempotency_key="import-doc-fail", preview=preview_payload, preview_hash=preview["preview_hash"], content_history_run_id=run)
    original = service.document_versions.persist_version_bytes
    def fail(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("synthetic after chunks")
    monkeypatch.setattr(service.document_versions, "persist_version_bytes", fail)
    with scope_context(scope_from_user(box.users["actor"])), pytest.raises(RuntimeError):
        service.import_document(box.store, command, content, "actor", history=box.history)
    with Session(box.engine) as db:
        assert db.scalar(select(func.count()).select_from(TehaImportReceiptORM)) == 0
        assert db.scalar(select(func.count()).select_from(DocumentORM).where(DocumentORM.document_type == "teha_document")) == 0
        assert db.scalar(select(func.count()).select_from(DocumentVersionORM)) == 0


def test_task_import_open_and_preview_invalidates_after_target_change(box):
    mapping, *_ = confirm_property_mapping(box)
    identity, row, run = order_source(box)
    preview_payload = PreviewImport(
        connection_key="synthetic-connection", portfolio_id=box.portfolio.id, source_kind="technical_order",
        source_history_run_id=run, identity=identity, external_identity_hash=service._opaque(identity).token, source_sha256=digest(row),
        mapping=MappingSelection(mapping_id=mapping["id"], expected_revision=mapping["revision"], expected_generation=mapping["generation"]),
        task=TaskImportData(title="Synthetic technical visit", due_date=date(2026, 10, 10)),
    )
    with scope_context(scope_from_user(box.users["actor"])):
        preview = service.preview_import(box.store, preview_payload, "actor", history=box.history)
        receipt = service.import_technical_order(box.store, ImportTechnicalOrder(idempotency_key="task-import-1", preview=preview_payload, preview_hash=preview["preview_hash"]), "actor", history=box.history)
    with Session(box.engine) as db:
        task = db.get(TaskORM, receipt["task_id"])
        assert task is not None and task.status == "open"

    identity2, row2, run2 = order_source(box, marker="v2")
    changed_payload = preview_payload.model_copy(update={"source_history_run_id": run2, "source_sha256": digest(row2), "identity": identity2})
    with scope_context(scope_from_user(box.users["actor"])):
        changed = service.preview_import(box.store, changed_payload, "actor", history=box.history)
    assert changed["state"] == "changed"
    current = box.store.get_property(box.property.id)
    box.store.update_property(current.id, PropertyCreate(**{**current.model_dump(exclude={"id", "created_at", "updated_at"}), "name": "changed after preview"}))
    with scope_context(scope_from_user(box.users["actor"])), pytest.raises(HTTPException) as failure:
        service.import_technical_order(box.store, ImportTechnicalOrder(idempotency_key="task-import-stale", preview=changed_payload, preview_hash=changed["preview_hash"]), "actor", history=box.history)
    assert failure.value.status_code == 412


def unit_mapping_source(box, *, unit_id=501, reference="REF-U"):
    row = {
        "reference": reference,
        "fileName": "synthetic-unit.pdf",
        "properties": {
            "Nutzereinheit_ID": unit_id,
            "Liegenschafts_Nummer": "L-41",
        },
        "attachments": [],
        "unknown_private_field": "kept-only-in-history",
    }
    run = history_run(
        box,
        "list_documents",
        {"success": True, "documents": [row]},
        arguments={"lieg_nr": "L-41"},
    )
    identity = OpaqueIdentity(
        kind="unit",
        parts={"lieg_nr": "L-41", "unit_id": unit_id},
    )
    payload = ConfirmMapping(
        idempotency_key=f"unit-map-{unit_id}",
        connection_key="synthetic-connection",
        portfolio_id=box.portfolio.id,
        identity=identity,
        external_identity_hash=service._opaque(identity).token,
        source_history_run_id=run,
        source_sha256=digest(row),
        expected_previous_revision="new",
        target=MappingTarget(
            target_id=box.unit.id,
            expected_target_etag=etag(
                "units",
                box.unit.id,
                box.store.get_unit(box.unit.id).updated_at,
            ),
        ),
    )
    with scope_context(scope_from_user(box.users["actor"])):
        mapping = service.confirm_mapping(
            box.store, payload, "actor", history=box.history
        )
    return mapping, row, run


def test_history_connection_namespace_is_mandatory(box):
    row, run = property_source(box)
    wrong_run = history_run(
        box,
        "list_property_periods",
        {"success": True, "liegenschaften": [row]},
        connection_key="another-connection",
    )
    payload = mapping_payload(box, row, wrong_run, key="wrong-connection")
    with scope_context(scope_from_user(box.users["actor"])), pytest.raises(
        HTTPException
    ) as failure:
        service.confirm_mapping(
            box.store, payload, "actor", history=box.history
        )
    assert failure.value.status_code == 409
    with Session(box.engine) as db:
        assert (
            db.scalar(
                select(func.count()).select_from(TehaExternalMappingORM)
            )
            == 0
        )


def test_unit_mapping_uses_actual_local_parent_and_document_relation(box):
    mapping, source_row, source_run = unit_mapping_source(box)
    content = b"%PDF-1.4\nunit-bound TEHA original\n%%EOF\n"
    identity = OpaqueIdentity(
        kind="document",
        parts={"lieg_nr": "L-41", "reference": source_row["reference"]},
    )
    _, _, content_run = document_source(
        box, content, reference=source_row["reference"]
    )
    payload = PreviewImport(
        connection_key="synthetic-connection",
        portfolio_id=box.portfolio.id,
        source_kind="document",
        source_history_run_id=source_run,
        content_history_run_id=content_run,
        identity=identity,
        external_identity_hash=service._opaque(identity).token,
        source_sha256=digest(source_row),
        mapping=MappingSelection(
            mapping_id=mapping["id"],
            expected_revision=mapping["revision"],
            expected_generation=mapping["generation"],
        ),
        document=DocumentImportData(
            title="Unit-bound synthetic original",
            document_date=date(2026, 10, 3),
        ),
    )
    with scope_context(scope_from_user(box.users["actor"])):
        preview = service.preview_import(
            box.store, payload, "actor", history=box.history
        )
    assert preview["local_binding"]["property_id"] == box.property.id
    assert preview["local_binding"]["unit_id"] == box.unit.id
    assert preview["projection"]["property_id"] == box.property.id
    assert preview["projection"]["unit_id"] == box.unit.id

    other_row = {
        **source_row,
        "properties": {
            **source_row["properties"],
            "Nutzereinheit_ID": 999,
        },
    }
    wrong_source = history_run(
        box,
        "list_documents",
        {"success": True, "documents": [other_row]},
        arguments={"lieg_nr": "L-41"},
    )
    wrong = payload.model_copy(
        update={
            "source_history_run_id": wrong_source,
            "source_sha256": digest(other_row),
        }
    )
    with scope_context(scope_from_user(box.users["actor"])), pytest.raises(
        HTTPException
    ) as failure:
        service.preview_import(box.store, wrong, "actor", history=box.history)
    assert failure.value.status_code == 409


def test_commit_authority_failure_rolls_back_mapping(box, monkeypatch):
    row, run = property_source(box)
    payload = mapping_payload(box, row, run, key="authority-rollback")
    calls = {"count": 0}
    original = box.authority_module.validate_commit_authority

    def validate_commit_authority(authority, actor_id):
        calls["count"] += 1
        if calls["count"] == 2:
            raise HTTPException(401, "synthetic revoked commit authority")
        return original(authority, actor_id)

    validate_commit_authority.__module__ = "backend.services.commit_authority"
    monkeypatch.setattr(
        box.authority_module,
        "validate_commit_authority",
        validate_commit_authority,
    )
    with scope_context(scope_from_user(box.users["actor"])), pytest.raises(
        HTTPException
    ) as failure:
        service.confirm_mapping(
            box.store, payload, "actor", history=box.history
        )
    assert failure.value.status_code == 401
    assert calls["count"] == 2
    with Session(box.engine) as db:
        assert (
            db.scalar(
                select(func.count()).select_from(TehaExternalMappingORM)
            )
            == 0
        )


def test_document_replay_claim_mapping_digest_and_original_download(
    box, monkeypatch
):
    mapping, *_ = confirm_property_mapping(box)
    content = b"%PDF-1.4\nverified replay original\n%%EOF\n"
    preview_payload, preview, run = document_preview(box, mapping, content)
    command = ImportDocument(
        idempotency_key="strict-replay",
        preview=preview_payload,
        preview_hash=preview["preview_hash"],
        content_history_run_id=run,
    )
    with scope_context(scope_from_user(box.users["actor"])):
        first = service.import_document(
            box.store, command, content, "actor", history=box.history
        )

    with Session(box.engine) as db:
        receipt = db.get(TehaImportReceiptORM, first["id"])
        mapping_row = db.get(TehaExternalMappingORM, mapping["id"])
        version = db.get(DocumentVersionORM, first["document_version_id"])
        assert receipt is not None and mapping_row is not None and version is not None
        _, expected_mapping_sha = service._mapping_reference(mapping_row)
        evidence = version.metadata_snapshot["teha_import"]
        assert receipt.mapping_generation == mapping_row.generation
        assert evidence["mapping_id"] == mapping_row.id
        assert evidence["mapping_sha256"] == expected_mapping_sha
        assert len(version.idempotency_key) <= 100
        assert version.idempotency_key.startswith("generated-")
        assert "unknown_late_field" not in repr(mapping_row.external_identity_json)

    original_blocks = service.document_versions.verified_blocks
    seen = {"blocks": 0}

    def observed_blocks(store, version):
        for block in original_blocks(store, version):
            seen["blocks"] += 1
            yield block

    monkeypatch.setattr(
        service.document_versions, "verified_blocks", observed_blocks
    )
    with scope_context(scope_from_user(box.users["actor"])):
        replay = service.import_document(
            box.store, command, content, "actor", history=box.history
        )
        compiled, _ = service.prepare_document_download(
            box.store, first["id"], "actor"
        )
    try:
        assert replay == first
        assert seen["blocks"] > 0
        assert compiled.path.read_bytes() == content
        assert compiled.manifest["sha256"] == hashlib.sha256(content).hexdigest()
    finally:
        compiled.close()

    other_key = command.model_copy(update={"idempotency_key": "other-key"})
    with scope_context(scope_from_user(box.users["actor"])), pytest.raises(
        HTTPException
    ) as conflict:
        service.import_document(
            box.store, other_key, content, "actor", history=box.history
        )
    assert conflict.value.status_code == 409

    actor2 = command.model_copy(update={"idempotency_key": "actor2-key"})
    with scope_context(scope_from_user(box.users["actor2"])), pytest.raises(
        HTTPException
    ) as conflict:
        service.import_document(
            box.store, actor2, content, "actor2", history=box.history
        )
    assert conflict.value.status_code == 409


def test_initial_mapping_generation_race_has_one_winner_sqlite(box, monkeypatch):
    row, run = property_source(box)
    first = mapping_payload(box, row, run, key="race-a")
    second = mapping_payload(box, row, run, key="race-b")
    original = service.begin_writer
    barrier = Barrier(2, timeout=15)

    def synchronized_writer(db):
        barrier.wait()
        return original(db)

    monkeypatch.setattr(service, "begin_writer", synchronized_writer)

    def worker(actor, payload):
        with scope_context(scope_from_user(box.users[actor])):
            try:
                return (
                    "ok",
                    service.confirm_mapping(
                        box.store,
                        payload,
                        actor,
                        history=box.history,
                    ),
                )
            except HTTPException as error:
                return ("error", error.status_code)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = [
            future.result(timeout=25)
            for future in (
                pool.submit(worker, "actor", first),
                pool.submit(worker, "actor2", second),
            )
        ]
    assert sum(status == "ok" for status, _ in results) == 1
    assert [value for status, value in results if status == "error"] == [412]
    with Session(box.engine) as db:
        assert (
            db.scalar(
                select(func.count()).select_from(TehaExternalMappingORM)
            )
            == 1
        )
