"""Immutable document originals: archive, verified reads, guards, snapshots and restore checks."""

import hashlib
import os
import sqlite3
import threading
import time
from typing import Any

import pytest
from archive_helpers import drop_guards, lease_with_document, pdf_bytes, purge_originals
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select

from backend import auth
from backend.app import app
from backend.auth import clear_users, create_access_token, register_user
from backend.db.document_version_models import CHUNK_BYTES, DocumentVersionORM
from backend.db.orm_models import Base
from backend.dependencies import store
from backend.repositories import SQLAlchemyStore
from backend.services import document_versions as archive
from backend.services.data_snapshot import SnapshotError, clear_business_data, export_snapshot, import_snapshot
from backend.services.document_original_snapshot import RESTORE_REFUSED
from backend.services.document_version_validation import ArchiveIntegrityError, verify_document_versions
from backend.services.sqlite_backup import verify_archived_originals
from backend.storage import InMemoryStore

SQL = os.environ.get("TEST_STORE_BACKEND", "memory") == "sql"
shared: Any = store       # SQLAlchemyStore in the sql run
WRITE = ("/documents",)


@pytest.fixture
def owner():
    purge_originals(store)
    clear_business_data(store)
    clear_users()
    user = register_user("owner", "owner@example.com", "Owner", "Secret123", "eigentuemer")
    yield user
    purge_originals(store)
    clear_users()
    clear_business_data(store)


@pytest.fixture
def client(owner):
    return TestClient(app, headers={"Authorization": f"Bearer {create_access_token(owner.id)}"})


def _archive(lease, actor_id, content, *, target=store, request_hash="a" * 64):
    document = lease["document"]
    with archive.work(target, actor_id, write_areas=WRITE) as unit:
        _, binding = archive.bind_document(unit, document.id, lock=True)
        return archive.publish_generated_original(unit, document, binding, content, request_hash,
                                                  version_id=f"v-{document.id}")


def _read(document_id, actor_id, target=store):
    with archive.work(target, actor_id) as unit:
        row = archive.head(unit, document_id)
        assert row is not None
        _, binding = archive.bind_document(unit, document_id)
        archive.authorized_version(unit, document_id, row.id, binding)
        return archive.original_bytes(unit, row)


def test_an_original_is_stored_in_blocks_and_read_back_verified(owner):
    lease = lease_with_document(store)
    content = pdf_bytes(2 * CHUNK_BYTES + 1234)

    row = _archive(lease, owner.id, content)

    assert row.sha256 == hashlib.sha256(content).hexdigest() and row.size_bytes == len(content)
    assert (row.portfolio_id, row.contract_id, row.tenant_id) == (
        lease["portfolio"].id, lease["contract"].id, lease["tenant"].id)
    assert _read(lease["document"].id, owner.id) == content
    page = archive.history(store, lease["document"].id, owner.id)
    assert [item["number"] for item in page["items"]] == [1] and page["next_before"] is None
    assert page["items"][0]["metadata_snapshot"]["file_url"] == lease["document"].file_url


def test_a_second_original_for_the_same_document_is_refused(owner):
    lease = lease_with_document(store)
    _archive(lease, owner.id, pdf_bytes(500))

    with pytest.raises(HTTPException) as error:
        _archive(lease, owner.id, pdf_bytes(600))

    assert error.value.status_code == 409


def test_blocks_that_do_not_match_the_manifest_leave_nothing_behind(owner):
    """Rollback after partly written blocks: neither the manifest nor any block stays."""
    lease = lease_with_document(store)
    document = lease["document"]
    content = pdf_bytes(3 * CHUNK_BYTES)

    with pytest.raises(HTTPException) as error:
        with archive.work(store, owner.id, write_areas=WRITE) as unit:
            _, binding = archive.bind_document(unit, document.id, lock=True)
            row = DocumentVersionORM(
                id="broken", document_id=document.id, **binding, number=1, actor_id=owner.id,
                idempotency_key="k", request_sha256="b" * 64, operation="archive_original", comment="",
                filename="x.pdf", media_type="application/pdf", sha256=hashlib.sha256(b"other").hexdigest(),
                size_bytes=len(content), metadata_snapshot=document.model_dump(mode="json"), created_at=archive.now())
            archive.persist_version_bytes(unit, row, [content[i:i + CHUNK_BYTES]
                                                      for i in range(0, len(content), CHUNK_BYTES)])

    assert error.value.status_code == 409
    assert archive.count_originals(store, "document", document.id) == 0
    if SQL:
        assert shared.db.execute(select(DocumentVersionORM)).first() is None
    else:
        assert not archive.memory_archive(store).chunks


