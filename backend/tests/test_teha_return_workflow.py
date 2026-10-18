"""Local export, source drift and evidenced follow-up payload; no live provider.

The shared fixture runs against memory or independent SQL sessions selected by
run_pro_matrix. No authenticated portal writes are implemented or exercised.
"""
import json
from datetime import date

import pytest
from fastapi import HTTPException

from backend import auth
from backend.db.orm_models import CostItemORM
from backend.models import AllocationKeyCreate, BillingPeriodCreate, CostItemCreate
from backend.services.providers.teha_evidence import portal_evidence
from backend.services.teha_types import (
    BatchDecision,
    FollowUpPreparation,
    FollowUpUserSource,
    MapItem,
    PrepareReturn,
    Stage,
    Target,
)
from backend.services.workspace_contexts import resolve_context
from backend.tests.test_teha_publication import confirmation, items, key, mapping, receive

pytest_plugins = ("backend.tests.test_teha_publication",)


def cost_draft(fx):
    period = fx.store.create_billing_period(BillingPeriodCreate(property_id=fx.prop.id, label="2026",
        start_date=date(2026, 1, 1), end_date=date(2026, 12, 31)))
    allocation = fx.store.create_allocation_key(AllocationKeyCreate(property_id=fx.prop.id, name="Fläche", key_type="area_sqm"))
    cost = fx.store.create_cost_item(CostItemCreate(billing_period_id=period.id, description="Quellkosten", amount=0.10, allocation_key_id=allocation.id))
    fx.store.create_cost_item(CostItemCreate(billing_period_id=period.id, description="Zweite Kosten", amount=0.20, allocation_key_id=allocation.id))
    _, batch = receive(fx, [{"kind": "period", "identity": {"object_id": 7, "period_number": 2},
        "title": "Periode", "raw": {"liegenschaftenNummer": "00017", "unknown": [None, {"deep": "ä"}]}}])
    item = items(fx, batch)[0]
    contexts = [resolve_context(fx.store, kind, identifier, fx.actor) for kind, identifier in (("property", fx.prop.id), ("billing_period", period.id))]
    fx.receive.map(fx.connection, item["id"], MapItem(idempotency_key=key(), mapping_revision=0, source_sha256=item["source_sha256"], confirm=True,
        targets=[Target(kind=ctx["kind"], id=ctx["entity_id"], revision=ctx["revision"]) for ctx in contexts]), fx.actor)
    command = PrepareReturn(idempotency_key=key(), kind="cost_user_data", mapping_revision=1,
        source=Target(kind="billing_period", id=period.id, revision=contexts[1]["revision"]), confirm=True)
    draft = fx.receive.prepare_return(fx.connection, item["id"], command, fx.actor)
    return draft, item, command, cost, batch


def order_source():
    return {"kind": "technical_order", "identity": {"termin_id": 41}, "title": "Techniktermin",
            "raw": {"auftragNummer": 501, "liegenschaftsnummer": "00017", "terminVon": "2026-10-20T09:00:00",
                    "terminBis": "2026-10-20T12:00:00", "unknown_order": True}}


def user_source(identifier=23, termin=41, **raw):
    return {"kind": "user", "identity": {"termin_id": termin, "user_id": identifier}, "title": "Empfangener Nutzer",
            "raw": {"id": identifier, "neId": 9, "lfdNr": "001", "bewohnerName": "Testperson", "anmeldeart": 2,
                    "kontaktdaten": "person@example.test", "zusatzinfos": "Anmeldehinweis", "erledigt": False,
                    "deleted": False, "unknown_user": {"future": [1, None]}, **raw}}


def order_draft_source(fx):
    _, batch = receive(fx, [order_source()])
    order = items(fx, batch)[0]
    mapping(fx, order)
    receipt = fx.receive.publish(fx.connection, order["id"], confirmation(fx, order), fx.actor)
    context = resolve_context(fx.store, "maintenance", receipt["project_id"], fx.actor)
    return order, Target(kind="maintenance", id=receipt["project_id"], revision=context["revision"])


def prepare_follow_up(fx, order, project, users, **changes):
    command = PrepareReturn(idempotency_key=key(), kind="maintenance_order", mapping_revision=1, source=project, confirm=True,
        follow_up=FollowUpPreparation(orderer_name="Testauftraggeber", orderer_email="auftrag@example.test",
            users=[FollowUpUserSource(item_id=user["id"], source_sha256=user["source_sha256"]) for user in users], **changes))
    return fx.receive.prepare_return(fx.connection, order["id"], command, fx.actor)


