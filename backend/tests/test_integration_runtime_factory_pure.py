"""Synthetic factory/file tests without app, conftest, SQL or child processes."""

import base64
import json
import socket
import sqlite3
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor

import pytest
from pydantic import ValidationError

from backend.services import iban_encryption
from backend.services.integrations import history_crypto, runtime_factory
from backend.services.integrations.config_store import ConfigStoreError, InMemoryIntegrationConfigStore
from backend.services.integrations.encrypted_config_store import FORMAT, EncryptedJsonIntegrationConfigStore
from backend.settings import ExplicitSettings

KEY = base64.urlsafe_b64encode(b"synthetic-factory-field-key-00000".ljust(32, b"0")[:32]).decode("ascii")
OTHER_KEY = base64.urlsafe_b64encode(b"synthetic-other-field-key-000000".ljust(32, b"1")[:32]).decode("ascii")
SECRET = "SYNTHETIC_FACTORY_PASSWORD_NEVER_PLAINTEXT"
FORBIDDEN = {
    "backend.app", "backend.config", "backend.dependencies", "backend.db.session",
    "backend.services.integrations.manager", "backend.services.integrations.providers",
    "backend.services.integrations.huggingface", "backend.services.integrations.history_store",
}


@pytest.fixture(autouse=True)
def no_application_sql_network_or_ambient_keys(monkeypatch):
    assert not FORBIDDEN.intersection(sys.modules)

    def refused(*_values, **_options):
        pytest.fail("factory used SQL/network/ambient keys or key generation")

    monkeypatch.setattr(sqlite3, "connect", refused)
    monkeypatch.setattr(socket, "create_connection", refused)
    monkeypatch.setattr(subprocess, "Popen", refused)
    monkeypatch.setattr(history_crypto, "current_keyring", refused)
    monkeypatch.setattr(iban_encryption, "current_keyring", refused)
    monkeypatch.setattr(iban_encryption, "generate_key", refused)
    yield
    assert not FORBIDDEN.intersection(sys.modules)


def configuration(tmp_path, **updates):
    return {
        "INTEGRATION_STATE_FILE": str(tmp_path / "integrations.json"),
        "ENCRYPTION_KEYRING": json.dumps({"synthetic": KEY}),
        "ENCRYPTION_ACTIVE_KEY_ID": "synthetic",
        **updates,
    }


def state():
    return {
        "enabled": {"email": True},
        "config": {"email": {"smtp_password": SECRET, "smtp_host": "smtp.synthetic.invalid"}},
        "unknown_discovery": {"nested": [None, {"retained": "SYNTHETIC_EXTENSION"}]},
    }


def test_normal_construction_does_not_materialize_read_initialize_or_create_directories(tmp_path, monkeypatch):
    root = tmp_path / "not-created"

    def forbidden(*_values, **_options):
        pytest.fail("normal factory materialized file store")

    monkeypatch.setattr(runtime_factory, "EncryptedJsonIntegrationConfigStore", forbidden)
    selected = runtime_factory.configured_runtime_store(configuration(root, ENCRYPTION_KEYRING="malformed"))
    assert isinstance(selected, runtime_factory.RuntimeEncryptedIntegrationConfigStore)
    assert not root.exists() and list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("path", [" ", 42, True])
def test_path_fault_is_deferred_until_actual_integration_use(tmp_path, path):
    selected = runtime_factory.configured_runtime_store(configuration(tmp_path, INTEGRATION_STATE_FILE=path))
    with pytest.raises(ConfigStoreError, match="invalid_store_path"):
        selected.load()
    assert list(tmp_path.iterdir()) == []


def test_memory_factory_keeps_no_key_requirement_and_existing_cas_behavior(tmp_path):
    selected = runtime_factory.configured_runtime_store({"INTEGRATION_STATE_FILE": None})
    assert isinstance(selected, InMemoryIntegrationConfigStore)
    assert selected.load() == {}
    selected.save(state())
    loaded, revision = selected.load_with_revision()
    assert loaded == state()
    _, updated = selected.update_if_revision(revision, lambda value: {**value, "future_field": 1})
    with pytest.raises(ConfigStoreError, match="state_revision_conflict"):
        selected.update_if_revision(revision, lambda _value: {})
    assert selected.load()["future_field"] == 1 and updated != revision
    assert list(tmp_path.iterdir()) == []


