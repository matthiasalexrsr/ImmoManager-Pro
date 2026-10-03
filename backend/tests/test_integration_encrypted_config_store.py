"""Encrypted integration config at rest; no provider or network calls."""

from __future__ import annotations

import json

import pytest

from backend.services.iban_encryption import IBANKeyring, generate_key
from backend.services.integrations.config_store import (
    ConfigStoreError,
    JsonFileIntegrationConfigStore,
)
from backend.services.integrations.encrypted_config_store import (
    FORMAT,
    EncryptedJsonIntegrationConfigStore,
)
from backend.services.integrations.manager import IntegrationManager
from backend.services.integrations.providers import EmailIntegrationProvider


@pytest.fixture
def rings():
    return (
        IBANKeyring("one", {"one": generate_key()}),
        IBANKeyring("two", {"two": generate_key()}),
    )


def test_encrypted_file_roundtrip_keeps_nested_discovery_without_plaintext(tmp_path, rings):
    path = tmp_path / "integrations.json"
    state = {
        "enabled": {"email": True},
        "config": {
            "email": {
                "smtp_host": "smtp.synthetic.invalid",
                "smtp_password": "SYNTHETIC_SECRET_NEVER_PLAINTEXT",
                "discovery": {
                    "late_unknown": ["alpha", {"provider_field": "preserve-me"}],
                    "capability_hint": "observed-not-accepted",
                },
            }
        },
    }
    store = EncryptedJsonIntegrationConfigStore(str(path), keyring=rings[0])

    assert store.initialize(state) == state
    assert store.load() == state

    raw = path.read_bytes()
    assert b"SYNTHETIC_SECRET_NEVER_PLAINTEXT" not in raw
    assert b"smtp.synthetic.invalid" not in raw
    assert b"preserve-me" not in raw
    envelope = json.loads(raw)
    assert set(envelope) == {"format", "ciphertext"}
    assert envelope["format"] == FORMAT
    assert envelope["ciphertext"].startswith("history:v1:one:")


def test_masked_display_value_never_replaces_actual_secret(tmp_path, rings):
    path = tmp_path / "integrations.json"
    store = EncryptedJsonIntegrationConfigStore(str(path), keyring=rings[0])
    store.initialize({})
    manager = IntegrationManager(store=store)
    manager.register(EmailIntegrationProvider())

    first = manager.update_config(
        "email",
        {
            "smtp_host": "smtp.synthetic.invalid",
            "sender_email": "sender@example.invalid",
            "smtp_user": "synthetic-user",
            "smtp_password": "ORIGINAL_SYNTHETIC_PASSWORD",
        },
    )
    assert first["config"]["smtp_password"] == "***"

    second = manager.update_config(
        "email",
        {
            "smtp_password": "***",
            "discovery": {"server_extension": "SYNTHETIC-X-EXT"},
        },
    )
    assert second["config"]["smtp_password"] == "***"
    loaded = store.load()
    assert loaded["config"]["email"]["smtp_password"] == "ORIGINAL_SYNTHETIC_PASSWORD"
    assert loaded["config"]["email"]["discovery"]["server_extension"] == "SYNTHETIC-X-EXT"
    assert b"ORIGINAL_SYNTHETIC_PASSWORD" not in path.read_bytes()


def test_wrong_key_and_tampered_ciphertext_fail_closed(tmp_path, rings):
    path = tmp_path / "integrations.json"
    good = EncryptedJsonIntegrationConfigStore(str(path), keyring=rings[0])
    good.initialize({"config": {"email": {"smtp_password": "synthetic"}}})

    wrong = EncryptedJsonIntegrationConfigStore(str(path), keyring=rings[1])
    with pytest.raises(ConfigStoreError) as failure:
        wrong.load()
    assert failure.value.code == "encrypted_state_unreadable"

    envelope = json.loads(path.read_text(encoding="utf-8"))
    token = envelope["ciphertext"]
    envelope["ciphertext"] = token[:-1] + ("A" if token[-1] != "A" else "B")
    path.write_text(json.dumps(envelope), encoding="utf-8")
    with pytest.raises(ConfigStoreError) as failure:
        good.load()
    assert failure.value.code == "encrypted_state_unreadable"


def test_plaintext_requires_explicit_migration_and_conversion_is_atomic(tmp_path, rings):
    path = tmp_path / "integrations.json"
    legacy_state = {
        "enabled": {"email": True},
        "config": {
            "email": {
                "smtp_host": "legacy.synthetic.invalid",
                "smtp_password": "LEGACY_SYNTHETIC_PASSWORD",
            }
        },
    }
    legacy = JsonFileIntegrationConfigStore(str(path))
    legacy.initialize(legacy_state)

    encrypted = EncryptedJsonIntegrationConfigStore(str(path), keyring=rings[0])
    with pytest.raises(ConfigStoreError) as failure:
        encrypted.initialize()
    assert failure.value.code == "plaintext_state_requires_migration"
    assert b"LEGACY_SYNTHETIC_PASSWORD" in path.read_bytes()

    assert encrypted.migrate_legacy_plaintext() == legacy_state
    assert encrypted.load() == legacy_state
    raw = path.read_bytes()
    assert b"LEGACY_SYNTHETIC_PASSWORD" not in raw
    assert json.loads(raw)["format"] == FORMAT


def test_failed_update_publishes_neither_plaintext_nor_partial_state(tmp_path, rings):
    path = tmp_path / "integrations.json"
    store = EncryptedJsonIntegrationConfigStore(str(path), keyring=rings[0])
    initial = {
        "enabled": {"email": False},
        "config": {"email": {"smtp_password": "STABLE_SYNTHETIC_SECRET"}},
    }
    store.initialize(initial)
    before = path.read_bytes()

    def broken(state):
        state["config"]["email"]["smtp_password"] = "NEW_SHOULD_NOT_PUBLISH"
        state["config"]["email"]["invalid"] = float("nan")
        return state

    with pytest.raises(ConfigStoreError):
        store.update(broken)

    assert path.read_bytes() == before
    assert store.load() == initial
    assert b"NEW_SHOULD_NOT_PUBLISH" not in path.read_bytes()


def test_envelope_like_damage_is_never_reinterpreted_as_legacy_plaintext(tmp_path, rings):
    path = tmp_path / "integrations.json"
    store = EncryptedJsonIntegrationConfigStore(str(path), keyring=rings[0])
    store.initialize({"config": {"email": {"smtp_password": "synthetic"}}})

    envelope = json.loads(path.read_text(encoding="utf-8"))
    envelope["unexpected"] = "must-not-be-migrated"
    path.write_text(json.dumps(envelope), encoding="utf-8")

    with pytest.raises(ConfigStoreError) as failure:
        store.migrate_legacy_plaintext()
    assert failure.value.code == "encrypted_state_invalid"
