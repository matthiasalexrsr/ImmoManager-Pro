"""Owned synthetic originals, real memory/SQLite and independent SQL writers."""

import hashlib
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from threading import Barrier
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, event, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend import auth
from backend.db.document_version_models import (
    DocumentVersionChunkORM,
    DocumentVersionORM,
    ensure_document_version_schema,
)
from backend.db.orm_models import Base
from backend.models import (
    ContractCreate,
    ContractPatch,
    DocumentCreate,
    DocumentPatch,
    PortfolioCreate,
    PropertyCreate,
    PropertyPatch,
    TenantCreate,
    UnitCreate,
)
from backend.repositories.sql_store import SQLAlchemyStore
from backend.services import document_versions as service
from backend.services.data_transfer import TransferError, export_store_data, import_store_data
from backend.services.document_version_types import OriginalCommand, RestoreCommand, VersionCommand
from backend.services.file_storage import LocalStorage
from backend.storage import InMemoryStore, ValidationError


@pytest.fixture(params=["memory", "sqlite"])
def active(request, tmp_path, monkeypatch):
    engine, db = None, None
    if request.param == "sqlite":
        engine = create_engine("sqlite:///" + (tmp_path / "versions.db").as_posix(),
            connect_args={"check_same_thread": False, "timeout": 20})
        @event.listens_for(engine, "connect")
        def configure(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("PRAGMA journal_mode=WAL")
        Base.metadata.create_all(engine)
        with engine.begin() as connection:
            ensure_document_version_schema(connection)
        db = Session(engine)
        store = SQLAlchemyStore(db)
    else:
        store = InMemoryStore()
    portfolio = store.create_portfolio(PortfolioCreate(name="Synthetic own portfolio"))
    foreign = store.create_portfolio(PortfolioCreate(name="Synthetic foreign portfolio"))
    prop = store.create_property(PropertyCreate(portfolio_id=portfolio.id, name="Own", property_type="residential"))
    other = store.create_property(PropertyCreate(portfolio_id=foreign.id, name="Foreign", property_type="residential"))
    unit = store.create_unit(UnitCreate(property_id=prop.id, label="A", unit_type="apartment"))
    storage = LocalStorage(str(tmp_path / "uploads"))
    content = b"Synthetic reviewed original\n" * 5000
    storage.save("documents/original.txt", BytesIO(content))
    document = store.create_document(DocumentCreate(property_id=prop.id, unit_id=unit.id,
        title="Synthetic original", file_url="/uploads/documents/original.txt", tags="original"))
    users = {"actor": dict(id="actor", role="verwalter", is_active=True, portfolio_access="selected", portfolio_ids=[portfolio.id]),
        "readonly": dict(id="readonly", role="readonly", is_active=True, portfolio_access="selected", portfolio_ids=[portfolio.id]),
        "foreign": dict(id="foreign", role="verwalter", is_active=True, portfolio_access="selected", portfolio_ids=[foreign.id])}
    monkeypatch.setattr(auth, "get_user_by_id", users.get)
    monkeypatch.setattr("backend.services.contract_attachment.get_file_storage", lambda: storage)
    yield SimpleNamespace(store=store, engine=engine, db=db, document=document, prop=prop, unit=unit,
        p=portfolio, foreign=foreign, other=other, users=users, storage=storage, content=content, tmp=tmp_path)
    if db is not None:
        db.close()
        engine.dispose()


def command(box, key="version", **changes):
    history = service.history(box.store, box.document.id, "actor")
    return VersionCommand(idempotency_key=key, expected_document_etag=history["document_etag"],
        expected_head_id=history["head"]["id"] if history["head"] else None, comment="Explicitly reviewed change", confirmed=True, **changes)


def archive(box, key="original"):
    preview = service.source_preview(box.store, box.document.id, "actor")
    payload = OriginalCommand(**command(box, key).model_dump(), expected_sha256=preview["sha256"])
    return service.publish(box.store, box.document.id, payload, "actor"), payload


def downloaded(box, row):
    compiled, _ = service.prepare_download(box.store, box.document.id, row["id"], "actor", parent=box.tmp)
    try:
        return compiled.path.read_bytes()
    finally:
        owned = compiled.path.parent
        compiled.close()
        assert not owned.exists()


def test_explicit_original_new_version_restore_and_source_gone(active):
    box = active
    assert service.history(box.store, box.document.id, "actor")["head"] is None
    original, payload = archive(box)
    assert original["number"] == 1 and original["predecessor_id"] is None
    assert service.publish(box.store, box.document.id, payload, "actor") == original
    request = command(box)
    current = service.publish(box.store, box.document.id, request, "actor", source=BytesIO(b"New reviewed version"), upload_name="new.txt")
    assert service.publish(box.store, box.document.id, request, "actor", source=BytesIO(b"New reviewed version"), upload_name="new.txt") == current
    assert current["predecessor_id"] == original["id"] and current["number"] == 2
    box.storage.delete("documents/original.txt")
    assert downloaded(box, original) == box.content
    assert downloaded(box, current) == b"New reviewed version"
    restore = RestoreCommand(**command(box, "restore").model_dump(), source_version_id=original["id"])
    restored = service.publish(box.store, box.document.id, restore, "actor", restore=True)
    assert restored["number"] == 3 and restored["predecessor_id"] == current["id"]
    assert restored["restored_from_id"] == original["id"] and downloaded(box, restored) == box.content
    assert box.store.get_document(box.document.id).file_url == "/uploads/documents/original.txt"
    page = service.history(box.store, box.document.id, "actor", limit=2)
    assert [r["number"] for r in page["items"]] == [3, 2] and page["next_before"] == 2
    assert [r["number"] for r in service.history(box.store, box.document.id, "actor", before=2)["items"]] == [1]
    if box.engine:
        with Session(box.engine) as fresh:
            assert service.history(SQLAlchemyStore(fresh), box.document.id, "actor")["head"]["id"] == restored["id"]


def test_missing_remote_changed_originals_are_not_invented(active):
    box = active
    preview = service.source_preview(box.store, box.document.id, "actor")
    payload = OriginalCommand(**command(box).model_dump(), expected_sha256=preview["sha256"])
    box.storage.save("documents/original.txt", BytesIO(b"Different file"))
    with pytest.raises(HTTPException) as error:
        service.publish(box.store, box.document.id, payload, "actor")
    assert error.value.status_code == 409
    box.storage.delete("documents/original.txt")
    with pytest.raises(ValidationError, match="nicht verfügbar"):
        service.publish(box.store, box.document.id, payload, "actor")
    box.store._patch_entity("document", box.document.id, DocumentPatch(file_url="https://example.test/foreign.pdf"))
    with pytest.raises(ValidationError, match="externen Verweis"):
        service.source_preview(box.store, box.document.id, "actor")
    assert service.history(box.store, box.document.id, "actor")["head"] is None


def test_metadata_edit_is_free_but_sources_and_parent_cascades_preserved(active):
    box = active
    original, _ = archive(box)
    changed = box.store._patch_entity("document", box.document.id, DocumentPatch(title="Reclassified title", tags="new tags"))
    assert changed.title == "Reclassified title" and original["metadata_snapshot"]["title"] == "Synthetic original"
    for patch in (DocumentPatch(file_url="/uploads/replacement.txt"), DocumentPatch(property_id=box.other.id)):
        with pytest.raises(ValidationError):
            box.store._patch_entity("document", box.document.id, patch)
        if box.db:
            box.db.rollback()
    with pytest.raises(ValidationError):
        box.store._patch_entity("property", box.prop.id, PropertyPatch(portfolio_id=box.foreign.id))
    if box.db:
        box.db.rollback()
    for kind, key in (("document", box.document.id), ("unit", box.unit.id), ("property", box.prop.id), ("portfolio", box.p.id)):
        with pytest.raises(ValidationError):
            getattr(box.store, "delete_" + kind)(key)
        if box.db:
            box.db.rollback()
    assert downloaded(box, original) == box.content


def test_command_replay_different_bytes_stale_head_and_metadata_cas(active):
    box = active
    archive(box)
    request = command(box)
    first = service.publish(box.store, box.document.id, request, "actor", source=BytesIO(b"one"), upload_name="new.txt")
    with pytest.raises(HTTPException) as error:
        service.publish(box.store, box.document.id, request, "actor", source=BytesIO(b"two"), upload_name="new.txt")
    assert error.value.status_code == 409
    with pytest.raises(HTTPException) as error:
        service.publish(box.store, box.document.id, request.model_copy(update={"idempotency_key": "stale"}), "actor", source=BytesIO(b"one"), upload_name="new.txt")
    assert error.value.status_code == 409
    request = command(box, "old-metadata")
    box.store._patch_entity("document", box.document.id, DocumentPatch(description="New metadata"))
    with pytest.raises(HTTPException) as error:
        service.publish(box.store, box.document.id, request, "actor", source=BytesIO(b"three"), upload_name="new.txt")
    assert error.value.status_code == 412
    assert service.history(box.store, box.document.id, "actor")["head"]["id"] == first["id"]


def test_failure_halfway_rolls_back_all_version_rows_and_chunks(active, monkeypatch):
    box = active
    actual = service._add
    def faulty(store, db, row):
        actual(store, db, row)
        if hasattr(row, "position") and row.position == 1:
            raise RuntimeError("Synthetic storage fault")
    monkeypatch.setattr(service, "_add", faulty)
    with pytest.raises(RuntimeError, match="Synthetic"):
        archive(box)
    assert service.history(box.store, box.document.id, "actor")["head"] is None
    if box.engine:
        with Session(box.engine) as fresh:
            assert fresh.scalar(select(DocumentVersionORM.id).limit(1)) is None
    else:
        assert box.store.__dict__["document_version_chunks"] == {}
    assert box.store.get_document(box.document.id).file_url == box.document.file_url


def test_readonly_foreign_and_revocation_before_commit_leave_no_new_version(active, monkeypatch):
    box = active
    payload = OriginalCommand(**command(box).model_dump(), expected_sha256=hashlib.sha256(box.content).hexdigest())
    with pytest.raises(HTTPException) as error:
        service.publish(box.store, box.document.id, payload, "readonly")
    assert error.value.status_code == 403
    from backend.storage import NotFoundError
    with pytest.raises(NotFoundError):
        service.history(box.store, box.document.id, "foreign")
    actual = service._add
    def revoke(store, db, row):
        actual(store, db, row)
        box.users["actor"]["portfolio_ids"] = []
    monkeypatch.setattr(service, "_add", revoke)
    with pytest.raises(HTTPException) as error:
        service.publish(box.store, box.document.id, payload, "actor")
    assert error.value.status_code == 403
    box.users["actor"]["portfolio_ids"] = [box.p.id]
    assert service.history(box.store, box.document.id, "actor")["head"] is None


def test_sql_immutable_guard_rejects_mutation_and_downgrade_preserves_rows(active):
    box = active
    if box.engine is None:
        pytest.skip("Native database trigger case")
    original, _ = archive(box)
    with pytest.raises(IntegrityError), box.engine.begin() as connection:
        connection.execute(update(DocumentVersionORM).where(DocumentVersionORM.id == original["id"]).values(comment="tamper"))
    assert downloaded(box, original) == box.content


@pytest.mark.parametrize("identical", [False, True])
def test_two_independent_writers_serialize_first_original(active, identical):
    box = active
    payload = OriginalCommand(**command(box, "same").model_dump(), expected_sha256=hashlib.sha256(box.content).hexdigest())
    barrier = Barrier(2)
    def create(number):
        request = payload if identical else payload.model_copy(update={"idempotency_key": f"request-{number}"})
        db = Session(box.engine) if box.engine else None
        try:
            barrier.wait(timeout=10)
            return service.publish(SQLAlchemyStore(db) if db else box.store, box.document.id, request, "actor")
        except HTTPException as error:
            return error.status_code
        finally:
            if db:
                db.close()
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(create, range(2)))
    if identical:
        assert results[0] == results[1] and results[0]["number"] == 1
    else:
        assert sum(isinstance(row, dict) for row in results) == 1 and 409 in results
    assert len(service.history(box.store, box.document.id, "actor")["items"]) == 1


