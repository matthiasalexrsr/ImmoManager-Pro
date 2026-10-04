"""Real local approval, original byte archive and manual observation receipts."""

import hashlib
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from backend.db.contract_correspondence_models import (
    CorrespondenceCommandORM,
    CorrespondenceDraftORM,
    CorrespondenceEventORM,
    ensure_contract_correspondence_schema,
)
from backend.db.document_version_models import ensure_document_version_schema
from backend.models import ContractPatch, TenantCreate
from backend.services import contract_correspondence as service
from backend.services import contract_lifecycle, document_versions
from backend.services.contract_correspondence_types import (
    ApproveLetter,
    CreateLetter,
    EditLetter,
    LetterData,
    ManualEvent,
    RevisionCommand,
)
from backend.services.contract_correspondence_validation import EvidenceError, validate_correspondence_journal
from backend.storage import ValidationError
from backend.tests.test_contract_lifecycle import active as active


@pytest.fixture
def letter(active):
    if active.engine is not None:
        with active.engine.begin() as connection:
            ensure_document_version_schema(connection)
            ensure_contract_correspondence_schema(connection)
    return active


def data(**changes):
    return LetterData(**{"letter_date": "2026-10-02", "deadline_date": "2026-11-05",
        "deadline_basis": "Manuell vereinbarter Verwaltungstermin, keine Rechtsberechnung",
        "deadline_confirmed": True, "recipient_name": "Synthetic recipient", "recipient_address": "Synthetic street 1\nSynthetic city",
        "subject": "Synthetic local letter", "body": "Sehr geehrte {{tenant_name}},\n\nVertrag {{contract_number}}: Termin {{deadline_date}}.", **changes})


def create(box, key="create", actor="actor", **changes):
    payload = CreateLetter(idempotency_key=key, expected_contract_etag=contract_lifecycle.contract_etag(box.store.get_contract(box.contract.id)), data=data(**changes))
    return service.create_draft(box.store, box.contract.id, payload, actor), payload


def command(row, key="review", **changes):
    return RevisionCommand(**{"idempotency_key": key, "expected_revision": row["revision"],
        "expected_contract_etag": row["source_contract_etag"], **changes})


def prepare(box, **changes):
    found, _ = create(box, **changes)
    return service.review_draft(box.store, box.contract.id, found["id"], command(found, "review-" + found["id"]), "actor")


def approval(row, key=None):
    return ApproveLetter(**command(row, key or "approve-" + row["id"]).model_dump(), confirmed=True, reviewed_hash=row["review_hash"])


def approved(box, **changes):
    found = prepare(box, **changes)
    return service.approve_draft(box.store, box.contract.id, found["id"], approval(found), "actor")


def event_payload(row, key="dispatch", **changes):
    return ManualEvent(**{"idempotency_key": key, "expected_revision": row["revision"], "expected_event_revision": 0,
        "kind": "dispatched", "event_date": "2026-10-02", "channel": "post", "reference": "Synthetic tracking record",
        "note": "Manuell beobachtet, keine Zustellgarantie", "confirmed": True, **changes})


def rows(box, model):
    if box.db is not None:
        box.db.expire_all()
        return list(box.db.scalars(select(model)))
    return list(box.store.__dict__.get(model.__tablename__, {}).values())


def test_local_approval_preserves_contract_and_cash_and_archives_identical_review_bytes(letter):
    before = letter.store.get_contract(letter.contract.id).model_dump(mode="json")
    found = prepare(letter)
    preview, sha = service.review_pdf(letter.store, letter.contract.id, found["id"], "actor")
    assert preview.startswith(b"%PDF-") and hashlib.sha256(preview).hexdigest() == sha
    payload = approval(found)
    published = service.approve_draft(letter.store, letter.contract.id, found["id"], payload, "actor")
    assert published["state"] == "approved" and published["document_version_id"]
    assert service.approve_draft(letter.store, letter.contract.id, found["id"], payload, "actor") == published
    assert letter.store.get_contract(letter.contract.id).model_dump(mode="json") == before
    assert letter.store.list_payments() == []
    compiled, _ = service.prepare_download(letter.store, letter.contract.id, found["id"], "readonly")
    try:
        assert compiled.path.read_bytes() == preview
        assert compiled.manifest["sha256"] == sha
    finally:
        compiled.close()
    assert service.read_pdf_for_key(letter.store, "contract-correspondence/" + found["id"] + ".pdf", "readonly") == preview
    assert service.deadline_projection(letter.store, letter.contract.id, "readonly")["items"][0]["date"] == "2026-11-05"
    if letter.engine:
        with letter.engine.connect() as connection:
            assert validate_correspondence_journal(connection)


