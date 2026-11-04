"""HTTP contracts for integration/settings review; no live provider is ever called."""
from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from test_connection_framework import ProbeProvider

from backend import auth
from backend.app import app
from backend.db.integration_connection_models import IntegrationActionRunORM, IntegrationConnectionORM
from backend.dependencies import store
from backend.routers import integration_connections, integrations
from backend.services.integrations import connection_storage as storage
from backend.services.integrations.base import IntegrationActionResult, IntegrationManifest, IntegrationRunRecord
from backend.services.integrations.config_store import JsonFileIntegrationConfigStore
from backend.services.integrations.connection_runs import ConnectionRuns
from backend.services.integrations.manager import IntegrationManager
from backend.services.integrations.providers import EmailIntegrationProvider, ListingPortalProvider
from backend.services.secret_box import SecretBox


class TypedProvider(ProbeProvider):
    @property
    def manifest(self):
        return IntegrationManifest(integration_id="typed-proof", name="Typisierte lokale Prüfung", category="test", description="Kein Netz",
            required_config_keys=["number", "flag"], config_fields=[
                {"key": "number", "type": "number", "required": True, "min": 0, "max": 1},
                {"key": "flag", "type": "boolean", "required": True}],
            actions=[{"id": "read", "effect": "local", "inputs": [
                {"key": "amount", "type": "number", "required": True, "min": 0, "max": 1},
                {"key": "approved", "type": "boolean", "required": True},
                {"key": "optional_label", "type": "string"},
                {"key": "messages", "type": "array", "required": True, "items": {"type": "object", "fields": [
                    {"key": "body", "type": "string", "required": True}]}}]}])

    def is_configured(self, config):
        return {"number", "flag"} <= config.keys()


def headers(user):
    return {"Authorization": "Bearer " + auth.create_access_token(user.id)}


@pytest.fixture
def http_case(tmp_path, monkeypatch):
    auth.clear_users()
    store.clear_all()
    store.__dict__.pop("_integration_connections", None)
    owner = auth.register_user("surface-owner", "surface-owner@example.test", "Eigentümer", "Secret123", "eigentuemer")
    manager_user = auth.register_user("surface-manager", "surface-manager@example.test", "Verwalter", "Secret123", "verwalter")
    auth.update_user(manager_user.id, {"portfolio_access": "all", "portfolio_ids": []})
    box = SecretBox(tmp_path / "review-keyring.json")
    manager = IntegrationManager(secret_box=box)
    provider = ProbeProvider()
    manager.register(provider)
    manager.register(EmailIntegrationProvider())
    manager.register(ListingPortalProvider())
    typed = TypedProvider()
    manager.register(typed)
    service = ConnectionRuns(store, manager, box)
    monkeypatch.setattr(integration_connections, "_service", lambda: service)
    monkeypatch.setattr(integrations, "integration_manager", manager)
    with TestClient(app, raise_server_exceptions=False) as client:
        yield SimpleNamespace(client=client, owner=owner, manager=manager_user, provider=provider,
                              service=service, registry=manager, typed=typed)
    auth.clear_users()
    store.clear_all()
    store.__dict__.pop("_integration_connections", None)


def create_connection(case, user=None):
    response = case.client.post("/api/v1/integration-connections", headers=headers(user or case.owner), json={
        "idempotency_key": str(uuid4()), "provider_id": "proof", "name": "Synthetische HTTP-Verbindung", "enabled": True,
        "config": {"endpoint": "synthetic.invalid", "api_token": "REVIEW-SECRET-NOT-PUBLIC"}})
    assert response.status_code == 201, response.text
    assert "REVIEW-SECRET-NOT-PUBLIC" not in response.text
    return response.json()


def prepare_run(case, connection, user=None, action="read"):
    response = case.client.post(f"/api/v1/integration-connections/{connection['id']}/runs", headers=headers(user or case.owner), json={
        "idempotency_key": str(uuid4()), "config_revision": connection["revision"], "action": action,
        "payload": {"text": "Nur synthetische Aktion"} if action == "send" else {}})
    assert response.status_code == 201, response.text
    assert case.provider.calls == []
    return response.json()