@pytest.mark.parametrize("damage", ["changed", "missing", "swapped"])
def test_damaged_blocks_are_never_returned(owner, damage):
    lease = lease_with_document(store)
    content = pdf_bytes(2 * CHUNK_BYTES + 10)
    row = _archive(lease, owner.id, content)

    if SQL:
        with shared.db.get_bind().begin() as connection:
            drop_guards(connection)
            statement = {
                "changed": "UPDATE document_version_chunks SET data = :data WHERE version_id = :id AND position = 1",
                "missing": "DELETE FROM document_version_chunks WHERE version_id = :id AND position = 1",
                "swapped": "UPDATE document_version_chunks SET position = 9 - position WHERE version_id = :id "
                           "AND position IN (0, 1)",
            }[damage]
            from sqlalchemy import text
            connection.execute(text(statement), {"id": row.id, "data": b"x" * CHUNK_BYTES})
            from backend.db.document_version_models import install_guards
            install_guards(connection)
    else:
        chunks = archive.memory_archive(store).chunks
        if damage == "changed":
            chunks[(row.id, 1)].data = b"x" * CHUNK_BYTES
        elif damage == "missing":
            del chunks[(row.id, 1)]
        else:
            chunks[(row.id, 0)].position, chunks[(row.id, 1)].position = 1, 0

    with pytest.raises(HTTPException) as error:
        _read(lease["document"].id, owner.id)
    assert error.value.status_code == 503


@pytest.mark.skipif(not SQL, reason="database triggers")
@pytest.mark.parametrize("statement", [
    "UPDATE document_versions SET comment = 'geändert'",
    "DELETE FROM document_versions",
    "UPDATE document_version_chunks SET data = X'00'",
    "DELETE FROM document_version_chunks",
])
def test_the_database_refuses_to_change_an_original(owner, statement):
    _archive(lease_with_document(store), owner.id, pdf_bytes(100))

    with pytest.raises(Exception, match="immutable"):
        with shared.db.get_bind().begin() as connection:
            connection.exec_driver_sql(statement)


def test_a_deactivated_account_or_a_missing_right_writes_nothing(owner):
    lease = lease_with_document(store)
    clerk = register_user("tech", "tech@example.com", "Technik", "Secret123", "techniker")

    with pytest.raises(HTTPException) as error:
        with archive.work(store, clerk.id, write_areas=("/contracts/x/housing-confirmations", *WRITE)):
            pass
    assert error.value.status_code == 403

    auth.update_user(owner.id, {"is_active": False})
    with pytest.raises(HTTPException) as error:
        _archive(lease, owner.id, pdf_bytes(100))
    assert error.value.status_code == 401
    assert archive.count_originals(store, "document", lease["document"].id) == 0


def test_an_account_change_waits_until_the_original_is_written(owner):
    """The rights checked at the start still hold at the commit (account fence)."""
    lease = lease_with_document(store)
    changed = threading.Event()

    def take_role_away():
        auth.update_user(owner.id, {"role": "readonly"})
        changed.set()

    document = lease["document"]
    with archive.work(store, owner.id, write_areas=WRITE) as unit:
        worker = threading.Thread(target=take_role_away)
        worker.start()
        time.sleep(0.3)
        assert not changed.is_set()          # waits for the unit
        _, binding = archive.bind_document(unit, document.id, lock=True)
        archive.publish_generated_original(unit, document, binding, pdf_bytes(300), "c" * 64, version_id="v1")
    worker.join(10)

    assert changed.is_set()
    assert archive.count_originals(store, "document", document.id) == 1
    with pytest.raises(HTTPException) as error:
        with archive.work(store, owner.id, write_areas=WRITE):
            pass
    assert error.value.status_code == 403


def test_records_with_originals_keep_their_binding_and_cannot_be_deleted(client, owner):
    lease = lease_with_document(store)
    _archive(lease, owner.id, pdf_bytes(400))
    other = lease_with_document(store, number="V-2", file_url="/uploads/documents/b.pdf")
    document_id, contract = lease["document"].id, lease["contract"]

    assert client.patch(f"/api/v1/documents/{document_id}", json={"title": "Neuer Titel"}).status_code == 200
    assert client.patch(f"/api/v1/documents/{document_id}",
                        json={"contract_id": other["contract"].id}).status_code == 409
    assert client.patch(f"/api/v1/documents/{document_id}", json={"file_url": "/uploads/x.pdf"}).status_code == 409
    assert client.delete(f"/api/v1/documents/{document_id}").status_code == 409
    bulk = client.post("/api/v1/admin/bulk-delete/documents", json={"ids": [document_id]}).json()
    assert bulk["deleted"] == 0 and bulk["errors"]
    moved = {**contract.model_dump(mode="json", exclude={"id", "created_at", "updated_at"}),
             "tenant_id": other["tenant"].id}
    assert client.put(f"/api/v1/contracts/{contract.id}", json=moved).status_code == 409
    assert client.patch(f"/api/v1/contracts/{contract.id}", json={"notes": "ok"}).status_code == 200
    assert client.patch(f"/api/v1/units/{lease['unit'].id}",
                        json={"property_id": other["property"].id}).status_code == 409
    assert client.patch(f"/api/v1/properties/{lease['property'].id}",
                        json={"portfolio_id": other["portfolio"].id}).status_code == 409
    assert client.delete(f"/api/v1/contracts/{contract.id}").status_code == 409
    assert _read(document_id, owner.id) == pdf_bytes(400)


