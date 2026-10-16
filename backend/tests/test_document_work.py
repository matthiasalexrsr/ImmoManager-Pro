"""Independent workflow oracles: native package bytes, conflicting editors,
lost replies, rollback/recovery, invoice amounts and immutable originals.
"""
import base64
import hashlib
import io
import zipfile
from uuid import uuid4

import pytest
from archive_helpers import drop_guards, lease_with_document, purge_originals
from fastapi import HTTPException
from fastapi.testclient import TestClient
from PIL import Image

from backend import auth
from backend.app import app
from backend.dependencies import store
from backend.document_work_models import (
    AnnotationSave,
    Command,
    EvidenceUpload,
    ExportRequest,
    InvoiceTakeover,
    OpenSession,
    SessionRebase,
)
from backend.models import DocumentCreate
from backend.services import document_work as service
from backend.services.data_snapshot import clear_business_data, export_snapshot, import_snapshot
from backend.services.document_formats import validate_docx
from backend.services.file_storage import LocalStorage, get_file_storage
from backend.storage import NotFoundError


def purge_test_versions():
    """Fixture-only cleanup in this matrix's owned database, children first.

    The old helper only had single originals and its bulk DELETE cannot remove
    self-referencing version chains under SQLite RESTRICT. Keep all FK checks.
    """
    if hasattr(store, "db"):
        from sqlalchemy import text

        from backend.db.document_version_models import install_guards
        from backend.db.document_work_models import install_guards as work_guards
        store.db.rollback()
        with store.db.get_bind().begin() as connection:
            if connection.dialect.name == "sqlite":
                for operation in ("update", "delete"):
                    connection.exec_driver_sql(f"DROP TRIGGER IF EXISTS immo_document_work_{operation}")
            else:
                connection.exec_driver_sql("DROP TRIGGER IF EXISTS immo_document_work_immutable ON document_work_events")
            connection.exec_driver_sql("DELETE FROM document_work_events")
            work_guards(connection)
            drop_guards(connection)
            connection.exec_driver_sql("DELETE FROM document_version_chunks")
            for identifier in connection.exec_driver_sql("SELECT id FROM document_versions ORDER BY number DESC").scalars().all():
                connection.execute(text("DELETE FROM document_versions WHERE id=:id"), {"id": identifier})
            install_guards(connection)
    else:
        purge_originals(store)


def docx_bytes(text="Änderung № 42 – Öl & Wärme €", paragraphs=800):
    """A real OOXML package built independently of the implementation under test."""
    from xml.sax.saxutils import escape
    image = io.BytesIO()
    Image.new("RGB", (20, 20), (200, 30, 40)).save(image, "PNG")
    namespace = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
    parts: dict[str, str | bytes] = {
        "[Content_Types].xml": '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Default Extension="png" ContentType="image/png"/>'
            '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
            '</Types>',
        "_rels/.rels": '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>',
        "word/document.xml": f'<w:document {namespace}><w:body>'
            + ''.join(f'<w:p><w:r><w:t>{number}: {escape(text)}</w:t></w:r></w:p>' for number in range(paragraphs))
            + '<w:tbl><w:tr><w:tc><w:p><w:r><w:t>Unabhängiges Tabellenorakel 119,00</w:t></w:r></w:p></w:tc></w:tr></w:tbl>'
            + '<w:sectPr><w:pgSz w:w="11906" w:h="16838"/></w:sectPr></w:body></w:document>',
        "word/header1.xml": f'<w:hdr {namespace}><w:p><w:r><w:t>Kopfzeile § 14</w:t></w:r></w:p></w:hdr>',
        "word/footer1.xml": f'<w:ftr {namespace}><w:p><w:r><w:fldChar w:fldCharType="begin"/><w:instrText>PAGE</w:instrText></w:r></w:p></w:ftr>',
        "word/media/image1.png": image.getvalue(),
    }
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as package:
        for name, value in parts.items():
            package.writestr(name, value)
    return output.getvalue()


