"""Current-source decisions, holds beyond expiry, restore gates and household isolation."""
import hashlib
from datetime import date, datetime, timedelta
from importlib import import_module
from uuid import uuid4

import pytest
import test_customer_portability as portable
import test_external_portal as portals
from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi import HTTPException
from sqlalchemy import create_engine, delete, select

from backend import auth
from backend.config import settings
from backend.db.data_transfer_models import PortabilityExportORM
from backend.db.orm_models import Base
from backend.db.privacy_models import PrivacyControlORM, RestoreReviewORM
from backend.dependencies import store
from backend.models import DocumentCreate, DocumentPatch
from backend.privacy_models import CompleteRestoreReview, ControlChange, ImportJournal
from backend.services import assistant_context, data_snapshot, global_search
from backend.services.integrations import connection_storage as db
from backend.services.privacy import backup, controls, journal
from backend.services.privacy.storage import read_unit, rows, work

portal = portals.portal


@pytest.fixture(autouse=True)
def clear_privacy():
    for model in backup.MODELS:
        if hasattr(store, "db"):
            store.db.execute(delete(model))
        else:
            store.__dict__.get("_integration_connections", {}).pop(model.__tablename__, None)
    if hasattr(store, "db"):
        store.db.commit()
    yield
    for model in backup.MODELS:
        if hasattr(store, "db"):
            store.db.execute(delete(model))
        else:
            store.__dict__.get("_integration_connections", {}).pop(model.__tablename__, None)
    if hasattr(store, "db"):
        store.db.commit()


def change(portal, kind, identifier, action, *, current=None):
    owner = portal["owner"]
    current = current or controls.detail(store, owner.id, kind, identifier)
    command = ControlChange(action=action, expected_revision=current["revision"], source_sha256=current["source_sha256"],
        reason="Unterlagen und Aufbewahrungsgrund ausdrücklich geprüft.", idempotency_key=uuid4().hex)
    result = controls.change(store, owner.id, kind, identifier, command)
    assert controls.change(store, owner.id, kind, identifier, command) == result
    return result["resource"]


def test_hold_survives_expiry_and_blocks_legacy_delete_even_with_override(portal):
    doc = store.create_document(DocumentCreate(title="Alte Korrespondenz", file_url="https://example.test/old.txt", document_date=date(1990, 1, 1), retention_class="business_letter"))
    snapshot = {"format": data_snapshot.SNAPSHOT_FORMAT, "format_version": data_snapshot.SNAPSHOT_FORMAT_VERSION, "documents": [doc.model_dump(mode="json")]}
    current = change(portal, "document", doc.id, "hold")
    assert current["held"] and not current["can_erase"]
    response = portal["office"].delete(f"/api/v1/documents/{doc.id}", params={"retention_override": "Frist ist bereits lange abgelaufen."})
    assert response.status_code == 409, response.text
    change(portal, "document", doc.id, "release_hold")
    assert portal["office"].delete(f"/api/v1/documents/{doc.id}").status_code == 204
    with pytest.raises(data_snapshot.SnapshotError, match="nicht erneut importiert"):
        data_snapshot.prepare_import(store, snapshot, replace=False)


def test_stale_source_or_control_revision_cannot_be_decided(portal):
    doc = store.create_document(DocumentCreate(title="Vorher", file_url="https://example.test/file.txt"))
    old = controls.detail(store, portal["owner"].id, "document", doc.id)
    store._patch_entity("document", doc.id, DocumentPatch(title="Nachher"))
    with pytest.raises(HTTPException) as conflict:
        change(portal, "document", doc.id, "hold", current=old)
    assert conflict.value.status_code == 409
    first = change(portal, "document", doc.id, "hold")
    change(portal, "document", doc.id, "restrict")
    with pytest.raises(HTTPException) as conflict:
        change(portal, "document", doc.id, "release_hold", current=first)
    assert conflict.value.status_code == 409


