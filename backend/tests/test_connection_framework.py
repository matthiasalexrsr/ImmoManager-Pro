"""Connection contracts with synthetic providers, never live external accounts."""

import hashlib
import json
from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy.exc import SQLAlchemyError

from backend import auth
from backend.db.integration_connection_models import (
    IntegrationActionRunORM,
    IntegrationConnectionORM,
    IntegrationConnectionSecretORM,
    IntegrationSourceBlockORM,
)
from backend.dependencies import store
from backend.models import PortfolioCreate, PropertyCreate
from backend.services.integrations import connection_storage as storage
from backend.services.integrations.base import IntegrationActionResult, IntegrationManifest, IntegrationProvider
from backend.services.integrations.connection_runs import ConnectionRuns
from backend.services.integrations.connection_types import (
    ConnectionCreate,
    ConnectionUpdate,
    MappingDecision,
    RunCancellation,
    RunDispatch,
    RunPreparation,
    SourceObservation,
)
from backend.services.integrations.manager import IntegrationManager
from backend.services.secret_box import SecretBox

SECRET = "SYNTHETIC-SECRET-NOT-IN-RESPONSES"
UNKNOWN = "SYNTHETIC-PRIVATE-UNKNOWN-FIELD"


class ProbeProvider(IntegrationProvider):
    def __init__(self):
        self.calls = []
        self.callback = lambda payload, config: IntegrationActionResult(True, "Synthetischer Erfolg", {"unknown": UNKNOWN})

    @property
    def manifest(self):
        return IntegrationManifest(integration_id="proof", name="Synthetische Prüfschnittstelle", category="test",
            description="Keine reale Gegenstelle", required_config_keys=["endpoint", "api_token"], secret_config_keys=["api_token"],
            config_fields=[{"key": "endpoint", "type": "string", "required": True},
                           {"key": "api_token", "type": "string", "secret": True, "required": True}],
            actions=[{"id": "preview", "effect": "local", "inputs": [{"key": "text", "type": "string"}]},
                     {"id": "read", "effect": "read", "inputs": []},
                     {"id": "send", "effect": "external_write", "inputs": [{"key": "text", "type": "string", "required": True}]},
                     {"id": "pages", "effect": "read", "inputs": [{"key": "cursor", "type": "string"}],
                      "cursor_field": "cursor", "has_more_field": "has_more", "next_cursor_field": "next_cursor"}])

    def is_configured(self, config):
        return bool(config.get("endpoint") and config.get("api_token"))

    def health(self, config):
        return {"status": "configured" if self.is_configured(config) else "not_configured"}

    def run(self, payload, config):
        self.calls.append((dict(payload), dict(config)))
        return self.callback(payload, config)


@pytest.fixture(autouse=True)
def clean():
    auth.clear_users()
    store.clear_all()
    store.__dict__.pop("_integration_connections", None)
    yield
    auth.clear_users()
    store.clear_all()
    store.__dict__.pop("_integration_connections", None)


@pytest.fixture
def fixture(tmp_path):
    owner = auth.register_user("connection-owner", "connections@example.test", "Prüfkonto", "Secret123", "eigentuemer")
    box = SecretBox(tmp_path / "keyring.json")
    manager = IntegrationManager(secret_box=box)
    provider = ProbeProvider()
    manager.register(provider)
    service = ConnectionRuns(store, manager, box)
    return SimpleNamespace(owner=owner, service=service, provider=provider, box=box, manager=manager)


def new_connection(fixture, **options):
    payload = ConnectionCreate(idempotency_key=str(uuid4()), provider_id="proof", name="Eigene Verbindung",
                               config={"endpoint": "synthetic.example.test", "api_token": SECRET, "future_nested": {"value": UNKNOWN}},
                               enabled=True, **options)
    return fixture.service.create(payload, fixture.owner.id)


def prepare(fixture, connection, action="read", values=None, **source):
    return fixture.service.prepare(connection["id"], RunPreparation(idempotency_key=str(uuid4()), config_revision=connection["revision"],
                                    action=action, payload=values or {}, **source), fixture.owner.id)


def dispatch(fixture, connection, run):
    command = RunDispatch(idempotency_key=str(uuid4()), base_revision=run["revision"], confirm=True)
    return fixture.service.dispatch(connection["id"], run["id"], command, fixture.owner.id)


def test_config_and_unknown_values_are_encrypted_while_the_provider_receives_only_declared_fields(fixture):
    connection = new_connection(fixture)
    assert SECRET not in json.dumps(connection) and UNKNOWN not in json.dumps(connection)
    assert connection["config"]["api_token"] == "***"
    assert connection["unmapped_fields"] == ["future_nested"]
    with storage.work(store, fixture.owner.id) as unit:
        item = storage.row(unit, IntegrationConnectionORM, connection["id"])
        assert UNKNOWN not in item.config_token and SECRET not in item.config_token
        secret = storage.row(unit, IntegrationConnectionSecretORM, item.secret_refs["api_token"])
        assert SECRET not in secret.value_token
        assert fixture.service.effective_config(unit, item)["future_nested"] == {"value": UNKNOWN}
    run = prepare(fixture, connection)
    assert fixture.provider.calls == []
    result = dispatch(fixture, connection, run)
    assert result["state"] == "completed"
    assert fixture.provider.calls[0][1] == {"endpoint": "synthetic.example.test", "api_token": SECRET}
    assert SECRET not in json.dumps(result) and UNKNOWN not in json.dumps(result)