def test_missing_normal_load_and_write_never_bootstrap_an_empty_state(tmp_path):
    selected = runtime_factory.configured_runtime_store(configuration(tmp_path))
    for operation in (selected.load, lambda: selected.save(state()), lambda: selected.update(lambda _value: state())):
        with pytest.raises(ConfigStoreError, match="state_missing"):
            operation()
    assert not (tmp_path / "integrations.json").exists()
    assert "--initialize-integrations" in runtime_factory.runtime_state_instruction("state_missing")


@pytest.mark.parametrize("keys", ["valid", "invalid"])
def test_plaintext_requires_explicit_maintenance_and_keeps_exact_bytes(tmp_path, keys):
    path = tmp_path / "integrations.json"
    original = json.dumps(state(), ensure_ascii=False, indent=3).encode("utf-8")
    path.write_bytes(original)
    values = configuration(tmp_path, **({"ENCRYPTION_KEYRING": "not-a-keyring"} if keys == "invalid" else {}))
    selected = runtime_factory.configured_runtime_store(values)
    with pytest.raises(ConfigStoreError) as error:
        selected.load()
    assert error.value.code == "plaintext_state_requires_migration"
    instruction = runtime_factory.runtime_state_instruction(error.value.code)
    assert runtime_factory.MAINTENANCE_HELP in instruction and SECRET not in instruction
    assert path.read_bytes() == original


def test_explicit_fresh_initialization_is_encrypted_and_reopens_with_stable_selected_keys(tmp_path, monkeypatch):
    values = configuration(tmp_path)
    monkeypatch.setenv("ENCRYPTION_KEY", OTHER_KEY)
    monkeypatch.setenv("ENCRYPTION_KEYRING", json.dumps({"foreign": OTHER_KEY}))
    selected = runtime_factory.initialize_new(values, expected_missing=True)
    assert isinstance(selected, EncryptedJsonIntegrationConfigStore)
    assert selected.load() == {}
    selected.save(state())
    raw = selected.path.read_bytes()
    assert SECRET.encode() not in raw and b"SYNTHETIC_EXTENSION" not in raw
    assert json.loads(raw)["format"] == FORMAT
    normal = runtime_factory.configured_runtime_store(values)
    assert normal.load() == state()
    assert selected.path.read_bytes() == raw


def test_explicit_initialization_authenticates_existing_cipher_as_exact_noop(tmp_path):
    values = configuration(tmp_path)
    created = runtime_factory.initialize_new(values)
    created.save(state())
    original = created.path.read_bytes()
    repeated = runtime_factory.initialize_new(values, expected_missing=True)
    assert repeated.load() == state()
    assert repeated.path.read_bytes() == original
    assert sorted(path.name for path in tmp_path.iterdir()) == [".integrations.json.lock", "integrations.json"]


@pytest.mark.parametrize("permission", [False, 1, None, "true"])
def test_initialization_requires_literal_explicit_permission_before_any_state_work(tmp_path, permission):
    with pytest.raises(ConfigStoreError, match="explicit_initialization_required"):
        runtime_factory.initialize_new(configuration(tmp_path), expected_missing=permission)
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("values", [
    {},
    {"JWT_SECRET_KEY": "synthetic-signing-key-is-not-a-field-key"},
    {"ENCRYPTION_KEY": "malformed-synthetic-key"},
    {"ENCRYPTION_KEYRING": "not-json"},
])
def test_fresh_initialization_refuses_missing_or_bad_field_keys_without_writing(tmp_path, values):
    values = {"INTEGRATION_STATE_FILE": str(tmp_path / "integrations.json"), **values}
    selected = runtime_factory.configured_runtime_store(values)
    assert not (tmp_path / "integrations.json").exists()
    with pytest.raises(ConfigStoreError, match="encryption_key_unavailable"):
        runtime_factory.initialize_new(values)
    assert list(tmp_path.iterdir()) == []
    with pytest.raises(ConfigStoreError, match="state_missing"):
        selected.load()