def test_private_drafts_are_not_shared_but_approved_history_is_readonly_visible(letter):
    found, payload = create(letter)
    assert service.create_draft(letter.store, letter.contract.id, payload, "actor") == found
    assert service.listing(letter.store, letter.contract.id, "other")["items"] == []
    with pytest.raises(HTTPException) as failure:
        service.get_draft(letter.store, letter.contract.id, found["id"], "other")
    assert failure.value.status_code == 404
    with pytest.raises(HTTPException) as failure:
        service.create_draft(letter.store, letter.contract.id, payload, "readonly")
    assert failure.value.status_code == 403
    reviewed = service.review_draft(letter.store, letter.contract.id, found["id"], command(found), "actor")
    published = service.approve_draft(letter.store, letter.contract.id, found["id"], approval(reviewed), "actor")
    assert service.listing(letter.store, letter.contract.id, "readonly", history=True)["items"][0]["id"] == published["id"]
    with pytest.raises(Exception):
        service.get_draft(letter.store, letter.contract.id, found["id"], "foreign")


def test_approved_letter_requires_review_after_changed_tenant_and_preserves_old_receipt(letter):
    found = prepare(letter)
    old_revision = found["revision"]
    letter.store.update_tenant(letter.tenant.id, TenantCreate(full_name="Synthetic renamed tenant"))
    with pytest.raises(HTTPException) as failure:
        service.approve_draft(letter.store, letter.contract.id, found["id"], approval(found), "actor")
    assert failure.value.status_code == 409
    assert rows(letter, CorrespondenceDraftORM)[0].revision == old_revision
    updated = service.review_draft(letter.store, letter.contract.id, found["id"], command(found, "rereview"), "actor")
    assert updated["review_hash"] != found["review_hash"]
    published = service.approve_draft(letter.store, letter.contract.id, found["id"], approval(updated), "actor")
    sent = service.record_event(letter.store, letter.contract.id, found["id"], event_payload(published), "other")
    letter.store._patch_entity("contract", letter.contract.id, ContractPatch(contract_number="Synthetic changed number"))
    with pytest.raises(HTTPException) as failure:
        service.record_event(letter.store, letter.contract.id, found["id"], event_payload(published, "new-dispatch", expected_event_revision=1), "actor")
    assert failure.value.status_code == 409
    received = service.record_event(letter.store, letter.contract.id, found["id"], event_payload(published, "receipt", expected_event_revision=1,
        kind="received", dispatch_event_id=sent["event"]["id"], event_date="2026-10-03"), "actor")
    assert received["event"]["data"]["kind"] == "received"
    assert service.record_event(letter.store, letter.contract.id, found["id"], event_payload(published), "other") == sent


@pytest.mark.parametrize("failure_point", ["chunks", "journal", "role"])
def test_late_failure_publishes_no_document_version_or_command_and_exact_retry_succeeds(letter, monkeypatch, failure_point):
    found = prepare(letter)
    payload = approval(found)
    original_record, original_insert = service.record, document_versions._add
    if failure_point == "chunks":
        def insert(store, db, value):
            original_insert(store, db, value)
            if value.__tablename__ == "document_version_chunks":
                raise RuntimeError("Synthetic late chunk failure")
        monkeypatch.setattr(document_versions, "_add", insert)
    else:
        def record(*args, **kwargs):
            result = original_record(*args, **kwargs)
            if args[4] == "approve":
                if failure_point == "role":
                    letter.users["actor"]["role"] = "readonly"
                else:
                    raise RuntimeError("Synthetic late command failure")
            return result
        monkeypatch.setattr(service, "record", record)
    with pytest.raises((RuntimeError, HTTPException)):
        service.approve_draft(letter.store, letter.contract.id, found["id"], payload, "actor")
    assert letter.store.list_documents() == []
    assert rows(letter, CorrespondenceDraftORM)[0].state == "reviewed"
    assert len(rows(letter, CorrespondenceCommandORM)) == 2
    from backend.db.document_version_models import DocumentVersionORM
    assert rows(letter, DocumentVersionORM) == []
    monkeypatch.setattr(service, "record", original_record)
    monkeypatch.setattr(document_versions, "_add", original_insert)
    letter.users["actor"]["role"] = "verwalter"
    assert service.approve_draft(letter.store, letter.contract.id, found["id"], payload, "actor")["state"] == "approved"