@pytest.mark.parametrize('action', ['restrict', 'delete'])
def test_direct_file_and_ocr_links_stay_blocked_after_metadata_deletion(portal, tmp_path, monkeypatch, action):
    from io import BytesIO

    from backend.services import file_storage
    from backend.services.privacy.storage import ensure_file_available
    storage = file_storage.LocalStorage(tmp_path / 'copies')
    monkeypatch.setattr(file_storage, '_storage', storage)
    # Use the same module-level accessor as the file routes.
    monkeypatch.setattr('backend.routers.files.get_file_storage', lambda: storage)
    key = 'privacy/source.pdf'
    storage.save(key, BytesIO(b'%PDF-1.4\nretained synthetic copy\n%%EOF'))
    storage.save('privacy/source_ocr.txt', BytesIO(b'private OCR text'))
    doc = store.create_document(DocumentCreate(title='Old letter', file_url='/uploads/' + key,
        document_date=date(1990, 1, 1), retention_class='business_letter'))
    office = portal['office']
    assert office.get('/api/v1/files/download', params={'key': key}).status_code == 200
    if action == 'delete':
        assert office.delete('/api/v1/documents/' + doc.id).status_code == 204
    else:
        change(portal, 'document', doc.id, 'restrict')
    for route, params in [('/download', {'key': key}), ('/download', {'key': 'privacy/source_ocr.txt'}),
                          ('/ocr-text', {'file_url': '/uploads/' + key})]:
        response = office.get('/api/v1/files' + route, params=params)
        assert response.status_code == 404, response.text
    assert office.post('/api/v1/files/analyze', params={'file_url': '/uploads/' + key}).status_code == 404
    assert office.post('/api/v1/files/ocr-process', params={'file_url': '/uploads/' + key}).status_code == 404
    with pytest.raises(HTTPException):
        ensure_file_available(store, '/uploads/' + key)
    saved = journal.export(store, portal['owner'].id)
    assert saved['controls'][0]['file_keys_sha256'] == [hashlib.sha256(key.encode()).hexdigest()]
    assert key not in str(saved)  # locator hashes, not the deleted personal filename
    # A freshly restored journal must retain this guard without the document row.
    with work(store, portal['owner'].id) as unit:
        db.remove(unit, PrivacyControlORM, saved['controls'][0]['id'])
    journal.merge(store, portal['owner'].id, ImportJournal(controls=saved['controls'], source_sha256=saved['sha256'],
        reason='Separates Löschjournal nach Wiederherstellung abgeglichen.', idempotency_key=uuid4().hex))
    assert office.get('/api/v1/files/download', params={'key': key}).status_code == 404


def test_pre_tombstone_journal_format_remains_importable(portal):
    from backend.services.data_transfer.common import digest
    doc = store.create_document(DocumentCreate(title='Legacy journal', file_url='/uploads/legacy.pdf'))
    change(portal, 'document', doc.id, 'restrict')
    saved = journal.export(store, portal['owner'].id)
    for row in saved['controls']:
        row.pop('file_keys_sha256', None)
    checksum = digest({'format': saved['format'], 'controls': saved['controls']})
    journal.merge(store, portal['owner'].id, ImportJournal(controls=saved['controls'], source_sha256=checksum,
        reason='Vorheriges Journal mit dem aktuellen Datenbestand abgeglichen.', idempotency_key=uuid4().hex))
    from backend.services.privacy.storage import ensure_file_available
    with pytest.raises(HTTPException):
        ensure_file_available(store, '/uploads/legacy.pdf')


def test_restriction_removes_current_portal_all_downloads_search_and_ai(portal):
    first = portal["households"][0]
    doc, version = portals.document(portal, first)
    publication = portals.publish(portal, first, version)
    assert assistant_context._source(store, "document", doc.id, portal["owner"].id)["file_sha256"] == version.sha256
    change(portal, "document", doc.id, "restrict")
    assert first["client"].get("/api/v1/portal/me/documents").json()["items"] == []
    for suffix in ("download", "preview"):
        assert first["client"].get(f"/api/v1/portal/me/documents/{publication['id']}/{suffix}").status_code == 404
    result = global_search.search_page(store, global_search.get_type("document"), "Originalfassung", limit=25)
    assert result.total == 0
    with pytest.raises(HTTPException) as denied:
        assistant_context._source(store, "document", doc.id, portal["owner"].id)
    assert denied.value.status_code == 404
    change(portal, "document", doc.id, "release_restriction")
    assert first["client"].get(f"/api/v1/portal/me/documents/{publication['id']}/download").status_code == 200