def test_explicit_initialization_does_not_turn_memory_mode_into_a_persistent_file(tmp_path):
    with pytest.raises(ConfigStoreError, match="integration_state_path_required"):
        runtime_factory.initialize_new({"ENCRYPTION_KEY": KEY})
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("fault", ["plaintext", "malformed", "wrong_key", "tampered", "unknown_format"])
def test_existing_invalid_state_is_refused_and_never_replaced_even_by_explicit_init(tmp_path, fault):
    values = configuration(tmp_path)
    actual = runtime_factory.initialize_new(values)
    actual.save(state())
    path = actual.path
    if fault == "plaintext":
        path.write_text(json.dumps(state()), encoding="utf-8")
    elif fault == "malformed":
        path.write_bytes(b"{invalid-private-state")
    elif fault == "wrong_key":
        values["ENCRYPTION_KEYRING"] = json.dumps({"synthetic": OTHER_KEY})
    else:
        envelope = json.loads(path.read_bytes())
        if fault == "tampered":
            envelope["ciphertext"] = envelope["ciphertext"][:-8] + "AAAAAAAA"
        else:
            envelope["format"] = "unknown-encrypted-version"
        path.write_text(json.dumps(envelope), encoding="utf-8")
    original = path.read_bytes()
    selected = runtime_factory.configured_runtime_store(values)
    for operation in (selected.load, lambda: runtime_factory.initialize_new(values)):
        with pytest.raises(ConfigStoreError) as error:
            operation()
        assert SECRET not in str(error.value) and KEY not in str(error.value)
        assert SECRET not in runtime_factory.runtime_state_instruction(error.value.code)
        assert path.read_bytes() == original


def test_immutable_explicit_key_snapshot_and_signer_rotation_preserve_unknown_fields(tmp_path):
    values = configuration(tmp_path, ENCRYPTION_KEYRING={"synthetic": KEY}, JWT_SECRET_KEY="synthetic-old-signer")
    created = runtime_factory.initialize_new(values)
    created.save(state())
    selected = runtime_factory.configured_runtime_store(values)
    values["ENCRYPTION_KEYRING"]["synthetic"] = OTHER_KEY
    values["JWT_SECRET_KEY"] = "synthetic-new-signer"
    assert selected.load() == state()
    rotated = runtime_factory.configured_runtime_store(configuration(tmp_path, JWT_SECRET_KEY="synthetic-new-signer"))
    assert rotated.load() == state()


def test_runtime_cas_delegation_preserves_secrets_and_rejects_stale_overwrite(tmp_path):
    values = configuration(tmp_path)
    runtime_factory.initialize_new(values).save(state())
    first = runtime_factory.configured_runtime_store(values)
    second = runtime_factory.configured_runtime_store(values)
    assert isinstance(first, runtime_factory.RuntimeEncryptedIntegrationConfigStore)
    assert isinstance(second, runtime_factory.RuntimeEncryptedIntegrationConfigStore)
    original, revision = first.load_with_revision()
    candidate, next_revision = first.update_if_revision(revision, lambda value: {**value, "new_field": "retained"})
    with pytest.raises(ConfigStoreError, match="state_revision_conflict"):
        second.update_if_revision(revision, lambda _value: {})
    assert first.load() == candidate
    assert candidate["config"] == original["config"] and candidate["unknown_discovery"] == original["unknown_discovery"]
    assert next_revision != revision and candidate["new_field"] == "retained"


def test_concurrent_first_use_materializes_one_existing_file_store(tmp_path, monkeypatch):
    values = configuration(tmp_path)
    runtime_factory.initialize_new(values).save(state())
    selected = runtime_factory.configured_runtime_store(values)
    constructor = runtime_factory.EncryptedJsonIntegrationConfigStore
    constructed = []

    def observe(*args, **options):
        actual = constructor(*args, **options)
        constructed.append(actual)
        return actual

    monkeypatch.setattr(runtime_factory, "EncryptedJsonIntegrationConfigStore", observe)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _item: selected.load(), range(8)))
    assert results == [state()] * 8 and len(constructed) == 1