def test_blank_and_masked_secret_keep_the_existing_value_and_explicit_clear_is_distinct(fixture):
    connection = new_connection(fixture)
    for placeholder in (None, "", "***"):
        connection = fixture.service.update(connection["id"], ConnectionUpdate(idempotency_key=str(uuid4()),
            base_revision=connection["revision"], config={"api_token": placeholder}), fixture.owner.id)
        assert connection["secret_fields_present"] == ["api_token"]
    connection = fixture.service.update(connection["id"], ConnectionUpdate(idempotency_key=str(uuid4()),
        base_revision=connection["revision"], enabled=False, clear_secrets=["api_token"]), fixture.owner.id)
    assert connection["secret_fields_present"] == [] and connection["configured"] is False
    assert fixture.provider.calls == []


def test_old_revision_and_reused_key_with_different_config_never_overwrite(fixture):
    connection = new_connection(fixture)
    command = ConnectionUpdate(idempotency_key=str(uuid4()), base_revision=connection["revision"], name="Neuer Name")
    first = fixture.service.update(connection["id"], command, fixture.owner.id)
    assert fixture.service.update(connection["id"], command, fixture.owner.id) == first
    for changed in (command.model_copy(update={"name": "Abweichend"}),
                    command.model_copy(update={"idempotency_key": str(uuid4()), "name": "Veraltet"})):
        with pytest.raises(HTTPException) as error:
            fixture.service.update(connection["id"], changed, fixture.owner.id)
        assert error.value.status_code == 409
    assert fixture.service.get(connection["id"], fixture.owner.id)["name"] == "Neuer Name"


def test_configuration_failure_rolls_back_parent_and_secret_versions(fixture, monkeypatch):
    def fail(*_args, **_kwargs):
        raise RuntimeError("synthetic receipt failure")
    monkeypatch.setattr(storage, "record_event", fail)
    with pytest.raises(RuntimeError):
        new_connection(fixture)
    assert fixture.service.list(fixture.owner.id)["total"] == 0
    with storage.work(store, fixture.owner.id) as unit:
        if unit.db is None:
            assert storage.memory(unit, IntegrationConnectionSecretORM) == {}
        else:
            assert unit.db.query(IntegrationConnectionSecretORM).count() == 0


def test_missing_key_is_not_an_empty_configuration_or_false_success(fixture, tmp_path):
    connection = new_connection(fixture)
    other = ConnectionRuns(store, fixture.manager, SecretBox(tmp_path / "wrong-keyring.json"))
    with pytest.raises(HTTPException) as error:
        other.get(connection["id"], fixture.owner.id)
    assert error.value.status_code == 503
    assert fixture.service.get(connection["id"], fixture.owner.id)["configured"] is True


def test_reader_cannot_write_and_portfolio_restricted_manager_cannot_read_installation_connections(fixture):
    connection = new_connection(fixture)
    reader = auth.register_user("connection-reader", "reader@example.test", "Leser", "Secret123", "readonly")
    auth.update_user(reader.id, {"portfolio_access": "all", "portfolio_ids": []})
    with pytest.raises(HTTPException) as error:
        fixture.service.update(connection["id"], ConnectionUpdate(idempotency_key=str(uuid4()), base_revision=1, name="Verboten"), reader.id)
    assert error.value.status_code == 403
    manager = auth.register_user("connection-manager", "manager@example.test", "Verwalter", "Secret123", "verwalter")
    auth.update_user(manager.id, {"portfolio_access": "selected", "portfolio_ids": []})
    with pytest.raises(HTTPException) as error:
        fixture.service.get(connection["id"], manager.id)
    assert error.value.status_code == 403
    assert fixture.provider.calls == []


def test_prepare_sends_nothing_and_repeated_dispatch_returns_the_same_receipt(fixture):
    connection = new_connection(fixture)
    run = prepare(fixture, connection, "send", {"text": "Ausdrücklich ausgewählte Nachricht"})
    assert fixture.provider.calls == []
    command = RunDispatch(idempotency_key=str(uuid4()), base_revision=run["revision"], confirm=True)
    first = fixture.service.dispatch(connection["id"], run["id"], command, fixture.owner.id)
    second = fixture.service.dispatch(connection["id"], run["id"], command, fixture.owner.id)
    assert first == second and first["state"] == "accepted"
    assert len(fixture.provider.calls) == 1
    with pytest.raises(HTTPException) as error:
        dispatch(fixture, connection, first)
    assert error.value.status_code == 409 and len(fixture.provider.calls) == 1


