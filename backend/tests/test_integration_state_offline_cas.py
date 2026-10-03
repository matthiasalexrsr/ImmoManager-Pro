"""Offline verification, maintenance conversion and CAS for integration state."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from backend import auth
from backend.services.iban_encryption import IBANKeyring, generate_key
from backend.services.integrations import history_crypto
from backend.services.integrations.config_store import (
    ConfigStoreError,
    JsonFileIntegrationConfigStore,
)
from backend.services.integrations.encrypted_config_store import (
    FORMAT,
    EncryptedJsonIntegrationConfigStore,
    build_encrypted_integration_store,
)
from backend.services.integrations.integration_state_offline import (
    verify_encrypted_integration_state,
)


def archive_configuration(key_id: str = "archive") -> tuple[dict[str, str], IBANKeyring]:
    key = generate_key()
    config = {
        "ENCRYPTION_KEYRING": json.dumps({key_id: key}),
        "ENCRYPTION_ACTIVE_KEY_ID": key_id,
    }
    return config, IBANKeyring(key_id, {key_id: key})


def nested_unknown(depth: int):
    value: object = "preserved"
    for index in range(depth):
        value = {f"unknown_{index}": value}
    return value


def test_resource_budgets_have_defaults_but_no_arbitrary_upper_ceiling(tmp_path):
    plain = JsonFileIntegrationConfigStore(
        str(tmp_path / "plain.json"),
        max_bytes=32 * 1024 * 1024,
        lock_timeout=120.5,
        max_json_depth=128,
    )
    assert plain._maximum == 32 * 1024 * 1024
    assert plain._timeout == 120.5
    assert plain._max_depth == 128

    _, ring = archive_configuration()
    encrypted = EncryptedJsonIntegrationConfigStore(
        str(tmp_path / "encrypted.json"),
        max_plaintext_bytes=32 * 1024 * 1024,
        lock_timeout=180,
        max_json_depth=96,
        keyring=ring,
    )
    assert encrypted._plaintext_maximum == 32 * 1024 * 1024
    assert encrypted._timeout == 180
    assert encrypted._max_depth == 96

    for kwargs in (
        {"max_bytes": True},
        {"max_bytes": 0},
        {"max_bytes": -1},
        {"lock_timeout": True},
        {"lock_timeout": 0},
        {"lock_timeout": float("nan")},
        {"max_json_depth": True},
        {"max_json_depth": 0},
    ):
        with pytest.raises(ConfigStoreError):
            JsonFileIntegrationConfigStore(
                str(tmp_path / ("invalid-" + str(len(kwargs)) + ".json")),
                **kwargs,
            )


def test_json_depth_is_explicit_policy_and_unknown_fields_are_preserved(tmp_path):
    _, ring = archive_configuration()
    state = {
        "enabled": {"email": True},
        "config": {
            "email": {
                "smtp_password": "SYNTHETIC_DEPTH_SECRET",
                "provider_unknown": nested_unknown(70),
            }
        },
        "future_top_level": {"still": "preserved"},
    }

    default = EncryptedJsonIntegrationConfigStore(
        str(tmp_path / "default.json"), keyring=ring
    )
    with pytest.raises(ConfigStoreError) as failure:
        default.initialize(state)
    assert failure.value.code == "state_too_deep"
    assert not (tmp_path / "default.json").exists()

    explicit = EncryptedJsonIntegrationConfigStore(
        str(tmp_path / "deep.json"),
        max_json_depth=96,
        keyring=ring,
    )
    assert explicit.initialize(state) == state
    assert explicit.load() == state
    assert b"SYNTHETIC_DEPTH_SECRET" not in (tmp_path / "deep.json").read_bytes()


def test_archive_verifier_is_read_only_and_uses_only_explicit_configuration(
    tmp_path, monkeypatch
):
    config, ring = archive_configuration()
    path = tmp_path / "integrations.json"
    state = {
        "enabled": {"email": True},
        "config": {
            "email": {
                "smtp_password": "SYNTHETIC_ARCHIVE_SECRET",
                "unknown": {"late": ["a", {"field": "kept"}]},
            }
        },
    }
    store = EncryptedJsonIntegrationConfigStore(str(path), keyring=ring)
    store.initialize(state)

    before_bytes = path.read_bytes()
    before_stat = path.stat()
    before_names = sorted(item.name for item in tmp_path.iterdir())

    monkeypatch.setattr(
        history_crypto,
        "current_keyring",
        lambda: (_ for _ in ()).throw(AssertionError("ambient keyring used")),
    )
    monkeypatch.setattr(
        auth,
        "get_user_by_id",
        lambda *_: (_ for _ in ()).throw(AssertionError("live auth used")),
    )

    result = verify_encrypted_integration_state(path, config)

    assert result["verified"] is True
    assert result["format"] == FORMAT
    assert result["key_id"] == "archive"
    assert result["enabled_integrations"] == 1
    assert result["configured_integrations"] == 1
    assert "SYNTHETIC_ARCHIVE_SECRET" not in repr(result)
    assert path.read_bytes() == before_bytes
    after_stat = path.stat()
    assert (after_stat.st_size, after_stat.st_mtime_ns) == (
        before_stat.st_size,
        before_stat.st_mtime_ns,
    )
    assert sorted(item.name for item in tmp_path.iterdir()) == before_names

    wrong, _ = archive_configuration("wrong")
    with pytest.raises(ConfigStoreError) as failure:
        verify_encrypted_integration_state(path, wrong)
    assert failure.value.code == "encrypted_state_unreadable"
    assert path.read_bytes() == before_bytes


def test_factory_is_construction_only_and_never_initializes_or_migrates(tmp_path):
    config, _ = archive_configuration()
    path = tmp_path / "not-created.json"

    store = build_encrypted_integration_store(
        str(path),
        config,
        max_plaintext_bytes=20 * 1024 * 1024,
        lock_timeout=75,
        max_json_depth=80,
    )

    assert isinstance(store, EncryptedJsonIntegrationConfigStore)
    assert store.path == path
    assert not path.exists()
    assert list(tmp_path.iterdir()) == []


def test_encrypted_store_cas_preserves_unknown_fields_and_stale_revision_is_atomic(
    tmp_path,
):
    _, ring = archive_configuration()
    path = tmp_path / "cas.json"
    state = {
        "enabled": {"email": False},
        "config": {
            "email": {
                "smtp_password": "SYNTHETIC_CAS_SECRET",
                "unknown": {"provider_field": "keep-me"},
            }
        },
    }
    store = EncryptedJsonIntegrationConfigStore(str(path), keyring=ring)
    store.initialize(state)
    loaded, revision = store.load_with_revision()
    assert loaded == state

    def enable(candidate):
        candidate["enabled"]["email"] = True
        return candidate

    updated, next_revision = store.update_if_revision(revision, enable)
    assert updated["enabled"]["email"] is True
    assert updated["config"]["email"]["smtp_password"] == "SYNTHETIC_CAS_SECRET"
    assert updated["config"]["email"]["unknown"] == {"provider_field": "keep-me"}
    assert next_revision != revision
    assert b"SYNTHETIC_CAS_SECRET" not in path.read_bytes()

    before = path.read_bytes()
    with pytest.raises(ConfigStoreError) as failure:
        store.update_if_revision(revision, lambda candidate: {})
    assert failure.value.code == "state_revision_conflict"
    assert path.read_bytes() == before
    assert store.load() == updated


def test_legacy_unfenced_cli_refuses_and_directs_to_complete_maintenance(tmp_path):
    state_path = tmp_path / "integrations.json"
    config_path = tmp_path / "archive-configuration.json"
    secret = "SYNTHETIC_CLI_SECRET_MUST_NOT_PRINT"
    state = {
        "enabled": {"email": True},
        "config": {
            "email": {
                "smtp_host": "smtp.synthetic.invalid",
                "smtp_password": secret,
                "unknown": {"provider_extension": "keep-me"},
            }
        },
    }
    JsonFileIntegrationConfigStore(str(state_path)).initialize(state)
    old_bytes = state_path.read_bytes()
    assert secret.encode() in old_bytes

    config, _ = archive_configuration()
    config_path.write_text(json.dumps(config), encoding="utf-8")
    root = Path(__file__).resolve().parents[2]
    command = [
        sys.executable,
        "scripts/integration_state_maintenance.py",
        "migrate-plaintext",
        "--state-file",
        str(state_path),
        "--configuration",
        str(config_path),
    ]
    result = subprocess.run(
        command,
        cwd=root,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 2, result.stderr
    assert secret not in result.stdout + result.stderr
    report = json.loads(result.stderr)
    assert report["code"] == "fenced_maintenance_required"
    assert "backend.integration_state_upgrade convert" in report["maintenance_command"]
    assert state_path.read_bytes() == old_bytes

    # Verification remains the original read-only command after a checked
    # conversion; here the lower-level primitive gets the actual source SHA.
    import hashlib
    store = build_encrypted_integration_store(str(state_path), config)
    store.migrate_legacy_plaintext(expected_revision=hashlib.sha256(old_bytes).hexdigest())
    before_second = state_path.read_bytes()
    command[2] = "verify"
    second = subprocess.run(
        command,
        cwd=root,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )
    assert second.returncode == 0
    assert secret not in second.stdout + second.stderr
    assert state_path.read_bytes() == before_second

    names = {item.name for item in tmp_path.iterdir()}
    assert not any(
        name.endswith(".bak")
        or name.endswith(".backup")
        or "rollback" in name.lower()
        for name in names
    )


def test_cli_failure_leaves_plaintext_bytes_unchanged_and_never_prints_secret(
    tmp_path,
):
    state_path = tmp_path / "legacy.json"
    config_path = tmp_path / "bad-config.json"
    secret = "SYNTHETIC_FAILED_MIGRATION_SECRET"
    state = {
        "config": {
            "email": {
                "smtp_password": secret,
                "too_deep": nested_unknown(70),
            }
        }
    }
    # Use a deliberately higher legacy policy so the source file is valid.
    JsonFileIntegrationConfigStore(
        str(state_path), max_json_depth=96
    ).initialize(state)
    before = state_path.read_bytes()
    config, _ = archive_configuration()
    config_path.write_text(json.dumps(config), encoding="utf-8")

    root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        [
            sys.executable,
            "scripts/integration_state_maintenance.py",
            "migrate-plaintext",
            "--state-file",
            str(state_path),
            "--configuration",
            str(config_path),
            "--max-json-depth",
            "64",
        ],
        cwd=root,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 2
    assert secret not in result.stdout + result.stderr
    assert state_path.read_bytes() == before
    assert json.loads(result.stderr)["code"] == "fenced_maintenance_required"
