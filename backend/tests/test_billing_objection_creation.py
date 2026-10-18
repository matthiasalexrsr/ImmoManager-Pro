"""Creation receipts prevent duplicate objections after an uncertain HTTP answer."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import date, timedelta
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from backend import auth
from backend.app import app
from backend.dependencies import store
from backend.models import BillingObjectionRejection
from backend.routers import billing
from backend.services import business_qol as commands
from backend.services.data_snapshot import export_snapshot
from backend.tests.test_billing_objection_rejection import issued_original, synthetic_isolated_store  # noqa: F401
from backend.tests.test_billing_objection_rejection_http import auth_headers, user


def test_lost_creation_answer_retries_exactly_one_objection_and_conflicts_on_changed_payload():
    period, originals = issued_original()
    actor = user("creation-owner")
    path = f"/api/v1/billing/periods/{period.id}/objections"
    payload = {"statement_id": originals[0].id, "reason": "Fläche laut Beleg abweichend",
               "received_on": "2026-10-18", "idempotency_key": "create-" + uuid4().hex}
    with TestClient(app) as client:
        first = client.post(path, json=payload, headers=auth_headers(actor))
        assert first.status_code == 201, first.text
        # The client may have lost this answer; send the same command again.
        replay = client.post(path, json=payload, headers=auth_headers(actor))
        assert replay.status_code == 201, replay.text
        assert replay.json() == first.json()
        assert len(store.list_billing_objections(period.id)) == 1
        for changes in ({"reason": "Jetzt andere Angaben"}, {"received_on": "2026-10-17"}, {"statement_id": originals[1].id}):
            changed = client.post(path, json={**payload, **changes}, headers=auth_headers(actor))
            assert changed.status_code == 409
        assert len(store.list_billing_objections(period.id)) == 1


def test_creation_receipt_survives_omitted_date_and_later_decision_without_reopening_period(monkeypatch):
    period, _ = issued_original()
    actor = user("creation-later-state")
    path = f"/api/v1/billing/periods/{period.id}/objections"
    payload = {"reason": "Nachträglich geprüfter Einwand", "idempotency_key": str(uuid4())}
    with TestClient(app) as client:
        first = client.post(path, json=payload, headers=auth_headers(actor))
        assert first.status_code == 201, first.text
        result = first.json()
        decision = BillingObjectionRejection(expected_revision=0,
            expected_source_sha256=billing._compute_snapshot_hash(period.id),
            rationale="Der Beleg bestätigt die ursprüngliche Verteilung", idempotency_key=str(uuid4()))
        billing.reject_issued_objection(result["id"], decision, actor.id)
        class Tomorrow(date):
            @classmethod
            def today(cls):
                return date.today() + timedelta(days=1)
        monkeypatch.setattr(billing, "date", Tomorrow)
        replay = client.post(path, json=payload, headers=auth_headers(actor))
        assert replay.status_code == 201, replay.text
        assert replay.json()["id"] == result["id"]
        assert replay.json()["received_on"] == result["received_on"]
        assert replay.json()["status"] == "rejected"
        assert store.get_billing_period(period.id).status == "delivered"
        assert len(store.list_billing_objections(period.id)) == 1


def test_creation_rolls_back_both_domain_and_journal_when_receipt_fails_after_insertion(monkeypatch):
    period, _ = issued_original()
    actor = user("creation-rollback")
    original_save = commands.save_command
    def fail_after_receipt(*args, **kwargs):
        original_save(*args, **kwargs)
        raise RuntimeError("synthetic creation receipt failure")
    monkeypatch.setattr(commands, "save_command", fail_after_receipt)
    before = export_snapshot(store)["business_qol_commands"]
    with TestClient(app) as client, pytest.raises(RuntimeError, match="synthetic creation receipt failure"):
        client.post(f"/api/v1/billing/periods/{period.id}/objections",
            json={"reason": "Einwand ohne verwaisten Beleg", "idempotency_key": str(uuid4())}, headers=auth_headers(actor))
    assert store.get_billing_period(period.id).status == "delivered"
    assert not store.list_billing_objections(period.id)
    assert export_snapshot(store)["business_qol_commands"] == before


def test_creation_rechecks_role_inside_write_after_dependency_has_already_authorized(monkeypatch):
    period, _ = issued_original()
    actor = user("creation-revoked")
    original_write = billing.billing_write
    @contextmanager
    def revoke_before_write(*args, **kwargs):
        auth.update_user(actor.id, {"role": "readonly"})
        with original_write(*args, **kwargs):
            yield
    monkeypatch.setattr(billing, "billing_write", revoke_before_write)
    with TestClient(app) as client:
        denied = client.post(f"/api/v1/billing/periods/{period.id}/objections",
            json={"reason": "Einwand mit entzogener Berechtigung", "idempotency_key": str(uuid4())}, headers=auth_headers(actor))
    assert denied.status_code == 403
    assert not store.list_billing_objections(period.id)


def test_creation_retry_rechecks_portfolio_grants_before_disclosing_receipt():
    period, originals = issued_original()
    portfolio_id = store.get_property(period.property_id).portfolio_id
    actor = user("creation-grants", role="verwalter", access="selected", portfolios=[portfolio_id])
    path = f"/api/v1/billing/periods/{period.id}/objections"
    payload = {"reason": "Einwand mit aktuellem Portfoliozugriff", "statement_id": originals[0].id,
               "idempotency_key": str(uuid4())}
    header = auth_headers(actor)
    with TestClient(app) as client:
        first = client.post(path, json=payload, headers=header)
        assert first.status_code == 201, first.text
        auth.update_user(actor.id, {"portfolio_access": "selected", "portfolio_ids": []})
        denied = client.post(path, json=payload, headers=header)
        assert denied.status_code in {403, 404}
        auth.update_user(actor.id, {"portfolio_access": "selected", "portfolio_ids": [portfolio_id]})
        replay = client.post(path, json=payload, headers=header)
        assert replay.status_code == 201, replay.text
        assert replay.json() == first.json()
        assert len(store.list_billing_objections(period.id)) == 1


def test_two_concurrent_requests_with_same_creation_key_create_one_objection():
    period, originals = issued_original()
    actor = user("creation-concurrent")
    path = f"/api/v1/billing/periods/{period.id}/objections"
    payload = {"reason": "Gleichzeitige Erfassungswiederholung", "statement_id": originals[0].id,
               "idempotency_key": str(uuid4())}
    with TestClient(app) as client, ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(lambda _n: client.post(path, json=payload, headers=auth_headers(actor)), range(2)))
    assert [response.status_code for response in responses] == [201, 201], [response.text for response in responses]
    assert responses[0].json() == responses[1].json()
    assert len(store.list_billing_objections(period.id)) == 1


def test_legacy_query_route_is_authorized_and_uses_the_same_optional_creation_receipt():
    period, _ = issued_original()
    actor = user("creation-query")
    header = auth_headers(actor)
    path = f"/api/v1/billing/periods/{period.id}/dispute"
    params = {"reason": "Legacy Einwand", "idempotency_key": str(uuid4())}
    with TestClient(app) as client:
        first = client.post(path, params=params, headers=header)
        second = client.post(path, params=params, headers=header)
        assert first.status_code == second.status_code == 200
        assert len(store.list_billing_objections(period.id)) == 1
        auth.update_user(actor.id, {"role": "readonly"})
        assert client.post(path, params=params, headers=header).status_code == 403