@pytest.fixture
def owner(tmp_path, monkeypatch):
    from backend.services import file_storage
    monkeypatch.setattr(file_storage, "_storage", file_storage.LocalStorage(tmp_path / "uploads"))
    purge_test_versions()
    clear_business_data(store)
    auth.clear_users()
    actor = auth.register_user("docowner", "docs@example.test", "Dokumente", "Secret123", "eigentuemer")
    yield actor
    purge_test_versions()
    clear_business_data(store)
    auth.clear_users()


@pytest.fixture
def prepared(owner):
    lease = lease_with_document(store)
    document = store.update_document(lease["document"].id, DocumentCreate.model_validate(lease["document"].model_dump() | {
        "file_url": "/uploads/documents/long.docx", "document_type": "Rechnung"}))
    content = docx_bytes()
    get_file_storage().save("documents/long.docx", io.BytesIO(content))
    return lease | {"document": document, "content": content}


def command(source, cls=Command, **kwargs):
    return cls(command_key=str(uuid4()), expected_version=source["version"]["id"] if source["version"] else None,
        expected_sha256=source["sha256"], expected_document_revision=source["document_revision"], **kwargs)


def archived(prepared, owner):
    identifier = prepared["document"].id
    initial = service.source(store, identifier, owner.id)
    saved = service.archive_upload(store, identifier, command(initial), owner.id)
    return service.source(store, identifier, owner.id), saved


def replace_local_fixture(key, content):
    storage = get_file_storage()
    assert isinstance(storage, LocalStorage)
    storage._path(key).write_bytes(content)


def test_long_native_docx_archive_preserves_every_part_and_viewer_uses_original(prepared, owner):
    identifier = prepared["document"].id
    initial = service.source(store, identifier, owner.id)
    request = command(initial)
    first = service.archive_upload(store, identifier, request, owner.id)
    # Simulate out-of-band disk tampering AFTER receipt. The storage service
    # itself now correctly refuses overwrites of original byte addresses.
    replace_local_fixture("documents/long.docx", b"replaced bytes")
    assert service.archive_upload(store, identifier, request, owner.id) == first
    stored, row = service.download(store, identifier, first["version"]["id"], owner.id)
    assert stored == prepared["content"]
    assert row["sha256"] == hashlib.sha256(prepared["content"]).hexdigest()
    with zipfile.ZipFile(io.BytesIO(stored)) as package:
        assert package.read("word/document.xml").count(b"<w:p>") == 801
        assert "Kopfzeile § 14" in package.read("word/header1.xml").decode()
        assert package.read("word/media/image1.png").startswith(b"\x89PNG")
    assert service.archived_upload(store, "documents/long.docx", owner.id)[0] == prepared["content"]
    client = TestClient(app, headers={"Authorization": "Bearer " + auth.create_access_token(owner.id)})
    assert client.get("/api/v1/files/download?key=documents/long.docx").content == prepared["content"]
    assert client.get("/uploads/documents/long.docx").content == prepared["content"]


def test_two_editors_conflict_preserves_losing_editors_crash_buffer(prepared, owner):
    source, _ = archived(prepared, owner)
    identifier = prepared["document"].id
    first = service.open_session(store, identifier, command(source, OpenSession, mode="docx"), owner.id)
    second = service.open_session(store, identifier, command(source, OpenSession, mode="docx"), owner.id)
    a = docx_bytes("Erste Fassung", 700)
    b = docx_bytes("Nicht verlieren: ü €", 900)
    save_request = command(source)
    saved = service.save_docx(store, identifier, first["session_id"], save_request, a, 1, owner.id)
    assert service.save_docx(store, identifier, first["session_id"], save_request, a, 1, owner.id) == saved
    assert saved["version_id"] != source["version"]["id"]
    buffer_request = command(source)
    buffered = service.save_docx(store, identifier, second["session_id"], buffer_request, b, 1, owner.id, autosave=True)
    with pytest.raises(HTTPException) as error:
        service.save_docx(store, identifier, second["session_id"], command(source), b, 2, owner.id)
    assert error.value.status_code == 409
    recovered = service.read_session(store, identifier, second["session_id"], owner.id)
    assert base64.b64decode(recovered["draft_base64"]) == b and recovered["revision"] == 2
    assert service.save_docx(store, identifier, second["session_id"], buffer_request, b, 1, owner.id, autosave=True) == buffered
    assert service.download(store, identifier, source["version"]["id"], owner.id)[0] == prepared["content"]
    assert service.download(store, identifier, saved["version_id"], owner.id)[0] == a
    current = service.source(store, identifier, owner.id)
    rebased = service.rebase_session(store, identifier, second["session_id"], command(current, SessionRebase,
        session_revision=2, confirmed_comparison=True), owner.id)
    assert base64.b64decode(rebased["draft_base64"]) == b
    final = service.save_docx(store, identifier, second["session_id"], command(current), b, 3, owner.id)
    assert service.download(store, identifier, final["version_id"], owner.id)[0] == b
    assert service.download(store, identifier, saved["version_id"], owner.id)[0] == a


