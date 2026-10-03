"""Actual private draft endpoint and actual reviewed journal; synthetic only."""

import json
from copy import deepcopy

from backend import auth
from backend.services.portfolio_scope import scope_context
from backend.tests.form_draft_api_support import ENDPOINT
from backend.tests.test_billing_disputes import (
    BASE,
    archive_original,
    context,
    draft_http,
    finalized,
    opening,
    preview_confirm,
)

# The imported fixtures retain all three genuine application profiles.
__all__ = ["context", "draft_http"]


def envelope(context, command, *, case_id="", review=None, original=None, pending=False, revision=None, owner=None):
    active = context["active"]
    values = {"period_id": context["period"]["id"], "case_id": case_id,
              "command_json": json.dumps(command, ensure_ascii=False),
              "review_json": json.dumps(review, ensure_ascii=False) if review else ""}
    return {"owner_id": (owner or active.owner).id, "collection": "billing/disputes", "entity_id": None,
        "form_key": ("event:" + case_id if case_id else "open:" + context["period"]["id"]),
        "schema": "period_id:text|case_id:text|command_json:text|review_json:text",
        "values": values, "original_values": original or deepcopy(values), "submission_pending": pending,
        "expected_revision": revision}


def query(body):
    return {key: body[key] for key in ("owner_id", "collection", "form_key")}


def save(context, body, *, headers=None, expected=200):
    response = context["active"].client.put(ENDPOINT, headers=headers or context["headers"], json=body)
    assert response.status_code == expected, response.text
    assert response.headers["cache-control"] == "no-store"
    return response.json()


def restore(context, body, *, headers=None, expected=200):
    response = context["active"].client.get(ENDPOINT, headers=headers or context["headers"], params=query(body))
    assert response.status_code == expected, response.text
    assert response.headers["cache-control"] == "no-store"
    return response.json().get("draft")


def reviewed(context, command, case_id=""):
    response = context["active"].client.post(BASE + (f"/{case_id}/preview" if case_id else "/preview"),
        headers=context["headers"], json=command)
    assert response.status_code == 200, response.text
    review = response.json()
    return {**review["request"], "preview_hash": review["preview_hash"]}, review


def test_incomplete_scalar_envelope_encrypts_without_creating_case(context):
    statement = finalized(context)
    command = opening(context, statement, reason="", received_on="", statement_id=None,
                      expected_statement_revision=None, expected_snapshot_hash=None)
    body = envelope(context, command)
    before = context["active"].client.get(BASE, headers=context["headers"]).json()
    receipt = save(context, body)
    draft = restore(context, body)
    assert draft["revision"] == receipt["revision"] and draft["values"] == body["values"]
    assert draft["original_values"] == body["original_values"] and draft["edit_revision"] is None
    assert not draft["submission_pending"]
    raw = context["active"].snapshot()[0]
    assert raw["payload"].startswith("draft:v1:")
    assert "command_json" not in raw["payload"] and statement["id"] not in raw["payload"]
    assert context["active"].client.get(BASE, headers=context["headers"]).json() == before
    assert raw["collection"] == "billing/disputes" and raw["entity_id"] is None


def test_exact_pending_open_and_old_event_preview_restore_after_real_success(context, monkeypatch, tmp_path):
    statement = finalized(context)
    version = archive_original(context, monkeypatch, tmp_path)
    command, review = reviewed(context, opening(context, statement, evidence_version_ids=[version]))
    body = envelope(context, command, review=review, pending=True)
    save(context, body)
    response = context["active"].client.post(BASE, headers=context["headers"], json=command)
    assert response.status_code == 201, response.text
    receipt = response.json()
    restored = restore(context, body)
    assert restored["submission_pending"] and restored["values"] == body["values"]
    assert json.loads(restored["values"]["command_json"]) == command
    assert context["active"].client.post(BASE, headers=context["headers"], json=command).json() == receipt
    event = {"expected_revision": 1, "kind": "in_review", "observed_on": "2026-10-03",
        "reason": "Private synthetic reviewed event €", "idempotency_key": "draft-old-reviewed-event"}
    event_command, event_review = reviewed(context, event, receipt["case_id"])
    event_body = envelope(context, event_command, case_id=receipt["case_id"], review=event_review, pending=True)
    save(context, event_body)
    path = BASE + f"/{receipt['case_id']}/events"
    response = context["active"].client.post(path, headers=context["headers"], json=event_command)
    assert response.status_code == 200, response.text
    event_receipt = response.json()
    current = context["active"].client.get(BASE + "/" + receipt["case_id"], headers=context["headers"]).json()
    assert current["revision"] == 2 and current["state"] == "in_review"
    restored = restore(context, event_body)
    assert restored["submission_pending"] and restored["values"] == event_body["values"]
    assert json.loads(restored["values"]["command_json"])["expected_revision"] == 1
    assert context["active"].client.post(path, headers=context["headers"], json=event_command).json() == event_receipt
    assert "Private synthetic" not in "".join(row["payload"] for row in context["active"].snapshot())