@pytest.mark.parametrize("surface", ["connections", "legacy"])
def test_huge_integer_is_a_validation_error_without_persisting_or_contacting_a_provider(http_case, surface):
    config = {"smtp_host": "smtp.synthetic.invalid", "sender_email": "sender@example.test", "smtp_port": 10 ** 1000}
    if surface == "connections":
        response = http_case.client.post("/api/v1/integration-connections", headers=headers(http_case.owner), json={
            "idempotency_key": str(uuid4()), "provider_id": "email", "name": "Unzulässiger Port", "config": config})
    else:
        response = http_case.client.put("/api/v1/integrations/email/config", headers=headers(http_case.owner), json={"config": config})
    assert response.status_code in (400, 422), response.text
    assert http_case.service.list(http_case.owner.id)["total"] == 0
    assert http_case.registry._config["email"] == {}
    assert http_case.provider.calls == []


def test_oversized_decimal_reminder_has_a_422_contract_and_preserves_preferences(http_case):
    before = http_case.client.get("/api/v1/auth/users/me/preferences", headers=headers(http_case.owner)).json()
    response = http_case.client.put("/api/v1/auth/users/me/preferences", headers=headers(http_case.owner), json={"reminder_days": "9" * 5000})
    assert response.status_code == 422, response.text
    assert http_case.client.get("/api/v1/auth/users/me/preferences", headers=headers(http_case.owner)).json() == before


@pytest.mark.parametrize("state", ["completed", "cancelled", "disabled", "archived", "config_changed"])
def test_run_cannot_advertise_dispatch_when_the_dispatch_contract_refuses_it(http_case, state):
    connection = create_connection(http_case)
    run = prepare_run(http_case, connection)
    root = f"/api/v1/integration-connections/{connection['id']}"
    run_url = root + "/runs/" + run["id"]
    assert run["can_dispatch"] is True
    if state in {"disabled", "archived", "config_changed"}:
        delta = {"enabled": False} if state == "disabled" else {"archived": True} if state == "archived" else {"name": "Geänderter Stand"}
        response = http_case.client.patch(root, headers=headers(http_case.owner), json={
            "idempotency_key": str(uuid4()), "base_revision": connection["revision"], **delta})
    elif state == "cancelled":
        response = http_case.client.post(run_url + "/cancel", headers=headers(http_case.owner), json={
            "idempotency_key": str(uuid4()), "base_revision": run["revision"], "reason": "Synthetisch abgebrochen"})
    else:
        response = http_case.client.post(run_url + "/dispatch", headers=headers(http_case.owner), json={
            "idempotency_key": str(uuid4()), "base_revision": run["revision"], "confirm": True})
    assert response.status_code == 200, response.text
    current = http_case.client.get(run_url, headers=headers(http_case.owner))
    assert current.status_code == 200, current.text
    assert current.json()["can_dispatch"] is False


def test_owner_can_cancel_another_actors_run_but_cannot_advertise_dispatch(http_case):
    connection = create_connection(http_case, http_case.manager)
    run = prepare_run(http_case, connection, http_case.manager)
    url = f"/api/v1/integration-connections/{connection['id']}/runs/{run['id']}"
    response = http_case.client.get(url, headers=headers(http_case.owner))
    assert response.status_code == 200, response.text
    assert response.json()["can_dispatch"] is False
    assert response.json()["can_cancel"] is True
    cancelled = http_case.client.post(url + "/cancel", headers=headers(http_case.owner), json={
        "idempotency_key": str(uuid4()), "base_revision": run["revision"], "reason": "Nur die weitere Ausführung stoppen"})
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["state"] == "cancelled" and cancelled.json()["can_cancel"] is False
    assert http_case.provider.calls == []


def test_revoked_write_role_cannot_advertise_run_commands(http_case):
    connection = create_connection(http_case, http_case.manager)
    run = prepare_run(http_case, connection, http_case.manager)
    auth.update_user(http_case.manager.id, {"role": "readonly"})
    response = http_case.client.get(f"/api/v1/integration-connections/{connection['id']}/runs/{run['id']}", headers=headers(http_case.manager))
    assert response.status_code == 200, response.text
    assert response.json()["can_dispatch"] is False and response.json()["can_cancel"] is False
    assert http_case.provider.calls == []