def test_changed_command_with_same_key_and_stale_metadata_are_conflicts(prepared, owner):
    source = service.source(store, prepared["document"].id, owner.id)
    request = command(source)
    service.archive_upload(store, prepared["document"].id, request, owner.id)
    with pytest.raises(HTTPException) as error:
        service.archive_upload(store, prepared["document"].id,
            request.model_copy(update={"expected_sha256": "0" * 64}), owner.id)
    assert error.value.status_code == 409
    source = service.source(store, prepared["document"].id, owner.id)
    store.update_document(prepared["document"].id, DocumentCreate.model_validate(prepared["document"].model_dump() | {"title": "Neue Metadaten"}))
    with pytest.raises(HTTPException) as error:
        service.open_session(store, prepared["document"].id, command(source, OpenSession, mode="docx"), owner.id)
    assert error.value.status_code == 409


def test_revoked_account_cannot_recover_or_save_even_with_valid_session(prepared, owner):
    source, _ = archived(prepared, owner)
    identifier = prepared["document"].id
    opened = service.open_session(store, identifier, command(source, OpenSession, mode="docx"), owner.id)
    auth.update_user(owner.id, {"role": "readonly"})
    for operation in (
        lambda: service.read_session(store, identifier, opened["session_id"], owner.id),
        lambda: service.save_docx(store, identifier, opened["session_id"], command(source), docx_bytes(), 1, owner.id),
    ):
        with pytest.raises(HTTPException) as error:
            operation()
        assert error.value.status_code == 403


def test_other_actor_cannot_read_private_recovery(prepared, owner):
    source, _ = archived(prepared, owner)
    opened = service.open_session(store, prepared["document"].id, command(source, OpenSession, mode="docx"), owner.id)
    other = auth.register_user("docother", "other@example.test", "Andere", "Secret123", "verwalter")
    with pytest.raises(HTTPException) as error:
        service.read_session(store, prepared["document"].id, opened["session_id"], other.id)
    assert error.value.status_code == 404
    assert not service.history(store, prepared["document"].id, other.id)["items"][1:]


def test_export_publish_crash_rolls_back_all_outputs_and_can_resume(prepared, owner, monkeypatch):
    source, _ = archived(prepared, owner)
    identifier = prepared["document"].id
    request = command(source, ExportRequest, operation="copy")
    job = service.queue_export(store, identifier, request, owner.id)
    original_publish = service.publish

    def crash(*args, **kwargs):
        original_publish(*args, **kwargs)
        raise RuntimeError("simulated power loss before commit")

    monkeypatch.setattr(service, "publish", crash)
    with pytest.raises(RuntimeError):
        service.run_export(store, identifier, job["job_id"], owner.id)
    assert len(store.list_documents()) == 1
    assert service.job_status(store, identifier, job["job_id"], owner.id)["state"] == "queued"
    monkeypatch.setattr(service, "publish", original_publish)
    output = service.run_export(store, identifier, job["job_id"], owner.id)
    assert output["state"] == "completed" and len(output["outputs"]) == 1
    assert service.queue_export(store, identifier, request, owner.id) == output
    assert service.run_export(store, identifier, job["job_id"], owner.id) == output
    result = output["outputs"][0]
    assert result["document_id"] != identifier
    assert service.download(store, result["document_id"], result["version_id"], owner.id)[0] == prepared["content"]
    assert len(store.list_documents()) == 2