def test_business_partial_restore_cannot_erase_journal(active):
    box = active
    business = export_store_data(box.store, "synthetic")
    original, _ = archive(box)
    assert "document_versions" not in business and box.content.decode() not in str(business)
    for replace in (False, True):
        with pytest.raises(TransferError, match="Dokumentversionen"):
            import_store_data(box.store, business, replace_existing=replace)
    assert downloaded(box, original) == box.content


def test_absolute_managed_original_and_offline_rebase_preserve_historical_uri(active, monkeypatch):
    box = active
    absolute = str(box.storage._path("documents/original.txt"))
    box.store._patch_entity("document", box.document.id, DocumentPatch(file_url=absolute))
    original, _ = archive(box)
    assert original["metadata_snapshot"]["file_url"] == absolute
    box.storage.delete("documents/original.txt")
    restored_storage = LocalStorage(str(box.tmp / "restored-uploads"))
    rebased = str(restored_storage._path("documents/original.txt"))
    # Models are edited directly ONLY in this owned offline-restore fixture.
    if box.engine:
        from backend.db.orm_models import DocumentORM
        with box.engine.begin() as connection:
            connection.execute(update(DocumentORM).where(DocumentORM.id == box.document.id).values(file_url=rebased))
        box.db.expire_all()
    else:
        box.store.documents[box.document.id] = box.store.documents[box.document.id].model_copy(update={"file_url": rebased})
    monkeypatch.setattr("backend.services.contract_attachment.get_file_storage", lambda: restored_storage)
    assert downloaded(box, original) == box.content
    assert service.history(box.store, box.document.id, "actor")["head"]["metadata_snapshot"]["file_url"] == absolute
    outside = box.tmp / "outside.txt"
    outside.write_bytes(b"Foreign unmanaged source")
    unsafe = box.store.create_document(DocumentCreate(property_id=box.prop.id, title="Unsafe", file_url=str(outside)))
    with pytest.raises(ValidationError, match="außerhalb"):
        service.source_preview(box.store, unsafe.id, "actor")


