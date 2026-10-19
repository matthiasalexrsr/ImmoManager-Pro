"""Evidence-bound findings use the existing reviewed draft and task boundaries."""
from copy import deepcopy
from typing import Any

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from backend import auth
from backend.app import app
from backend.assistant_models import ProposalApply, ProposalPreview, RevisionCommand
from backend.dependencies import store
from backend.models import PortfolioCreate, PropertyCreate, TaskCreate, UnitCreate
from backend.services import assistant, assistant_context, assistant_findings as findings, assistant_runner, workspace
from backend.services import assistant_storage as db
from backend.tests.test_assistant_workspace import (
    clean, command, conversation, fake_execute, isolated_assistant, submit,
)


@pytest.fixture
def owner():
    # Creating a private chat does not grant task-write rights. Use an explicit
    # owner for the positive path and downgrade that account in denial tests.
    return auth.register_user("finding-owner", "finding@example.test", "Prüfer", "Secret123", "eigentuemer")


@pytest.fixture
def estate():
    portfolio = store.create_portfolio(PortfolioCreate(name="Prüfbestand"))
    house = store.create_property(PropertyCreate(portfolio_id=portfolio.id, name="Prüfhaus", property_type="residential"))
    unit = store.create_unit(UnitCreate(property_id=house.id, label="Wohnung ohne Fläche", unit_type="residential"))
    return house, unit


def checked_run(owner, estate):
    house, unit = estate
    queued = submit(owner, conversation(owner), context={"property_ids": [house.id], "unit_ids": [unit.id]})
    assistant_runner.run(store, queued["id"], owner.id, execute=fake_execute)
    run = assistant.get_run(store, owner.id, queued["id"])
    assert run["state"] == "completed", run
    finding = next(item for item in run["findings"] if item["code"] == "unit_area_missing")
    return run, finding


def prepare(owner, run, finding, payload=None):
    payload = payload or RevisionCommand(**command(expected_revision=run["revision"]))
    return findings.prepare_task(store, owner.id, run["id"], finding["id"], payload)


def rewrite_run(owner, run, *, state=None, **changes):
    with db.work(store, owner.id, write=True) as transaction:
        row = db.owned_child(transaction, assistant.Run, run["id"])
        data = db.payload(row)
        data.update(changes)
        db.put(transaction, assistant.Run, data, row=row, state=state)
    return assistant.get_run(store, owner.id, run["id"])


def assert_failure(status, action):
    with pytest.raises(HTTPException) as error:
        action()
    assert error.value.status_code == status, error.value.detail


def test_normalize_deduplicates_by_code_and_source_revision_without_mutating_inputs():
    evidence = {"kind": "unit", "id": "unit-1", "revision": "r1", "sha256": "a" * 64,
                "title": "Wohnung", "href": "/units/unit-1"}
    first: dict[str, Any] = {"id": "untrusted-provider-id", "code": "unit_area_missing", "message": "Fläche fehlt", "evidence": [evidence]}
    relabeled = deepcopy(first)
    relabeled.update(id="another-id", message="Fläche prüfen")
    relabeled["evidence"][0]["title"] = "Neue Quellenbeschriftung"
    changed = deepcopy(first)
    changed["evidence"][0]["revision"] = "r2"
    original = deepcopy([first, relabeled, changed])
    normalized = findings.normalize([first, relabeled, changed])
    assert [first, relabeled, changed] == original
    assert len(normalized) == 2
    assert normalized[0]["message"] == "Fläche prüfen"
    assert normalized[0]["id"] == findings.normalize([first])[0]["id"]
    assert normalized[0]["id"] != normalized[1]["id"]
    assert len(normalized[0]["id"]) == 64


def test_collected_includes_only_completed_tool_findings_and_deduplicates_local():
    def item(code):
        return {"code": code, "message": code, "evidence": []}
    local = item("local")
    data = {"local_findings": [local], "activity": [
        {"status": "completed", "findings": [local, item("completed")]},
        {"status": "running", "findings": [item("running")]},
        {"status": "failed", "findings": [item("failed")]},
        {"findings": [item("unknown")]},
    ]}
    assert [item["code"] for item in findings.collected(data)] == ["local", "completed"]


