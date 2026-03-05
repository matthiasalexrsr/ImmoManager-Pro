"""Integration registry, configuration, and execution manager."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict

from ...config import settings
from .base import IntegrationProvider, IntegrationRunRecord
from .config_store import InMemoryIntegrationConfigStore, JsonFileIntegrationConfigStore
from .providers import (
    ContractWizardProvider,
    DeutschePostProvider,
    EmailIntegrationProvider,
    ListingPortalProvider,
    WhatsAppIntegrationProvider,
)


class IntegrationManager:
    def __init__(self, store=None) -> None:
        self._providers: dict[str, IntegrationProvider] = {}
        self._enabled: dict[str, bool] = {}
        self._config: dict[str, dict] = {}
        self._history: dict[str, list[IntegrationRunRecord]] = defaultdict(list)
        self._store = store or InMemoryIntegrationConfigStore()

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
        self._load_state()

    def list_integrations(self) -> list[dict]:
        return [self.get_integration(integration_id) for integration_id in sorted(self._providers.keys())]

    def list_categories(self) -> list[str]:
        categories = {provider.manifest.category for provider in self._providers.values()}
        return sorted(categories)

    def get_integration(self, integration_id: str) -> dict:
        provider = self._providers.get(integration_id)
        if provider is None:
            raise KeyError(integration_id)

        manifest = provider.manifest
        config = self._config.get(integration_id, {})
        health = provider.health(config)
        enabled = self._enabled.get(integration_id, False)
        configured = provider.is_configured(config)
        return {
            "id": manifest.integration_id,
            "name": manifest.name,
            "category": manifest.category,
            "description": manifest.description,
            "planned": manifest.planned,
            "enabled": enabled,
            "configured": configured,
            "capabilities": manifest.capabilities,
            "health": health,
            "config": self._safe_config(manifest, config),
            "required_config_keys": manifest.required_config_keys,
            "secret_config_keys": manifest.secret_config_keys,
            "message": self._to_message(configured=configured, enabled=enabled, health=health),
        }

    def get_schema(self, integration_id: str) -> dict:
        provider = self._providers.get(integration_id)
        if provider is None:
            raise KeyError(integration_id)
        manifest = provider.manifest
        return {
            "id": manifest.integration_id,
            "required_config_keys": manifest.required_config_keys,
            "secret_config_keys": manifest.secret_config_keys,
            "capabilities": manifest.capabilities,
        }

    def validate_config(self, integration_id: str, config: dict) -> dict:
        provider = self._providers.get(integration_id)
        if provider is None:
            raise KeyError(integration_id)
        if not isinstance(config, dict):
            return {"valid": False, "missing_keys": [], "message": "Konfiguration muss ein Objekt sein"}

        manifest = provider.manifest
        missing = [k for k in manifest.required_config_keys if not config.get(k)]
        if missing:
            return {"valid": False, "missing_keys": missing, "message": "Pflichtfelder fehlen"}
        return {"valid": True, "missing_keys": [], "message": "Konfiguration ist gültig"}

    def set_enabled(self, integration_id: str, enabled: bool) -> dict:
        if integration_id not in self._providers:
            raise KeyError(integration_id)
        self._enabled[integration_id] = enabled
        self._persist_state()
        return {"id": integration_id, "enabled": enabled}

    def update_config(self, integration_id: str, config_updates: dict) -> dict:
        if integration_id not in self._providers:
            raise KeyError(integration_id)
        if not isinstance(config_updates, dict):
            raise ValueError("Config updates must be a dictionary")
        current = self._config.setdefault(integration_id, {})
        current.update(config_updates)
        self._persist_state()
        manifest = self._providers[integration_id].manifest
        return {"id": integration_id, "config": self._safe_config(manifest, current)}

    def run(self, integration_id: str, payload: dict) -> dict:
        provider = self._providers.get(integration_id)
        if provider is None:
            raise KeyError(integration_id)

        if not self._enabled.get(integration_id, False):
            result = {"success": False, "message": "Integration ist deaktiviert"}
            self._append_history(integration_id, payload, result)
            return result

        config = self._config.get(integration_id, {})
        validation = self.validate_config(integration_id, config)
        if not validation.get("valid"):
            result = {
                "success": False,
                "message": validation.get("message", "Ungültige Konfiguration"),
                "details": validation,
            }
            self._append_history(integration_id, payload, result)
            return result

        action = provider.run(payload, config)
        result = {"success": action.success, "message": action.message, "details": action.details}
        self._append_history(integration_id, payload, result)
        return result

    def list_history(self, integration_id: str, limit: int = 20) -> list[dict]:
        if integration_id not in self._providers:
            raise KeyError(integration_id)
        entries = self._history.get(integration_id, [])[-limit:]
        return [asdict(e) for e in reversed(entries)]

    def clear_history(self, integration_id: str) -> dict:
        if integration_id not in self._providers:
            raise KeyError(integration_id)
        count = len(self._history.get(integration_id, []))
        self._history[integration_id] = []
        return {"id": integration_id, "cleared": count}

    def get_metrics(self) -> dict:
        total = len(self._providers)
        enabled = sum(1 for k in self._providers if self._enabled.get(k, False))
        configured = sum(
            1 for k, provider in self._providers.items() if provider.is_configured(self._config.get(k, {}))
        )
        runs_total = sum(len(v) for v in self._history.values())
        successful = sum(1 for runs in self._history.values() for r in runs if r.success)
        failed = runs_total - successful
        return {
            "total_integrations": total,
            "enabled_integrations": enabled,
            "configured_integrations": configured,
            "runs_total": runs_total,
            "runs_successful": successful,
            "runs_failed": failed,
            "categories": self.list_categories(),
        }

    def _append_history(self, integration_id: str, payload: dict, result: dict) -> None:
        record = IntegrationRunRecord(
            integration_id=integration_id,
            success=bool(result.get("success")),
            message=result.get("message", ""),
            payload=payload,
            details=result.get("details"),
        )
        self._history[integration_id].append(record)
        if len(self._history[integration_id]) > 200:
            self._history[integration_id] = self._history[integration_id][-200:]

    def _persist_state(self) -> None:
        self._store.save({"enabled": self._enabled, "config": self._config})

    def _load_state(self) -> None:
        state = self._store.load()
        enabled = state.get("enabled", {}) if isinstance(state, dict) else {}
        config = state.get("config", {}) if isinstance(state, dict) else {}
        if isinstance(enabled, dict):
            for integration_id, value in enabled.items():
                if integration_id in self._providers and isinstance(value, bool):
                    self._enabled[integration_id] = value
        if isinstance(config, dict):
            for integration_id, value in config.items():
                if integration_id in self._providers and isinstance(value, dict):
                    self._config[integration_id] = value

    @staticmethod
    def _safe_config(manifest, config: dict) -> dict:
        masked = dict(config)
        for key in manifest.secret_config_keys:
            if key in masked and masked[key]:
                masked[key] = "***"
        return masked

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


_config_store = (
    JsonFileIntegrationConfigStore(settings.integration_state_file)
    if settings.integration_state_file
    else InMemoryIntegrationConfigStore()
)
integration_manager = IntegrationManager(store=_config_store)
integration_manager.seed_defaults()