def test_controlled_ocr_takeover_uses_existing_invoice_review_vat_and_skonto(prepared, owner):
    source, _ = archived(prepared, owner)
    identifier = prepared["document"].id
    proposal = service.propose_invoice(store, identifier, command(source), owner.id)
    fields = {field: "manual_correction" for field in (
        "supplier", "invoice_number", "invoice_date", "net_amount", "vat_rate", "vat_amount", "gross_amount")}
    request = command(source, InvoiceTakeover, proposal_id=proposal["proposal_id"], confirmed=True,
        field_sources=fields, receipt={"invoice": {"supplier": "Müller & Söhne", "invoice_number": "R-0042",
            "invoice_date": "2026-10-01", "net_amount": 100, "vat_rate": 19, "vat_amount": 19, "gross_amount": 119},
            "skonto_percent": 2, "skonto_days": 10, "payment_days": 30,
            "vat_lines": [{"rate": 19, "net": 100, "vat": 19}]})
    result = service.take_invoice(store, identifier, request, owner.id)
    assert service.take_invoice(store, identifier, request, owner.id) == result
    assert len(store.list_invoices()) == 1 and not store.list_bookings()
    invoice = store.get_invoice(result["invoice_id"])
    assert (invoice.net_amount, invoice.vat_amount, invoice.gross_amount) == (100, 19, 119)
    assert invoice.status == "open" and invoice.source_document_id == identifier
    review = result["review"]["review"]
    assert review["status"] == "received" and review["skonto_until"] == "2026-10-11" and review["due_on"] == "2026-10-31"
    assert review["document_sha256"] == hashlib.sha256(prepared["content"]).hexdigest()
    with pytest.raises(HTTPException) as error:
        service.take_invoice(store, identifier, request.model_copy(update={"command_key": str(uuid4())}), owner.id)
    assert error.value.status_code == 409


def test_snapshot_contains_recovery_and_source_bytes_and_merges_idempotently(prepared, owner):
    source, _ = archived(prepared, owner)
    opened = service.open_session(store, prepared["document"].id, command(source, OpenSession, mode="docx"), owner.id)
    buffer = docx_bytes("Wiederanlauf", 600)
    service.save_docx(store, prepared["document"].id, opened["session_id"], command(source), buffer, 1, owner.id, autosave=True)
    snapshot = export_snapshot(store)
    assert snapshot["document_work_events"]
    assert any(row["payload"].get("draft_base64") == base64.b64encode(buffer).decode() for row in snapshot["document_work_events"])
    assert import_snapshot(store, snapshot, replace=False)
    assert base64.b64decode(service.read_session(store, prepared["document"].id, opened["session_id"], owner.id)["draft_base64"]) == buffer


@pytest.mark.parametrize("content", [b"not a zip", b"PK\x03\x04", b"", b"<html>not docx</html>"])
def test_malformed_docx_is_rejected(content):
    with pytest.raises(HTTPException) as error:
        validate_docx(content)
    assert error.value.status_code == 422


@pytest.mark.parametrize("name,data", [("../escape.xml", "<x/>"), ("word/vbaProject.bin", b"macro"),
    ("word/evil.xml", '<!DOCTYPE x [<!ENTITY y "evil">]><x/>')])
def test_active_or_unsafe_docx_never_reaches_archive(name, data):
    output = io.BytesIO(docx_bytes())
    with zipfile.ZipFile(output, "a") as package:
        package.writestr(name, data)
    with pytest.raises(HTTPException):
        validate_docx(output.getvalue())