def test_failed_dispatch_claim_never_enters_the_provider(fixture, monkeypatch):
    connection = new_connection(fixture)
    run = prepare(fixture, connection, "send", {"text": "Nicht gesendet"})
    def fail(*_args, **_kwargs):
        raise SQLAlchemyError("PRIVATE-SQL-MUST-NOT-LEAK")
    monkeypatch.setattr(storage, "receipt", fail)
    with pytest.raises(HTTPException) as error:
        dispatch(fixture, connection, run)
    assert error.value.status_code == 503
    assert "PRIVATE-SQL" not in str(error.value.detail)
    assert fixture.provider.calls == []
    assert fixture.service.get_run(connection["id"], run["id"], fixture.owner.id)["state"] == "prepared"


def test_provider_exception_leaves_an_unknown_external_outcome_not_a_blind_retry(fixture):
    connection = new_connection(fixture)
    def fail(_payload, _config):
        raise RuntimeError(SECRET)
    fixture.provider.callback = fail
    run = prepare(fixture, connection, "send", {"text": "Ausgang unklar"})
    unknown = dispatch(fixture, connection, run)
    assert unknown["state"] == "unknown" and unknown["external_outcome_unknown"]
    assert SECRET not in json.dumps(unknown)
    with pytest.raises(HTTPException) as error:
        dispatch(fixture, connection, unknown)
    assert error.value.status_code == 409 and len(fixture.provider.calls) == 1


def test_lost_result_persistence_keeps_the_claim_and_expired_write_is_not_reissued(fixture, monkeypatch):
    connection = new_connection(fixture)
    run = prepare(fixture, connection, "send", {"text": "Angenommen aber Bestätigung verloren"})
    original = fixture.service._finish
    def fail(*_args, **_kwargs):
        raise SQLAlchemyError("PRIVATE-FINALIZATION-FAILURE")
    monkeypatch.setattr(fixture.service, "_finish", fail)
    with pytest.raises(HTTPException) as error:
        dispatch(fixture, connection, run)
    assert error.value.status_code == 503 and "PRIVATE" not in str(error.value.detail)
    assert len(fixture.provider.calls) == 1
    monkeypatch.setattr(fixture.service, "_finish", original)
    with storage.work(store, fixture.owner.id, write=True) as unit:
        pending = storage.row(unit, IntegrationActionRunORM, run["id"], lock=True)
        storage.put(unit, IntegrationActionRunORM, {**storage.values(pending), "lease_until": storage.now() - timedelta(seconds=1)})
    stale = fixture.service.get_run(connection["id"], run["id"], fixture.owner.id)
    assert stale["interrupted"] and stale["external_outcome_unknown"]
    unknown = dispatch(fixture, connection, stale)
    assert unknown["state"] == "unknown" and len(fixture.provider.calls) == 1


def test_current_configuration_and_source_revision_are_rechecked_before_network_activity(fixture):
    connection = new_connection(fixture)
    run = prepare(fixture, connection)
    fixture.service.update(connection["id"], ConnectionUpdate(idempotency_key=str(uuid4()), base_revision=1, name="Geändert"), fixture.owner.id)
    with pytest.raises(HTTPException) as error:
        dispatch(fixture, connection, run)
    assert error.value.status_code == 409 and fixture.provider.calls == []
    portfolio = store.create_portfolio(PortfolioCreate(name="Quellbestand"))
    prop = store.create_property(PropertyCreate(portfolio_id=portfolio.id, name="Quellhaus", property_type="residential"))
    connection = fixture.service.get(connection["id"], fixture.owner.id)
    run = prepare(fixture, connection, source_kind="property", source_id=prop.id, source_revision=prop.updated_at.isoformat())
    store.update_property(prop.id, PropertyCreate(portfolio_id=portfolio.id, name="Geändertes Quellhaus", property_type="residential"))
    with pytest.raises(HTTPException) as error:
        dispatch(fixture, connection, run)
    assert error.value.status_code == 409 and fixture.provider.calls == []


def test_read_pages_resume_explicitly_and_keep_each_raw_result(fixture):
    connection = new_connection(fixture)
    fixture.provider.callback = lambda payload, _config: IntegrationActionResult(True, "Seite", {
        "items": ["second"] if payload.get("cursor") else ["first"],
        "has_more": not bool(payload.get("cursor")), "next_cursor": None if payload.get("cursor") else "second-page",
        "unmapped": UNKNOWN,
    })
    first = dispatch(fixture, connection, prepare(fixture, connection, "pages"))
    assert first["state"] == "awaiting_page" and first["completed_pages"] == 1
    # A new service instance reads the durable checkpoint, rather than a local future.
    second_service = ConnectionRuns(store, fixture.manager, fixture.box)
    final = second_service.dispatch(connection["id"], first["id"], RunDispatch(idempotency_key=str(uuid4()),
        base_revision=first["revision"], confirm=True), fixture.owner.id)
    assert final["state"] == "completed" and final["completed_pages"] == 2
    assert [call[0].get("cursor") for call in fixture.provider.calls] == [None, "second-page"]
    with storage.work(store, fixture.owner.id) as unit:
        if unit.db is None:
            rows = list(storage.memory(unit, IntegrationSourceBlockORM).values())
        else:
            rows = unit.db.query(IntegrationSourceBlockORM).filter_by(run_id=final["id"]).all()
        assert {row.category for row in rows if row.category.startswith("attempt-")} == {"attempt-1", "attempt-2"}
        assert all(UNKNOWN not in row.data_token for row in rows)


