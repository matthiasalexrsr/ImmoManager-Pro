"""Untrusted model output can become only an explicitly reviewed private draft."""

from copy import deepcopy
from typing import Any
from uuid import uuid4

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from backend import auth
from backend.dependencies import store
from backend.models import PropertyCreate, UnitCreate
from backend.services import assistant_context as context
from backend.services import assistant_proposals as proposals
from backend.services import document_versions, workspace
from backend.tests.test_assistant_context import document
from backend.tests.test_assistant_context import estate as estate


def suggestion(estate, kind="task", **values):
    bundle = context.build_context(store, {"property_ids": [estate.prop.id]}, estate.user.id)
    source = bundle["sources"][0]
    return {"kind": kind, "anchor": {"kind": "property", "id": estate.prop.id},
            "evidence": [{key: source[key] for key in ("kind", "id", "revision", "sha256")}],
            "values": values or {"title": "Fläche anhand der Akte prüfen", "property_id": estate.prop.id}}, bundle


def test_task_preview_and_handoff_save_only_private_draft_with_retry(estate):
    proposal, bundle = suggestion(estate)
    review = proposals.validate_proposal(store, proposal, estate.user.id, context_bundle=bundle)
    identifier, key = str(uuid4()), str(uuid4())
    first = proposals.handoff_proposal(store, proposal, estate.user.id, draft_id=identifier,
                                       idempotency_key=key, review_hash=review["review_hash"], context_bundle=bundle)
    assert first["draft"]["values"]["title"] == proposal["values"]["title"]
    assert first["draft"]["anchor"] == proposal["anchor"]
    assert first["draft_revision"] == 1 and not first["domain_writes"]
    assert store.list_tasks() == []
    again = proposals.handoff_proposal(store, proposal, estate.user.id, draft_id=identifier,
                                       idempotency_key=key, review_hash=review["review_hash"], context_bundle=bundle)
    assert again == first
    other = auth.register_user("other", "other@example.test", "Other", "Secret123", "eigentuemer")
    with pytest.raises(HTTPException) as private:
        workspace.get_record(store, other.id, "drafts", identifier)
    assert private.value.status_code == 404


@pytest.mark.parametrize("mutation", [
    {"kind": "shell", "values": {"command": "anything"}},
    {"values": {"title": "Test", "callback_url": "https://example.test"}},
    {"values": {"title": "Test", "status": "completed"}},
    {"values": {"title": "Test", "assignee": "someone"}},
    {"values": {"title": " "}},
])
def test_nonwhitelisted_actions_fields_and_confirmation_are_rejected(estate, mutation):
    proposal, bundle = suggestion(estate)
    proposal.update(mutation)
    with pytest.raises(ValidationError):
        proposals.validate_proposal(store, proposal, estate.user.id, context_bundle=bundle)


def test_evidence_cannot_expand_original_context_even_for_accessible_ids(estate):
    proposal, bundle = suggestion(estate)
    extra = context.build_context(store, {"property_ids": [estate.foreign.id]}, estate.user.id)["sources"][0]
    proposal["evidence"].append({key: extra[key] for key in ("kind", "id", "revision", "sha256")})
    with pytest.raises(HTTPException) as unselected:
        proposals.validate_proposal(store, proposal, estate.user.id, context_bundle=bundle)
    assert unselected.value.status_code == 422


def test_modified_values_after_review_do_not_save_a_draft(estate):
    proposal, bundle = suggestion(estate)
    review = proposals.validate_proposal(store, proposal, estate.user.id, context_bundle=bundle)
    proposal["values"]["title"] = "Ungeprüfte Änderung"
    with pytest.raises(HTTPException) as changed:
        proposals.handoff_proposal(store, proposal, estate.user.id, draft_id=str(uuid4()),
                                   idempotency_key=str(uuid4()), review_hash=review["review_hash"], context_bundle=bundle)
    assert changed.value.status_code == 409
    assert workspace.list_records(store, estate.user.id, "drafts")["items"] == []


