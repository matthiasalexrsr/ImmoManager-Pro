from backend.services.integrations.config_store import InMemoryIntegrationConfigStore
from backend.services.integrations.manager import IntegrationManager
from backend.services.integrations.providers import (
    ContractWizardProvider,
    ListingPortalProvider,
    WhatsAppIntegrationProvider,
)


def test_manager_records_history_for_disabled_run():
    manager = IntegrationManager()
    manager.register(ContractWizardProvider())

    manager.set_enabled("contract-wizard", False)
    result = manager.run("contract-wizard", {"tenant_name": "T"})
    assert result["success"] is False
    assert "deaktiviert" in result["message"].lower()

    history = manager.list_history("contract-wizard")
    assert len(history) == 1
    assert history[0]["success"] is False


def test_secret_config_is_masked_in_output_and_persisted():
    store = InMemoryIntegrationConfigStore()
    manager = IntegrationManager(store=store)
    manager.register(WhatsAppIntegrationProvider())

    manager.update_config("whatsapp", {"phone_number_id": "123", "api_token": "secret", 'graph_version': 'v26.0',
                                        'app_secret': 'synthetic-app', 'verify_token': 'synthetic-verify'})
    details = manager.get_integration("whatsapp")

    assert details["configured"] is True
    assert details["config"]["api_token"] == "***"

    raw = store.load()
    assert raw["config"]["whatsapp"]["api_token"] == "secret"


def test_listing_portal_provider_refuses_the_legacy_unbound_update_action():
    manager = IntegrationManager()
    manager.register(ListingPortalProvider())
    manager.set_enabled("listing-portals", True)

    result = manager.run("listing-portals", {"action": "update", "listing": {"title": "L1"}})
    assert result["success"] is False
    assert result['details']['code'] == 'invalid_payload'
    assert result['details']['errors']['action'] == 'Nicht unterstützte Aktion'
    assert manager.list_history('listing-portals')[0]['success'] is False


def test_metrics_counts_runs():
    manager = IntegrationManager()
    manager.register(ContractWizardProvider())
    manager.set_enabled("contract-wizard", True)
    manager.run("contract-wizard", {"tenant_name": "A"})

    metrics = manager.get_metrics()
    assert metrics["runs_total"] == 1
    assert metrics["runs_successful"] == 1
