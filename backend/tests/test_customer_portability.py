"""Customer package round trip, document hashes, absent secrets and hostile ZIPs."""
import hashlib
import io
import zipfile
from uuid import uuid4

import pytest
import test_data_transfer as transfer_fixtures
import test_e_invoice_intakes as invoice_fixtures
from fastapi import HTTPException
from fastapi.testclient import TestClient

from backend import auth
from backend.app import app
from backend.data_transfer_models import BatchOptions, CommitImport, CreatePortabilityExport
from backend.dependencies import store
from backend.invoice_review_models import CheckRequest, DecisionRequest
from backend.models import DocumentCreate
from backend.payment_security_models import AuthorizePayment, RecipientChange
from backend.services import document_original_snapshot, invoice_review, payment_security
from backend.services.data_transfer import exports, imports, jobs, portable_archive
from backend.services.e_invoice import service as invoice_intakes
from backend.services.file_storage import LocalStorage
from backend.services.jobs import JobRunner, MemoryJobStore, SqlJobStore

migration = transfer_fixtures.migration
valid_engine = invoice_fixtures.valid_engine


def export(migration):
    command = CreatePortabilityExport(idempotency_key=uuid4().hex)
    row = exports.create(store, migration[0].id, command)
    assert exports.create(store, migration[0].id, command)["id"] == row["id"]
    queue = SqlJobStore(store.db.get_bind()) if hasattr(store, "db") else MemoryJobStore(lambda: store)
    jobs.recover(queue, store)
    runs = JobRunner(queue, {jobs.KIND: jobs.handler}).run_until_idle()
    assert runs and all(run.status == "succeeded" for run in runs), runs
    result = exports.detail(store, migration[0].id, row["id"])
    assert result["state"] == "ready", result
    return exports.download(store, migration[0].id, row["id"]), result


def test_fresh_reimport_preserves_counts_amounts_hashes_and_requires_new_bank_approval(migration, valid_engine):
    imported = transfer_fixtures.create(migration)
    transfer_fixtures.commit(migration, imported)
    owner, portfolio, _ = migration
    prop = store.list_properties()[0]
    receipt = invoice_fixtures.receipt((owner, prop, portfolio))
    accepted = invoice_intakes.accept(store, owner.id, receipt["id"], invoice_fixtures.command(receipt))
    identifier = accepted["invoice_id"]
    invoice_review.factual_check(store, identifier, CheckRequest(result="confirmed"), owner.id)
    invoice_review.arithmetic_check(store, identifier, CheckRequest(result="confirmed"), owner.id)
    invoice_review.decide(store, identifier, DecisionRequest(decision="approve"), owner.id)
    payment = payment_security.read(store, owner.id, identifier)
    payment = payment_security.change_recipient(store, owner.id, identifier, RecipientChange(expected_revision=payment["revision"],
        idempotency_key=uuid4().hex, name="Testbetrieb", iban="DE89370400440532013000", reason="Bankdaten aus geprüfter Rechnung"))
    checker = auth.register_user("checker", "checker@example.test", "Checker", "DoNotExportPassword42", "buchhaltung")
    payment_security.authorize(store, checker.id, identifier, AuthorizePayment(expected_revision=payment["revision"], idempotency_key=uuid4().hex,
        reason="Unabhängige Betragskontrolle", bank_verification="Bankkonto telefonisch über bekannte Rufnummer gegengeprüft."))
    before = document_original_snapshot.export(store)
    content, metadata = export(migration)
    snapshot, evidence, assets, extract, manifest = portable_archive.read(content)
    assert assets == [] and evidence
    assert manifest["controls"]["receivables"]["amounts"]["amount_due"] == "123.45"
    assert manifest["controls"]["invoices"]["amounts"]["gross_amount"] == "172.50"
    with zipfile.ZipFile(io.BytesIO(content)) as bundle:
        text = b"\n".join(bundle.read(name) for name in bundle.namelist() if name.endswith('.json'))
        for secret in (b"DoNotExportPassword42", b'"password_hash"', b'"totp_secret"', b'"refresh_token"'):
            assert secret not in text
    assert hashlib.sha256(content).hexdigest() == metadata["sha256"]
    transfer_fixtures.purge()
    new_owner = auth.register_user("new-owner", "new@example.test", "Fresh instance", "NewPassword123", "eigentuemer")
    batch = imports.create(store, new_owner.id, [("customer.zip", content)], BatchOptions(source_system="Kundenwechsel"), uuid4().hex)
    assert batch["state"] == "ready", batch["preview"]
    result = imports.commit(store, new_owner.id, batch["id"], CommitImport(expected_revision=1, idempotency_key=uuid4().hex,
        acknowledge_warnings=True, reason="Frische Instanz mit Quellbestand abgeglichen."))
    assert result["state"] == "committed"
    after = document_original_snapshot.export(store)
    assert {row["id"]: row["sha256"] for row in after} == {row["id"]: row["sha256"] for row in before}
    assert {row["id"]: row["blocks"] for row in after} == {row["id"]: row["blocks"] for row in before}
    assert len(store.list_units()) == len(snapshot["units"])
    assert invoice_intakes.detail(store, new_owner.id, receipt["id"])["invoice_id"] == identifier
    new_payment = payment_security.read(store, new_owner.id, identifier)
    assert not new_payment["authorized"]
    assert new_payment["recipient"]["created_by"] == new_owner.id
    with pytest.raises(HTTPException) as denied:
        payment_security.authorize(store, new_owner.id, identifier, AuthorizePayment(expected_revision=new_payment["revision"],
            idempotency_key=uuid4().hex, reason="Import ersetzt keine Gegenprüfung", bank_verification="Importierter Stand geprüft, aber zweite Person fehlt."))
    assert denied.value.status_code in (403, 409)