def test_changed_evidence_and_revoked_write_role_fail_before_handoff(estate):
    proposal, bundle = suggestion(estate)
    reviewer = auth.register_user("reviewer", "reviewer@example.test", "Reviewer", "Secret123", "verwalter")
    review = proposals.validate_proposal(store, proposal, reviewer.id, context_bundle=bundle)
    auth.update_user(reviewer.id, {"role": "readonly"})
    with pytest.raises(HTTPException) as denied:
        proposals.handoff_proposal(store, proposal, reviewer.id, draft_id=str(uuid4()), idempotency_key=str(uuid4()),
                                   review_hash=review["review_hash"], context_bundle=bundle)
    assert denied.value.status_code == 403
    store.update_property(estate.prop.id, PropertyCreate(portfolio_id=estate.north.id, name="Neue Quelle", property_type="residential"))
    with pytest.raises(HTTPException) as stale:
        proposals.validate_proposal(store, proposal, estate.user.id)
    assert stale.value.status_code == 409


def test_note_uses_existing_note_form_without_sending_or_recording_a_conversation(estate):
    proposal, bundle = suggestion(estate, kind="note", body="Offene Unterlagen am Original prüfen.")
    review = proposals.validate_proposal(store, proposal, estate.user.id, context_bundle=bundle)
    result = proposals.handoff_proposal(store, proposal, estate.user.id, draft_id=str(uuid4()),
                                        idempotency_key=str(uuid4()), review_hash=review["review_hash"], context_bundle=bundle)
    assert result["context"] == "conversation-note"
    assert result["draft"]["values"] == {"body": proposal["values"]["body"], "conversation_kind": "note"}
    assert store.list_tasks() == []


def test_invoice_requires_document_and_exact_decimal_arithmetic_and_preserves_evidence(estate):
    row, _ = document(estate)
    bundle = context.build_context(store, {"property_ids": [estate.prop.id], "document_ids": [row.id]}, estate.user.id)
    proposal: dict[str, Any] = {"kind": "invoice", "anchor": {"kind": "property", "id": estate.prop.id},
                "evidence": [{key: source[key] for key in ("kind", "id", "revision", "sha256")} for source in bundle["sources"]],
                "values": {"supplier": "Original prüfen", "invoice_date": "2026-10-18", "net_amount": "0.30",
                           "vat_amount": "0.06", "gross_amount": "0.36", "property_id": estate.prop.id}}
    review = proposals.validate_proposal(store, proposal, estate.user.id, context_bundle=bundle)
    assert review["normalized"]["values"]["gross_amount"] == "0.36"
    result = proposals.handoff_proposal(store, proposal, estate.user.id, draft_id=str(uuid4()),
                                        idempotency_key=str(uuid4()), review_hash=review["review_hash"], context_bundle=bundle)
    assert result["draft"]["values"]["gross_amount"] == "0.36"
    assert store.list_invoices() == [] and store.list_bookings() == []
    invalid = deepcopy(proposal)
    invalid["values"]["gross_amount"] = "0.31"
    with pytest.raises(ValidationError):
        proposals.validate_proposal(store, invalid, estate.user.id, context_bundle=bundle)
    invalid = deepcopy(proposal)
    invalid["evidence"] = [ref for ref in invalid["evidence"] if ref["kind"] != "document"]
    with pytest.raises(HTTPException) as no_original:
        proposals.validate_proposal(store, invalid, estate.user.id, context_bundle=bundle)
    assert no_original.value.status_code == 422


def test_references_and_unit_property_relationship_need_explicit_evidence(estate):
    proposal, bundle = suggestion(estate)
    proposal["values"]["unit_id"] = estate.unit.id
    with pytest.raises(HTTPException) as no_evidence:
        proposals.validate_proposal(store, proposal, estate.user.id, context_bundle=bundle)
    assert no_evidence.value.status_code == 422
    assert isinstance(no_evidence.value.detail, dict)
    assert no_evidence.value.detail["code"] == "assistant_reference_evidence_missing"
    assert no_evidence.value.detail["missing_kinds"] == ["unit"]


