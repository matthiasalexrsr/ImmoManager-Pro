"""Backward-compatible facade for integrations manager."""

from .integrations.manager import integration_manager


class IntegrationServiceFacade:
    def list_status(self) -> list[dict]:
        return integration_manager.list_integrations()

    def toggle(self, integration_id: str, enabled: bool) -> dict:
        return integration_manager.set_enabled(integration_id, enabled)

    def run_action(self, integration_id: str, payload: dict) -> dict:
        return integration_manager.run(integration_id, payload)


integration_service = IntegrationServiceFacade()