def test_corrupt_restored_chunk_is_rejected_before_publishing_a_download(active):
    box = active
    original, _ = archive(box)
    if box.engine:
        # A synthetic restored/corrupt DB without its constraints. The SELECT
        # must return NULL for its oversized BLOB rather than load it wholesale.
        with box.engine.begin() as connection:
            connection.exec_driver_sql("DROP TRIGGER immo_document_version_chunks_update")
            connection.exec_driver_sql("PRAGMA ignore_check_constraints=ON")
            connection.execute(update(DocumentVersionChunkORM).where(DocumentVersionChunkORM.version_id == original["id"],
                DocumentVersionChunkORM.position == 0).values(data=b"x" * 100000))
            connection.exec_driver_sql("PRAGMA ignore_check_constraints=OFF")
        match = "ungültigen Datenblock"
    else:
        box.store.__dict__["document_version_chunks"][(original["id"], 0)].data = memoryview(bytearray(100000))
        match = "unvollständig oder beschädigt"
    paths_before = set(box.tmp.iterdir())
    with pytest.raises(HTTPException, match=match) as error:
        service.prepare_download(box.store, box.document.id, original["id"], "actor", parent=box.tmp)
    assert error.value.status_code == 503
    assert set(box.tmp.iterdir()) == paths_before


