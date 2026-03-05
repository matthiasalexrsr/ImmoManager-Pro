from backend.services.integrations.manager import IntegrationManager
from backend.services.integrations.providers import ContractWizardProvider


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