def test_prepare_creates_one_typed_proposal_and_no_task_or_draft(owner, estate):
    run, finding = checked_run(owner, estate)
    first_command = RevisionCommand(**command(expected_revision=run["revision"]))
    result = prepare(owner, run, finding, first_command)
    proposal = result["proposal"]
    payload = proposal["payload"]
    assert proposal["origin"] == "local_finding" and proposal["finding_id"] == finding["id"]
    assert proposal["state"] == "proposed" and proposal["decision"] is None
    assert payload["kind"] == "task"
    assert payload["anchor"] == {"kind": "unit", "id": estate[1].id}
    assert payload["values"]["unit_id"] == estate[1].id
    assert payload["values"]["property_id"] == estate[0].id
    assert payload["values"]["status"] == "open"
    assert finding["message"] in payload["values"]["description"]
    assert run["local_checks"]["as_of"] in payload["values"]["description"]
    assert {(source["kind"], source["id"]) for source in payload["evidence"]} == {
        ("property", estate[0].id), ("unit", estate[1].id)}
    assert result["run"]["revision"] == run["revision"] + 1
    assert [row["id"] for row in result["run"]["proposals"]] == [proposal["id"]]
    assert store.list_tasks() == []
    assert workspace.list_records(store, owner.id, "drafts")["items"] == []
    # Same-key retries and a second click with a fresh key both reuse the proposal,
    # even though the first click has advanced the run revision.
    assert prepare(owner, run, finding, first_command)["proposal"]["id"] == proposal["id"]
    second_command = RevisionCommand(**command(expected_revision=run["revision"]))
    assert prepare(owner, run, finding, second_command)["proposal"]["id"] == proposal["id"]
    assert len(assistant.list_records(store, owner.id, assistant.Proposal)["items"]) == 1
    assert assistant.get_run(store, owner.id, run["id"])["revision"] == result["run"]["revision"]
    assert_failure(409, lambda: prepare(owner, run, finding, first_command.model_copy(
        update={"expected_revision": result["run"]["revision"]})))


def test_prepare_preview_apply_and_explicit_task_save_through_http(owner, estate):
    run, finding = checked_run(owner, estate)
    client = TestClient(app, headers={"Authorization": "Bearer " + auth.create_access_token(owner.id)})
    prepared = client.post(f'/api/v1/assistant/runs/{run["id"]}/findings/{finding["id"]}/prepare-task',
                           json=command(expected_revision=run["revision"]))
    assert prepared.status_code == 200, prepared.text
    proposal = prepared.json()["proposal"]
    reviewed = client.post(f'/api/v1/assistant/proposals/{proposal["id"]}/preview',
                          json={"expected_revision": proposal["revision"]})
    assert reviewed.status_code == 200, reviewed.text
    review = reviewed.json()["review"]
    assert review["domain_writes"] is False and review["confirmation_required"] is True
    apply_body = command(expected_revision=proposal["revision"], review_hash=review["review_hash"])
    applied = client.post(f'/api/v1/assistant/proposals/{proposal["id"]}/apply', json=apply_body)
    assert applied.status_code == 200, applied.text
    handoff = applied.json()["handoff"]
    assert store.list_tasks() == []
    replayed = client.post(f'/api/v1/assistant/proposals/{proposal["id"]}/apply', json=apply_body)
    assert replayed.status_code == 200 and replayed.json()["handoff"]["draft_id"] == handoff["draft_id"]
    draft = client.get('/api/v1/workspace/drafts/' + handoff["draft_id"])
    assert draft.status_code == 200, draft.text
    assert draft.json()["values"] == handoff["values"]
    saved = client.post('/api/v1/tasks', json=draft.json()["values"])
    assert saved.status_code == 201, saved.text
    assert saved.json()["unit_id"] == estate[1].id
    assert len(store.list_tasks()) == 1


@pytest.mark.parametrize("state", ["queued", "running", "failed", "cancelled", "unknown", "blocked"])
def test_prepare_requires_a_completed_run(owner, estate, state):
    run, finding = checked_run(owner, estate)
    run = rewrite_run(owner, run, state=state)
    assert_failure(409, lambda: prepare(owner, run, finding))
    assert assistant.list_records(store, owner.id, assistant.Proposal)["items"] == []


def test_prepare_rejects_stale_run_revision_without_side_effects(owner, estate):
    run, finding = checked_run(owner, estate)
    assert_failure(409, lambda: prepare(owner, run, finding, RevisionCommand(**command(expected_revision=run["revision"] - 1))))
    assert assistant.list_records(store, owner.id, assistant.Proposal)["items"] == []
    assert assistant.get_run(store, owner.id, run["id"])["revision"] == run["revision"]


def test_prepare_rejects_changed_evidence(owner, estate):
    run, finding = checked_run(owner, estate)
    unit = estate[1]
    store.update_unit(unit.id, UnitCreate(**{**unit.model_dump(exclude={"id", "created_at", "updated_at"}), "area_sqm": 75}))
    assert_failure(409, lambda: prepare(owner, run, finding))
    assert assistant.list_records(store, owner.id, assistant.Proposal)["items"] == []