def test_actual_settings_and_archived_strings_accept_higher_positive_budgets(tmp_path):
    settings = ExplicitSettings(**{
        key.lower(): value for key, value in configuration(tmp_path).items()
    }, integration_state_payload_bytes=17 * 1024**2,
        integration_state_json_depth=128, integration_state_lock_timeout_seconds=120)
    snapshot = settings.model_dump(mode="json")
    archived = {key.upper(): str(value) for key, value in snapshot.items()
                if value is not None and (key.startswith("integration_state_") or key in {
                    "encryption_keyring", "encryption_active_key_id",
                })}
    initialized = runtime_factory.initialize_new(archived)
    assert initialized._plaintext_maximum == 17 * 1024**2
    assert initialized._max_depth == 128 and initialized._timeout == 120


@pytest.mark.parametrize("name,bad", [
    ("integration_state_payload_bytes", True),
    ("integration_state_payload_bytes", 0),
    ("integration_state_payload_bytes", -1),
    ("integration_state_payload_bytes", 1.0),
    ("integration_state_payload_bytes", "1.5"),
    ("integration_state_json_depth", False),
    ("integration_state_json_depth", 0),
    ("integration_state_json_depth", 64.5),
    ("integration_state_lock_timeout_seconds", True),
    ("integration_state_lock_timeout_seconds", 0),
    ("integration_state_lock_timeout_seconds", -0.1),
    ("integration_state_lock_timeout_seconds", float("nan")),
    ("integration_state_lock_timeout_seconds", float("inf")),
    ("integration_state_lock_timeout_seconds", "nan"),
])
def test_settings_and_direct_factory_reject_invalid_operational_budget(tmp_path, name, bad):
    with pytest.raises(ValidationError):
        ExplicitSettings(**{name: bad})
    with pytest.raises(ConfigStoreError):
        runtime_factory.configured_runtime_store(configuration(tmp_path, **{name.upper(): bad}))
    assert list(tmp_path.iterdir()) == []


def test_actual_larger_payload_profile_persists_complete_state_and_small_profile_refuses(tmp_path):
    values = configuration(tmp_path, INTEGRATION_STATE_PAYLOAD_BYTES=2 * 1024**2)
    selected = runtime_factory.initialize_new(values)
    original = {"unknown_full_value": "S" * (1024**2 + 100)}
    selected.save(original)
    before = selected.path.read_bytes()
    assert runtime_factory.configured_runtime_store(values).load() == original
    with pytest.raises(ConfigStoreError, match="state_too_large"):
        runtime_factory.configured_runtime_store(configuration(tmp_path)).load()
    assert selected.path.read_bytes() == before


def test_actual_larger_depth_profile_retains_all_unknown_values_without_truncation(tmp_path):
    values = configuration(tmp_path, INTEGRATION_STATE_JSON_DEPTH=80)
    selected = runtime_factory.initialize_new(values)
    extension: dict = {"retained": SECRET}
    for _level in range(70):
        extension = {"child": extension}
    original = {"unknown_extension": extension}
    selected.save(original)
    before = selected.path.read_bytes()
    assert runtime_factory.configured_runtime_store(values).load() == original
    with pytest.raises(ConfigStoreError, match="state_too_deep"):
        runtime_factory.configured_runtime_store(configuration(tmp_path)).load()
    assert selected.path.read_bytes() == before


def test_safe_actions_do_not_echo_unknown_code_or_any_exception_values():
    instruction = runtime_factory.runtime_state_instruction(SECRET)
    assert SECRET not in instruction and KEY not in instruction
    assert "Originaldatei" in instruction
    assert runtime_factory.MAINTENANCE_HELP.endswith(" convert --help")


def test_revision_conflict_instruction_requires_fresh_read_and_review():
    instruction = runtime_factory.runtime_state_instruction("state_revision_conflict")
    assert "neu laden" in instruction and "erneut prüfen" in instruction
    assert SECRET not in instruction and KEY not in instruction


@pytest.mark.parametrize("code", ["state_io_failed", "lock_close_failed"])
def test_uncertain_publication_instruction_requires_check_before_retry(code):
    instruction = runtime_factory.runtime_state_instruction(code)
    assert "veröffentlicht" in instruction and "ungewiss" in instruction
    assert "prüfen, bevor" in instruction and "nicht automatisch wiederholen" in instruction
    assert SECRET not in instruction and KEY not in instruction
