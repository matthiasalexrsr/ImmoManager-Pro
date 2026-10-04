"""DDL-free connection-test and parameter-evidence contract."""

from dataclasses import dataclass
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.routers import integrations as integrations_router
from backend.services import checked_publication
from backend.services.integrations.base import IntegrationManifest
from backend.services.integrations.config_store import (
    ConfigStoreError,
    InMemoryIntegrationConfigStore,
)
from backend.services.integrations.connection_contract import (
    ConnectionProbeResult,
    ParameterEvidence,
    accept_mapping,
    map_business_field,
    mark_observed,
)
from backend.services.integrations.manager import IntegrationManager
from backend.services.integrations.providers import EmailIntegrationProvider


def configured_email(manager: IntegrationManager) -> None:
    manager.update_config(
        "email",
        {
            "smtp_host": "smtp.synthetic.invalid",
            "smtp_port": 587,
            "smtp_user": "synthetic-user",
            "smtp_password": "SYNTHETIC_PASSWORD",
            "smtp_use_tls": True,
            "smtp_use_ssl": False,
            "sender_email": "sender@example.invalid",
        },
    )


def test_email_connection_test_never_sends_or_claims_network_probe(monkeypatch):
    manager = IntegrationManager(store=InMemoryIntegrationConfigStore())
    provider = EmailIntegrationProvider()
    manager.register(provider)
    configured_email(manager)

    def forbidden_run(*args, **kwargs):
        raise AssertionError("connection-test must never use the mail send action")

    monkeypatch.setattr(provider, "run", forbidden_run)
    result = manager.connection_test("email")

    assert result["status"] == "not_supported"
    assert result["configured"] is True
    assert result["probe_supported"] is False
    assert result["network_checked"] is False
    assert result["business_action_performed"] is False
    assert result["test_message_sent"] is False
    assert result["details"]["mail_test_policy"] == "explicit_outbox_recipient_only"
    assert result["details"]["automatic_external_retry"] is False


def test_invalid_connection_config_is_local_only():
    manager = IntegrationManager(store=InMemoryIntegrationConfigStore())
    manager.register(EmailIntegrationProvider())

    result = manager.connection_test("email")

    assert result["status"] == "configuration_invalid"
    assert result["configured"] is False
    assert result["network_checked"] is False
    assert result["test_message_sent"] is False
    assert result["details"]["validation"]["valid"] is False


@dataclass
class SyntheticProbeProvider:
    @property
    def manifest(self):
        return IntegrationManifest(
            integration_id="synthetic-probe",
            name="Synthetic Probe",
            category="test",
            description="Synthetic side-effect-free connection probe",
            required_config_keys=["endpoint"],
            secret_config_keys=["credential"],
        )

    def is_configured(self, config):
        return bool(config.get("endpoint"))

    def health(self, config):
        return {"status": "configured"}

    def run(self, payload, config):
        raise AssertionError("business action must not be used by connection-test")

    def probe_connection(self, config):
        assert config["endpoint"] == "synthetic.invalid"
        return ConnectionProbeResult(
            integration_id="synthetic-probe",
            status="checked",
            configured=True,
            probe_supported=True,
            network_checked=True,
            business_action_performed=False,
            test_message_sent=False,
            details={"transport": "synthetic-only"},
        )


def test_explicit_probe_contract_accepts_only_side_effect_free_result():
    manager = IntegrationManager(store=InMemoryIntegrationConfigStore())
    manager.register(SyntheticProbeProvider())
    manager.update_config(
        "synthetic-probe",
        {"endpoint": "synthetic.invalid", "credential": "synthetic-secret"},
    )

    result = manager.connection_test("synthetic-probe")

    assert result["status"] == "checked"
    assert result["network_checked"] is True
    assert result["business_action_performed"] is False
    assert result["test_message_sent"] is False


def test_parameter_stages_are_distinct_and_acceptance_requires_mapping():
    manager = IntegrationManager(store=InMemoryIntegrationConfigStore())
    manager.register(EmailIntegrationProvider())

    catalog = manager.parameter_catalog("email")
    password = next(
        item for item in catalog["items"] if item["name"] == "smtp_password"
    )

    assert catalog["stages"] == ["discovered", "observed", "mapped", "accepted"]
    assert password["secret"] is True
    assert password["discovered"] is True
    assert password["observed"] is False
    assert password["mapped"] is False
    assert password["accepted"] is False

    base = ParameterEvidence(
        name="external_object_id",
        location="response",
        discovered=True,
        evidence_source="public-client-catalog:v1",
    )
    with pytest.raises(ValueError):
        accept_mapping(base, source="human-review")

    observed = mark_observed(base, source="synthetic-import-fixture")
    assert observed.observed is True and observed.mapped is False
    mapped = map_business_field(
        observed,
        business_field="provider_object_mapping.external_id",
        source="mapping-review",
    )
    assert mapped.mapped is True and mapped.accepted is False
    accepted = accept_mapping(mapped, source="explicit-acceptance")
    assert accepted.accepted is True


