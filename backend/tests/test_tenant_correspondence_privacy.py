"""Actual approved originals, private work exclusion and exact tenant evidence."""

import base64
import hashlib
import json
from copy import deepcopy

import pytest
from fastapi import HTTPException
from sqlalchemy import event

from backend.db.contract_correspondence_models import (
    CORRESPONDENCE_MODELS,
    CorrespondenceCommandORM,
    CorrespondenceDraftORM,
    CorrespondenceEventORM,
)
from backend.models import ContractCreate, ContractPatch, TenantCreate
from backend.services import contract_correspondence as service
from backend.services import contract_lifecycle as lifecycle
from backend.services import tenant_correspondence_graph
from backend.services.contract_correspondence_types import EditLetter
from backend.services.portfolio_scope import scope_context, scope_from_user
from backend.services.tenant_data_graph import TenantExportError
from backend.services.tenant_privacy import (
    PrivacyConflict,
    anonymize_tenant_profile,
    export_tenant_metadata,
    prepare_tenant_export,
    preview_tenant_anonymization,
)
from backend.tests import test_contract_correspondence as fixtures
from backend.tests import test_contract_lifecycle as lifecycle_fixtures
from backend.tests.test_contract_lifecycle import active as active

letter = fixtures.letter


def checksum(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
        allow_nan=False, separators=(",", ":")).encode("utf-8")).hexdigest()


def inactive(box):
    box.store._patch_entity("contract", box.contract.id, ContractPatch(status="draft"))


def graph(box):
    with scope_context(scope_from_user(box.users["actor"])):
        return export_tenant_metadata(box.store, box.tenant.id)


def snapshot(box):
    return {model.__tablename__: [{column.name: deepcopy(getattr(row, column.name)) for column in model.__table__.columns}
        for row in sorted(fixtures.rows(box, model), key=lambda value: value.id)] for model in CORRESPONDENCE_MODELS}


def test_approved_current_text_exact_receipts_and_opaque_private_history(letter):
    old, _ = fixtures.create(letter, body="PRIVATE_OLD_BODY_293", recipient_name="PRIVATE_OLD_RECIPIENT_623")
    edited = service.edit_draft(letter.store, letter.contract.id, old["id"],
        EditLetter(**fixtures.command(old, "edit-public").model_dump(), data=fixtures.data()), "actor")
    reviewed = service.review_draft(letter.store, letter.contract.id, old["id"], fixtures.command(edited), "actor")
    approved = service.approve_draft(letter.store, letter.contract.id, old["id"], fixtures.approval(reviewed), "actor")
    observed = service.record_event(letter.store, letter.contract.id, old["id"], fixtures.event_payload(approved), "other")
    private, _ = fixtures.create(letter, key="other-private", actor="other", body="PRIVATE_OTHER_BODY_927",
        recipient_name="PRIVATE_OTHER_RECIPIENT_428")
    statements = []
    if letter.engine:
        def recorded(_connection, _cursor, sql, _parameters, context, _many):
            if "contract_correspondence" in sql:
                columns = getattr(getattr(context.compiled, "statement", None), "selected_columns", ())
                statements.append((sql, context.execution_options, {value.key for value in columns}))
        event.listen(letter.engine, "before_cursor_execute", recorded)
    result = graph(letter)
    assert result["schema_version"] == "tenant-data-graph/6"
    assert [row["id"] for row in result["contract_correspondence_drafts"]] == [approved["id"]]
    assert {row["operation"] for row in result["contract_correspondence_commands"]} == {"approve", "event"}
    assert result["contract_correspondence_events"][0]["data"] == observed["event"]["data"]
    assert result["scope"]["private_correspondence_drafts"]["count"] == 1
    assert result["scope"]["private_correspondence_drafts"]["contents_exported"] is False
    encoded = json.dumps(result, ensure_ascii=False)
    for secret in ("PRIVATE_OLD_BODY_293", "PRIVATE_OLD_RECIPIENT_623", "PRIVATE_OTHER_BODY_927",
                   "PRIVATE_OTHER_RECIPIENT_428", private["id"]):
        assert secret not in encoded
    for name in tenant_correspondence_graph.PERSONAL_FIELDS:
        for row in result[name]:
            assert row["source_sha256"] == checksum({key: value for key, value in row.items() if key != "source_sha256"})
    scope = result["scope"]["contract_correspondence"]
    assert scope["delivery_policy"] == "manual_observation_only"
    assert scope["command_proofs"][0]["review"]["revision"] == reviewed["revision"]
    assert scope["source_sha256"] == checksum([result["contract_correspondence_drafts"], result["contract_correspondence_commands"],
        result["contract_correspondence_events"], result["scope"]["private_correspondence_drafts"], scope["command_proofs"]])
    if letter.engine:
        private_selects = [sql for sql, _, _columns in statements if sql.startswith("SELECT contract_correspondence_drafts.id, contract_correspondence_drafts.revision")]
        assert private_selects and all(".data" not in sql and "actor_id" not in sql and ".review," not in sql for sql in private_selects)
        assert any(options.get("yield_per") == 100 for _, options, _columns in statements)
        proof_selects = [columns for sql, _options, columns in statements if 'AS review_revision' in sql]
        assert proof_selects and all(columns == {"id", "draft_id", "actor_id", "operation", "command_key",
            "request_hash", "review_revision", "review_hash"} for columns in proof_selects)