def test_required_whitespace_is_not_a_configured_connection(http_case):
    response = http_case.client.post("/api/v1/integration-connections", headers=headers(http_case.owner), json={
        "idempotency_key": str(uuid4()), "provider_id": "proof", "name": "Leerraum ist kein Zugang", "enabled": True,
        "config": {"endpoint": "   ", "api_token": "REVIEW-SECRET"}})
    assert response.status_code == 422, response.text
    assert http_case.service.list(http_case.owner.id)["total"] == 0
    assert http_case.provider.calls == []


def test_inactive_portal_can_be_saved_as_an_incomplete_draft_without_becoming_configured(http_case):
    response = http_case.client.post("/api/v1/integration-connections", headers=headers(http_case.owner), json={
        "idempotency_key": str(uuid4()), "provider_id": "listing-portals", "name": "Noch unvollständiger Entwurf",
        "enabled": False, "config": {"default_portal": "is24"}})
    assert response.status_code == 201, response.text
    assert response.json()["configured"] is False and response.json()["enabled"] is False
    assert http_case.provider.calls == []


def test_legacy_result_and_history_never_reveal_configured_secrets_even_when_the_provider_echoes_them(http_case):
    secret = "REVIEW-SECRET-RESPONSE-ECHO"
    http_case.registry.update_config("proof", {"endpoint": "synthetic.invalid", "api_token": secret})
    http_case.registry.set_enabled("proof", True)
    http_case.provider.callback = lambda _payload, _config: IntegrationActionResult(
        True, "Provider echoed " + secret, {"authorization": secret, "echo": "Nested " + secret})
    response = http_case.client.post("/api/v1/integrations/proof/run", headers=headers(http_case.owner), json={"payload": {"action": "read"}})
    assert response.status_code == 200, response.text
    assert secret not in response.text
    history = http_case.client.get("/api/v1/integrations/proof/history", headers=headers(http_case.owner))
    assert history.status_code == 200 and secret not in history.text
    assert len(http_case.provider.calls) == 1


def test_legacy_unknown_loaded_credentials_are_not_returned_in_configuration(http_case):
    secret = "REVIEW-UNKNOWN-FUTURE-SECRET"
    http_case.registry._store.save({"enabled": {}, "config": {"proof": {
        "endpoint": "synthetic.invalid", "api_token": "KNOWN-REVIEW-SECRET", "future_credentials": {"api_token": secret}}}})
    http_case.registry._load_state()
    response = http_case.client.get("/api/v1/integrations/proof", headers=headers(http_case.owner))
    assert response.status_code == 200, response.text
    assert secret not in response.text
    assert "future_credentials" not in response.json()["config"]
    assert http_case.provider.calls == []


@pytest.mark.parametrize("surface", ["connections", "legacy"])
def test_required_zero_and_false_are_present_values_and_typed_action_values_remain_exact(http_case, surface):
    config = {"number": 0, "flag": False}
    if surface == "legacy":
        response = http_case.client.put("/api/v1/integrations/typed-proof/config", headers=headers(http_case.owner), json={"config": config})
        assert response.status_code == 200, response.text
        assert response.json()["configured"] is True
        return
    response = http_case.client.post("/api/v1/integration-connections", headers=headers(http_case.owner), json={
        "idempotency_key": str(uuid4()), "provider_id": "typed-proof", "name": "Null ist ein Wert", "enabled": True, "config": config})
    assert response.status_code == 201, response.text
    connection = response.json()
    assert connection["configured"] is True and connection["config"] == config
    root = f"/api/v1/integration-connections/{connection['id']}/runs"
    payload = {"amount": 0.25, "approved": False, "optional_label": None, "messages": [{"body": "Synthetische Nachricht"}]}
    prepared = http_case.client.post(root, headers=headers(http_case.owner), json={
        "idempotency_key": str(uuid4()), "config_revision": 1, "action": "read", "payload": payload})
    assert prepared.status_code == 201, prepared.text
    preview = http_case.client.get(root + "/" + prepared.json()["id"] + "/preview", headers=headers(http_case.owner))
    assert preview.status_code == 200, preview.text
    assert preview.json()["payload"] == {key: value for key, value in payload.items() if value is not None}
    assert http_case.typed.calls == []