def test_probe_result_that_claims_business_action_is_rejected():
    @dataclass
    class BadProvider(SyntheticProbeProvider):
        def probe_connection(self, config):
            return ConnectionProbeResult(
                integration_id="synthetic-probe",
                status="checked",
                configured=True,
                probe_supported=True,
                network_checked=True,
                business_action_performed=True,
                test_message_sent=False,
                details={},
            )

    manager = IntegrationManager(store=InMemoryIntegrationConfigStore())
    manager.register(BadProvider())
    manager.update_config(
        "synthetic-probe",
        {"endpoint": "synthetic.invalid", "credential": "synthetic-secret"},
    )

    with pytest.raises(ValueError, match="side-effect-free"):
        manager.connection_test("synthetic-probe")


def test_connection_state_cas_preserves_masked_secret_and_unknown_fields():
    store = InMemoryIntegrationConfigStore()
    manager = IntegrationManager(store=store)
    manager.register(EmailIntegrationProvider())
    manager.update_config(
        "email",
        {
            "smtp_host": "smtp.synthetic.invalid",
            "sender_email": "sender@example.invalid",
            "smtp_password": "SYNTHETIC_CAS_PASSWORD",
            "unknown": {"provider_field": "preserve-me"},
        },
    )

    state = manager.connection_state("email")
    assert state["config"]["smtp_password"] == "***"
    assert state["config"]["unknown"] == {"provider_field": "preserve-me"}

    changed = manager.update_connection_state(
        "email",
        expected_revision=state["revision"],
        enabled=True,
        config_updates={
            "smtp_password": "***",
            "unknown": {
                "provider_field": "preserve-me",
                "late_field": "new-observation",
            },
        },
    )
    assert changed["revision"] != state["revision"]
    assert changed["enabled"] is True
    assert changed["config"]["smtp_password"] == "***"
    raw = store.load()
    assert raw["config"]["email"]["smtp_password"] == "SYNTHETIC_CAS_PASSWORD"
    assert raw["config"]["email"]["unknown"] == {
        "provider_field": "preserve-me",
        "late_field": "new-observation",
    }

    before = store.load()
    with pytest.raises(ConfigStoreError) as failure:
        manager.update_connection_state(
            "email",
            expected_revision=state["revision"],
            config_updates={"smtp_host": "stale.invalid"},
        )
    assert failure.value.code == "state_revision_conflict"
    assert store.load() == before


def test_connection_state_http_exposes_revision_and_maps_stale_cas_to_412(
    monkeypatch,
):
    store = InMemoryIntegrationConfigStore()
    manager = IntegrationManager(store=store)
    manager.register(EmailIntegrationProvider())
    configured_email(manager)

    monkeypatch.setattr(integrations_router, "integration_manager", manager)
    async def fake_security(_request):
        return SimpleNamespace(credentials="synthetic-access")

    monkeypatch.setattr(checked_publication, "current_scope", lambda: object())
    monkeypatch.setattr(checked_publication, "refresh_scope", lambda captured: captured)
    monkeypatch.setattr(checked_publication, "security", fake_security)
    monkeypatch.setattr(
        checked_publication,
        "decode_token",
        lambda _token: SimpleNamespace(type="access"),
    )

    app = FastAPI()
    app.include_router(integrations_router.router)
    app.dependency_overrides[
        integrations_router._require_integration_administration
    ] = lambda: None
    client = TestClient(app)

    current = client.get("/integrations/email/connection-state")
    assert current.status_code == 200
    payload = current.json()
    assert payload["config"]["smtp_password"] == "***"
    assert len(payload["revision"]) == 64

    updated = client.patch(
        "/integrations/email/connection-state",
        json={
            "expected_revision": payload["revision"],
            "enabled": True,
            "config": {"smtp_password": "***"},
        },
    )
    assert updated.status_code == 200
    assert updated.json()["revision"] != payload["revision"]

    stale = client.patch(
        "/integrations/email/connection-state",
        json={
            "expected_revision": payload["revision"],
            "config": {"smtp_host": "stale.invalid"},
        },
    )
    assert stale.status_code == 412
    assert stale.json()["detail"]["code"] == "state_revision_conflict"