def test_two_independent_new_uploads_compete_without_overwriting_original(active):
    box = active
    original, _ = archive(box)
    request = command(box, "parallel-upload")
    barrier = Barrier(2)
    def save(number):
        db = Session(box.engine) if box.engine else None
        try:
            barrier.wait(timeout=10)
            return service.publish(SQLAlchemyStore(db) if db else box.store, box.document.id,
                request.model_copy(update={"idempotency_key": f"upload-{number}"}), "actor",
                source=BytesIO(f"New upload {number}".encode()), upload_name="reviewed.txt")
        except HTTPException as error:
            return error.status_code
        finally:
            if db:
                db.close()
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(save, range(2)))
    assert sum(isinstance(row, dict) for row in results) == 1 and 409 in results
    assert [r["number"] for r in service.history(box.store, box.document.id, "actor")["items"]] == [2, 1]
    assert downloaded(box, original) == box.content


def test_configured_budget_and_explicit_confirmation_preserve_retry(active, monkeypatch):
    box = active
    from backend.config import settings
    monkeypatch.setattr(settings, "max_upload_size_bytes", 0)
    with pytest.raises(ValidationError, match="technische Uploadbudget"):
        service.source_preview(box.store, box.document.id, "actor")
    monkeypatch.setattr(settings, "max_upload_size_bytes", 50 * 1024 * 1024)
    preview = service.source_preview(box.store, box.document.id, "actor")
    request = OriginalCommand(**command(box).model_copy(update={"confirmed": False}).model_dump(), expected_sha256=preview["sha256"])
    with pytest.raises(ValidationError, match="bestätigt"):
        service.publish(box.store, box.document.id, request, "actor")
    assert service.history(box.store, box.document.id, "actor")["head"] is None
    saved = service.publish(box.store, box.document.id, request.model_copy(update={"confirmed": True}), "actor")
    assert downloaded(box, saved) == box.content