@pytest.mark.parametrize("clear_on_update", [False, True])
def test_optional_null_resets_smtp_to_its_default_instead_of_disabling_starttls(http_case, monkeypatch, clear_on_update):
    from backend.services.integrations import providers
    captured = []
    def check_only(config):
        captured.append(config)
        return True
    monkeypatch.setattr(providers, "check_email_connection", check_only)
    response = http_case.client.post("/api/v1/integration-connections", headers=headers(http_case.owner), json={
        "idempotency_key": str(uuid4()), "provider_id": "email", "name": "Nur abgefangene Konfigurationsprüfung", "enabled": True,
        "config": {"sender_email": "sender@example.test", "smtp_host": "smtp.synthetic.invalid", "smtp_use_tls": False if clear_on_update else None}})
    assert response.status_code == 201, response.text
    connection = response.json()
    root = f"/api/v1/integration-connections/{connection['id']}"
    if clear_on_update:
        response = http_case.client.patch(root, headers=headers(http_case.owner), json={
            "idempotency_key": str(uuid4()), "base_revision": connection["revision"], "config": {"smtp_use_tls": None}})
        assert response.status_code == 200, response.text
        connection = response.json()
    run = http_case.client.post(root + "/runs", headers=headers(http_case.owner), json={
        "idempotency_key": str(uuid4()), "config_revision": connection["revision"], "action": "check_connection", "payload": {}}).json()
    result = http_case.client.post(root + "/runs/" + run["id"] + "/dispatch", headers=headers(http_case.owner), json={
        "idempotency_key": str(uuid4()), "base_revision": run["revision"], "confirm": True})
    assert result.status_code == 200, result.text
    assert result.json()["state"] == "completed"
    assert len(captured) == 1 and captured[0].smtp_use_tls is True
    assert "smtp_use_tls" not in connection["config"]


def test_legacy_persisted_null_is_normalized_on_reload_for_display_validation_and_transport(http_case, tmp_path, monkeypatch):
    from backend.services.integrations import providers
    config_store = JsonFileIntegrationConfigStore(str(tmp_path / "legacy-integrations.json"))
    observations = {"last_seen": None, "nested": {"remaining": None, "count": 0}}
    config_store.save({"enabled": {"email": True}, "config": {
        "email": {"sender_email": "sender@example.test", "smtp_host": "smtp.synthetic.invalid", "smtp_use_tls": None},
        "proof": {"observations": observations}}})
    original_bytes = (tmp_path / "legacy-integrations.json").read_bytes()
    reloaded = IntegrationManager(config_store, secret_box=http_case.service.box)
    reloaded.register(EmailIntegrationProvider())
    reloaded.register(ProbeProvider())
    reloaded._load_state()
    assert reloaded._config["proof"]["observations"] == observations
    monkeypatch.setattr(integrations, "integration_manager", reloaded)
    captured = []
    def check_only(config):
        captured.append(config)
        return True
    monkeypatch.setattr(providers, "check_email_connection", check_only)
    url = "/api/v1/integrations/email"
    displayed = http_case.client.get(url, headers=headers(http_case.owner))
    assert displayed.status_code == 200, displayed.text
    assert displayed.json()["configured"] is True and "smtp_use_tls" not in displayed.json()["config"]
    assert next(field for field in displayed.json()["config_fields"] if field["key"] == "smtp_use_tls")["default"] is True
    validated = http_case.client.post(url + "/validate", headers=headers(http_case.owner), json={"config": displayed.json()["config"]})
    assert validated.status_code == 200 and validated.json()["valid"] is True, validated.text
    result = http_case.client.post(url + "/run", headers=headers(http_case.owner), json={"payload": {"action": "check_connection"}})
    assert result.status_code == 200 and result.json()["success"] is True, result.text
    assert len(captured) == 1 and captured[0].smtp_use_tls is True
    assert (tmp_path / "legacy-integrations.json").read_bytes() == original_bytes
    assert reloaded._config["proof"]["observations"] == observations


