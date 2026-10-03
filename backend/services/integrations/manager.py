"""Integration registry, configuration, and execution manager."""

from __future__ import annotations

from copy import deepcopy

from ...config import settings
from .base import IntegrationProvider
from .config_store import InMemoryIntegrationConfigStore, JsonFileIntegrationConfigStore
from .history_policy import preserve_config_masks, public_config, request_observation, response_observation
from .history_store import configured_history
from .history_types import HistoryActor, HistoryError
from .huggingface import HuggingFaceProvider
from .providers import (
    ContractWizardProvider,
    DeutschePostProvider,
    EmailIntegrationProvider,
    ListingPortalProvider,
    WhatsAppIntegrationProvider,
)


class IntegrationManager:
    def __init__(self, store=None, *, history_store=None, history_actor=None) -> None:
        self._providers: dict[str, IntegrationProvider] = {}
        self._store = store or InMemoryIntegrationConfigStore()
        self._history_store = history_store
        self._history_actor = history_actor

    def _journal(self):
        return self._history_store if self._history_store is not None else configured_history()

    def _actor(self):
        return self._history_actor or HistoryActor.authenticated()

    def register(self, provider: IntegrationProvider) -> None:
        integration_id = provider.manifest.integration_id
        self._providers[integration_id] = provider

    def seed_defaults(self) -> None:
        for provider in (
            EmailIntegrationProvider(),
            WhatsAppIntegrationProvider(),
            ContractWizardProvider(),
            DeutschePostProvider(),
            ListingPortalProvider(),
            HuggingFaceProvider(),
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
        enabled, config = self._snapshot(integration_id)
        health = provider.health(config)
        configured = provider.is_configured(config)
        return {
            "id": manifest.integration_id,
            "name": manifest.name,
            "category": manifest.category,
            "description": manifest.description,
            "planned": manifest.planned,
            "enabled": enabled,
            "configured": configured,
            "operational": not manifest.planned and enabled and configured and health.get("status") == "ok",
            "capabilities": manifest.capabilities,
            "health": health,
            "config": self._safe_config(manifest, config),
            "required_config_keys": manifest.required_config_keys,
            "secret_config_keys": manifest.secret_config_keys,
            "message": "Geplant — Adapter noch nicht implementiert" if manifest.planned else self._to_message(configured=configured, enabled=enabled, health=health),
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
        if integration_id == "email" and not provider.is_configured(config):
            return {"valid": False, "missing_keys": [], "message": "SMTP-Konfiguration ist unvollständig oder ungültig"}
        return {"valid": True, "missing_keys": [], "message": "Konfiguration ist gültig"}

    def set_enabled(self, integration_id: str, enabled: bool) -> dict:
        if integration_id not in self._providers:
            raise KeyError(integration_id)
        self._store.update(lambda state: {**state, "enabled": {**state.get("enabled", {}), integration_id: enabled}})
        return {"id": integration_id, "enabled": enabled}

    def update_config(self, integration_id: str, config_updates: dict) -> dict:
        if integration_id not in self._providers:
            raise KeyError(integration_id)
        if not isinstance(config_updates, dict):
            raise ValueError("Config updates must be a dictionary")
        manifest = self._providers[integration_id].manifest
        updates = deepcopy(config_updates)
        def merge(state):
            current = state.setdefault("config", {}).setdefault(integration_id, {})
            current.update(preserve_config_masks(updates, current, manifest))
            return state
        current = self._store.update(merge)["config"][integration_id]
        return {"id": integration_id, "config": self._safe_config(manifest, current)}

    def run(self, integration_id: str, payload: dict) -> dict:
        provider = self._providers.get(integration_id)
        if provider is None:
            raise KeyError(integration_id)

        enabled, config = self._snapshot(integration_id)
        actor = self._actor()
        journal = self._journal()
        request, schema, known_secrets = request_observation(integration_id, payload, config, provider.manifest)
        ticket = journal.accept(integration_id, actor, request, schema)

        def finish(result, state):
            safe, response_schema = response_observation(result, known_secrets)
            journal.append(ticket, state, {"response": safe, "schema": response_schema})
            return {**safe, "run_id": ticket.run_id, "history_status": state, "history_recorded": True}

        if not enabled:
            result = {"success": False, "message": "Integration ist deaktiviert"}
            return finish(result, "rejected")

        if provider.manifest.planned:
            result = {"success": False, "message": "Adapter noch nicht implementiert; keine externe Aktion ausgeführt", "details": {"planned": True, "implemented": False}}
            return finish(result, "rejected")
        validation = self.validate_config(integration_id, config)
        if integration_id != "email" and not validation.get("valid"):
            result = {
                "success": False,
                "message": validation.get("message", "Ungültige Konfiguration"),
                "details": validation,
            }
            return finish(result, "rejected")

        journal.append(ticket, "execution_started", actor=actor)
        try:
            actor.refresh()
        except Exception:
            # No provider action has begun. Retain the accepted audit, but
            # preserve the original scope/auth denial for the HTTP caller.
            journal.append(ticket, "outcome_uncertain", {"response": {"success": False,
                "message": "Rechteprüfung vor Anbieteraufruf fehlgeschlagen; keine Aktion gestartet.",
                "details": {"status": "not_sent", "code": "actor_revoked_before_provider", "retry_automatically": False}}, "schema": {"version": 1}})
            raise
        try:
            action = provider.run(payload, config)
        except Exception:
            # Free provider exceptions can contain passwords/payloads. Do not
            # log or expose them; an effect may have happened before the crash.
            return finish({"success": False, "message": "Das Anbieterergebnis ist ungewiss. Vor einer Wiederholung prüfen.",
                "details": {"status": "outcome_unconfirmed", "code": "provider_exception", "retry_automatically": False}}, "outcome_uncertain")
        result = {"success": action.success, "message": action.message, "details": action.details}
        try:
            return finish(result, "completed")
        except HistoryError as error:
            if error.code != "HISTORY_INPUT_INVALID":
                raise
            return finish({"success": False, "message": "Anbieterergebnis konnte nicht vollständig beobachtet werden. Vor einer Wiederholung prüfen.",
                "details": {"status": "outcome_unconfirmed", "code": "observation_failed", "retry_automatically": False}}, "observation_failed")

    def list_history(self, integration_id: str, limit: int = 20) -> list[dict]:
        if integration_id not in self._providers:
            raise KeyError(integration_id)
        return self.history_page(integration_id, limit=limit)["items"]

    def history_page(self, integration_id, **options):
        if integration_id not in self._providers:
            raise KeyError(integration_id)
        return self._journal().page(integration_id, self._actor(), **options)

    def history_detail(self, integration_id, run_id):
        if integration_id not in self._providers:
            raise KeyError(integration_id)
        return self._journal().detail(integration_id, run_id, self._actor())

    def clear_history(self, integration_id: str) -> dict:
        if integration_id not in self._providers:
            raise KeyError(integration_id)
        return self._journal().clear(integration_id, self._actor())

    def get_metrics(self) -> dict:
        rows = self.list_integrations()
        total = len(rows)
        enabled = sum(row["enabled"] for row in rows)
        configured = sum(row["configured"] for row in rows)
        history = self._journal().metrics(list(self._providers), self._actor())
        return {
            "total_integrations": total,
            "enabled_integrations": enabled,
            "configured_integrations": configured,
            **history,
            "categories": self.list_categories(),
        }

    def _snapshot(self, key: str) -> tuple[bool, dict]:
        state = self._store.load()
        return (state.get("enabled", {}).get(key, self._providers[key].manifest.enabled_by_default),
                deepcopy(state.get("config", {}).get(key, {})))

    @property
    def _config(self) -> dict:
        """Compatibility read view; persisted state remains authoritative."""
        return deepcopy(self._store.load().get("config", {}))

    def _load_state(self) -> None:
        self._store.load()

    @staticmethod
    def _safe_config(manifest, config: dict) -> dict:
        return public_config(config, manifest)

    @staticmethod
    def _to_message(*, configured: bool, enabled: bool, health: dict) -> str:
        health_state = health.get("status", "unknown")
        if not enabled:
            return "Deaktiviert"
        if not configured:
            return "Konfiguration erforderlich"
        if health.get("transport_checked") is False:
            return "Konfiguriert; SMTP-Transport noch ungeprüft"
        if health_state in {"ok", "configured"}:
            return "Aktiv"
        return "Aktiv (eingeschränkt)"


_config_store = (
    JsonFileIntegrationConfigStore(settings.integration_state_file)
    if settings.integration_state_file
    else InMemoryIntegrationConfigStore()
)
integration_manager = IntegrationManager(store=_config_store)
if isinstance(_config_store, JsonFileIntegrationConfigStore):
    # Explicit startup bootstrap. Subsequent reads fail on a missing/damaged file.
    _config_store.initialize()
integration_manager.seed_defaults()