def test_mapping_observations_are_not_accepted_and_changed_source_revokes_previous_acceptance(fixture):
    connection = new_connection(fixture)
    raw = {"unknown_nested": [{"name": UNKNOWN, "amount": "123.45"}], "external": "OBJECT-1"}
    sha = hashlib.sha256(json.dumps(raw, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()
    observed = fixture.service.observe(connection["id"], SourceObservation(idempotency_key=str(uuid4()),
        source_kind="property", external_key="OBJECT-1", raw=raw, source_sha256=sha), fixture.owner.id)
    assert observed["state"] == "observed" and observed["target_id"] is None
    assert any(field["path"].endswith("/amount") and field["status"] == "observed" for field in observed["fields"])
    portfolio = store.create_portfolio(PortfolioCreate(name="Zielbestand"))
    prop = store.create_property(PropertyCreate(portfolio_id=portfolio.id, name="Zielhaus", property_type="residential"))
    mapped = fixture.service.decide_mapping(connection["id"], observed["id"], MappingDecision(idempotency_key=str(uuid4()),
        base_revision=observed["revision"], source_sha256=sha, target_kind="property", target_id=prop.id,
        target_revision=prop.updated_at.isoformat(), decision="accepted"), fixture.owner.id)
    assert mapped["state"] == "accepted" and mapped["confirmed_by"] == fixture.owner.id
    changed = {**raw, "later": True}
    next_observation = fixture.service.observe(connection["id"], SourceObservation(idempotency_key=str(uuid4()),
        source_kind="property", external_key="OBJECT-1", raw=changed, source_sha256=storage.digest(changed), base_revision=mapped["revision"]), fixture.owner.id)
    assert next_observation["state"] == "observed" and next_observation["confirmed_by"] is None
    assert next_observation["target_id"] == prop.id
    assert fixture.provider.calls == []


def test_cancel_is_explicit_and_cannot_pretend_an_accepted_action_was_unsent(fixture):
    connection = new_connection(fixture)
    run = prepare(fixture, connection, "send", {"text": "Vorschau"})
    cancelled = fixture.service.cancel(connection["id"], run["id"], RunCancellation(idempotency_key=str(uuid4()),
        base_revision=run["revision"], reason="Nicht freigegeben"), fixture.owner.id)
    assert cancelled["state"] == "cancelled" and fixture.provider.calls == []
    accepted = dispatch(fixture, connection, prepare(fixture, connection, "send", {"text": "Freigegeben"}))
    with pytest.raises(HTTPException) as error:
        fixture.service.cancel(connection["id"], accepted["id"], RunCancellation(idempotency_key=str(uuid4()),
            base_revision=accepted["revision"], reason="Kann nicht ungesendet gemacht werden"), fixture.owner.id)
    assert error.value.status_code == 409


def test_private_receipt_unit_binds_actor_and_storage_without_granting_an_owner_role(fixture):
    with fixture.service._receipt_writer(fixture.owner.id) as unit:
        assert unit.actor_id == fixture.owner.id
        assert unit.user["role"] == "receipt_only"
        if hasattr(store, "db"):
            assert unit.db is not None and unit.archive is None
        else:
            assert unit.db is None and unit.archive is not None


@pytest.mark.parametrize("details", [{}, {"has_more": "false"}, {"has_more": True, "next_cursor": None}])
def test_incomplete_pagination_contract_never_claims_a_complete_result(fixture, details):
    connection = new_connection(fixture)
    fixture.provider.callback = lambda _payload, _config: IntegrationActionResult(True, "Unvollständige Seite", details)
    result = dispatch(fixture, connection, prepare(fixture, connection, "pages"))
    assert result["state"] == "blocked" and result["completed_pages"] == 0
    assert result["result_bytes"] > 0
    assert len(fixture.provider.calls) == 1


def test_non_adjacent_cursor_cycle_is_blocked_and_all_observed_pages_are_retained(fixture):
    connection = new_connection(fixture)
    def page(payload, _config):
        current = payload.get("cursor")
        continuation = {None: "one", "one": "two", "two": "one"}[current]
        return IntegrationActionResult(True, "Seite", {"has_more": True, "next_cursor": continuation, "items": [current]})
    fixture.provider.callback = page
    run = prepare(fixture, connection, "pages")
    for _ in range(3):
        run = dispatch(fixture, connection, run)
    assert run["state"] == "blocked" and run["completed_pages"] == 2
    assert len(fixture.provider.calls) == 3
    with pytest.raises(HTTPException) as error:
        dispatch(fixture, connection, run)
    assert error.value.status_code == 409


def test_api_is_registered_requires_auth_and_never_echoes_invalid_secret_inputs(fixture, monkeypatch, caplog):
    from fastapi.testclient import TestClient

    from backend.app import app
    from backend.routers import integration_connections as routes
    monkeypatch.setattr(routes, "_service", lambda: fixture.service)
    anonymous = TestClient(app)
    assert anonymous.get("/api/v1/integration-connections").status_code == 401
    client = TestClient(app, headers={"Authorization": "Bearer " + auth.create_access_token(fixture.owner.id)})
    invalid = {"idempotency_key": str(uuid4()), "provider_id": "proof", "name": {"secret": SECRET},
               "config": {"api_token": SECRET}}
    response = client.post("/api/v1/integration-connections", json=invalid)
    assert response.status_code == 422
    assert SECRET not in response.text and SECRET not in caplog.text
    assert not fixture.provider.calls
    assert fixture.service.list(fixture.owner.id)["total"] == 0


def test_api_configuration_and_frozen_action_preview_are_real_and_private(fixture, monkeypatch):
    from fastapi.testclient import TestClient

    from backend.app import app
    from backend.routers import integration_connections as routes
    monkeypatch.setattr(routes, "_service", lambda: fixture.service)
    client = TestClient(app, headers={"Authorization": "Bearer " + auth.create_access_token(fixture.owner.id)})
    command = {"idempotency_key": str(uuid4()), "provider_id": "proof", "name": "HTTP-Verbindung", "enabled": True,
               "config": {"endpoint": "synthetic.example.test", "api_token": SECRET}}
    response = client.post("/api/v1/integration-connections", json=command)
    assert response.status_code == 201, response.text
    assert response.headers["cache-control"] == "private, no-store"
    connection = response.json()
    assert SECRET not in response.text and connection["config"]["api_token"] == "***"
    again = client.post("/api/v1/integration-connections", json=command)
    assert again.status_code == 201 and again.json()["id"] == connection["id"]
    root = "/api/v1/integration-connections/" + connection["id"]
    preview = client.post(root + "/runs", json={"idempotency_key": str(uuid4()), "config_revision": 1,
        "action": "send", "payload": {"text": "Nur diese ausdrücklich ausgewählte Nachricht"}})
    assert preview.status_code == 201, preview.text
    assert fixture.provider.calls == []
    run = preview.json()
    frozen = client.get(root + "/runs/" + run["id"] + "/preview")
    assert frozen.status_code == 200, frozen.text
    assert frozen.json()["payload"] == {"text": "Nur diese ausdrücklich ausgewählte Nachricht"}
    assert frozen.json()["external_action_started"] is False
    assert SECRET not in frozen.text
    assert client.get(root + "/runs").json()["total"] == 1
    schema = client.get("/openapi.json").json()
    body = schema["paths"]["/api/v1/integration-connections"]["post"]["requestBody"]
    assert body["content"]["application/json"]["schema"]["properties"]["idempotency_key"]["maxLength"] == 128


def test_oversized_http_command_is_refused_before_business_processing(fixture, monkeypatch):
    from fastapi.testclient import TestClient

    from backend.app import app
    from backend.config import settings
    from backend.routers import integration_connections as routes
    monkeypatch.setattr(routes, "_service", lambda: fixture.service)
    monkeypatch.setattr(settings, "integration_step_max_bytes", 512)
    client = TestClient(app, headers={"Authorization": "Bearer " + auth.create_access_token(fixture.owner.id)})
    response = client.post("/api/v1/integration-connections", content=b'{"oversized":"' + b'x' * 1024 + b'"}')
    assert response.status_code == 413
    assert fixture.service.list(fixture.owner.id)["total"] == 0
    assert not fixture.provider.calls


def test_frozen_preview_is_bound_to_the_authorized_connection(fixture):
    a = new_connection(fixture)
    b = new_connection(fixture)
    run = prepare(fixture, a, "send", {"text": "Private A-Nachricht"})
    with pytest.raises(HTTPException) as error:
        fixture.service.preview(b["id"], run["id"], fixture.owner.id)
    assert error.value.status_code == 404
    assert "Private A-Nachricht" not in str(error.value.detail)


def test_new_connection_rejects_a_secret_mask_instead_of_enabling_an_empty_credential(fixture):
    command = ConnectionCreate(idempotency_key=str(uuid4()), provider_id="proof", name="Keine echte Anmeldung",
                               config={"endpoint": "synthetic.example.test", "api_token": "***"}, enabled=True)
    with pytest.raises(HTTPException) as error:
        fixture.service.create(command, fixture.owner.id)
    assert error.value.status_code == 422
    assert fixture.service.list(fixture.owner.id)["total"] == 0
    assert fixture.provider.calls == []


def test_a_failed_decryption_does_not_hide_other_connections_or_claim_an_empty_success(fixture, tmp_path):
    first = new_connection(fixture)
    other_box = SecretBox(tmp_path / "separate-connection-key.json")
    other = ConnectionRuns(store, fixture.manager, other_box)
    second = other.create(ConnectionCreate(idempotency_key=str(uuid4()), provider_id="proof", name="Separater Schlüssel",
        config={"endpoint": "synthetic.example.test", "api_token": "SECOND-SYNTHETIC-SECRET"}, enabled=True), fixture.owner.id)
    page = fixture.service.list(fixture.owner.id)
    assert page["total"] == 2
    by_id = {item["id"]: item for item in page["items"]}
    assert by_id[first["id"]]["configured"] is True
    assert by_id[second["id"]]["configured"] is None
    assert by_id[second["id"]]["configuration_state"] == "unreadable"
    assert by_id[second["id"]]["read_error"]
    assert "SECOND-SYNTHETIC-SECRET" not in json.dumps(page)
    with pytest.raises(HTTPException) as error:
        fixture.service.get(second["id"], fixture.owner.id)
    assert error.value.status_code == 503


def test_unreadable_connection_can_be_explicitly_disabled_without_mutating_ciphertext_or_creating_keys(fixture, tmp_path):
    connection = new_connection(fixture)
    with storage.work(store, fixture.owner.id) as unit:
        before = storage.values(storage.row(unit, IntegrationConnectionORM, connection["id"]))
    missing_key = tmp_path / "must-not-be-created.json"
    other = ConnectionRuns(store, fixture.manager, SecretBox(missing_key))
    command = ConnectionUpdate(idempotency_key=str(uuid4()), base_revision=1, enabled=False)
    disabled = other.update(connection["id"], command, fixture.owner.id)
    assert disabled["enabled"] is False and disabled["revision"] == 2
    assert disabled["configured"] is None and disabled["read_error"]
    assert other.update(connection["id"], command, fixture.owner.id) == disabled
    assert not missing_key.exists()
    with storage.work(store, fixture.owner.id) as unit:
        after = storage.values(storage.row(unit, IntegrationConnectionORM, connection["id"]))
    assert after["config_token"] == before["config_token"]
    assert after["secret_refs"] == before["secret_refs"]
    assert fixture.service.get(connection["id"], fixture.owner.id)["enabled"] is False
    assert fixture.provider.calls == []


def test_event_pagination_and_count_do_not_disclose_another_actors_private_runs(fixture):
    connection = new_connection(fixture)
    foreign = prepare(fixture, connection, "send", {"text": "Nur für den Ersteller"})
    manager = auth.register_user("event-manager", "event-manager@example.test", "Verwalter", "Secret123", "verwalter")
    auth.update_user(manager.id, {"portfolio_access": "all", "portfolio_ids": []})
    own = fixture.service.prepare(connection["id"], RunPreparation(idempotency_key=str(uuid4()), config_revision=1,
        action="read"), manager.id)
    found, cursor = [], None
    while True:
        page = fixture.service.events(connection["id"], manager.id, cursor=cursor, limit=1)
        assert page["total"] == 2  # one shared configuration event and this actor's preparation
        found.extend(page["items"])
        if not page["has_more"]:
            break
        cursor = page["next_cursor"]
    assert len(found) == len({item["id"] for item in found}) == 2
    assert {item["run_id"] for item in found} == {None, own["id"]}
    assert foreign["id"] not in json.dumps(found)
    assert fixture.service.events(connection["id"], fixture.owner.id)["total"] == 3


def test_command_identity_cannot_be_overwritten_after_a_competing_creation(fixture):
    from backend.services import business_qol as office
    connection = new_connection(fixture)
    command = ConnectionUpdate(idempotency_key=str(uuid4()), base_revision=1, name="Ein bestätigter Stand")
    confirmed = fixture.service.update(connection["id"], command, fixture.owner.id)
    identifier = office.command_id(fixture.owner.id, command.idempotency_key)
    with storage.work(store, fixture.owner.id) as unit:
        before = office.dump(office.get_record(unit, "business_qol_commands", identifier))
    with pytest.raises(HTTPException) as error:
        with storage.work(store, fixture.owner.id, write=True) as unit:
            current = storage.row(unit, IntegrationConnectionORM, connection["id"], lock=True)
            storage.put(unit, IntegrationConnectionORM, {**storage.values(current), "name": "Muss zurückgerollt werden"})
            office.save_command(unit, fixture.owner.id, "connection:update:" + connection["id"], command,
                {"kind": "integration_connection", "entity_id": connection["id"], "property_id": None},
                {"wrong": "cannot overwrite the first result"})
    assert error.value.status_code == 409
    assert fixture.service.get(connection["id"], fixture.owner.id) == confirmed
    with storage.work(store, fixture.owner.id) as unit:
        assert office.dump(office.get_record(unit, "business_qol_commands", identifier)) == before


def test_parallel_connection_creation_replays_once_on_independent_database_connections(fixture, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from sqlalchemy import text
    from sqlalchemy.orm import Session

    from backend.services import document_versions as archive
    command = ConnectionCreate(idempotency_key=str(uuid4()), provider_id="proof", name="Eine einzige Verbindung",
        config={"endpoint": "synthetic.example.test", "api_token": SECRET}, enabled=True)
    bind = store.db.get_bind() if hasattr(store, "db") else None
    native = bind is not None and bind.dialect.name == "postgresql"
    barrier = Barrier(2)
    database_pids = []
    original = archive.begin_writer
    if native:
        def begin(db):
            original(db)
            database_pids.append(db.scalar(text("SELECT pg_backend_pid()")))
            barrier.wait(timeout=15)
        monkeypatch.setattr(archive, "begin_writer", begin)
    def create(_index):
        if bind is None:
            return fixture.service.create(command, fixture.owner.id)["id"]
        from backend.repositories.sql_store import SQLAlchemyStore
        with Session(bind=bind) as session:
            service = ConnectionRuns(SQLAlchemyStore(session), fixture.manager, fixture.box)
            return service.create(command, fixture.owner.id)["id"]
    with ThreadPoolExecutor(max_workers=2) as pool:
        identifiers = list(pool.map(create, range(2)))
    assert identifiers[0] == identifiers[1]
    assert fixture.service.list(fixture.owner.id)["total"] == 1
    if native:
        assert len(set(database_pids)) == 2, "Two sessions on one PostgreSQL connection do not prove concurrency"
    assert fixture.provider.calls == []


def test_expired_worker_retains_its_real_acknowledgement_for_explicit_review_without_resending(fixture):
    from backend.services.integrations.connection_types import RecordedResultReconcile
    connection = new_connection(fixture)
    run = prepare(fixture, connection, "send", {"text": "Genau ein externer Aufruf"})
    def late_success(_payload, _config):
        with storage.work(store, fixture.owner.id, write=True) as unit:
            executing = storage.row(unit, IntegrationActionRunORM, run["id"], lock=True)
            storage.put(unit, IntegrationActionRunORM, {**storage.values(executing),
                "lease_until": storage.now() - timedelta(seconds=1)})
        expired = fixture.service.get_run(connection["id"], run["id"], fixture.owner.id)
        fenced = dispatch(fixture, connection, expired)
        assert fenced["state"] == "unknown"
        return IntegrationActionResult(True, "Verspätet bestätigt", {"receipt": "SYNTHETIC-ACK", "echo": SECRET})
    fixture.provider.callback = late_success
    current = dispatch(fixture, connection, run)
    assert current["state"] == "unknown" and current["late_result_count"] == 1
    assert len(fixture.provider.calls) == 1
    page = fixture.service.attempts(connection["id"], run["id"], fixture.owner.id, limit=1)
    assert page["total"] == 1
    attempt = page["items"][0]
    assert attempt["detached"] and attempt["state"] == "finished"
    proof = fixture.service.attempt(connection["id"], run["id"], attempt["id"], fixture.owner.id)
    assert proof["verified"] and proof["projection_is_original"] is False
    assert proof["projection"]["details"] == {"receipt": "SYNTHETIC-ACK", "echo": "***"}
    assert SECRET not in json.dumps(proof)
    command = RecordedResultReconcile(idempotency_key=str(uuid4()), base_revision=current["revision"],
        attempt_id=attempt["id"], confirm=True, reason="Verspäteten Beleg geprüft")
    accepted = fixture.service.reconcile_recorded(connection["id"], run["id"], command, fixture.owner.id)
    assert accepted["state"] == "accepted" and accepted["late_result_count"] == 0
    assert accepted["result_sha256"] == attempt["result_sha256"]
    assert accepted["result_bytes"] == attempt["result_bytes"]
    assert fixture.service.reconcile_recorded(connection["id"], run["id"], command, fixture.owner.id) == accepted
    assert len(fixture.provider.calls) == 1
    after = fixture.service.attempt(connection["id"], run["id"], attempt["id"], fixture.owner.id)
    assert after["manifest"] == proof["manifest"] and after["projection"] == proof["projection"]
    assert after["attempt"]["reviewed_at"]


def test_result_projection_is_verified_before_return_and_detects_missing_or_extra_blocks(fixture):
    connection = new_connection(fixture)
    fixture.provider.callback = lambda _payload, _config: IntegrationActionResult(True, "Beleg", {"large": "x" * 70000})
    completed = dispatch(fixture, connection, prepare(fixture, connection))
    attempt = fixture.service.attempts(connection["id"], completed["id"], fixture.owner.id)["items"][0]
    assert attempt["result_blocks"] == 2
    good = fixture.service.attempt(connection["id"], completed["id"], attempt["id"], fixture.owner.id)
    assert good["verified"] and len(good["projection"]["details"]["large"]) == 70000
    with storage.work(store, fixture.owner.id, write=True) as unit:
        block = storage.find_one(unit, IntegrationSourceBlockORM, run_id=completed["id"], sequence=1)
        storage.put(unit, IntegrationSourceBlockORM, {**storage.values(block), "sequence": 2})
    with pytest.raises(HTTPException) as error:
        fixture.service.attempt(connection["id"], completed["id"], attempt["id"], fixture.owner.id)
    assert error.value.status_code == 503


def test_result_rejects_a_block_copied_between_runs_even_when_the_plaintext_hash_matches(fixture):
    connection = new_connection(fixture)
    first = dispatch(fixture, connection, prepare(fixture, connection))
    second = dispatch(fixture, connection, prepare(fixture, connection))
    assert first["result_sha256"] == second["result_sha256"]
    attempt = fixture.service.attempts(connection["id"], second["id"], fixture.owner.id)["items"][0]
    with storage.work(store, fixture.owner.id, write=True) as unit:
        source = storage.find_one(unit, IntegrationSourceBlockORM, run_id=first["id"], sequence=0)
        target = storage.find_one(unit, IntegrationSourceBlockORM, run_id=second["id"], sequence=0)
        storage.put(unit, IntegrationSourceBlockORM, {**storage.values(target), "data_token": source.data_token})
    with pytest.raises(HTTPException) as error:
        fixture.service.attempt(connection["id"], second["id"], attempt["id"], fixture.owner.id)
    assert error.value.status_code == 503


def test_each_paginated_attempt_has_a_complete_independently_recoverable_result(fixture):
    connection = new_connection(fixture)
    fixture.provider.callback = lambda payload, _config: IntegrationActionResult(True, "Seite", {
        "items": [2] if payload.get("cursor") else [1], "has_more": not bool(payload.get("cursor")),
        "next_cursor": None if payload.get("cursor") else "next", "future_field": {"untouched": UNKNOWN}})
    first = dispatch(fixture, connection, prepare(fixture, connection, "pages"))
    final = dispatch(fixture, connection, first)
    page = fixture.service.attempts(connection["id"], final["id"], fixture.owner.id)
    assert page["total"] == 2 and final["recorded_attempts"] == 2
    results = [fixture.service.attempt(connection["id"], final["id"], item["id"], fixture.owner.id) for item in page["items"]]
    assert sorted(value for result in results for value in result["projection"]["details"]["items"]) == [1, 2]
    assert final["result_bytes"] == sum(result["manifest"]["bytes"] for result in results)
    assert final["retained_result_bytes"] == final["result_bytes"]
    assert all(result["projection"]["details"]["future_field"] == {"untouched": UNKNOWN} for result in results)
    with storage.work(store, fixture.owner.id) as unit:
        row = storage.row(unit, IntegrationActionRunORM, final["id"])
        checkpoint = storage.unseal(row.checkpoint_token, f"connection-run/{row.id}/checkpoint", fixture.box)
        assert "seen_cursor_hashes" not in checkpoint


def test_deleted_business_source_keeps_history_but_cannot_authorize_another_dispatch(fixture):
    connection = new_connection(fixture)
    portfolio = store.create_portfolio(PortfolioCreate(name="Historischer Bestand"))
    prop = store.create_property(PropertyCreate(portfolio_id=portfolio.id, name="Historische Quelle", property_type="residential"))
    run = prepare(fixture, connection, source_kind="property", source_id=prop.id, source_revision=prop.updated_at.isoformat())
    store.delete_property(prop.id)
    historical = fixture.service.get_run(connection["id"], run["id"], fixture.owner.id)
    assert historical["source_status"] == "unavailable" and historical["can_dispatch"] is False
    assert fixture.service.runs(connection["id"], fixture.owner.id)["total"] == 1
    preview = fixture.service.preview(connection["id"], run["id"], fixture.owner.id)
    assert preview["run"]["source_status"] == "unavailable"
    with pytest.raises(HTTPException) as error:
        dispatch(fixture, connection, historical)
    assert error.value.status_code == 404
    assert fixture.provider.calls == []
    cancelled = fixture.service.cancel(connection["id"], run["id"], RunCancellation(idempotency_key=str(uuid4()),
        base_revision=historical["revision"], reason="Quelle wurde entfernt"), fixture.owner.id)
    assert cancelled["state"] == "cancelled"


def test_owner_can_cancel_an_inactive_creators_prepared_run_without_impersonating_or_sending(fixture):
    connection = new_connection(fixture)
    run = prepare(fixture, connection, "send", {"text": "Nicht versendet"})
    recovery = auth.register_user("recovery-owner", "recovery-owner@example.test", "Zweites Eigentümerkonto", "Secret123", "eigentuemer")
    auth.update_user(fixture.owner.id, {"is_active": False})
    cancelled = fixture.service.cancel(connection["id"], run["id"], RunCancellation(idempotency_key=str(uuid4()),
        base_revision=run["revision"], reason="Ersteller deaktiviert; Auftrag zurückgenommen"), recovery.id)
    assert cancelled["state"] == "cancelled" and cancelled["actor_id"] == fixture.owner.id
    assert fixture.provider.calls == []