def test_download_includes_exact_archived_original_once_and_preserves_payload_hash(letter, tmp_path):
    published = fixtures.approved(letter)
    native, _ = service.prepare_download(letter.store, letter.contract.id, published["id"], "actor")
    try:
        original = native.path.read_bytes()
    finally:
        native.close()
    with scope_context(scope_from_user(letter.users["actor"])):
        compiled, _ = prepare_tenant_export(letter.store, letter.tenant.id, parent=tmp_path)
    try:
        raw = compiled.path.read_bytes()
        result = json.loads(raw)
        original_versions = [value for value in result["document_versions"] if value["id"] == published["document_version_id"]]
        assert len(original_versions) == 1
        version = original_versions[0]
        blocks = next(value["blocks"] for value in result["document_version_contents"]
            if value["id"] == "document-version:" + version["id"])
        restored = b"".join(base64.b64decode(value["data_base64"], validate=True) for value in blocks)
        assert restored == original and original.startswith(b"%PDF-")
        assert hashlib.sha256(restored).hexdigest() == version["sha256"]
        assert hashlib.sha256(raw).hexdigest() == compiled.manifest["sha256"]
    finally:
        compiled.close()


def test_profile_anonymization_preserves_all_original_approved_and_private_evidence(letter):
    inactive(letter)
    published = fixtures.approved(letter)
    service.record_event(letter.store, letter.contract.id, published["id"], fixtures.event_payload(published), "other")
    fixtures.create(letter, key="retained-private", actor="other", body="PRIVATE_RETAINED_BODY_232")
    original = snapshot(letter)
    with scope_context(scope_from_user(letter.users["actor"])):
        before = export_tenant_metadata(letter.store, letter.tenant.id)
        plan = preview_tenant_anonymization(letter.store, letter.tenant.id)
        assert plan["can_anonymize"] and plan["correspondence_note"]
        assert plan["retained_personal_evidence"]["private_correspondence_drafts"]["contents_exported"] is False
        result = anonymize_tenant_profile(letter.store, letter.tenant.id,
            plan_hash=plan["plan_hash"], confirm_tenant_id=letter.tenant.id)
        after = export_tenant_metadata(letter.store, letter.tenant.id)
    assert result["status"] == "profile_anonymized" and result["correspondence_note"]
    assert snapshot(letter) == original
    for name in tenant_correspondence_graph.PERSONAL_FIELDS:
        assert before[name] == after[name]
    assert before["document_versions"] == after["document_versions"]
    assert "Synthetic tenant" in json.dumps(after["contract_correspondence_drafts"])
    assert "PRIVATE_RETAINED_BODY_232" not in json.dumps(after)