def test_tab_cas_current_grants_and_owner_discard_keep_private_envelope(context):
    statement = finalized(context)
    active = context["active"]
    headers = active.headers(active.member)
    body = envelope(context, opening(context, statement, reason="Private synthetic input", received_on=""), owner=active.member)
    first = save(context, body, headers=headers)
    body["expected_revision"] = first["revision"]
    changed = deepcopy(body)
    value = json.loads(changed["values"]["command_json"])
    value["reason"] = "Newer tab retains this input"
    changed["values"]["command_json"] = json.dumps(value)
    second = save(context, changed, headers=headers)
    save(context, body, headers=headers, expected=409)
    assert restore(context, body, headers=headers)["values"] == changed["values"]
    # The account keeps a write role and another portfolio, so the owner's
    # explicit discard remains authorised despite lost old resource access.
    with scope_context(None):
        auth.update_user(active.member.id, {"portfolio_access": "selected", "portfolio_ids": [active.portfolios[1].id]}, actor_id=active.owner.id)
    restore(context, body, headers=headers, expected=403)
    response = active.client.delete(ENDPOINT, headers=headers,
        params={**query(body), "expected_revision": second["revision"]})
    assert response.status_code == 200 and response.json() == {"discarded": True}, response.text
    assert active.snapshot() == []


def test_nested_unknown_forged_review_original_refs_and_foreign_evidence_are_rejected(context, monkeypatch, tmp_path):
    statement = finalized(context)
    version = archive_original(context, monkeypatch, tmp_path)
    body = envelope(context, opening(context, statement, reason="", received_on=""))
    variations = []
    unknown = deepcopy(body)
    value = json.loads(unknown["values"]["command_json"])
    value["access_token"] = "synthetic forbidden field"
    unknown["values"]["command_json"] = json.dumps(value)
    variations.append(unknown)
    duplicate = deepcopy(body)
    duplicate["values"]["command_json"] = duplicate["values"]["command_json"][:-1] + ',"reason":"duplicate"}'
    variations.append(duplicate)
    wrong_original = deepcopy(body)
    original_command = json.loads(wrong_original["original_values"]["command_json"])
    original_command["period_id"] = "foreign-period"
    wrong_original["original_values"]["command_json"] = json.dumps(original_command)
    variations.append(wrong_original)
    for invalid in variations:
        save(context, invalid, expected=422)
    other = next(row for row in context["active"].client.get("/api/v1/billing/statements", headers=context["headers"]).json() if row["id"] != statement["id"])
    save(context, envelope(context, opening(context, other, evidence_version_ids=[version])), expected=404)
    command, review = reviewed(context, opening(context, statement))
    review["binding"]["original_snapshot"]["original_party"]["identity"]["full_name"] = "Invented original identity"
    save(context, envelope(context, command, review=review, pending=True), expected=422)
    save(context, envelope(context, command, pending=True), expected=422)
    assert context["active"].snapshot() == []
    assert context["active"].client.get(BASE, headers=context["headers"]).json()["items"] == []


def test_original_event_and_actual_correction_lineage_are_checked_even_before_review(context):
    statement = finalized(context)
    _command, receipt = preview_confirm(context, opening(context, statement))
    client, headers = context["active"].client, context["headers"]
    response = client.post(f"/api/v1/billing/periods/{statement['billing_period_id']}/revisions", headers=headers,
                           params={"revision_notes": "Synthetic explicit correction"})
    assert response.status_code == 200, response.text
    revised_id = response.json()["new_period_id"]
    assert client.post(f"/api/v1/billing/periods/{revised_id}/generate", headers=headers).status_code == 201
    assert client.post(f"/api/v1/billing/periods/{revised_id}/finalize", headers=headers).status_code == 200
    statements = client.get("/api/v1/billing/statements", headers=headers).json()
    correct = next(row for row in statements if row["billing_period_id"] == revised_id and row["contract_id"] == statement["contract_id"])
    other = next(row for row in statements if row["billing_period_id"] == revised_id and row["contract_id"] != statement["contract_id"])
    command = {"expected_revision": 1, "kind": "correction_link", "observed_on": "", "reason": "",
        "idempotency_key": "private-correction-ref", "correction_statement_id": other["id"]}
    save(context, envelope(context, command, case_id=receipt["case_id"]), expected=409)
    command["correction_statement_id"] = correct["id"]
    body = envelope(context, command, case_id=receipt["case_id"])
    saved = save(context, body)
    assert restore(context, body)["values"] == body["values"]
    command = {"expected_revision": 1, "kind": "correction", "observed_on": "", "reason": "",
        "idempotency_key": "private-event-ref", "corrects_event_id": "foreign-event"}
    save(context, envelope(context, command, case_id=receipt["case_id"], revision=saved["revision"]), expected=404)
    # Only the explicitly confirmed opening exists. Draft checks never append.
    assert client.get(BASE + f"/{receipt['case_id']}", headers=headers).json()["revision"] == 1