def test_history_keyset_has_no_silent_total_limit(prepared, owner):
    source, _ = archived(prepared, owner)
    identifier = prepared["document"].id
    for _ in range(7):
        service.open_session(store, identifier, command(source, OpenSession, mode="docx"), owner.id)
    found, cursor = [], None
    while True:
        page = service.history(store, identifier, owner.id, after=cursor, limit=3)
        found += page["items"]
        cursor = page["next_after"]
        if not cursor:
            break
    assert len(found) == 8 and len({row["id"] for row in found}) == 8


def test_revoke_portfolio_blocks_original_session_export_and_invoice(prepared, owner):
    source, _ = archived(prepared, owner)
    actor = auth.register_user("scopedocs", "scope@example.test", "Bestandsverwaltung", "Secret123", "verwalter")
    auth.update_user(actor.id, {"portfolio_access": "selected", "portfolio_ids": [prepared["portfolio"].id]})
    identifier = prepared["document"].id
    session = service.open_session(store, identifier, command(source, OpenSession, mode="docx"), actor.id)
    job = service.queue_export(store, identifier, command(source, ExportRequest, operation="copy"), actor.id)
    auth.update_user(actor.id, {"portfolio_access": "selected", "portfolio_ids": []})
    for action in (
        lambda: service.source(store, identifier, actor.id),
        lambda: service.download(store, identifier, source["version"]["id"], actor.id),
        lambda: service.read_session(store, identifier, session["session_id"], actor.id),
        lambda: service.run_export(store, identifier, job["job_id"], actor.id),
        lambda: service.propose_invoice(store, identifier, command(source), actor.id),
    ):
        with pytest.raises((HTTPException, NotFoundError)) as error:
            action()
        assert getattr(error.value, "status_code", None) == 404 or "nicht gefunden" in str(error.value).lower()
    assert len(store.list_documents()) == 1


def test_original_photo_upload_is_atomic_replay_safe_and_protocol_binding_stays(prepared, owner):
    from datetime import date

    from backend.models import HandoverProtocolCreate
    protocol = store.create_handover_protocol(HandoverProtocolCreate(contract_id=prepared["contract"].id,
        unit_id=prepared["unit"].id, protocol_type="move_in", protocol_date=date(2026, 10, 16)))
    image = io.BytesIO()
    Image.new("RGB", (43, 29), (123, 45, 67)).save(image, "PNG")
    content = image.getvalue()
    original = service.protocol_source(store, protocol.id, owner.id)
    request = EvidenceUpload(command_key=str(uuid4()), expected_protocol_revision=original["revision"],
        expected_sha256=hashlib.sha256(content).hexdigest(), purpose="original_photo")
    result = service.upload_evidence(store, protocol.id, request, content, "Wohnzimmer-original.png", owner.id)
    assert service.upload_evidence(store, protocol.id, request, content, "Wohnzimmer-original.png", owner.id) == result
    assert service.download(store, result["document_id"], result["version_id"], owner.id)[0] == content
    assert service.protocol_evidence(store, protocol.id, owner.id)["items"] == [result]
    assert result["signature_validity"] == "not_verified"
    with pytest.raises(HTTPException) as error:
        store.delete_handover_protocol(protocol.id)
    assert error.value.status_code == 409
    altered = request.model_copy(update={"expected_sha256": "0" * 64})
    with pytest.raises(HTTPException):
        service.upload_evidence(store, protocol.id, altered, content, "Wohnzimmer-original.png", owner.id)
    assert len(store.list_documents()) == 2


def test_stale_protocol_and_wrong_hash_write_no_evidence(prepared, owner):
    from datetime import date

    from backend.models import HandoverProtocolCreate
    protocol = store.create_handover_protocol(HandoverProtocolCreate(contract_id=prepared["contract"].id,
        unit_id=prepared["unit"].id, protocol_type="move_in", protocol_date=date(2026, 10, 16)))
    image = io.BytesIO()
    Image.new("RGB", (9, 8), (50, 60, 70)).save(image, "PNG")
    content = image.getvalue()
    request = EvidenceUpload(command_key=str(uuid4()), expected_protocol_revision="0" * 64,
        expected_sha256=hashlib.sha256(content).hexdigest(), purpose="signed_return")
    with pytest.raises(HTTPException) as error:
        service.upload_evidence(store, protocol.id, request, content, "Rueckscan.png", owner.id)
    assert error.value.status_code == 409
    assert len(store.list_documents()) == 1
    assert service.protocol_evidence(store, protocol.id, owner.id)["items"] == []