def test_subject_export_and_anonymization_include_only_own_portal_chain(portal):
    first, second = portal["households"]
    case, _, _ = portals.damage(first, image=True)
    other, _, _ = portals.damage(second, image=True)
    result = portal["office"].get(f"/api/v1/admin/dsgvo/tenant/{first['tenant'].id}/export")
    assert result.status_code == 200, result.text
    data = result.json()["extensions"]
    assert [row["id"] for row in data["portal_cases"]] == [case["id"]]
    assert len(data["portal_images"]) == 1
    assert other["id"] not in result.text and "password_hash" not in result.text and "token_sha256" not in result.text
    result = portal["office"].post(f"/api/v1/admin/dsgvo/tenant/{first['tenant'].id}/anonymize")
    assert result.status_code == 200, result.text
    assert result.json()["extensions"]["retained_messages"] == 1
    assert first["client"].get("/api/v1/portal/me").status_code == 401
    assert second["client"].get("/api/v1/portal/me").status_code == 200


def test_request_never_claims_complete_erasure_of_retained_records_and_checks_inventory(portal):
    office, first = portal["office"], portal["households"][0]
    response = office.post("/api/v1/privacy/requests", json={"subject_kind": "tenant", "subject_id": first["tenant"].id,
        "request_type": "erasure", "verification": "Identität anhand bestehender Akte geprüft.", "due_on": "2026-12-01", "idempotency_key": uuid4().hex})
    assert response.status_code == 201, response.text
    identifier = response.json()["id"]
    current = office.get(f"/api/v1/privacy/requests/{identifier}").json()
    command = {"expected_revision": 1, "source_sha256": current["source_sha256"], "outcome": "fulfilled", "reason": "Die Anfrage wurde vollständig bearbeitet.", "idempotency_key": uuid4().hex}
    assert office.post(f"/api/v1/privacy/requests/{identifier}/decision", json=command).status_code == 409
    portals.damage(first)
    command.update(outcome="partially_fulfilled", idempotency_key=uuid4().hex)
    assert office.post(f"/api/v1/privacy/requests/{identifier}/decision", json=command).status_code == 409
    current = office.get(f"/api/v1/privacy/requests/{identifier}").json()
    command.update(source_sha256=current["source_sha256"], idempotency_key=uuid4().hex)
    result = office.post(f"/api/v1/privacy/requests/{identifier}/decision", json=command)
    assert result.status_code == 200 and result.json()["state"] == "partially_fulfilled", result.text
    assert office.get(f"/api/v1/privacy/requests/{identifier}/export").headers["cache-control"] == "no-store"


def test_restore_epoch_blocks_existing_review_and_must_match_current_journal(portal, monkeypatch):
    owner, first = portal["owner"], portal["households"][0]
    assert journal.status(store, owner.id)["pending"] is False
    monkeypatch.setattr(settings, "privacy_restore_id", "new-restoration")
    assert first["client"].get("/api/v1/portal/me").status_code == 503
    with pytest.raises(HTTPException) as denied:
        global_search.search_page(store, global_search.get_type("tenant"), "Haushalt", limit=25)
    assert denied.value.status_code == 503
    current = journal.status(store, owner.id)
    command = CompleteRestoreReview(expected_revision=current["revision"], journal_sha256=current["journal_sha256"],
        reason="Aktuelles separates Journal und sämtliche späteren Entscheidungen geprüft.", decisions_reconciled=True, idempotency_key=uuid4().hex)
    assert journal.complete(store, owner.id, command)["pending"] is False
    assert first["client"].get("/api/v1/portal/me").status_code == 200
    monkeypatch.setattr(settings, "privacy_restore_id", "another-restoration")
    assert first["client"].get("/api/v1/portal/me").status_code == 503