def exported(fx, draft):
    raw, filename = fx.receive.return_export(fx.connection, draft["id"], draft["snapshot_sha256"], fx.actor)
    assert filename == f"TEHA-Pruefpaket-{draft['id']}.json"
    return json.loads(raw)


def test_review_export_preserves_unknown_source_cent_total_and_observed_provenance(fx):
    draft, _, _, _, _ = cost_draft(fx)
    value = exported(fx, draft)
    assert value["snapshot_sha256"] == draft["snapshot_sha256"]
    assert value["snapshot"]["external_source"]["raw"]["unknown"] == [None, {"deep": "ä"}]
    assert value["validation"]["summary"]["total_decimal"] == "0.30"
    assert value["validation"]["local_valid"] is True
    assert value["portal_evidence"]["source_sha256"] == "328ac6c642b9892e7604ee67cf4e3c0d83b0b5f8700795561ec01b7b94bfa618"
    assert value["portal_evidence"]["catalogue_call_site_count"] == 78
    assert value["external_write_enabled"] is False
    assert value["snapshot"]["portal_contract"] is None
    assert fx.store.list_bookings() == []


def test_content_drift_without_timestamp_change_is_detected_and_packet_stays_frozen(fx):
    draft, item, command, cost, _ = cost_draft(fx)
    before = exported(fx, draft)["snapshot"]
    # Simulate an out-of-band data repair preserving updated_at. Comparing
    # only row IDs/timestamps would silently miss this changed amount.
    if fx.engine is None:
        fx.store.cost_items[cost.id] = cost.model_copy(update={"amount": 1.23})
    else:
        with fx.receive.work(fx.actor, write=True) as unit:
            unit.db.get(CostItemORM, cost.id).amount = 1.23
    after = exported(fx, draft)
    assert after["snapshot"] == before
    assert after["source_changed"] is True
    assert after["validation"]["local_valid"] is False
    assert "related_data_changed" in {issue["code"] for issue in after["validation"]["issues"]}
    assert fx.receive.prepare_return(fx.connection, item["id"], command, fx.actor)["replayed"] is True
    assert fx.receive.returns(fx.connection, fx.actor)["total"] == 1


def test_missing_local_source_is_recoverable_without_hiding_frozen_packet(fx, monkeypatch):
    draft, _, command, _, _ = cost_draft(fx)
    from backend.services import teha_receive
    original = teha_receive.resolve_context
    def missing(store, kind, identifier, actor, **kwargs):
        if kind == "billing_period" and identifier == command.source.id:
            raise HTTPException(404, "Synthetisch gelöschte Periode")
        return original(store, kind, identifier, actor, **kwargs)
    monkeypatch.setattr(teha_receive, "resolve_context", missing)
    value = exported(fx, draft)
    assert value["snapshot"]["source"]["entity_id"] == command.source.id
    assert "local_source_unavailable" in {issue["code"] for issue in value["validation"]["issues"]}
    assert fx.receive.returns(fx.connection, fx.actor)["total"] == 1


def test_revoked_receive_and_stale_download_hash_are_rejected_or_reported(fx):
    draft, _, _, _, batch = cost_draft(fx)
    fx.receive.decide_batch(fx.connection, batch["id"], BatchDecision(idempotency_key=key(), base_revision=batch["revision"],
        state="revoked", reason="Quelle widerrufen"), fx.actor)
    assert "receive_inactive" in {issue["code"] for issue in exported(fx, draft)["validation"]["issues"]}
    with pytest.raises(HTTPException) as error:
        fx.receive.return_export(fx.connection, draft["id"], "f" * 64, fx.actor)
    assert error.value.status_code == 409


def test_opening_existing_staged_run_does_not_restart_or_duplicate_items(fx):
    run, batch = receive(fx, [order_source()])
    reopened = fx.receive.stage(fx.connection, run["id"], Stage(idempotency_key=key(), run_revision=run["revision"]), fx.actor)
    assert reopened == batch
    assert len(items(fx, batch)) == 1