def test_legacy_outcome_redaction_uses_the_invocation_snapshot_when_credentials_rotate_during_the_call(http_case):
    old_secret = "REVIEW-SECRET-BEFORE-ROTATION"
    new_secret = "REVIEW-SECRET-AFTER-ROTATION"
    http_case.registry.update_config("proof", {"endpoint": "synthetic.invalid", "api_token": old_secret})
    http_case.registry.set_enabled("proof", True)
    def rotate_and_echo(_payload, config):
        assert config["api_token"] == old_secret
        http_case.registry.update_config("proof", {"api_token": new_secret})
        assert config["api_token"] == old_secret
        return IntegrationActionResult(True, "Previous credential " + config["api_token"], {"echo": config["api_token"]})
    http_case.provider.callback = rotate_and_echo
    response = http_case.client.post("/api/v1/integrations/proof/run", headers=headers(http_case.owner), json={"payload": {"action": "read"}})
    assert response.status_code == 200 and response.json()["success"] is True, response.text
    history = http_case.client.get("/api/v1/integrations/proof/history", headers=headers(http_case.owner))
    assert history.status_code == 200, history.text
    assert all(secret not in response.text + history.text for secret in (old_secret, new_secret))
    assert old_secret not in str(http_case.registry._journal.list("proof"))
    assert http_case.registry._config["proof"]["api_token"] == new_secret
    assert len(http_case.provider.calls) == 1


def test_historical_provider_echo_is_redacted_for_a_reader_without_rewriting_the_original_journal(http_case):
    secret = "REVIEW-HISTORICAL-SECRET"
    http_case.registry.update_config("proof", {"endpoint": "synthetic.invalid", "api_token": secret})
    http_case.registry._journal.append(IntegrationRunRecord("proof", True, "Old " + secret, {}, {"authorization": secret, "echo": secret}))
    reader = auth.register_user("surface-reader", "surface-reader@example.test", "Lesekonto", "Secret123", "readonly")
    auth.update_user(reader.id, {"portfolio_access": "all", "portfolio_ids": []})
    response = http_case.client.get("/api/v1/integrations/proof/history", headers=headers(reader))
    assert response.status_code == 200, response.text
    assert secret not in response.text
    assert secret in str(http_case.registry._journal.list("proof"))
    assert http_case.provider.calls == []


@pytest.mark.parametrize("action", ["read", "send"])
def test_expired_lease_has_a_separate_recovery_command_that_does_not_contact_the_provider(http_case, monkeypatch, action):
    from fastapi import HTTPException
    connection = create_connection(http_case)
    run = prepare_run(http_case, connection, action=action)
    url = f"/api/v1/integration-connections/{connection['id']}/runs/{run['id']}"
    def interrupted(*_args, **_kwargs):
        raise HTTPException(503, "Synthetischer Ausfall nach dem lokalen Anbieterergebnis")
    with monkeypatch.context() as change:
        change.setattr(http_case.service, "_finish", interrupted)
        failed = http_case.client.post(url + "/dispatch", headers=headers(http_case.owner), json={
            "idempotency_key": str(uuid4()), "base_revision": run["revision"], "confirm": True})
    assert failed.status_code == 503 and len(http_case.provider.calls) == 1
    with storage.work(store, http_case.owner.id, write=True) as unit:
        record = storage.row(unit, IntegrationActionRunORM, run["id"], lock=True)
        storage.put(unit, IntegrationActionRunORM, {**storage.values(record), "lease_until": storage.now() - timedelta(seconds=1)})
    current = http_case.client.get(url, headers=headers(http_case.owner)).json()
    assert current["interrupted"] is True and current["can_dispatch"] is False and current["can_cancel"] is False
    assert current["can_recover_interrupted"] is True
    recovered = http_case.client.post(url + "/dispatch", headers=headers(http_case.owner), json={
        "idempotency_key": str(uuid4()), "base_revision": current["revision"], "confirm": True})
    assert recovered.status_code == 200, recovered.text
    assert recovered.json()["state"] == ("unknown" if action == "send" else "retryable")
    assert recovered.json()["can_recover_interrupted"] is False
    assert recovered.json()["can_dispatch"] is (action == "read")
    assert len(http_case.provider.calls) == 1


