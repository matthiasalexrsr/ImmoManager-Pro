"""Versioned sources, lifecycle staleness, preservation and source-gone bytes."""

import sqlite3
from contextlib import closing
from copy import deepcopy
from datetime import date
from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from backend.db.contract_correspondence_models import CorrespondenceCommandORM, CorrespondenceDraftORM
from backend.db.contract_wizard_models import ensure_contract_wizard_schema
from backend.models import ContractPatch
from backend.repositories.sql_store import SQLAlchemyStore
from backend.services import contract_correspondence as service
from backend.services import contract_lifecycle, contract_wizard
from backend.services.contract_correspondence_validation import EvidenceError, validate_correspondence_journal
from backend.services.contract_wizard_types import TemplateCreate
from backend.tests.test_contract_correspondence import approval, approved, command, create, event_payload, prepare
from backend.tests.test_contract_correspondence import letter as letter
from backend.tests.test_contract_lifecycle import active as active
from backend.tests.test_contract_lifecycle import confirmation
from backend.tests.test_contract_lifecycle import prepare as prepare_lifecycle


def test_existing_immutable_template_version_is_frozen_and_foreign_template_is_never_expanded(letter):
    if letter.engine:
        with letter.engine.begin() as connection:
            ensure_contract_wizard_schema(connection)
    else:
        letter.store.__dict__.setdefault("contract_template_versions", {})
    template = contract_wizard.create_template(letter.store, TemplateCreate(idempotency_key="template", portfolio_id=letter.p.id,
        title="Synthetic template", body="{{tenant_name}} / {{contract_number}} / {{deadline_date}}"), "actor")
    found = prepare(letter, body=None, template_id=template["id"])
    assert found["review"]["template"]["id"] == template["id"] and found["review"]["template"]["version"] == 1
    new = contract_wizard.create_template(letter.store, TemplateCreate(idempotency_key="template-2", portfolio_id=letter.p.id,
        title="Synthetic later version", body="Changed {{tenant_name}}", previous_id=template["id"]), "actor")
    assert new["version"] == 2
    result = service.approve_draft(letter.store, letter.contract.id, found["id"], approval(found), "actor")
    assert result["review"]["template"]["id"] == template["id"]
    foreign_id = letter.users["foreign"]["portfolio_ids"][0]
    foreign = contract_wizard.create_template(letter.store, TemplateCreate(idempotency_key="foreign-template", portfolio_id=foreign_id,
        title="Synthetic private foreign title", body="Synthetic foreign body"), "foreign")
    drafted, _ = create(letter, key="bad-template", body=None, template_id=foreign["id"])
    with pytest.raises(HTTPException) as failure:
        service.review_draft(letter.store, letter.contract.id, drafted["id"], command(drafted, "review-bad"), "actor")
    assert failure.value.status_code == 404 and "foreign body" not in str(failure.value.detail)
    if letter.engine:
        with letter.engine.connect() as connection:
            assert validate_correspondence_journal(connection)


def test_lifecycle_binding_is_exact_accepted_command_and_supersession_requires_new_dispatch_review(letter):
    pending = prepare_lifecycle(letter)
    accepted = contract_lifecycle.confirm_draft(letter.store, letter.contract.id, pending["id"], confirmation(pending), "actor")
    if letter.db:
        command_id = letter.db.connection().exec_driver_sql("SELECT id FROM contract_lifecycle_commands WHERE operation='confirm'").scalar_one()
        letter.db.rollback()
    else:
        command_id = next(value.id for value in letter.store.contract_lifecycle_commands.values() if value.operation == "confirm")
    found = approved(letter, lifecycle_command_id=command_id)
    assert found["review"]["lifecycle"]["draft_id"] == accepted["id"]
    assert service.get_draft(letter.store, letter.contract.id, found["id"], "readonly")["source_review_status"] == "current"
    # An explicitly reviewed correction, not a direct mutation or fake expiry.
    correction = prepare_lifecycle(letter, key="correction-create", termination_end_date="2026-11-20")
    contract_lifecycle.confirm_draft(letter.store, letter.contract.id, correction["id"], confirmation(correction, "correction-confirm"), "actor")
    current = service.get_draft(letter.store, letter.contract.id, found["id"], "readonly")
    assert current["source_review_status"] == "requires_review" and current["document_version_id"] == found["document_version_id"]
    with pytest.raises(HTTPException) as failure:
        service.record_event(letter.store, letter.contract.id, found["id"], event_payload(found), "actor")
    assert failure.value.status_code == 409
    if letter.engine:
        with letter.engine.connect() as connection:
            assert validate_correspondence_journal(connection)