@pytest.mark.parametrize("mutation", ["traversal", "duplicate", "tampered", "missing"])
def test_tampered_or_ambiguous_package_never_enters_business_store(migration, mutation):
    content, _ = export(migration)
    with zipfile.ZipFile(io.BytesIO(content)) as source:
        parts = {name: source.read(name) for name in source.namelist()}
    if mutation == "traversal":
        parts["../escape"] = b"x"
    elif mutation == "tampered":
        parts["business.json"] = parts["business.json"].replace(b"Zielbestand", b"Other data")
    elif mutation == "missing":
        del parts["schema.json"]
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as target:
        for name, raw in parts.items():
            target.writestr(name, raw)
        if mutation == "duplicate":
            with pytest.warns(UserWarning):
                target.writestr("business.json", parts["business.json"])
    row = imports.create(store, migration[0].id, [("malicious.zip", output.getvalue())], BatchOptions(source_system="Prüffall"), uuid4().hex)
    assert row["state"] == "invalid" and row["preview"]["error_count"]
    assert store.list_properties() == []


def test_revoked_creator_cannot_generate_or_download_export(migration):
    owner, _, client = migration
    row = exports.create(store, owner.id, CreatePortabilityExport(idempotency_key=uuid4().hex))
    auth.update_user(owner.id, {"role": "readonly"})
    queue = SqlJobStore(store.db.get_bind()) if hasattr(store, "db") else MemoryJobStore(lambda: store)
    jobs.recover(queue, store)
    JobRunner(queue, {jobs.KIND: jobs.handler}).run_until_idle()
    assert client.get(f"/api/v1/data/portability-exports/{row['id']}/download").status_code == 403
    auth.update_user(owner.id, {"role": "eigentuemer"})
    assert exports.detail(store, owner.id, row["id"])["state"] == "failed"


def test_export_api_serves_attachment_and_rechecks_current_user(migration):
    content, row = export(migration)
    result = migration[2].get(f"/api/v1/data/portability-exports/{row['id']}/download")
    assert result.content == content and result.headers["cache-control"] == "no-store"
    assert "attachment" in result.headers["content-disposition"]
    other = auth.register_user("limited", "limited@example.test", "Limited", "Secret123", "verwalter", portfolio_access="selected", portfolio_ids=[])
    limited = TestClient(app, headers={"Authorization": "Bearer " + auth.create_access_token(other.id)})
    assert limited.get(f"/api/v1/data/portability-exports/{row['id']}/download").status_code == 403


def test_unarchived_attachments_survive_fresh_reimport_and_checksum_is_verified(migration, tmp_path, monkeypatch):
    from backend.services import file_storage
    source = LocalStorage(tmp_path / "source")
    monkeypatch.setattr(file_storage, "_storage", source)
    transfer_fixtures.commit(migration, transfer_fixtures.create(migration))
    prop = store.list_properties()[0]
    content = b"%PDF-1.7\nsynthetic attachment bytes for exact transport\n%%EOF"
    source.save("documents/fixture.pdf", io.BytesIO(content))
    document = store.create_document(DocumentCreate(title="Quelle", file_url="/uploads/documents/fixture.pdf", property_id=prop.id))
    archive, _ = export(migration)
    transfer_fixtures.purge()
    destination = LocalStorage(tmp_path / "destination")
    monkeypatch.setattr(file_storage, "_storage", destination)
    owner = auth.register_user("fresh-attachment", "fresh@example.test", "Fresh", "NewPassword123", "eigentuemer")
    batch = imports.create(store, owner.id, [("customer.zip", archive)], BatchOptions(source_system="Quellbestand"), uuid4().hex)
    assert batch["state"] == "ready", batch["preview"]
    assert batch["preview"]["additional_evidence"]["attachments"] == 1
    assert destination.get("documents/fixture.pdf") is None
    imports.commit(store, owner.id, batch["id"], CommitImport(expected_revision=1, idempotency_key=uuid4().hex,
        acknowledge_warnings=True, reason="Dateien und Originalhashes gegengeprüft."))
    assert destination.get("documents/fixture.pdf") == content
    assert store.get_document(document.id).file_url == document.file_url


def test_same_key_with_different_attachment_prevents_every_business_write(migration, tmp_path, monkeypatch):
    from backend.services import file_storage
    storage = LocalStorage(tmp_path / "sources")
    monkeypatch.setattr(file_storage, "_storage", storage)
    transfer_fixtures.commit(migration, transfer_fixtures.create(migration))
    prop = store.list_properties()[0]
    storage.save("documents/conflict.pdf", io.BytesIO(b"%PDF-1.7\nold content"))
    store.create_document(DocumentCreate(title="Quelle", file_url="/uploads/documents/conflict.pdf", property_id=prop.id))
    archive, _ = export(migration)
    transfer_fixtures.purge()
    storage = LocalStorage(tmp_path / "conflicting-destination")
    monkeypatch.setattr(file_storage, "_storage", storage)
    storage.save("documents/conflict.pdf", io.BytesIO(b"%PDF-1.7\ndifferent content"))
    owner = auth.register_user("conflict-owner", "conflict@example.test", "Fresh", "NewPassword123", "eigentuemer")
    batch = imports.create(store, owner.id, [("customer.zip", archive)], BatchOptions(source_system="Quellbestand"), uuid4().hex)
    assert batch["state"] == "invalid" and "Dateipfad" in " ".join(batch["preview"]["errors"])
    assert store.list_documents() == [] and store.list_properties() == []
