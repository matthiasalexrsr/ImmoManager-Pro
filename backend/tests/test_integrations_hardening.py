"""Failure-boundary regressions; no external delivery or model downloads."""

import json
from types import SimpleNamespace

import pytest

from backend.services import email_service
from backend.services.ai.hf_runtime import _LOAD_FAILED
from backend.services.integrations import huggingface
from backend.services.integrations.base import IntegrationManifest
from backend.services.integrations.config_store import InMemoryIntegrationConfigStore, JsonFileIntegrationConfigStore
from backend.services.integrations.manager import IntegrationManager
from backend.services.integrations.providers import (
    ContractWizardProvider,
    EmailIntegrationProvider,
    ListingPortalProvider,
    WhatsAppIntegrationProvider,
)


def manager_for(provider, store=None):
    manager = IntegrationManager(store=store)
    manager.register(provider)
    return manager


def test_masked_roundtrip_preserves_stored_secret():
    store = InMemoryIntegrationConfigStore()
    manager = manager_for(WhatsAppIntegrationProvider(), store)
    manager.update_config("whatsapp", {"phone_number_id": "123", "api_token": "original"})
    manager.update_config("whatsapp", manager.get_integration("whatsapp")["config"])
    assert store.load()["config"]["whatsapp"]["api_token"] == "original"


@pytest.mark.parametrize("operation", ["config", "toggle"])
def test_disk_failure_does_not_publish_candidate(operation):
    class FailingStore(InMemoryIntegrationConfigStore):
        def save(self, state):
            raise OSError("disk full")

    manager = manager_for(WhatsAppIntegrationProvider(), FailingStore())
    before = manager.get_integration("whatsapp")
    with pytest.raises(OSError):
        if operation == "config":
            manager.update_config("whatsapp", {"phone_number_id": "123", "api_token": "secret"})
        else:
            manager.set_enabled("whatsapp", True)
    assert manager.get_integration("whatsapp") == before


def test_json_replace_failure_preserves_previous_file(tmp_path, monkeypatch):
    path = tmp_path / "integrations.json"
    store = JsonFileIntegrationConfigStore(str(path))
    store.save({"config": {"old": True}})
    import os
    monkeypatch.setattr(os, "replace", lambda *args: (_ for _ in ()).throw(OSError("disk full")))
    with pytest.raises(OSError):
        store.save({"config": {"new": True}})
    assert json.loads(path.read_text(encoding="utf-8")) == {"config": {"old": True}}
    assert list(tmp_path.iterdir()) == [path]


@pytest.mark.parametrize("updates", [{"smtp_port": "587"}, {"smtp_use_tls": "false"}, {"smtp_timeout": 0}, {"sender_email": 42}])
def test_email_config_rejects_bad_types_without_mutation(updates):
    manager = manager_for(EmailIntegrationProvider())
    with pytest.raises(ValueError):
        manager.update_config("email", updates)
    assert manager.get_integration("email")["config"] == {}


@pytest.mark.parametrize("action", [42, "destroy"])
def test_invalid_action_is_failed_result_and_history(action):
    manager = manager_for(ListingPortalProvider())
    manager.update_config("listing-portals", {"default_portal": "Immowelt"})
    manager.set_enabled("listing-portals", True)
    result = manager.run("listing-portals", {"action": action})
    assert result["success"] is False
    assert result["details"]["code"] == "invalid_payload"
    assert manager.list_history("listing-portals")[0]["success"] is False


def test_provider_exception_is_failed_result_and_history_without_secret_leak():
    class BrokenProvider:
        manifest = IntegrationManifest("broken", "Broken", "test", "test", enabled_by_default=True)
        def is_configured(self, config): return True
        def health(self, config): return {"status": "ok"}
        def run(self, payload, config): raise RuntimeError("secret-password")

    manager = manager_for(BrokenProvider())
    result = manager.run("broken", {})
    assert result["success"] is False
    assert result["details"]["code"] == "provider_error"
    assert "secret-password" not in str(manager.list_history("broken"))


def test_email_sender_alone_is_not_a_configured_transport():
    manager = manager_for(EmailIntegrationProvider())
    manager.update_config("email", {"sender_email": "sender@example.test"})
    assert manager.get_integration("email")["configured"] is False