def test_erased_bytes_restored_from_old_backup_require_reapplication_before_access(portal):
    owner = portal["owner"]
    identifier = str(uuid4())
    content = b"synthetic customer archive"
    old = dict(id=identifier, created_by=owner.id, idempotency_key=uuid4().hex, request_sha256="0" * 64, state="ready", revision=1,
        content=content, sha256=hashlib.sha256(content).hexdigest(), size_bytes=len(content), manifest={}, error=None,
        created_at=datetime.now() - timedelta(days=30), updated_at=datetime.now() - timedelta(days=30))
    with work(store, owner.id) as unit:
        db.put(unit, PortabilityExportORM, old)
    change(portal, "portability_export", identifier, "hold")
    with pytest.raises(HTTPException):
        change(portal, "portability_export", identifier, "erase")
    change(portal, "portability_export", identifier, "release_hold")
    change(portal, "portability_export", identifier, "erase")
    saved = journal.export(store, owner.id)
    with work(store, owner.id) as unit:
        db.put(unit, PortabilityExportORM, old)  # isolated simulation of old restored bytes
    journal.merge(store, owner.id, ImportJournal(controls=saved["controls"], source_sha256=saved["sha256"],
        reason="Späteres Journal mit alter Sicherung abgeglichen.", idempotency_key=uuid4().hex))
    pending = journal.status(store, owner.id)
    assert pending["pending"] and len(pending["pending_erasure"]) == 1
    with pytest.raises(HTTPException):
        journal.complete(store, owner.id, CompleteRestoreReview(expected_revision=pending["revision"], journal_sha256=pending["journal_sha256"],
            reason="Die Prüfliste wurde vollständig durchgesehen.", decisions_reconciled=True, idempotency_key=uuid4().hex))
    result = change(portal, "portability_export", identifier, "erase")
    assert result["erased_at"] and not result["erasure_due"]
    assert db.row(read_unit(store), PortabilityExportORM, identifier).content is None


def test_customer_archive_preserves_holds_restrictions_without_credentials(portal):
    doc, _ = portals.document(portal, portal["households"][0])
    change(portal, "document", doc.id, "hold")
    change(portal, "document", doc.id, "restrict")
    content, _ = portable.export((portal["owner"], portal["portfolio"], portal["office"]))
    _, evidence, _, _, _ = portable.portable_archive.read(content)
    kept = next(row for row in evidence if row["source_type"] == "privacy_controls")
    assert kept["payload"]["held"] and kept["payload"]["restricted"]
    assert kept["payload"]["record_id"] == doc.id
    for model in backup.MODELS:
        if hasattr(store, "db"):
            store.db.execute(delete(model))
        else:
            store.__dict__.get("_integration_connections", {}).pop(model.__tablename__, None)
    if hasattr(store, "db"):
        store.db.commit()
    portals.purge()
    owner = auth.register_user("fresh", "fresh@example.test", "Fresh", "NewPassword123", "eigentuemer")
    from backend.data_transfer_models import BatchOptions, CommitImport
    from backend.services.data_transfer import imports
    batch = imports.create(store, owner.id, [("customer.zip", content)], BatchOptions(source_system="Kundenwechsel"), uuid4().hex)
    assert batch["state"] == "ready", batch["preview"]
    imports.commit(store, owner.id, batch["id"], CommitImport(expected_revision=batch["revision"], idempotency_key=uuid4().hex,
        acknowledge_warnings=True, reason="Sperren und Originale in frischer Umgebung abgeglichen."))
    restored = controls.detail(store, owner.id, "document", doc.id)
    assert restored["held"] and restored["restricted"]
    assert store.get_document(doc.id).title == doc.title


def test_privacy_migration_and_full_restore_close_access_before_activation(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'privacy.db'}")
    Base.metadata.create_all(engine)
    migration = import_module("backend.db.migrations.versions.d6e8f0a2b4c7_privacy_controls")
    with engine.begin() as connection:
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
        result = backup.verify(connection, normalize=True)
        assert result["access_suspended"]
        assert connection.execute(select(RestoreReviewORM.pending)).scalar_one() is True
    engine.dispose()


def test_current_actor_role_and_scope_are_rechecked_for_decisions(portal):
    doc = store.create_document(DocumentCreate(title="Test", file_url="https://example.test/file.txt"))
    previous = controls.detail(store, portal["owner"].id, "document", doc.id)
    auth.update_user(portal["owner"].id, {"role": "readonly"})
    with pytest.raises(HTTPException) as denied:
        change(portal, "document", doc.id, "restrict", current=previous)
    assert denied.value.status_code == 403
    assert not rows(read_unit(store), PrivacyControlORM)
