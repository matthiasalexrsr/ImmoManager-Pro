"""Integration registry, configuration, and execution manager."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict

from .base import IntegrationProvider, IntegrationRunRecord
from .providers import (
    ContractWizardProvider,
    DeutschePostProvider,
    EmailIntegrationProvider,
    ListingPortalProvider,
    WhatsAppIntegrationProvider,
)


class IntegrationManager:
    def __init__(self) -> None:
        self._providers: dict[str, IntegrationProvider] = {}
        self._enabled: dict[str, bool] = {}
        self._config: dict[str, dict] = {}
        self._history: dict[str, list[IntegrationRunRecord]] = defaultdict(list)

    def register(self, provider: IntegrationProvider) -> None:
        integration_id = provider.manifest.integration_id
        self._providers[integration_id] = provider
        self._enabled.setdefault(integration_id, provider.manifest.enabled_by_default)
        self._config.setdefault(integration_id, {})

    def seed_defaults(self) -> None:
        for provider in (
            EmailIntegrationProvider(),
            WhatsAppIntegrationProvider(),
            ContractWizardProvider(),
            DeutschePostProvider(),
            ListingPortalProvider(),
        ):
            self.register(provider)

    def list_integrations(self) -> list[dict]:
        result = []
        for integration_id in sorted(self._providers.keys()):
            result.append(self.get_integration(integration_id))
        return result

    def get_integration(self, integration_id: str) -> dict:
        provider = self._providers.get(integration_id)
        if provider is None:
            raise KeyError(integration_id)

        manifest = provider.manifest
        config = self._config.get(integration_id, {})
        health = provider.health(config)
        configured = provider.is_configured(config)
        return {
            "id": manifest.integration_id,
            "name": manifest.name,
            "category": manifest.category,
            "description": manifest.description,
            "planned": manifest.planned,
            "enabled": self._enabled.get(integration_id, False),
            "configured": configured,
            "capabilities": manifest.capabilities,
            "health": health,
            "config": config,
            "message": self._to_message(
                configured=configured,
                enabled=self._enabled.get(integration_id, False),
                health=health,
            ),
        }

    def set_enabled(self, integration_id: str, enabled: bool) -> dict:
        if integration_id not in self._providers:
            raise KeyError(integration_id)
        self._enabled[integration_id] = enabled
        return {"id": integration_id, "enabled": enabled}

    def update_config(self, integration_id: str, config_updates: dict) -> dict:
        if integration_id not in self._providers:
            raise KeyError(integration_id)
        current = self._config.setdefault(integration_id, {})
        current.update(config_updates)
        return {"id": integration_id, "config": current}

    def run(self, integration_id: str, payload: dict) -> dict:
        provider = self._providers.get(integration_id)
        if provider is None:
            raise KeyError(integration_id)

        if not self._enabled.get(integration_id, False):
            result = {"success": False, "message": "Integration ist deaktiviert"}
            self._append_history(integration_id, payload, result)
            return result

        config = self._config.get(integration_id, {})
        action = provider.run(payload, config)
        result = {"success": action.success, "message": action.message, "details": action.details}
        self._append_history(integration_id, payload, result)
        return result

    def list_history(self, integration_id: str, limit: int = 20) -> list[dict]:
        if integration_id not in self._providers:
            raise KeyError(integration_id)
        entries = self._history.get(integration_id, [])[-limit:]
        return [asdict(e) for e in reversed(entries)]

    def _append_history(self, integration_id: str, payload: dict, result: dict) -> None:
        record = IntegrationRunRecord(
            integration_id=integration_id,
            success=bool(result.get("success")),
            message=result.get("message", ""),
            payload=payload,
            details=result.get("details"),
        )
        self._history[integration_id].append(record)
        # keep memory bounded
        if len(self._history[integration_id]) > 200:
            self._history[integration_id] = self._history[integration_id][-200:]

    @staticmethod
    def _to_message(*, configured: bool, enabled: bool, health: dict) -> str:
        health_state = health.get("status", "unknown")
        if not enabled:
            return "Deaktiviert"
        if not configured:
            return "Konfiguration erforderlich"
        if health_state in {"ok", "configured"}:
            return "Aktiv"
        return "Aktiv (eingeschränkt)"


integration_manager = IntegrationManager()
integration_manager.seed_defaults()