def test_contract_bound_original_keeps_tenant_and_derived_unit_through_all_cascades(active):
    box = active
    tenant = box.store.create_tenant(TenantCreate(full_name="Synthetic original subject"))
    other = box.store.create_tenant(TenantCreate(full_name="Synthetic other subject"))
    contract = box.store.create_contract(ContractCreate(tenant_id=tenant.id, property_id=box.prop.id,
        unit_id=box.unit.id, contract_number="Synthetic version source", start_date="2026-10-01", status="draft"))
    # A legitimate legacy document may bind only to a contract; resolved FK
    # identities still protect its property/unit and the original tenant.
    box.store._patch_entity("document", box.document.id, DocumentPatch(property_id=None, unit_id=None, contract_id=contract.id))
    original, _ = archive(box)
    assert original["metadata_snapshot"]["unit_id"] is None
    with pytest.raises(ValidationError):
        box.store._patch_entity("contract", contract.id, ContractPatch(tenant_id=other.id))
    if box.db:
        box.db.rollback()
    for kind, identifier in (("tenant", tenant.id), ("contract", contract.id), ("unit", box.unit.id), ("property", box.prop.id)):
        with pytest.raises(ValidationError):
            getattr(box.store, "delete_" + kind)(identifier)
        if box.db:
            box.db.rollback()
    assert box.store.get_contract(contract.id).tenant_id == tenant.id
    assert downloaded(box, original) == box.content


def test_corrupt_snapshot_identity_is_refused_before_history_or_file_publication(active):
    box = active
    original, _ = archive(box)
    corrupt = {**original["metadata_snapshot"], "id": "foreign-document"}
    if box.engine:
        with box.engine.begin() as connection:
            connection.exec_driver_sql("DROP TRIGGER immo_document_versions_update")
            connection.execute(update(DocumentVersionORM).where(DocumentVersionORM.id == original["id"]).values(metadata_snapshot=corrupt))
    else:
        box.store.__dict__["document_versions"][original["id"]].metadata_snapshot = corrupt
    with pytest.raises(HTTPException, match="beschädigt") as error:
        service.history(box.store, box.document.id, "actor")
    assert error.value.status_code == 503
    before = set(box.tmp.iterdir())
    with pytest.raises(HTTPException, match="beschädigt") as error:
        service.prepare_download(box.store, box.document.id, original["id"], "actor", parent=box.tmp)
    assert error.value.status_code == 503 and set(box.tmp.iterdir()) == before
