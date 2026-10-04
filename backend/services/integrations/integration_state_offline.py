"""Read-only verification for archived encrypted integration state.

No runtime settings, auth state, provider code or filesystem mutation is used.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Mapping
from pathlib import Path

from ..iban_encryption import IBANEncryptionError, keyring_from_configuration
from .config_store import (
    _JSON_DEPTH,
    _LIMIT,
    ConfigStoreError,
    _decode,
    _regular,
    _verify_handle,
)
from .encrypted_config_store import FORMAT, IDENTITY, _envelope_limit
from .history_crypto import decrypt
from .history_types import HistoryError


def _positive_int(value: object, code: str) -> int:
    if type(value) is not int or value < 1:
        raise ConfigStoreError(code)
    return value


def _read_only_bytes(path: Path, maximum: int) -> bytes:
    _regular(path)
    descriptor = None
    try:
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags | getattr(os, "O_BINARY", 0))
        size = _verify_handle(path, descriptor).st_size
        if size > maximum:
            raise ConfigStoreError("state_too_large")
        with os.fdopen(descriptor, "rb") as source:
            descriptor = None
            raw = source.read(size + 1)
    except OSError:
        raise ConfigStoreError("state_unreadable") from None
    finally:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                raise ConfigStoreError("state_read_close_failed") from None
    if len(raw) > maximum:
        raise ConfigStoreError("state_too_large")
    return raw


def verify_encrypted_integration_state(
    file_path: str | Path,
    explicit_configuration: Mapping,
    *,
    max_plaintext_bytes: int = _LIMIT,
    max_json_depth: int = _JSON_DEPTH,
) -> dict[str, object]:
    """Authenticate/decrypt an archived state without writing or ambient fallback."""
    plaintext_limit = _positive_int(
        max_plaintext_bytes, "invalid_store_limit"
    )
    depth = _positive_int(max_json_depth, "invalid_json_depth")
    if not isinstance(explicit_configuration, Mapping):
        raise ConfigStoreError("encryption_key_unavailable")

    try:
        ring = keyring_from_configuration(explicit_configuration)
    except IBANEncryptionError:
        raise ConfigStoreError("encryption_key_unavailable") from None

    try:
        path = Path(file_path).expanduser().absolute()
        if not path.name:
            raise ValueError
        path = path.parent.resolve() / path.name
    except (OSError, RuntimeError, ValueError):
        raise ConfigStoreError("invalid_store_path") from None

    raw = _read_only_bytes(path, _envelope_limit(plaintext_limit))
    envelope = _decode(raw, depth)
    if set(envelope) != {"format", "ciphertext"}:
        if "format" in envelope or "ciphertext" in envelope:
            raise ConfigStoreError("encrypted_state_invalid")
        raise ConfigStoreError("plaintext_state_requires_migration")
    token = envelope.get("ciphertext")
    if envelope.get("format") != FORMAT or not isinstance(token, str):
        raise ConfigStoreError("encrypted_state_invalid")

    try:
        plain = decrypt(token, IDENTITY, ring)
    except HistoryError:
        raise ConfigStoreError("encrypted_state_unreadable") from None
    if len(plain) > plaintext_limit:
        raise ConfigStoreError("state_too_large")
    state = _decode(plain, depth)

    parts = token.split(":", 3)
    if len(parts) != 4 or parts[0:2] != ["history", "v1"]:
        raise ConfigStoreError("encrypted_state_invalid")
    enabled = state.get("enabled", {})
    configs = state.get("config", {})
    return {
        "verified": True,
        "format": FORMAT,
        "key_id": parts[2],
        "file_size_bytes": len(raw),
        "plaintext_size_bytes": len(plain),
        "state_revision": hashlib.sha256(raw).hexdigest(),
        "enabled_integrations": sum(
            1 for value in enabled.values() if value is True
        ),
        "configured_integrations": len(configs),
        "top_level_fields": len(state),
    }


def load_explicit_configuration(
    path: str | Path, *, max_bytes: int = _LIMIT
) -> dict:
    """Strict JSON configuration reader for maintenance tools, without settings."""
    try:
        source = Path(path).expanduser().absolute()
        if not source.name:
            raise ValueError
        source = source.parent.resolve() / source.name
    except (OSError, RuntimeError, ValueError):
        raise ConfigStoreError("invalid_configuration_path") from None

    raw = _read_only_bytes(
        source, _positive_int(max_bytes, "invalid_configuration_limit")
    )

    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError
            result[key] = value
        return result

    def reject_constant(_value):
        raise ValueError

    try:
        value = json.loads(
            raw.decode("utf-8-sig"),
            object_pairs_hook=unique,
            parse_constant=reject_constant,
        )
    except (ValueError, UnicodeError, RecursionError):
        raise ConfigStoreError("invalid_configuration") from None
    if not isinstance(value, dict):
        raise ConfigStoreError("invalid_configuration")
    return value