def test_parallel_exact_approval_and_competing_manual_events_are_atomic(letter):
    found = prepare(letter)
    barrier = Barrier(2)
    def approve():
        barrier.wait()
        return service.approve_draft(letter.store, letter.contract.id, found["id"], approval(found), "actor")
    with ThreadPoolExecutor(max_workers=2) as executor:
        a, b = [future.result(timeout=20) for future in [executor.submit(approve), executor.submit(approve)]]
    assert a == b and len(letter.store.list_documents()) == 1
    barrier = Barrier(2)
    def observe(key):
        barrier.wait()
        try:
            return service.record_event(letter.store, letter.contract.id, a["id"], event_payload(a, key), "actor")
        except HTTPException as error:
            return error.status_code
    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = [future.result(timeout=20) for future in [executor.submit(observe, "event-a"), executor.submit(observe, "event-b")]]
    assert sum(isinstance(value, dict) for value in outcomes) == 1 and 409 in outcomes
    assert len(rows(letter, CorrespondenceEventORM)) == 1


def test_retention_guards_do_not_delete_and_stale_edits_do_not_erase_review(letter):
    found = prepare(letter)
    with pytest.raises(ValidationError):
        service.guard_delete_link(letter.store, "tenants", letter.tenant.id)
    with pytest.raises(ValidationError):
        service.guard_destructive_reset(letter.store)
    service.guard_delete_link(letter.store, "contracts", "unrelated")
    payload = EditLetter(**command(found, "edit").model_dump(), data=data(subject="Changed synthetic subject"))
    edited = service.edit_draft(letter.store, letter.contract.id, found["id"], payload, "actor")
    assert edited["state"] == "draft" and edited["review"] is None
    assert service.edit_draft(letter.store, letter.contract.id, found["id"], payload, "actor") == edited
    with pytest.raises(HTTPException):
        service.review_draft(letter.store, letter.contract.id, found["id"], command(found, "stale-review"), "actor")
    assert rows(letter, CorrespondenceDraftORM)[0].revision == edited["revision"]


def test_offline_validator_rejects_missing_commands_and_corrupt_approved_pdf(letter):
    if letter.engine is None:
        pytest.skip("Offline SQL journal corruption fixture")
    found = approved(letter)
    with letter.engine.connect() as connection:
        assert validate_correspondence_journal(connection)
    with letter.engine.begin() as connection:
        connection.exec_driver_sql("DROP TRIGGER immo_contract_correspondence_commands_delete")
        connection.exec_driver_sql("DELETE FROM contract_correspondence_commands WHERE operation='approve'")
    with letter.engine.connect() as connection, pytest.raises(EvidenceError):
        validate_correspondence_journal(connection)
    assert service.get_draft(letter.store, letter.contract.id, found["id"], "actor")["state"] == "approved"


@pytest.mark.parametrize("changes", [{"deadline_confirmed": False}, {"body": "{{tenant.__class__}}"}, {"body": "{{unknown}}"}])
def test_invalid_confirmation_or_unknown_placeholders_are_not_approved(letter, changes):
    if changes.get("deadline_confirmed") is False:
        with pytest.raises(ValueError):
            data(**changes)
    else:
        found, _ = create(letter, **changes)
        with pytest.raises(ValidationError):
            service.review_draft(letter.store, letter.contract.id, found["id"], command(found), "actor")
        assert rows(letter, CorrespondenceDraftORM)[0].state == "draft"