def test_changed_private_revision_aborts_anonymization_without_exposing_body(letter):
    inactive(letter)
    private, _ = fixtures.create(letter, key="private", actor="other", body="PRIVATE_INITIAL_392")
    with scope_context(scope_from_user(letter.users["actor"])):
        plan = preview_tenant_anonymization(letter.store, letter.tenant.id)
    service.edit_draft(letter.store, letter.contract.id, private["id"], EditLetter(
        **fixtures.command(private, "private-edit").model_dump(), data=fixtures.data(body="PRIVATE_CHANGED_823")), "other")
    with scope_context(scope_from_user(letter.users["actor"])):
        with pytest.raises(PrivacyConflict):
            anonymize_tenant_profile(letter.store, letter.tenant.id, plan_hash=plan["plan_hash"], confirm_tenant_id=letter.tenant.id)
    assert letter.store.get_tenant(letter.tenant.id).full_name == "Synthetic tenant"
    assert "PRIVATE_CHANGED_823" not in json.dumps(graph(letter))


def test_same_property_unrelated_tenant_cannot_obtain_letter_or_observation(letter):
    published = fixtures.approved(letter, recipient_name="EXACT_SUBJECT_RECIPIENT_644")
    service.record_event(letter.store, letter.contract.id, published["id"],
        fixtures.event_payload(published, note="EXACT_SUBJECT_OBSERVATION_762"), "other")
    other = letter.store.create_tenant(TenantCreate(full_name="Unrelated same property tenant"))
    letter.store.create_contract(ContractCreate(contract_number="Unrelated same property contract", tenant_id=other.id,
        property_id=letter.property.id, unit_id=letter.unit.id, start_date="2027-01-01", status="draft"))
    result = export_tenant_metadata(letter.store, other.id)
    assert not result["contract_correspondence_drafts"] and not result["contract_correspondence_events"]
    assert not result["contract_correspondence_commands"] and not result["document_versions"]
    assert "EXACT_SUBJECT_RECIPIENT_644" not in json.dumps(result) and "EXACT_SUBJECT_OBSERVATION_762" not in json.dumps(result)


@pytest.mark.parametrize("kind", ["hidden_portfolio", "foreign_actor", "missing_create", "missing_review", "missing_approve",
                                  "approval_document", "event_response", "private_child_portfolio"])
def test_corrupt_subject_evidence_cannot_be_filtered_or_exported_partially(letter, kind):
    published = fixtures.approved(letter)
    service.record_event(letter.store, letter.contract.id, published["id"], fixtures.event_payload(published), "other")
    private, _ = fixtures.create(letter, key="private", actor="other")
    models = {kind: CorrespondenceDraftORM} if kind == "hidden_portfolio" else {kind: CorrespondenceCommandORM}
    selected = next(row for row in fixtures.rows(letter, models[kind]) if (
        row.id == published["id"] if kind == "hidden_portfolio" else row.operation == (
        "create" if kind == "missing_create" else "review" if kind == "missing_review" else "event" if kind == "event_response"
        else "create" if kind == "private_child_portfolio" else "approve") and
        row.draft_id == (private["id"] if kind == "private_child_portfolio" else published["id"])))
    values = {}
    if kind in {"hidden_portfolio", "private_child_portfolio"}:
        values["portfolio_id"] = next(value.id for value in letter.store.list_portfolios() if value.id != letter.p.id)
    elif kind == "foreign_actor":
        values["actor_id"] = "foreign"
    elif kind in {"approval_document", "event_response"}:
        altered = deepcopy(selected.result)
        if kind == "approval_document":
            altered["document_id"] = "contradictory-original-id"
        else:
            altered["event"]["data"]["note"] = "CONTRADICTORY_REPLY_382"
        values["result"] = altered
    if letter.db is None:
        if kind.startswith("missing_"):
            del letter.store.__dict__[selected.__tablename__][selected.id]
        else:
            for key, value in values.items():
                setattr(selected, key, value)
    else:
        identifier, table = selected.id, selected.__table__
        letter.db.rollback()
        with letter.engine.begin() as connection:
            triggers = connection.exec_driver_sql("SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name IN ('contract_correspondence_drafts','contract_correspondence_commands')").fetchall()
            for name, in triggers:
                connection.exec_driver_sql('DROP TRIGGER "' + name.replace('"', '""') + '"')
            statement = table.delete().where(table.c.id == identifier) if kind.startswith("missing_") else table.update().where(table.c.id == identifier).values(**values)
            connection.execute(statement)
        letter.db.expire_all()
    with pytest.raises(TenantExportError):
        graph(letter)
    assert letter.store.get_tenant(letter.tenant.id).full_name == "Synthetic tenant"