def test_unconfigured_email_is_not_sent(monkeypatch):
    monkeypatch.setattr(email_service, "_config", email_service.EmailConfig())
    assert email_service.send_email("recipient@example.test", "Hello", "Hello") is False


class SMTPRecorder:
    def __init__(self, host, port, **kwargs):
        self.host, self.port, self.kwargs = host, port, kwargs
        self.events = []
        self.refused = {}
    def ehlo(self): self.events.append("ehlo")
    def starttls(self, **kwargs): self.events.append("tls")
    def login(self, user, password): self.events.append(("login", user, password))
    def noop(self):
        self.events.append("noop")
        return (250, b"ok")
    def send_message(self, message, **kwargs):
        self.events.append(("send", message, kwargs))
        return self.refused
    def quit(self): self.events.append("quit")
    def close(self): self.events.append("close")


@pytest.fixture
def smtp(monkeypatch):
    connections = []
    def connect(*args, **kwargs):
        connection = SMTPRecorder(*args, **kwargs)
        connections.append(connection)
        return connection
    monkeypatch.setattr(email_service.smtplib, "SMTP", connect)
    monkeypatch.setattr(email_service.smtplib, "SMTP_SSL", connect)
    return connections


SMTP_CONFIG = {"sender_email": "sender@example.test", "smtp_host": "smtp.example.test", "smtp_port": 587,
               "smtp_user": "login", "smtp_password": "secret", "smtp_use_tls": True, "smtp_timeout": 7}


@pytest.mark.parametrize("key", ["smtp_use_tls", "smtp_use_ssl", "smtp_port", "smtp_timeout"])
def test_empty_nontext_config_rejected_without_changing_saved_or_live_state(key):
    store = InMemoryIntegrationConfigStore()
    manager = manager_for(EmailIntegrationProvider(), store)
    manager.update_config("email", SMTP_CONFIG)
    before_saved = store.load()
    before_live = manager.get_integration("email")

    with pytest.raises(ValueError, match=key):
        manager.update_config("email", {key: ""})

    assert store.load() == before_saved
    assert manager.get_integration("email") == before_live


@pytest.mark.parametrize("key", ["smtp_use_tls", "smtp_use_ssl", "smtp_port", "smtp_timeout"])
def test_loaded_empty_nontext_config_is_invalid_and_cannot_start_smtp(key, smtp):
    store = InMemoryIntegrationConfigStore()
    store.save({"enabled": {"email": True}, "config": {"email": {**SMTP_CONFIG, key: ""}}})
    manager = IntegrationManager(store=store)
    manager.seed_defaults()

    validation = manager.validate_config("email", {})
    result = manager.run("email", {"action": "check_connection"})

    assert validation["valid"] is False
    assert key in validation["errors"]
    assert manager.get_integration("email")["configured"] is False
    assert result["success"] is False
    assert key in result["details"]["errors"]
    assert smtp == []


@pytest.mark.parametrize("provider,payload,key,kind", [
    (ListingPortalProvider(), {"action": "publish", "listing": ""}, "listing", "object"),
    (huggingface.HuggingFaceProvider(), {"action": "summarize", "messages": ""}, "messages", "array"),
])
def test_empty_nontext_action_input_rejected_before_execution(provider, payload, key, kind, monkeypatch):
    def unexpected_execution(*args, **kwargs):
        pytest.fail("Invalid action must not reach its provider")

    monkeypatch.setattr(provider, "run", unexpected_execution)
    manager = manager_for(provider)
    if provider.manifest.integration_id == "listing-portals":
        manager.update_config("listing-portals", {"default_portal": "Immowelt"})
    manager.set_enabled(provider.manifest.integration_id, True)
    result = manager.run(provider.manifest.integration_id, payload)

    assert result["success"] is False
    assert result["details"]["code"] == "invalid_payload"
    assert result["details"]["errors"][key] == f"Ungültiger Typ: {kind} erwartet"