def test_manual_receipt_cannot_link_another_letter_or_precede_its_dispatch(letter):
    first = approved(letter)
    second = approved(letter, key="create-second")
    sent = service.record_event(letter.store, letter.contract.id, first["id"], event_payload(first), "actor")
    with pytest.raises(Exception):
        service.record_event(letter.store, letter.contract.id, second["id"], event_payload(second, "bad-receipt", kind="received", dispatch_event_id=sent["event"]["id"]), "actor")
    assert service.events(letter.store, letter.contract.id, second["id"], "readonly")["items"] == []
    with pytest.raises(Exception):
        service.record_event(letter.store, letter.contract.id, first["id"], event_payload(first, "early-receipt", expected_event_revision=1,
            kind="received", dispatch_event_id=sent["event"]["id"], event_date="2026-10-01"), "actor")
    assert service.events(letter.store, letter.contract.id, first["id"], "readonly")["event_revision"] == 1


def test_due_projection_is_scoped_bounded_and_marks_stale_management_dates(letter):
    first = approved(letter)
    assert service.due_deadlines(letter.store, "readonly", date(2026, 11, 4))["items"] == []
    page = service.due_deadlines(letter.store, "readonly", date(2026, 11, 5), limit=1)
    assert page["items"][0]["id"] == first["id"] and page["items"][0]["policy"] == "user_confirmed_management_date"
    assert set(page["items"][0]).isdisjoint({"recipient_address", "rendered_body", "data"})
    assert service.due_deadlines(letter.store, "foreign", date(2026, 11, 5))["items"] == []
    letter.store._patch_entity("contract", letter.contract.id, ContractPatch(contract_number="Synthetic renamed"))
    assert service.due_deadlines(letter.store, "readonly", date(2026, 11, 5))["items"][0]["source_review_status"] == "requires_review"


def test_owned_sqlite_snapshot_source_gone_retains_exact_original_and_manual_history(letter, tmp_path):
    if not letter.engine:
        pytest.skip("Actual owned SQLite source-gone copy")
    found = approved(letter)
    sent = service.record_event(letter.store, letter.contract.id, found["id"], event_payload(found), "actor")
    content = service.read_pdf_for_key(letter.store, "contract-correspondence/" + found["id"] + ".pdf", "readonly")
    source = Path(letter.engine.url.database).resolve()
    assert source.parent == tmp_path.resolve() and source.name == "lifecycle.db"
    target = tmp_path / "restored-owned.sqlite"
    with closing(sqlite3.connect(source)) as before, closing(sqlite3.connect(target)) as after:
        before.backup(after)
        assert validate_correspondence_journal(after)
    letter.db.close()
    letter.engine.dispose()
    source.unlink()
    assert not source.exists()
    engine = create_engine("sqlite:///" + target.as_posix())
    try:
        with Session(engine) as db:
            store = SQLAlchemyStore(db)
            assert service.read_pdf_for_key(store, "contract-correspondence/" + found["id"] + ".pdf", "readonly") == content
            assert service.events(store, letter.contract.id, found["id"], "readonly")["items"][0]["id"] == sent["event"]["id"]
            compiled, _ = service.prepare_download(store, letter.contract.id, found["id"], "readonly", parent=tmp_path)
            owned = compiled.path.parent
            assert compiled.path.read_bytes() == content
            compiled.close()
            assert not owned.exists()
    finally:
        engine.dispose()


def test_offline_pre_revision_all_absent_is_legacy_but_partial_is_invalid(tmp_path):
    with closing(sqlite3.connect(tmp_path / "owned-legacy.sqlite")) as db:
        assert validate_correspondence_journal(db) is False
        db.execute("CREATE TABLE contract_correspondence_events(id TEXT)")
        with pytest.raises(EvidenceError, match="Incomplete"):
            validate_correspondence_journal(db)


def test_corrupt_foreign_journal_tail_fails_before_history_event_or_download_and_exposes_no_bytes(letter):
    found = approved(letter)
    foreign = letter.users["foreign"]["portfolio_ids"][0]
    if letter.engine:
        with letter.engine.begin() as connection:
            connection.exec_driver_sql("DROP TRIGGER immo_contract_correspondence_drafts_update")
            connection.execute(CorrespondenceDraftORM.__table__.update().where(CorrespondenceDraftORM.id == found["id"]).values(portfolio_id=foreign))
    else:
        letter.store.contract_correspondence_drafts[found["id"]].portfolio_id = foreign
    for operation in (lambda: service.listing(letter.store, letter.contract.id, "actor", history=True),
            lambda: service.prepare_download(letter.store, letter.contract.id, found["id"], "actor"),
            lambda: service.record_event(letter.store, letter.contract.id, found["id"], event_payload(found), "actor")):
        with pytest.raises(HTTPException) as failure:
            operation()
        assert failure.value.status_code == 503
        assert "Synthetic" not in str(failure.value.detail)
    if letter.engine:
        with letter.engine.connect() as connection:
            assert connection.scalar(select(CorrespondenceDraftORM.state).where(CorrespondenceDraftORM.id == found["id"])) == "approved"