@pytest.mark.parametrize("field,replacement", [("revision", "obsolete-revision"), ("sha256", "0" * 64)])
def test_each_evidence_version_component_is_checked(owner, estate, field, replacement):
    run, finding = checked_run(owner, estate)
    finding = deepcopy(finding)
    finding["evidence"][0][field] = replacement
    run = rewrite_run(owner, run, local_findings=[finding])
    assert_failure(409, lambda: prepare(owner, run, run["findings"][0]))
    assert assistant.list_records(store, owner.id, assistant.Proposal)["items"] == []


def test_prepare_rejects_stale_analysis(owner, estate):
    run, finding = checked_run(owner, estate)
    run = rewrite_run(owner, run, verification_status="stale")
    assert_failure(409, lambda: prepare(owner, run, finding))


def test_prepare_rejects_unknown_and_unevidenced_findings(owner, estate):
    run, finding = checked_run(owner, estate)
    assert_failure(404, lambda: prepare(owner, run, {"id": "unknown-finding"}))
    run = rewrite_run(owner, run, local_findings=[{"code": "no_source", "message": "Unbelegt", "evidence": []}])
    assert_failure(404, lambda: prepare(owner, run, run["findings"][0]))


def test_readonly_user_and_revoked_write_rights_cannot_prepare_even_on_replay(owner, estate):
    run, finding = checked_run(owner, estate)
    auth.update_user(owner.id, {"role": "readonly"})
    assert_failure(403, lambda: prepare(owner, run, finding))
    auth.update_user(owner.id, {"role": "eigentuemer"})
    payload = RevisionCommand(**command(expected_revision=run["revision"]))
    prepared = prepare(owner, run, finding, payload)
    auth.update_user(owner.id, {"role": "readonly"})
    assert_failure(403, lambda: prepare(owner, run, finding, payload))
    assert_failure(403, lambda: prepare(owner, prepared["run"], finding))
    assert store.list_tasks() == []


def test_other_owner_cannot_prepare_private_finding(owner, estate):
    run, finding = checked_run(owner, estate)
    other = auth.register_user("other-finding-owner", "other-finding@example.test", "Andere", "Secret123", "eigentuemer")
    assert_failure(404, lambda: prepare(other, run, finding))


def test_existing_task_finding_cannot_duplicate_task(owner, estate):
    task = store.create_task(TaskCreate(title="Vorhandene Aufgabe", property_id=estate[0].id))
    queued = submit(owner, conversation(owner), context={"task_ids": [task.id]})
    assistant_runner.run(store, queued["id"], owner.id, execute=fake_execute)
    run = assistant.get_run(store, owner.id, queued["id"])
    finding = next(item for item in run["findings"] if item["code"] == "task_due_missing")
    assert_failure(422, lambda: prepare(owner, run, finding))
    assert len(store.list_tasks()) == 1
    assert assistant.list_records(store, owner.id, assistant.Proposal)["items"] == []


def test_existing_task_later_in_evidence_cannot_duplicate_task(owner, estate):
    run, _ = checked_run(owner, estate)
    task = store.create_task(TaskCreate(title="Vorhandene Prüfung", property_id=estate[0].id))
    sources = [assistant_context._source(store, kind, identifier, owner.id)
               for kind, identifier in (("property", estate[0].id), ("task", task.id))]
    candidate = {"code": "related_task_review", "message": "Vorhandene Aufgabe prüfen",
                 "evidence": [{key: source[key] for key in ("kind", "id", "revision", "sha256")}
                              for source in sources]}
    run = rewrite_run(owner, run, local_findings=[candidate])
    assert_failure(422, lambda: prepare(owner, run, run["findings"][0]))
    assert len(store.list_tasks()) == 1
    assert assistant.list_records(store, owner.id, assistant.Proposal)["items"] == []


def test_completed_discovery_findings_use_same_preparation_path(owner, estate):
    run, local = checked_run(owner, estate)
    discovery = {**local, "code": "discovered_unit_area_missing"}
    failed = {**local, "code": "failed_tool_hint"}
    run = rewrite_run(owner, run, local_findings=[], activity=[
        {"status": "completed", "findings": [discovery]},
        {"status": "failed", "findings": [failed]},
    ])
    assert [item["code"] for item in run["findings"]] == ["discovered_unit_area_missing"]
    proposal = prepare(owner, run, run["findings"][0])["proposal"]
    assert proposal["payload"]["anchor"] == {"kind": "unit", "id": estate[1].id}
    assert proposal["finding_id"] == run["findings"][0]["id"]
    assert store.list_tasks() == []