def test_a_snapshot_carries_originals_with_their_bytes(owner):
    lease = lease_with_document(store)
    content = pdf_bytes(CHUNK_BYTES + 77)
    _archive(lease, owner.id, content)

    snapshot = export_snapshot(store)
    assert snapshot["format_version"] == 3 and len(snapshot["document_originals"]) == 1

    copy = InMemoryStore()
    result = import_snapshot(copy, snapshot, replace=False)
    assert result["imported"]["document_originals"] == 1
    assert _read(lease["document"].id, owner.id, target=copy) == content
    # importing the same file again changes nothing
    again = import_snapshot(copy, snapshot, replace=False)
    assert again["skipped_existing"]["document_originals"] == 1


@pytest.mark.parametrize("tamper", ["block", "binding", "document"])
def test_an_import_proves_every_original_first(owner, tamper):
    lease = lease_with_document(store)
    _archive(lease, owner.id, pdf_bytes(1000))
    snapshot = export_snapshot(store)
    record = snapshot["document_originals"][0]
    if tamper == "block":
        record["blocks"][0] = record["blocks"][0][:-8] + "AAAAAAA="
    elif tamper == "binding":
        record["tenant_id"] = snapshot["tenants"][0]["id"] + "-x"
    else:
        snapshot["documents"][0]["file_url"] = "/uploads/documents/andere.pdf"

    copy = InMemoryStore()
    with pytest.raises(SnapshotError):
        import_snapshot(copy, snapshot, replace=False)
    assert not copy.documents and not archive.memory_archive(copy).versions


def test_a_restore_never_deletes_archived_originals(owner):
    lease = lease_with_document(store)
    _archive(lease, owner.id, pdf_bytes(300))

    with pytest.raises(SnapshotError) as error:
        import_snapshot(store, {"format": "immomanager-snapshot", "format_version": 3}, replace=True)

    assert RESTORE_REFUSED in str(error.value)
    assert _read(lease["document"].id, owner.id) == pdf_bytes(300)


def _sqlite_with_archive(path, owner_id):
    engine = create_engine(f"sqlite:///{path}")
    Base.metadata.create_all(engine)
    from sqlalchemy.orm import Session
    file_store = SQLAlchemyStore(Session(engine))
    lease = lease_with_document(file_store)
    _archive(lease, owner_id, pdf_bytes(CHUNK_BYTES + 5), target=file_store)
    file_store.db.close()
    engine.dispose()


@pytest.mark.skipif(SQL, reason="builds its own database files (accounts in memory)")
def test_a_database_backup_is_proven_before_it_is_restored(owner, tmp_path):
    good = tmp_path / "good.db"
    _sqlite_with_archive(good, owner.id)
    assert verify_archived_originals(good) == 1

    before_archive = tmp_path / "old.db"
    sqlite3.connect(before_archive).execute("CREATE TABLE portfolios (id TEXT)").connection.close()
    assert verify_archived_originals(before_archive) == 0

    with sqlite3.connect(good) as connection:
        connection.execute("DROP TRIGGER immo_document_version_chunks_update")
        connection.execute("UPDATE document_version_chunks SET data = zeroblob(10) WHERE position = 1")
    with pytest.raises(ArchiveIntegrityError):
        verify_archived_originals(good)


@pytest.mark.skipif(SQL, reason="builds its own database files (accounts in memory)")
def test_the_verifier_finds_a_moved_document(owner, tmp_path):
    path = tmp_path / "moved.db"
    _sqlite_with_archive(path, owner.id)
    with sqlite3.connect(path) as connection:
        assert verify_document_versions(connection) == 1
        connection.execute("UPDATE documents SET file_url = '/uploads/other.pdf'")
        with pytest.raises(ArchiveIntegrityError):
            verify_document_versions(connection)