def test_unreadable_connection_disables_dispatch_but_still_allows_safe_cancellation(http_case):
    connection = create_connection(http_case)
    run = prepare_run(http_case, connection)
    with storage.work(store, http_case.owner.id, write=True) as unit:
        record = storage.row(unit, IntegrationConnectionORM, connection["id"], lock=True)
        storage.put(unit, IntegrationConnectionORM, {**storage.values(record), "config_token": "SYNTHETIC-CORRUPT-TOKEN"})
    response = http_case.client.get(f"/api/v1/integration-connections/{connection['id']}/runs/{run['id']}", headers=headers(http_case.owner))
    assert response.status_code == 200, response.text
    assert response.json()["can_dispatch"] is False and response.json()["can_cancel"] is True
    assert http_case.provider.calls == []


def test_http_idempotency_and_portfolio_revocation_prevent_a_second_provider_call(http_case):
    connection = create_connection(http_case, http_case.manager)
    run = prepare_run(http_case, connection, http_case.manager)
    url = f"/api/v1/integration-connections/{connection['id']}/runs/{run['id']}"
    command = {"idempotency_key": str(uuid4()), "base_revision": run["revision"], "confirm": True}
    first = http_case.client.post(url + "/dispatch", headers=headers(http_case.manager), json=command)
    assert first.status_code == 200, first.text
    again = http_case.client.post(url + "/dispatch", headers=headers(http_case.manager), json=command)
    assert again.status_code == 200 and again.json() == first.json() and len(http_case.provider.calls) == 1
    auth.update_user(http_case.manager.id, {"portfolio_access": "selected", "portfolio_ids": []})
    assert http_case.client.get(url, headers=headers(http_case.manager)).status_code == 403
    assert http_case.client.post(url + "/dispatch", headers=headers(http_case.manager), json=command).status_code == 403
    assert len(http_case.provider.calls) == 1


def test_actual_hf_message_schema_accepts_json_objects_without_loading_models(http_case, monkeypatch):
    from backend.services.integrations.huggingface import HuggingFaceProvider
    provider = HuggingFaceProvider()
    captured = []
    def local(payload, _config):
        captured.append(payload)
        return IntegrationActionResult(True, "Synthetische Schema-Prüfung", {"count": len(payload["messages"])})
    monkeypatch.setattr(provider, "run", local)
    http_case.registry.register(provider)
    payload = {"action": "summarize", "messages": [{"body": "Synthetische Nachricht"}], "subject": "Nur Typprüfung"}
    response = http_case.client.post("/api/v1/integrations/huggingface/run", headers=headers(http_case.owner), json={"payload": payload})
    assert response.status_code == 200 and response.json()["success"] is True, response.text
    assert captured == [payload]


def test_teha_public_labels_preserve_field_keys_and_both_credential_secret_flags(http_case):
    from backend.services.providers.teha_provider import TehaProvider
    http_case.registry.register(TehaProvider())
    response = http_case.client.get("/api/v1/integration-connections/catalog", headers=headers(http_case.owner))
    assert response.status_code == 200, response.text
    manifest = next(item for item in response.json()["providers"] if item["provider_id"] == "teha")
    fields = {field["key"]: field for field in manifest["config_fields"]}
    assert fields["username"]["label"] == "Benutzername" and fields["username"]["secret"] is True
    assert fields["password"]["label"] == "Passwort" and fields["password"]["secret"] is True
    inputs = {field["key"]: field for action in manifest["actions"] for field in action["inputs"]}
    assert {key: inputs[key]["label"] for key in ("lieg_nr", "reference", "termin_id")} == {
        "lieg_nr": "Liegenschaftsnummer", "reference": "Dokumentreferenz", "termin_id": "Termin-ID"}
    assert all(action["effect"] == "read" for action in manifest["actions"])