def test_invoice_takeover_crash_rolls_back_invoice_review_and_command(prepared, owner, monkeypatch):
    from backend.services import invoice_review
    source, _ = archived(prepared, owner)
    identifier = prepared["document"].id
    proposal = service.propose_invoice(store, identifier, command(source), owner.id)
    original = invoice_review.start_review
    request = command(source, InvoiceTakeover, proposal_id=proposal["proposal_id"], confirmed=True,
        field_sources={name: "manual_correction" for name in ("supplier", "invoice_number", "invoice_date", "net_amount", "vat_rate", "vat_amount", "gross_amount")},
        receipt={"invoice": {"supplier": "Heizung", "invoice_number": "R1", "invoice_date": "2026-10-01",
            "net_amount": "200.00", "vat_rate": "7", "vat_amount": "14.00", "gross_amount": "214.00"}})

    def crash(*args, **kwargs):
        original(*args, **kwargs)
        raise RuntimeError("power loss after invoice insert")

    monkeypatch.setattr(invoice_review, "start_review", crash)
    with pytest.raises(RuntimeError):
        service.take_invoice(store, identifier, request, owner.id)
    assert store.list_invoices() == []
    monkeypatch.setattr(invoice_review, "start_review", original)
    result = service.take_invoice(store, identifier, request, owner.id)
    assert store.get_invoice(result["invoice_id"]).gross_amount == 214
    assert len(store.list_invoices()) == 1


def test_failed_optional_conversion_is_durable_and_retry_has_no_output(prepared, owner, monkeypatch):
    monkeypatch.delenv("DOCUMENT_LIBREOFFICE_EXECUTABLE", raising=False)
    source, _ = archived(prepared, owner)
    identifier = prepared["document"].id
    job = service.queue_export(store, identifier, command(source, ExportRequest, operation="docx_pdf"), owner.id)
    result = service.run_export(store, identifier, job["job_id"], owner.id)
    assert result["state"] == "failed" and "LibreOffice" in result["error"] and result["outputs"] == []
    retried = service.run_export(store, identifier, job["job_id"], owner.id)
    assert retried["state"] == "failed" and len(store.list_documents()) == 1


def test_snapshot_restores_native_archive_and_private_recovery_to_fresh_store(prepared, owner, monkeypatch):
    from backend.storage import InMemoryStore
    source, _ = archived(prepared, owner)
    opened = service.open_session(store, prepared["document"].id, command(source, OpenSession, mode="docx"), owner.id)
    content = docx_bytes("Nach Wiederherstellung vollständig", 950)
    service.save_docx(store, prepared["document"].id, opened["session_id"], command(source), content, 1, owner.id, autosave=True)
    snapshot = export_snapshot(store)
    fresh = InMemoryStore()
    import_snapshot(fresh, snapshot, replace=False)
    # This is a separate restored memory installation. Its account backend
    # must match its business backend, including when the source used SQL.
    accounts = auth.InMemoryUserStore()
    account = auth.get_user_by_id(owner.id)
    assert account is not None
    accounts.create(dict(account))
    with monkeypatch.context() as restored:
        restored.setattr(auth, "_user_store", accounts)
        assert service.download(fresh, prepared["document"].id, source["version"]["id"], owner.id)[0] == prepared["content"]
        recovered = service.read_session(fresh, prepared["document"].id, opened["session_id"], owner.id)
        assert base64.b64decode(recovered["draft_base64"]) == content