def test_grant_revocation_cleans_staged_download_before_publication(letter, monkeypatch, tmp_path):
    fixtures.approved(letter)
    original = tenant_correspondence_graph.append_correspondence_graph
    def revoked(store, result):
        found = original(store, result)
        letter.users["actor"]["portfolio_ids"] = []
        return found
    monkeypatch.setattr(tenant_correspondence_graph, "append_correspondence_graph", revoked)
    with scope_context(scope_from_user(letter.users["actor"])):
        with pytest.raises(HTTPException) as failure:
            prepare_tenant_export(letter.store, letter.tenant.id, parent=tmp_path)
    assert failure.value.status_code == 403
    assert not list(tmp_path.rglob("tenant-export.json"))


def test_observation_history_exceeds_one_batch_without_truncation(letter):
    published = fixtures.approved(letter)
    identifiers = []
    for number in range(101):
        receipt = service.record_event(letter.store, letter.contract.id, published["id"],
            fixtures.event_payload(published, "dispatch-" + str(number), expected_event_revision=number, reference="Synthetic observation " + str(number)), "other")
        identifiers.append(receipt["event"]["id"])
    result = graph(letter)
    assert {row["id"] for row in result["contract_correspondence_events"]} == set(identifiers)
    assert len(result["contract_correspondence_commands"]) == 102
    assert len(result["scope"]["contract_correspondence"]["command_proofs"]) == 1


def test_original_linked_lifecycle_receipt_survives_legitimate_supersession(letter):
    original, _ = lifecycle_fixtures.create(letter, key="original-termination", reason="ACCEPTED_OLD_REASON_823")
    reviewed = lifecycle.review_draft(letter.store, letter.contract.id, original["id"],
        lifecycle_fixtures.command(original, "old-review"), "actor")
    pending = lifecycle.confirm_draft(letter.store, letter.contract.id, original["id"],
        lifecycle_fixtures.confirmation(reviewed, "old-confirm"), "actor")
    from backend.db.contract_lifecycle_models import ContractLifecycleCommandORM
    command_id = next(value.id for value in fixtures.rows(letter, ContractLifecycleCommandORM) if value.operation == "confirm")
    published = fixtures.approved(letter, lifecycle_command_id=command_id)
    replacement, _ = lifecycle_fixtures.create(letter, key="replacement", termination_end_date="2026-11-15")
    replacement_review = lifecycle.review_draft(letter.store, letter.contract.id, replacement["id"],
        lifecycle_fixtures.command(replacement, "replacement-review"), "actor")
    lifecycle.confirm_draft(letter.store, letter.contract.id, replacement["id"],
        lifecycle_fixtures.confirmation(replacement_review, "replacement-confirm"), "actor")
    result = graph(letter)
    assert result["contract_correspondence_drafts"][0]["review"]["lifecycle"]["command_id"] == command_id
    assert result["contract_correspondence_drafts"][0]["review"]["lifecycle"]["current_state"] == "pending_effective"
    old_draft = next(value for value in result["contract_lifecycle_drafts"] if value["id"] == original["id"])
    old_command = next(value for value in result["contract_lifecycle_commands"] if value["id"] == command_id)
    assert old_draft["state"] == "superseded" and old_command["result"] == pending
    assert result["contract_correspondence_drafts"][0]["document_version_id"] == published["document_version_id"]


def test_memory_snapshot_comparison_detects_changes_to_both_journals(letter):
    if letter.db is not None:
        pytest.skip("Memory detached comparison; SQL uses transactional journal locks")
    from backend.services.tenant_privacy import _memory_copy, _memory_state
    published = fixtures.approved(letter)
    service.record_event(letter.store, letter.contract.id, published["id"], fixtures.event_payload(published), "other")
    copied = _memory_copy(letter.store)
    before = _memory_state(copied.__dict__)
    for model, field in ((CorrespondenceDraftORM, "data"), (CorrespondenceCommandORM, "result"), (CorrespondenceEventORM, "data")):
        row = next(iter(copied.__dict__[model.__tablename__].values()))
        saved = deepcopy(getattr(row, field))
        setattr(row, field, {**saved, "changed_snapshot": True})
        assert _memory_state(copied.__dict__) != before
        setattr(row, field, saved)
        assert _memory_state(copied.__dict__) == before
