"""Public authenticated rejection gate; no fictional completed deliveries."""
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from backend import auth
from backend.app import app
from backend.dependencies import store
from backend.models import BillingObjectionRequest
from backend.routers import billing
from backend.tests.test_billing_objection_rejection import issued_original, synthetic_isolated_store  # noqa: F401


@pytest.fixture(autouse=True)
def no_live_sessions():
    auth.clear_users()
    yield
    auth.clear_users()


def auth_headers(user):
    return {"Authorization": f"Bearer {auth.create_access_token(user.id)}"}


def user(name, *, role="eigentuemer", portfolios=(), access="all"):
    return auth.register_user(name + "-" + uuid4().hex[:8], f"{uuid4().hex}@example.test",
                              "Synthetic reviewer", "SyntheticPass123!", role,
                              portfolio_access=access, portfolio_ids=list(portfolios))


def test_http_owner_can_reject_once_with_same_idempotency_key_and_without_changing_originals():
    period, originals = issued_original()
    objection = billing._record_objection(period.id, BillingObjectionRequest(
        statement_id=originals[0].id,
        reason="Künstlicher ursprünglicher Einwand, der unverändert bleiben muss"))
    owner = user("owner")
    denied = user("viewer", role="readonly")
    payload = {"rationale": "Prüfung ergab denselben belegten Verteilungsschlüssel",
               "expected_revision": 0, "expected_source_sha256": billing._compute_snapshot_hash(period.id), "idempotency_key": "synthetic-reject-" + uuid4().hex}
    path = "/api/v1/billing/objections/" + objection.id + "/reject"
    with TestClient(app) as client:
        outsider = client.post(path, json=payload, headers=auth_headers(denied))
        assert outsider.status_code == 403
        invalid = client.post(path, json={**payload, "rationale": "zu kurz"}, headers=auth_headers(owner))
        assert invalid.status_code == 422
        accepted = client.post(path, json=payload, headers=auth_headers(owner))
        assert accepted.status_code == 200, accepted.text
        response = accepted.json()
        assert response["status"] == "rejected"
        assert response["reason"] == objection.reason
        assert response["decision_reason"] == payload["rationale"]
        assert response["decision_revision"] == 1
        assert response["decision_actor_id"] == owner.id
        assert response["decided_at"].endswith("Z")
        replay = client.post(path, json=payload, headers=auth_headers(owner))
        assert replay.status_code == 200
        assert replay.json() == response
        changed = client.post(path, json={**payload, "idempotency_key": "other-" + uuid4().hex},
                              headers=auth_headers(owner))
        assert changed.status_code == 409
        assert store.get_billing_period(period.id).status == "delivered"
        after = {s.id: s.model_dump() for s in store.list_utility_statements()}
        assert after[originals[0].id]["final_document"] == originals[0].final_document
        assert after[originals[1].id]["snapshot_hash"] == originals[1].snapshot_hash


def test_http_preview_and_revision_require_current_role_and_portfolio_grants():
    period, originals = issued_original()
    objection = billing._record_objection(period.id, BillingObjectionRequest(
        statement_id=originals[0].id, reason="Synthetischer Einwand zur Verteilung"))
    portfolio_id = store.get_property(period.property_id).portfolio_id
    manager = user("selected-manager", role="verwalter", portfolios=[portfolio_id], access="selected")
    path = "/api/v1/billing/objections/" + objection.id
    header = auth_headers(manager)
    before = {row.id: row.model_dump() for row in originals}
    with TestClient(app) as client:
        preview = client.get(path + "/decision-preview", headers=header)
        assert preview.status_code == 200, preview.text
        payload = {"rationale": "Die belegte Fläche wird in einer eigenen Korrektur geprüft",
                   "expected_revision": preview.json()["objection"]["decision_revision"],
                   "expected_source_sha256": preview.json()["source_sha256"],
                   "idempotency_key": "synthetic-revise-" + uuid4().hex}
        # The same issued token loses its portfolio immediately, also for replay.
        auth.update_user(manager.id, {"portfolio_access": "selected", "portfolio_ids": []})
        denied = client.post(path + "/revise", json=payload, headers=header)
        assert denied.status_code in {403, 404}
        assert store.get_billing_objection(objection.id).status == "open"
        auth.update_user(manager.id, {"portfolio_access": "selected", "portfolio_ids": [portfolio_id]})
        accepted = client.post(path + "/revise", json=payload, headers=header)
        assert accepted.status_code == 200, accepted.text
        result = accepted.json()
        assert result["status"] == "correction" and result["decision_actor_id"] == manager.id
        assert result["correction_period_id"] and result["decided_at"]
        replay = client.post(path + "/revise", json=payload, headers=header)
        assert replay.status_code == 200 and replay.json() == result
        auth.update_user(manager.id, {"role": "readonly"})
        revoked = client.post(path + "/revise", json=payload, headers=header)
        assert revoked.status_code == 403
        assert {row.id: row.model_dump() for row in billing._period_statements(period.id)} == before


def test_http_invalid_creation_and_stale_source_are_rejected_without_writes():
    period, originals = issued_original()
    owner = user("owner")
    header = auth_headers(owner)
    with TestClient(app) as client:
        path = f"/api/v1/billing/periods/{period.id}/objections"
        invalid = client.post(path, json={"reason": "   "}, headers=header)
        assert invalid.status_code == 422
        assert not store.list_billing_objections(period.id)
        created = client.post(path, json={"reason": "Fläche wird bestritten", "statement_id": originals[0].id,
                                         "received_on": "2026-10-17"}, headers=header)
        assert created.status_code == 201
        objection_id = created.json()["id"]
        rejected = client.post(f"/api/v1/billing/objections/{objection_id}/reject", json={
            "rationale": "Belege sind vollständig und bestätigen die Fläche", "expected_revision": 0,
            "expected_source_sha256": "0" * 64, "idempotency_key": "stale-http-" + uuid4().hex,
        }, headers=header)
        assert rejected.status_code == 409
        assert store.get_billing_objection(objection_id).status == "open"