def test_two_independent_sql_connections_publish_only_one_winning_editor(prepared, owner):
    import threading
    from concurrent.futures import ThreadPoolExecutor

    from sqlalchemy.orm import Session

    from backend.repositories import SQLAlchemyStore
    source, _ = archived(prepared, owner)
    identifier = prepared["document"].id
    sessions = [service.open_session(store, identifier, command(source, OpenSession, mode="docx"), owner.id) for _ in range(2)]
    barrier = threading.Barrier(2)
    engine = store.db.get_bind() if hasattr(store, "db") else None

    def save(index):
        barrier.wait(timeout=10)
        content = docx_bytes(f"Paralleler Editor {index}", 40)
        try:
            if engine is None:
                result = service.save_docx(store, identifier, sessions[index]["session_id"], command(source), content, 1, owner.id)
            else:
                with Session(engine) as database:
                    result = service.save_docx(SQLAlchemyStore(database), identifier, sessions[index]["session_id"], command(source), content, 1, owner.id)
            return result["version_id"]
        except HTTPException as error:
            assert error.status_code == 409
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(save, [0, 1]))
    assert results.count("conflict") == 1
    history = service.archive.history(store, identifier, owner.id)
    assert [row["number"] for row in history["items"]] == [2, 1]


def test_unassigned_ordinary_upload_viewer_still_works(owner):
    # Existing intake deliberately allows documents before property assignment.
    content = b"unassigned intake bytes"
    get_file_storage().save("documents/intake.txt", io.BytesIO(content))
    store.create_document(DocumentCreate(title="Noch zuzuordnen", file_url="/uploads/documents/intake.txt"))
    client = TestClient(app, headers={"Authorization": "Bearer " + auth.create_access_token(owner.id)})
    response = client.get("/api/v1/files/download?key=documents/intake.txt")
    assert response.status_code == 200 and response.content == content


def test_utf8_text_autosave_recovery_and_empty_new_version_preserve_original(prepared, owner):
    identifier = prepared["document"].id
    doc = store.update_document(identifier, DocumentCreate.model_validate(prepared["document"].model_dump() | {
        "file_url": "/uploads/documents/text.txt"}))
    original = "Öl, Wärme, Größe, € und § 14\nZweite Zeile".encode()
    get_file_storage().save("documents/text.txt", io.BytesIO(original))
    initial = service.source(store, doc.id, owner.id)
    service.archive_upload(store, doc.id, command(initial), owner.id)
    source = service.source(store, doc.id, owner.id)
    opened = service.open_session(store, doc.id, command(source, OpenSession, mode="text"), owner.id)
    buffer = service.save_docx(store, doc.id, opened["session_id"], command(source), b"", 1, owner.id,
                              autosave=True, native_format="text")
    assert buffer["draft_base64"] == ""
    saved = service.save_docx(store, doc.id, opened["session_id"], command(source), b"", 2, owner.id, native_format="text")
    assert service.download(store, doc.id, saved["version_id"], owner.id)[0] == b""
    assert service.source(store, doc.id, owner.id)["inspection"]["format"] == "text"
    assert service.download(store, doc.id, source["version"]["id"], owner.id)[0] == original


def test_real_ooxml_relationships_headers_footnotes_comments_and_images_are_preserved(prepared, owner):
    from scripts.document_qa_fixtures import rich_docx
    content = rich_docx()
    replace_local_fixture("documents/long.docx", content)
    identifier = prepared["document"].id
    initial = service.source(store, identifier, owner.id)
    result = service.archive_upload(store, identifier, command(initial), owner.id)
    stored = service.download(store, identifier, result["version"]["id"], owner.id)[0]
    assert stored == content
    with zipfile.ZipFile(io.BytesIO(stored)) as package:
        main = package.read("word/document.xml").decode()
        assert main.count("<w:tr>") == 65 and main.count("<w:footnoteReference") == 1
        assert '<a:blip r:embed="img1"' in main and 'w:headerReference' in main
        assert 'word/header1.xml' in package.namelist() and 'word/footnotes.xml' in package.namelist()
        assert 'Wärme €' in package.read("word/comments.xml").decode()