def test_optional_text_clear_null_default_and_masked_secret_roundtrip(smtp):
    store = InMemoryIntegrationConfigStore()
    manager = manager_for(EmailIntegrationProvider(), store)
    manager.update_config("email", {**SMTP_CONFIG, "sender_name": "Old sender", "smtp_use_tls": False})
    displayed = manager.get_integration("email")["config"]
    assert displayed["smtp_password"] == "***"

    manager.update_config("email", {**displayed, "sender_name": "", "smtp_use_tls": None})
    saved = store.load()["config"]["email"]
    assert saved["sender_name"] == ""
    assert "smtp_use_tls" not in saved
    assert saved["smtp_password"] == "secret"
    assert manager.get_integration("email")["configured"] is True
    assert manager.run("email", {"action": "check_connection"})["success"] is True
    assert "tls" in smtp[0].events
    assert ("login", "login", "secret") in smtp[0].events


def test_connection_check_uses_saved_config_and_never_sends(smtp):
    result = EmailIntegrationProvider().run({"action": "check_connection"}, SMTP_CONFIG)
    assert result.success
    connection = smtp[0]
    assert connection.host == "smtp.example.test"
    assert connection.kwargs["timeout"] == 7
    assert "tls" in connection.events
    assert ("login", "login", "secret") in connection.events
    assert "noop" in connection.events
    assert not any(isinstance(event, tuple) and event[0] == "send" for event in connection.events)


def test_explicit_send_uses_configured_sender_and_selected_recipient(smtp):
    result = EmailIntegrationProvider().run({"action": "send", "recipient": "chosen@example.test", "subject": "Hi", "body": "Body"}, SMTP_CONFIG)
    assert result.success
    event = next(event for event in smtp[0].events if isinstance(event, tuple) and event[0] == "send")
    assert "sender@example.test" in event[1]["From"]
    assert event[1]["To"] == "chosen@example.test"


def test_smtp_recipient_rejection_is_not_success(smtp, monkeypatch):
    monkeypatch.setattr(SMTPRecorder, "send_message", lambda self, *args, **kwargs: {"chosen@example.test": (550, b"rejected")})
    result = EmailIntegrationProvider().run({"action": "send", "recipient": "chosen@example.test"}, SMTP_CONFIG)
    assert result.success is False


@pytest.mark.parametrize("stage", ["connect", "tls", "login"])
def test_smtp_transport_failure_is_not_success(smtp, monkeypatch, stage):
    def fail(*args, **kwargs): raise TimeoutError("secret-password")
    if stage == "connect":
        monkeypatch.setattr(email_service.smtplib, "SMTP", fail)
    else:
        monkeypatch.setattr(SMTPRecorder, "starttls" if stage == "tls" else "login", fail)
    result = EmailIntegrationProvider().run({"action": "send", "recipient": "chosen@example.test"}, SMTP_CONFIG)
    assert not result.success
    assert "secret-password" not in str(result)
    assert not any(isinstance(event, tuple) and event[0] == "send" for connection in smtp for event in connection.events)


def test_accepted_message_stays_success_when_quit_fails(smtp, monkeypatch):
    monkeypatch.setattr(SMTPRecorder, "quit", lambda *args: (_ for _ in ()).throw(OSError("closed")))
    result = EmailIntegrationProvider().run({"action": "send", "recipient": "chosen@example.test"}, SMTP_CONFIG)
    assert result.success
    assert "close" in smtp[0].events


def test_json_corruption_is_reported_without_replacing_file(tmp_path):
    path = tmp_path / "integrations.json"
    path.write_text('{"incomplete":', encoding="utf-8")
    with pytest.raises(ValueError):
        JsonFileIntegrationConfigStore(str(path)).load()
    assert path.read_text(encoding="utf-8") == '{"incomplete":'


def test_planned_portals_are_not_healthy():
    manager = manager_for(ListingPortalProvider())
    manager.update_config("listing-portals", {"default_portal": "Immowelt"})
    result = manager.get_integration("listing-portals")
    assert result["planned"] is True
    assert result["health"]["status"] == "not_implemented"


def test_hf_failed_sentinel_is_not_counted_as_loaded(monkeypatch):
    monkeypatch.setattr(huggingface, "runtime", SimpleNamespace(is_available=True, _pipelines={"failed": _LOAD_FAILED, "loaded": object()}, _embedder=None, config=SimpleNamespace(device="cpu")))
    health = huggingface.HuggingFaceProvider().health({})
    assert health["models_loaded"] == 1
    assert health["models_failed"] == 1
    assert health["status"] == "degraded"


