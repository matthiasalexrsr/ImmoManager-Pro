"""Authenticated HTTP export contract with the isolated TEHA transaction fixture."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend import auth
from backend.routers import teha
from backend.services.teha_follow_up import follow_up_preview
from backend.services.teha_types import FollowUpPreparation, FollowUpUserSource
from backend.tests.test_teha_return_workflow import cost_draft, user_source

pytest_plugins = ("backend.tests.test_teha_publication",)


def test_frozen_packet_http_requires_auth_and_matching_hash_and_has_private_download_headers(fx, monkeypatch):
    draft, _, _, _, _ = cost_draft(fx)
    monkeypatch.setattr(teha, "service", lambda: fx.receive)
    app = FastAPI()
    app.include_router(teha.router)
    path = f"/teha/{fx.connection}/returns/{draft['id']}/export"
    headers = {"Authorization": "Bearer " + auth.create_access_token(fx.actor)}
    with TestClient(app) as client:
        assert client.get(path, params={"snapshot_sha256": draft["snapshot_sha256"]}).status_code == 401
        assert client.get(path, headers=headers).status_code == 422
        assert client.get(path, headers=headers, params={"snapshot_sha256": "f" * 64}).status_code == 409
        response = client.get(path, headers=headers, params={"snapshot_sha256": draft["snapshot_sha256"]})
        assert response.status_code == 200, response.text
        assert response.headers["cache-control"] == "private, no-store"
        assert response.headers["x-content-type-options"] == "nosniff"
        assert response.headers["content-disposition"].startswith("attachment;")
        assert response.headers["content-type"] == "application/json"
        assert response.json()["snapshot_sha256"] == draft["snapshot_sha256"]
        assert response.json()["external_write_enabled"] is False
        assert client.get(f"/teha/{fx.connection}/evidence", headers=headers).json()["observed_on"] == "2026-10-18"


def test_another_manager_cannot_export_or_list_an_owners_private_packet(fx):
    from fastapi import HTTPException
    draft, _, _, _, _ = cost_draft(fx)
    manager = auth.register_user("manager-" + fx.actor, fx.actor + "@manager.example.test", "Prüfverwalter", "Synthetic123!", "verwalter")
    assert fx.receive.returns(fx.connection, manager.id)["items"] == []
    for supplied_hash in (draft["snapshot_sha256"], "f" * 64):
        with pytest.raises(HTTPException) as error:
            fx.receive.return_export(fx.connection, draft["id"], supplied_hash, manager.id)
        assert error.value.status_code == 404


def test_vacant_000_user_can_keep_null_resident_name_in_local_follow_up_preview():
    command = FollowUpPreparation(orderer_name="Auftraggeber", users=[FollowUpUserSource(item_id="source", source_sha256="a" * 64)])
    # Keep the complete evidence wrapper: the builder derives Id from identity,
    # never from a resident name or a local tenant ID.
    value = follow_up_preview({"raw": {"auftragNummer": 501}}, command,
                              [user_source(lfdNr="000", bewohnerName=None, anmeldeart=0, kontaktdaten=None)])
    assert value["payload"]["Nutzer"][0]["BewohnerName"] is None
    assert value["payload"]["Nutzer"][0]["Id"] == 23


def test_review_costs_use_the_applications_half_up_cent_rule(fx):
    from backend.db.orm_models import CostItemORM
    from backend.tests.test_teha_return_workflow import exported
    draft, item, command, cost, _ = cost_draft(fx)
    if fx.engine is None:
        fx.store.cost_items[cost.id] = cost.model_copy(update={"amount": 1.005})
    else:
        with fx.receive.work(fx.actor, write=True) as unit:
            unit.db.get(CostItemORM, cost.id).amount = 1.005
    prepared = fx.receive.prepare_return(fx.connection, item["id"], command.model_copy(update={"idempotency_key": "new-rounding-key"}), fx.actor)
    assert exported(fx, prepared)["validation"]["summary"]["total_decimal"] == "1.21"