def test_local_analysis_reads_archived_pdf_bytes_and_persists_proposal_without_invoice(prepared, owner):
    from reportlab.pdfgen import canvas
    stream = io.BytesIO()
    pdf = canvas.Canvas(stream)
    for index, line in enumerate(["Muster GmbH", "Rechnungsnr: R-73", "Rechnungsdatum: 01.10.2026", "Gesamtbetrag: 119,00 EUR"]):
        pdf.drawString(30, 780 - index * 30, line)
    pdf.save()
    content = stream.getvalue()
    identifier = prepared["document"].id
    store.update_document(identifier, DocumentCreate.model_validate(prepared["document"].model_dump() | {
        "file_url": "/uploads/documents/rechnung.pdf"}))
    get_file_storage().save("documents/rechnung.pdf", io.BytesIO(content))
    initial = service.source(store, identifier, owner.id)
    service.archive_upload(store, identifier, command(initial), owner.id)
    source = service.source(store, identifier, owner.id)
    request = command(source)
    job = service.queue_analysis(store, identifier, request, owner.id)
    # The disk upload no longer resembles the received invoice; analysis must
    # use the archived input rather than a guessed filesystem sidecar.
    replace_local_fixture("documents/rechnung.pdf", b"replaced")
    result = service.run_analysis(store, identifier, job["job_id"], owner.id)
    assert result["state"] == "completed", result["error"]
    assert result["result"]["invoice_number"] == "R-73" and result["result"]["total_amount"] == 119
    assert service.queue_analysis(store, identifier, request, owner.id) == result
    assert service.run_analysis(store, identifier, job["job_id"], owner.id) == result
    proposal = service.propose_invoice(store, identifier, command(source), owner.id)
    assert proposal["observation_state"] == "current" and proposal["observed"]["invoice_number"] == "R-73"
    assert not store.list_invoices() and not store.list_bookings()


def test_local_analysis_failure_is_explicit_and_retryable_without_any_invoice(prepared, owner):
    source, _ = archived(prepared, owner)
    identifier = prepared["document"].id
    job = service.queue_analysis(store, identifier, command(source), owner.id)
    result = service.run_analysis(store, identifier, job["job_id"], owner.id)
    assert result["state"] == "failed" and result["error"] and result["result"] is None
    assert service.run_analysis(store, identifier, job["job_id"], owner.id)["state"] == "failed"
    assert not store.list_invoices()


def test_native_annotation_validation_does_not_hold_writer_and_rechecks_source(prepared, owner, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor

    from scripts.document_qa_fixtures import pdf_fixture

    identifier = prepared["document"].id
    document = store.update_document(identifier, DocumentCreate.model_validate(prepared["document"].model_dump() | {
        "file_url": "/uploads/documents/annotations.pdf"}))
    get_file_storage().save("documents/annotations.pdf", io.BytesIO(pdf_fixture()))
    initial = service.source(store, identifier, owner.id)
    service.archive_upload(store, identifier, command(initial), owner.id)
    source = service.source(store, identifier, owner.id)
    session = service.open_session(store, identifier, command(source, OpenSession, mode="annotations"), owner.id)

    def during_native_validation(*args, **kwargs):
        # A different writer must finish while the native worker is running.
        # With the old long transaction this times out on the archive/SQL lock.
        executor = ThreadPoolExecutor(max_workers=1)
        try:
            future = executor.submit(service.open_session, store, identifier,
                command(source, OpenSession, mode="annotations"), owner.id)
            assert future.result(timeout=3)["mode"] == "annotations"
        finally:
            executor.shutdown(wait=False, cancel_futures=True)
        store.update_document(identifier, DocumentCreate.model_validate(document.model_dump() | {"title": "Geänderte Quelle"}))

    monkeypatch.setattr("backend.services.document_pdf.isolated", during_native_validation)
    with pytest.raises(HTTPException) as failure:
        service.save_annotations(store, identifier, session["session_id"],
            command(source, AnnotationSave, session_revision=0, annotations=[]), owner.id)
    assert failure.value.status_code == 409
    assert service.source(store, identifier, owner.id)["layer_revision"] == 0