def test_approved_original_remains_available_after_renderer_update_but_private_preview_requires_new_review(letter, monkeypatch):
    original = approved(letter)
    private = prepare(letter, key="new-private")
    monkeypatch.setattr(service, "render_pdf", lambda _review: b"%PDF-synthetic-new-renderer")
    compiled, _ = service.prepare_download(letter.store, letter.contract.id, original["id"], "readonly")
    try:
        assert compiled.manifest["sha256"] == original["review"]["pdf_sha256"]
        assert compiled.path.read_bytes() != b"%PDF-synthetic-new-renderer"
    finally:
        compiled.close()
    assert service.get_draft(letter.store, letter.contract.id, original["id"], "readonly")["source_review_status"] == "current"
    with pytest.raises(HTTPException) as failure:
        service.review_pdf(letter.store, letter.contract.id, private["id"], "actor")
    assert failure.value.status_code == 409


def corrupt_event_reply(letter, found, payload):
    original = service.record_event(letter.store, letter.contract.id, found["id"], payload, "actor")
    result = deepcopy(original)
    result["event"]["data"]["note"] = "Synthetic contradictory replay note"
    if letter.engine:
        with letter.engine.begin() as connection:
            connection.exec_driver_sql("DROP TRIGGER immo_contract_correspondence_commands_update")
            connection.execute(CorrespondenceCommandORM.__table__.update().where(
                CorrespondenceCommandORM.command_key == payload.idempotency_key).values(result=result))
    else:
        saved = next(value for value in letter.store.contract_correspondence_commands.values()
            if value.command_key == payload.idempotency_key)
        saved.result = result
    return original


def test_corrupt_manual_command_reply_is_not_replayed_as_a_successful_contradictory_observation(letter):
    found = approved(letter)
    payload = event_payload(found)
    original = corrupt_event_reply(letter, found, payload)
    with pytest.raises(HTTPException) as failure:
        service.record_event(letter.store, letter.contract.id, found["id"], payload, "actor")
    assert failure.value.status_code == 503 and "Synthetic" not in str(failure.value.detail)
    assert service.events(letter.store, letter.contract.id, found["id"], "readonly")["items"] == [original["event"]]


def test_offline_manual_command_response_must_equal_the_actual_immutable_event(letter):
    if not letter.engine:
        pytest.skip("Actual SQLite offline journal verification")
    found = approved(letter)
    corrupt_event_reply(letter, found, event_payload(found))
    with letter.engine.connect() as connection, pytest.raises(EvidenceError):
        validate_correspondence_journal(connection)


def corrupt_approval_reply(letter, found, payload):
    result = deepcopy(found)
    result["document_id"] = "synthetic-nonexistent-document"
    result["download_url"] = "/documents/synthetic-nonexistent-document/versions/" + result["document_version_id"] + "/download"
    if letter.engine:
        with letter.engine.begin() as connection:
            connection.exec_driver_sql("DROP TRIGGER immo_contract_correspondence_commands_update")
            connection.execute(CorrespondenceCommandORM.__table__.update().where(
                CorrespondenceCommandORM.command_key == payload.idempotency_key).values(result=result))
    else:
        saved = next(value for value in letter.store.contract_correspondence_commands.values()
            if value.command_key == payload.idempotency_key)
        saved.result = result


def test_approval_replay_cannot_point_to_a_different_document_than_the_immutable_approved_letter(letter):
    reviewed = prepare(letter)
    payload = approval(reviewed)
    found = service.approve_draft(letter.store, letter.contract.id, reviewed["id"], payload, "actor")
    corrupt_approval_reply(letter, found, payload)
    with pytest.raises(HTTPException) as failure:
        service.approve_draft(letter.store, letter.contract.id, found["id"], payload, "actor")
    assert failure.value.status_code == 503
    assert service.get_draft(letter.store, letter.contract.id, found["id"], "readonly")["document_id"] == found["document_id"]


def test_offline_approval_response_must_point_to_the_actual_approved_document(letter):
    if not letter.engine:
        pytest.skip("Actual SQLite offline journal verification")
    reviewed = prepare(letter)
    payload = approval(reviewed)
    found = service.approve_draft(letter.store, letter.contract.id, reviewed["id"], payload, "actor")
    corrupt_approval_reply(letter, found, payload)
    with letter.engine.connect() as connection, pytest.raises(EvidenceError):
        validate_correspondence_journal(connection)


@pytest.mark.parametrize("state", ["reviewed", "approved"])
def test_offline_current_review_or_approval_cannot_survive_a_missing_exact_review_command(letter, state):
    if not letter.engine:
        pytest.skip("Actual SQLite offline review-chain verification")
    found = prepare(letter)
    if state == "approved":
        found = service.approve_draft(letter.store, letter.contract.id, found["id"], approval(found), "actor")
    with letter.engine.begin() as connection:
        assert validate_correspondence_journal(connection)
        connection.exec_driver_sql("DROP TRIGGER immo_contract_correspondence_commands_delete")
        connection.execute(CorrespondenceCommandORM.__table__.delete().where(
            CorrespondenceCommandORM.draft_id == found["id"], CorrespondenceCommandORM.operation == "review"))
    with letter.engine.connect() as connection, pytest.raises(EvidenceError, match="review history"):
        validate_correspondence_journal(connection)
