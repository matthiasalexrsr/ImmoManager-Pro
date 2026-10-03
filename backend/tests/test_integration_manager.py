import pytest

from backend.services.integrations.config_store import InMemoryIntegrationConfigStore
from backend.services.integrations.manager import IntegrationManager
from backend.services.integrations.providers import (
    ContractWizardProvider,
    ListingPortalProvider,
    WhatsAppIntegrationProvider,
)
from backend.tests.test_integration_history_core import ACTOR  # noqa: F401
from backend.tests.test_integration_history_core import journal as journal


@pytest.fixture
def manager_factory(journal):
    def create(store=None):
        return IntegrationManager(store=store, history_store=journal[0], history_actor=ACTOR)
    return create


def test_manager_records_history_for_disabled_run(manager_factory):
    manager = manager_factory()
    manager.register(ContractWizardProvider())

    manager.set_enabled("contract-wizard", False)
    result = manager.run("contract-wizard", {"tenant_name": "T"})
    assert result["success"] is False
    assert "deaktiviert" in result["message"].lower()

    history = manager.list_history("contract-wizard")
    assert len(history) == 1
    assert history[0]["success"] is False


def test_secret_config_is_masked_in_output_and_persisted(manager_factory):
    store = InMemoryIntegrationConfigStore()
    manager = manager_factory(store)
    manager.register(WhatsAppIntegrationProvider())

    manager.update_config("whatsapp", {"phone_number_id": "123", "api_token": "secret"})
    details = manager.get_integration("whatsapp")

    assert details["configured"] is True
    assert details["config"]["api_token"] == "***"

    raw = store.load()
    assert raw["config"]["whatsapp"]["api_token"] == "secret"


def test_listing_portal_provider_reports_unimplemented_adapter(manager_factory):
    manager = manager_factory()
    manager.register(ListingPortalProvider())
    manager.set_enabled("listing-portals", True)
    manager.update_config("listing-portals", {"default_portal": "Immowelt"})

    result = manager.run("listing-portals", {"action": "update", "listing": {"title": "L1"}})
    assert result["success"] is False
    assert "nicht implementiert" in result["message"]


def test_saved_credentials_do_not_make_planned_providers_operational(manager_factory):
    manager = manager_factory()
    manager.seed_defaults()
    for integration_id, config in (
        ("whatsapp", {"phone_number_id": "synthetic", "api_token": "synthetic"}),
        ("deutsche-post", {"api_key": "synthetic"}),
        ("listing-portals", {"default_portal": "Immowelt"}),
    ):
        manager.set_enabled(integration_id, True)
        manager.update_config(integration_id, config)
        detail = manager.get_integration(integration_id)
        assert detail["configured"] is True
        assert detail["planned"] is True
        assert detail["operational"] is False
        assert detail["health"]["status"] == "planned"
        assert manager.run(integration_id, {"action": "status", "portal_listing_id": "synthetic"})["success"] is False


def test_metrics_counts_runs(manager_factory):
    manager = manager_factory()
    manager.register(ContractWizardProvider())
    manager.set_enabled("contract-wizard", True)
    manager.run("contract-wizard", {"tenant_name": "A"})

    metrics = manager.get_metrics()
    assert metrics["runs_total"] == 1
    assert metrics["runs_successful"] == 1