def test_schema_describes_config_fields_and_distinct_email_actions():
    manager = manager_for(EmailIntegrationProvider())
    schema = manager.get_schema("email")
    assert next(field for field in schema["config_fields"] if field["key"] == "smtp_port")["type"] == "integer"
    assert {action["id"] for action in schema["actions"]} == {"check_connection", "send"}


def test_history_survives_restart_and_pages_beyond_old_cap(tmp_path):
    path = str(tmp_path / "settings.json")
    manager = manager_for(ContractWizardProvider(), JsonFileIntegrationConfigStore(path))
    for index in range(205):
        assert manager.run("contract-wizard", {"tenant_name": f"Tenant {index}"})["success"]
    restarted = manager_for(ContractWizardProvider(), JsonFileIntegrationConfigStore(path))
    assert restarted.get_metrics()["runs_total"] == 205
    first = restarted.list_history("contract-wizard", limit=100)
    second = restarted.list_history("contract-wizard", limit=100, skip=100)
    last = restarted.list_history("contract-wizard", limit=100, skip=200)
    assert len(first) == 100 and len(second) == 100 and len(last) == 5
    assert len({item["id"] for item in first + second + last}) == 205
    assert last[-1]["payload"]["tenant_name"] == "Tenant 0"


def test_unknown_action_keys_are_rejected_and_secret_values_not_journaled():
    manager = manager_for(ContractWizardProvider())
    result = manager.run("contract-wizard", {"tenant_name": "Tenant", "smtp_password": "secret-value"})
    assert not result["success"]
    assert "secret-value" not in str(manager.list_history("contract-wizard"))


def test_unknown_config_field_is_invalid_when_validated():
    manager = manager_for(EmailIntegrationProvider())
    result = manager.validate_config("email", {**SMTP_CONFIG, "smtp_pasword": "secret"})
    assert not result["valid"]
    assert "smtp_pasword" in result["errors"]


def test_nested_hf_messages_are_validated_before_provider_execution():
    manager = manager_for(huggingface.HuggingFaceProvider())
    result = manager.run("huggingface", {"action": "summarize", "messages": [42]})
    assert result["details"]["code"] == "invalid_payload"


def test_journal_failure_prevents_provider_invocation(smtp, monkeypatch):
    manager = manager_for(EmailIntegrationProvider())
    manager.update_config("email", SMTP_CONFIG)
    monkeypatch.setattr(manager._journal, "append", lambda record: (_ for _ in ()).throw(OSError("disk full")))
    result = manager.run("email", {"action": "send", "recipient": "chosen@example.test"})
    assert not result["success"] and result["details"]["code"] == "history_unavailable"
    assert smtp == []


def test_journal_finish_failure_preserves_accepted_delivery_and_pending_record(smtp, monkeypatch):
    manager = manager_for(EmailIntegrationProvider())
    manager.update_config("email", SMTP_CONFIG)
    monkeypatch.setattr(manager._journal, "finish", lambda record: (_ for _ in ()).throw(OSError("disk full")))
    result = manager.run("email", {"action": "send", "recipient": "chosen@example.test"})
    assert result["success"] and result["history_warning"]
    assert manager.list_history("email")[0]["details"]["code"] == "in_progress"


def test_sqlite_connect_failure_is_reported_as_journal_unavailable(tmp_path, smtp, monkeypatch):
    import sqlite3
    manager = manager_for(EmailIntegrationProvider(), JsonFileIntegrationConfigStore(str(tmp_path / "settings.json")))
    manager.update_config("email", SMTP_CONFIG)
    monkeypatch.setattr(sqlite3, "connect", lambda *args, **kwargs: (_ for _ in ()).throw(sqlite3.OperationalError("unavailable")))
    result = manager.run("email", {"action": "send", "recipient": "chosen@example.test"})
    assert result["details"]["code"] == "history_unavailable"
    assert smtp == []


def test_loaded_corrupt_config_is_visible_and_cannot_be_overwritten(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text('{"broken":', encoding="utf-8")
    manager = IntegrationManager(store=JsonFileIntegrationConfigStore(str(path)))
    manager.seed_defaults()
    assert manager.get_integration("email")["persistence_error"]
    with pytest.raises(OSError):
        manager.update_config("email", SMTP_CONFIG)
    assert path.read_text(encoding="utf-8") == '{"broken":'
