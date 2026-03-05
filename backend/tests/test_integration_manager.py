from backend.services.integrations.config_store import InMemoryIntegrationConfigStore
from backend.services.integrations.manager import IntegrationManager
from backend.services.integrations.providers import ContractWizardProvider, WhatsAppIntegrationProvider


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

    manager.update_config("whatsapp", {"phone_number_id": "123", "api_token": "secret"})
    details = manager.get_integration("whatsapp")

    assert details["configured"] is True
    assert details["config"]["api_token"] == "***"

    raw = store.load()
    assert raw["config"]["whatsapp"]["api_token"] == "secret"
