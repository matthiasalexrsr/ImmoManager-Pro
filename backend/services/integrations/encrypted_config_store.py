"""Encrypted durable integration state using the existing stable field keyring.

The outer file remains a small JSON object so the existing full-backup container
can copy it opaquely. Provider configuration, secrets and unknown discovery
fields are all inside the authenticated ciphertext.
"""

from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
from pathlib import Path
from typing import Any

from .config_store import (
    _LIMIT,
    ConfigStoreError,
    JsonFileIntegrationConfigStore,
    _decode,
    _encode,
    _regular,
)
from .history_crypto import decrypt, encrypt, ring_for
from .history_types import HistoryError

FORMAT = "immomanager/integration-state-encrypted/v1"
IDENTITY = {"kind": "integration_config_state", "version": 1}


def _envelope_limit(plaintext_limit: int) -> int:
    # AES-GCM adds a nonce/tag and base64 expands to 4/3. The version/key-id
    # header and JSON framing are tiny; keep explicit margin without reducing
    # the historical plaintext budget.
    return ((plaintext_limit + 64 + 2) // 3) * 4 + 4096


class EncryptedJsonIntegrationConfigStore(JsonFileIntegrationConfigStore):
    """Atomic encrypted state file; no plaintext fallback on normal reads."""

    def __init__(
        self,
        file_path: str,
        *,
        max_plaintext_bytes: int = _LIMIT,
        lock_timeout: float = 5.0,
        keyring: Any = None,
    ):
        if type(max_plaintext_bytes) is not int or not 1 <= max_plaintext_bytes <= 16 * 1024**2:
            raise ConfigStoreError("invalid_store_limit")
        envelope_limit = _envelope_limit(max_plaintext_bytes)
        # Reuse the reviewed file-lock/replace implementation without reducing
        # its historical plaintext allowance. The subclass's outer envelope is
        # larger only because authenticated encryption/base64 add bytes.
        super().__init__(
            file_path,
            max_bytes=min(envelope_limit, 16 * 1024**2),
            lock_timeout=lock_timeout,
        )
        self._maximum = envelope_limit
        self._plaintext_maximum = max_plaintext_bytes
        self._keyring = keyring

    def _ring(self):
        try:
            return ring_for(self._keyring)
        except HistoryError:
            raise ConfigStoreError("encryption_key_unavailable") from None

    def _encrypted_raw(self, state: dict) -> bytes:
        plain = _encode(state, self._plaintext_maximum)
        try:
            token = encrypt(plain, IDENTITY, self._ring())
        except HistoryError:
            raise ConfigStoreError("encryption_failed") from None
        envelope = {"format": FORMAT, "ciphertext": token}
        return _encode(envelope, self._maximum)

    def _decrypt_envelope(self, envelope: dict) -> dict:
        if set(envelope) != {"format", "ciphertext"}:
            if "format" in envelope or "ciphertext" in envelope:
                raise ConfigStoreError("encrypted_state_invalid")
            raise ConfigStoreError("plaintext_state_requires_migration")
        if envelope.get("format") != FORMAT or not isinstance(envelope.get("ciphertext"), str):
            raise ConfigStoreError("encrypted_state_invalid")
        try:
            plain = decrypt(envelope["ciphertext"], IDENTITY, self._ring())
        except HistoryError:
            raise ConfigStoreError("encrypted_state_unreadable") from None
        if len(plain) > self._plaintext_maximum:
            raise ConfigStoreError("state_too_large")
        return _decode(plain)

    def _load_decrypted_locked(self) -> dict:
        return self._decrypt_envelope(super()._load_locked())

    def load(self) -> dict:
        with self._locked():
            return self._load_decrypted_locked()

    def initialize(self, state: dict | None = None) -> dict:
        """Create only a missing encrypted file; never auto-convert plaintext."""
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
        except OSError:
            raise ConfigStoreError("state_io_failed") from None
        with self._locked():
            if _regular(self._path, missing_ok=True) is not None:
                return self._load_decrypted_locked()
            selected = {} if state is None else deepcopy(state)
            raw = self._encrypted_raw(selected)
            self._write_locked(raw)
            return _decode(_encode(selected, self._plaintext_maximum))

    def save(self, state: dict) -> None:
        """Whole-state replacement after proving the previous encrypted file."""
        raw = self._encrypted_raw(state)
        with self._locked():
            self._load_decrypted_locked()
            self._write_locked(raw)

    def update(self, mutate: Callable[[dict], dict]) -> dict:
        with self._locked():
            current = self._load_decrypted_locked()
            candidate = mutate(deepcopy(current))
            # Validate the full candidate before encryption/publication.
            checked = _decode(_encode(candidate, self._plaintext_maximum))
            self._write_locked(self._encrypted_raw(checked))
            return deepcopy(checked)

    def migrate_legacy_plaintext(self) -> dict:
        """Explicit one-time conversion; never called by normal startup."""
        with self._locked():
            current = super()._load_locked()
            if "format" in current or "ciphertext" in current:
                return self._decrypt_envelope(current)
            checked = _decode(_encode(current, self._plaintext_maximum))
            self._write_locked(self._encrypted_raw(checked))
            return deepcopy(checked)

    @property
    def path(self) -> Path:
        return self._path