@pytest.mark.parametrize("stage", ["preview", "apply"])
def test_changed_source_cannot_be_handed_off_after_preparation(owner, estate, stage):
    run, finding = checked_run(owner, estate)
    proposal = prepare(owner, run, finding)["proposal"]
    preview = ProposalPreview(expected_revision=proposal["revision"])
    review = assistant.proposal_preview(store, owner.id, proposal["id"], preview)["review"]
    unit = estate[1]
    store.update_unit(unit.id, UnitCreate(**{**unit.model_dump(exclude={"id", "created_at", "updated_at"}), "area_sqm": 75}))
    if stage == "preview":
        action = lambda: assistant.proposal_preview(store, owner.id, proposal["id"], preview)
    else:
        body = ProposalApply(**command(expected_revision=proposal["revision"], review_hash=review["review_hash"]))
        action = lambda: assistant.decide_proposal(store, owner.id, proposal["id"], body)
    assert_failure(409, action)
    assert workspace.list_records(store, owner.id, "drafts")["items"] == []
    assert store.list_tasks() == []


def test_retry_discards_old_findings_actions_and_tool_proofs_but_preserves_history(owner, estate):
    run, local = checked_run(owner, estate)
    old_values = {
        "local_findings": [local],
        "local_checks": {"as_of": "2026-10-01", "scope": "previous_attempt"},
        "finding_proposals": {local["id"]: "previous-attempt-proposal"},
        "_tool_reports": {"old-report": {"hash": "old-report-hash"}},
        "_tool_results": {"old-result": {"text": "Old result"}},
        "_tool_timelines": {"old-timeline": {"hash": "old-timeline-hash"}},
        "_tool_investigations": {"old-investigation": {"hash": "old-investigation-hash"}},
        "activity": [{"status": "completed", "findings": [{**local, "code": "old_discovery"}]}],
        "tool_calls": [{"id": "old-call"}],
    }
    failed = rewrite_run(owner, run, state="failed", **old_values)
    body = RevisionCommand(**command(expected_revision=failed["revision"]))
    retried = assistant.retry(store, owner.id, failed["id"], body)
    assert retried["id"] != failed["id"] and retried["retry_of"] == failed["id"]
    assert retried["state"] == "queued" and retried["verification_status"] == "pending"
    assert retried["findings"] == [] and retried["tool_budget"]["used"] == 0
    assert retried["activity"] == [] and retried["tool_calls"] == []
    assert retried["proposals"] == []
    with db.work(store, owner.id) as transaction:
        fresh = db.payload(db.owned_child(transaction, assistant.Run, retried["id"]))
        previous = db.payload(db.owned_child(transaction, assistant.Run, failed["id"]))
    for key, value in old_values.items():
        assert previous[key] == value, key
        if key not in ("activity", "tool_calls"):
            assert not fresh.get(key), key
    assert assistant.get_run(store, owner.id, failed["id"])["findings"] == failed["findings"]
    assert assistant.retry(store, owner.id, failed["id"], body)["id"] == retried["id"]


@pytest.mark.parametrize("call_count", [0, 2, 67])
def test_run_list_retains_normalized_findings_and_tool_budget_after_reload(owner, estate, call_count):
    from backend.services.assistant_tools import MAX_CALLS

    run, local = checked_run(owner, estate)
    discovery = {**local, "id": "tool-specific-id", "code": "discovered_missing_area"}
    run = rewrite_run(owner, run, activity=[
        {"status": "completed", "findings": [local, discovery]},
        {"status": "failed", "findings": [{**local, "code": "failed_discovery"}]},
    ], tool_calls=[{"id": str(index)} for index in range(call_count)])
    listed = assistant.list_records(store, owner.id, assistant.Run, conversation_id=run["conversation_id"])
    summary = next(item for item in listed["items"] if item["id"] == run["id"])
    loaded = assistant.get_run(store, owner.id, run["id"])
    assert summary["findings"] == loaded["findings"]
    assert summary["tool_budget"] == loaded["tool_budget"]
    assert [item["code"] for item in summary["findings"]] == ["unit_area_missing", "discovered_missing_area"]
    assert summary["findings"][1]["id"] != "tool-specific-id"
    assert summary["tool_budget"] == {
        "used": min(call_count, MAX_CALLS), "limit": MAX_CALLS,
        "exhausted": call_count >= MAX_CALLS,
        "continuation": "followup" if call_count >= MAX_CALLS else None,
    }