def test_unit_anchor_does_not_implicitly_attest_property(estate):
    # An actual model selected the unit as its anchor but omitted the separate
    # property evidence. This must remain blocked, with an actionable reason.
    bundle = context.build_context(store, {"property_ids": [estate.prop.id], "unit_ids": [estate.unit.id]}, estate.user.id)
    proposal = {"kind": "task", "anchor": {"kind": "unit", "id": estate.unit.id},
                "evidence": [{key: source[key] for key in ("kind", "id", "revision", "sha256")}
                             for source in bundle["sources"] if source["kind"] == "unit"],
                "values": {"title": "Prüfen", "property_id": estate.prop.id, "unit_id": estate.unit.id}}
    with pytest.raises(HTTPException) as missing:
        proposals.validate_proposal(store, proposal, estate.user.id, context_bundle=bundle)
    assert missing.value.status_code == 422
    assert isinstance(missing.value.detail, dict)
    assert missing.value.detail["missing_kinds"] == ["property"]
    assert "Immobilie" in missing.value.detail["message"]
    assert "korrigierten Vorschlag" in missing.value.detail["message"]
    proposal["evidence"] = [{key: source[key] for key in ("kind", "id", "revision", "sha256")}
                            for source in bundle["sources"]]
    assert proposals.validate_proposal(store, proposal, estate.user.id, context_bundle=bundle)["allowed"]


def test_secondary_source_changed_between_preview_and_write_is_blocked_in_preflight(estate, monkeypatch):
    bundle = context.build_context(store, {"property_ids": [estate.prop.id], "unit_ids": [estate.unit.id]}, estate.user.id)
    proposal = {"kind": "task", "anchor": {"kind": "property", "id": estate.prop.id},
                "evidence": [{key: source[key] for key in ("kind", "id", "revision", "sha256")} for source in bundle["sources"]],
                "values": {"title": "Fläche prüfen", "property_id": estate.prop.id, "unit_id": estate.unit.id}}
    review = proposals.validate_proposal(store, proposal, estate.user.id, context_bundle=bundle)
    original_mutate = workspace.mutate

    def racing_mutation(*args, **kwargs):
        store.update_unit(estate.unit.id, UnitCreate(property_id=estate.prop.id, label="Neue Quelle", unit_type="apartment"))
        return original_mutate(*args, **kwargs)

    monkeypatch.setattr(workspace, "mutate", racing_mutation)
    with pytest.raises(HTTPException) as changed:
        proposals.handoff_proposal(store, proposal, estate.user.id, draft_id=str(uuid4()), idempotency_key=str(uuid4()),
                                   review_hash=review["review_hash"], context_bundle=bundle)
    assert changed.value.status_code == 409
    assert workspace.list_records(store, estate.user.id, "drafts")["items"] == []


def test_handoff_participates_in_callers_atomic_unit_and_rolls_back(estate):
    proposal, bundle = suggestion(estate)
    review = proposals.validate_proposal(store, proposal, estate.user.id, context_bundle=bundle)
    identifier = str(uuid4())
    with pytest.raises(RuntimeError, match="decision failed"):
        with document_versions.work(store, estate.user.id, write_areas=("/workspace",)) as unit:
            result = proposals.handoff_proposal(unit.store, proposal, estate.user.id, draft_id=identifier,
                                                idempotency_key=str(uuid4()), review_hash=review["review_hash"],
                                                context_bundle=bundle, unit=unit)
            assert result["draft_id"] == identifier
            raise RuntimeError("decision failed")
    with pytest.raises(HTTPException) as missing:
        workspace.get_record(store, estate.user.id, "drafts", identifier)
    assert missing.value.status_code == 404
