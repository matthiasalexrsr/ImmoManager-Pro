"""Integration registry, configuration, and execution manager."""

from __future__ import annotations

from copy import deepcopy
from threading import RLock

from ...config import settings
from ...paths import get_data_dir
from .base import IntegrationProvider, IntegrationRunRecord
from .config_store import InMemoryIntegrationConfigStore, JsonFileIntegrationConfigStore
from .history_store import IntegrationHistoryStore
from .huggingface import HuggingFaceProvider
from .providers import (
    ContractWizardProvider,
    DeutschePostProvider,
    EmailIntegrationProvider,
    ListingPortalProvider,
    WhatsAppIntegrationProvider,
)
from .validation import config_fields, field_errors


class IntegrationManager:
    def __init__(self, store=None, history_store=None) -> None:
        self._providers: dict[str, IntegrationProvider] = {}
        self._enabled: dict[str, bool] = {}
        self._config: dict[str, dict] = {}
        self._store = store or InMemoryIntegrationConfigStore()
        self._journal = history_store or IntegrationHistoryStore(getattr(self._store, "history_path", ":memory:"))
        self._lock = RLock()
        self._state_error = None

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
        config = self._config.get(integration_id, {})
        health = provider.health(config)
        enabled = self._enabled.get(integration_id, False)
        configured = provider.is_configured(config) and self.validate_config(integration_id, config)["valid"]
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
            "config_fields": config_fields(manifest),
            "actions": manifest.actions,
            "persistence_error": self._state_error,
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
            "config_fields": config_fields(manifest),
            "actions": manifest.actions,
            "default_action": manifest.default_action,
        }

    def validate_config(self, integration_id: str, config: dict) -> dict:
        provider = self._providers.get(integration_id)
        if provider is None:
            raise KeyError(integration_id)
        if not isinstance(config, dict):
            return {"valid": False, "missing_keys": [], "message": "Konfiguration muss ein Objekt sein"}

        manifest = provider.manifest
        config = self._candidate_config(integration_id, config)
        fields = config_fields(manifest)
        errors = field_errors(config, fields, required=True)
        errors.update({key: "Unbekanntes Konfigurationsfeld" for key in set(config) - {field["key"] for field in fields}})
        if integration_id == "email":
            if config.get("smtp_user") and not config.get("smtp_password"):
                errors["smtp_password"] = "Passwort für SMTP-Benutzer fehlt"
            if config.get("smtp_use_ssl") and config.get("smtp_use_tls", True):
                errors["smtp_use_ssl"] = "STARTTLS und direktes TLS können nicht gleichzeitig aktiv sein"
        missing = [k for k in manifest.required_config_keys if not config.get(k)]
        if missing:
            return {"valid": False, "missing_keys": missing, "errors": errors, "message": "Pflichtfelder fehlen"}
        if errors:
            return {"valid": False, "missing_keys": [], "errors": errors, "message": "Ungültige Konfiguration"}
        return {"valid": True, "missing_keys": [], "message": "Konfiguration ist gültig"}

    def set_enabled(self, integration_id: str, enabled: bool) -> dict:
        if integration_id not in self._providers:
            raise KeyError(integration_id)
        if type(enabled) is not bool:
            raise ValueError("enabled muss ein boolescher Wert sein")
        with self._lock:
            self._ensure_writable()
            candidate = dict(self._enabled)
            candidate[integration_id] = enabled
            self._store.save({"enabled": candidate, "config": deepcopy(self._config)})
            self._enabled = candidate
        return self.get_integration(integration_id)

    def update_config(self, integration_id: str, config_updates: dict) -> dict:
        if integration_id not in self._providers:
            raise KeyError(integration_id)
        if not isinstance(config_updates, dict):
            raise ValueError("Config updates must be a dictionary")
        manifest = self._providers[integration_id].manifest
        fields = config_fields(manifest)
        unknown = set(config_updates) - {field["key"] for field in fields}
        errors = field_errors(config_updates, fields)
        if unknown:
            errors.update({key: "Unbekanntes Konfigurationsfeld" for key in unknown})
        if errors:
            raise ValueError("; ".join(f"{key}: {message}" for key, message in errors.items()))
        with self._lock:
            self._ensure_writable()
            current = self._candidate_config(integration_id, config_updates)
            if integration_id == "email" and current.get("smtp_use_ssl") and current.get("smtp_use_tls", True):
                raise ValueError("STARTTLS und direktes TLS können nicht gleichzeitig aktiv sein")
            candidate = deepcopy(self._config)
            candidate[integration_id] = current
            self._store.save({"enabled": dict(self._enabled), "config": candidate})
            self._config = candidate
        return self.get_integration(integration_id)

    def _ensure_writable(self):
        if self._state_error:
            raise OSError(self._state_error)

    def _candidate_config(self, integration_id, updates):
        current = deepcopy(self._config.get(integration_id, {}))
        secrets = self._providers[integration_id].manifest.secret_config_keys
        for key, value in updates.items():
            if key in secrets and value == "***":
                continue
            if value is None:
                current.pop(key, None)
            else:
                current[key] = value
        return current

    def run(self, integration_id: str, payload: dict) -> dict:
        provider = self._providers.get(integration_id)
        if provider is None:
            raise KeyError(integration_id)

        errors = {}
        manifest = provider.manifest
        if not isinstance(payload, dict):
            errors["payload"] = "Aktionsangaben müssen ein Objekt sein"
            payload = {}
        action_id = payload.get("action", manifest.default_action)
        if action_id is not None and not isinstance(action_id, str):
            errors["action"] = "Aktion muss Text sein"
        elif manifest.actions:
            action_id = action_id.lower() if action_id else manifest.default_action
            action_schema = next((item for item in manifest.actions if item["id"] == action_id), None)
            if action_schema is None:
                errors["action"] = "Nicht unterstützte Aktion"
            else:
                errors.update(field_errors(payload, action_schema.get("inputs", []), required=True))
                allowed = {"action"} | {field["key"] for field in action_schema.get("inputs", [])}
                errors.update({key: "Unbekanntes Aktionsfeld" for key in set(payload) - allowed})
                payload = {**payload, "action": action_id}
        if errors:
            result = {"success": False, "message": "Ungültige Aktionsangaben: " + ", ".join(errors),
                      "details": {"code": "invalid_payload", "errors": errors}}
            self._append_history(integration_id, payload, result)
            return result

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

        record = IntegrationRunRecord(integration_id, False, "Ausführung begonnen; Ergebnis unbestätigt",
                                      self._history_payload(manifest, payload), {"code": "in_progress"})
        try:
            self._ensure_writable()
            self._journal.append(record)
        except OSError:
            return {"success": False, "message": "Integrationsjournal nicht verfügbar; Aktion wurde nicht ausgeführt.",
                    "details": {"code": "history_unavailable"}}
        try:
            action = provider.run(payload, deepcopy(config))
            result = {"success": action.success, "message": action.message, "details": action.details}
        except Exception as exc:
            result = {"success": False, "message": "Integration fehlgeschlagen. Konfiguration prüfen und erneut versuchen.",
                      "details": {"code": "provider_error", "error_type": type(exc).__name__}}
        record.success = bool(result["success"])
        record.message = result["message"]
        record.details = result.get("details")
        try:
            self._journal.finish(record)
        except OSError:
            result["history_warning"] = "Ergebnis konnte nicht dauerhaft protokolliert werden. Versand nicht automatisch wiederholen."
        return result

    def list_history(self, integration_id: str, limit: int = 20, skip: int = 0) -> list[dict]:
        if integration_id not in self._providers:
            raise KeyError(integration_id)
        if limit < 1 or limit > 100 or skip < 0:
            raise ValueError("Ungültige Journal-Seitenauswahl")
        return self._journal.list(integration_id, limit=limit, skip=skip)

    def history_count(self, integration_id):
        if integration_id not in self._providers:
            raise KeyError(integration_id)
        return self._journal.count(integration_id)

    def clear_history(self, integration_id: str) -> dict:
        if integration_id not in self._providers:
            raise KeyError(integration_id)
        count = self._journal.clear(integration_id)
        return {"id": integration_id, "cleared": count}

    def get_metrics(self) -> dict:
        total = len(self._providers)
        enabled = sum(1 for k in self._providers if self._enabled.get(k, False))
        configured = sum(
            1 for k, provider in self._providers.items() if provider.is_configured(self._config.get(k, {}))
        )
        runs_total, successful = self._journal.metrics()
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
            payload=self._history_payload(self._providers[integration_id].manifest, payload),
            details=result.get("details"),
        )
        self._journal.append(record)

    @staticmethod
    def _history_payload(manifest, payload):
        allowed = {"action"} | {field["key"] for action in manifest.actions for field in action.get("inputs", [])}
        def redact(value):
            if isinstance(value, dict):
                return {key: ("***" if key in manifest.secret_config_keys or any(word in key.lower() for word in ("password", "token", "secret", "api_key")) else redact(item))
                        for key, item in value.items()}
            if isinstance(value, list):
                return [redact(item) for item in value]
            return value
        return redact({key: value for key, value in payload.items() if not manifest.actions or key in allowed})

    def _load_state(self) -> None:
        try:
            state = self._store.load()
        except (ValueError, OSError):
            self._state_error = "Gespeicherte Integrationskonfiguration ist beschädigt oder nicht lesbar. Datei prüfen; Änderungen sind gesperrt."
            return
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
        if health_state == "not_implemented":
            return "Noch nicht implementiert"
        if not configured:
            return "Konfiguration erforderlich"
        if health_state == "configured":
            return "Konfiguriert (Verbindung ungeprüft)"
        if health_state in {"ok", "available"}:
            return "Aktiv"
        return "Aktiv (eingeschränkt)"


_config_store = JsonFileIntegrationConfigStore(settings.integration_state_file or str(get_data_dir() / "integrations.json"))
integration_manager = IntegrationManager(store=_config_store)
integration_manager.seed_defaults()