def test_follow_up_uses_order_number_and_exact_received_user_fields_without_network(fx, monkeypatch):
    order, project = order_draft_source(fx)
    _, batch = receive(fx, [user_source()])
    selected = items(fx, batch)
    monkeypatch.setattr(fx.provider, "run", lambda *args, **kwargs: pytest.fail("Preparing/exporting must not contact a provider"))
    draft = prepare_follow_up(fx, order, project, selected)
    value = exported(fx, draft)
    preview = value["snapshot"]["portal_preview"]
    assert preview["payload"] == {"Altauftrag": 501, "AuftraggeberName": "Testauftraggeber", "AuftraggeberMail": "auftrag@example.test",
        "Nutzer": [{"Id": 23, "BewohnerName": "Testperson", "Anmeldeart": 2, "Kontaktdaten": "person@example.test", "Zusatzinfos": "Anmeldehinweis"}]}
    assert preview["path"] == "/api/Auftrag/create-folgeauftrag"
    assert preview["runtime_verified"] is False
    assert preview["external_write_enabled"] is False
    assert preview["user_identity_binding"] == "not_verified_against_open_order_users"
    assert "follow_up_user_identity_unverified" in {note["code"] for note in value["validation"]["warnings"]}
    assert value["snapshot"]["follow_up_sources"][0]["source"]["raw"]["unknown_user"] == {"future": [1, None]}


@pytest.mark.parametrize("change,status", [({"erledigt": True}, 422), ({"deleted": True}, 422),
    ({"bewohnerName": ""}, 422), ({"kontaktdaten": "invalid-email"}, 422), ({"anmeldeart": 4}, 422)])
def test_invalid_received_follow_up_user_does_not_create_a_draft(fx, change, status):
    order, project = order_draft_source(fx)
    _, batch = receive(fx, [user_source(**change)])
    with pytest.raises(HTTPException) as error:
        prepare_follow_up(fx, order, project, items(fx, batch))
    assert error.value.status_code == status
    assert fx.receive.returns(fx.connection, fx.actor)["total"] == 0


def test_follow_up_user_must_belong_to_same_termin_and_latest_source(fx):
    order, project = order_draft_source(fx)
    _, batch = receive(fx, [user_source(termin=42)])
    with pytest.raises(HTTPException) as error:
        prepare_follow_up(fx, order, project, items(fx, batch))
    assert error.value.status_code == 409
    _, first = receive(fx, [user_source()])
    stale = items(fx, first)
    draft = prepare_follow_up(fx, order, project, stale)
    receive(fx, [user_source(bewohnerName="Neuer Quellname")])
    with pytest.raises(HTTPException) as error:
        prepare_follow_up(fx, order, project, stale)
    assert error.value.status_code == 409
    assert exported(fx, draft)["source_changed"] is True


def test_follow_up_supports_251_received_users_with_paged_selection(fx):
    order, project = order_draft_source(fx)
    run, batch = receive(fx, [user_source(identifier=identifier) for identifier in range(1, 252)])
    batch = fx.receive.stage(fx.connection, run["id"], Stage(idempotency_key=key(), run_revision=run["revision"],
        batch_revision=batch["revision"]), fx.actor)
    one = fx.receive.follow_up_users(fx.connection, order["id"], fx.actor, limit=250)
    two = fx.receive.follow_up_users(fx.connection, order["id"], fx.actor, cursor=one["next_cursor"], limit=250)
    assert len(one["items"]) == 250 and len(two["items"]) == 1
    selected = [{"id": entry["id"], "source_sha256": entry["source_sha256"]} for entry in one["items"] + two["items"]]
    draft = prepare_follow_up(fx, order, project, selected)
    assert len(exported(fx, draft)["snapshot"]["portal_preview"]["payload"]["Nutzer"]) == 251


def test_portfolio_withdrawal_prevents_frozen_resident_export(fx):
    draft, _, _, _, _ = cost_draft(fx)
    auth.update_user(fx.actor, {"role": "verwalter", "portfolio_access": "selected", "portfolio_ids": []})
    with pytest.raises(HTTPException) as error:
        fx.receive.return_export(fx.connection, draft["id"], draft["snapshot_sha256"], fx.actor)
    assert error.value.status_code == 403


def test_discovery_evidence_is_separate_and_cannot_enable_a_write(fx):
    evidence = fx.receive.evidence(fx.connection, fx.actor)
    assert evidence["observed_on"] == "2026-10-18"
    assert all(row["runtime_request_schema_verified"] is False and row["live_verified"] is False for row in evidence["candidates"])
    evidence["candidates"][0]["direct_keys"].clear()
    assert portal_evidence()["candidates"][0]["direct_keys"] == ["AbrLfdNr", "LiegId", "Positionen"]
    assert all(action["effect"] == "read" for action in fx.provider.manifest.actions)
