"""Pure proof of the connection state inside a complete recovery container."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from pathlib import Path

from .integrations.config_store import ConfigStoreError, _decode
from .integrations.encrypted_config_store import _envelope_limit
from .integrations.integration_state_offline import (
    _positive_int,
    _read_only_bytes,
    verify_encrypted_integration_state,
)
from .recovery_archive import RecoveryError


def verify_archived_integration_state(
    path: Path,
    configuration: Mapping,
    *,
    max_plaintext_bytes: int,
    max_json_depth: int,
) -> dict[str, object]:
    """Explicit archived keys only; preserve legacy bytes without converting.

    Callers bind state_revision to the actual archived file record. No store
    initialization, sidecar lock, auth lookup or ambient keyring is involved.
    """
    try:
        maximum = _positive_int(max_plaintext_bytes, "invalid_store_limit")
        depth = _positive_int(max_json_depth, "invalid_json_depth")
        raw = _read_only_bytes(path, _envelope_limit(maximum))
        state = _decode(raw, depth)
        revision = hashlib.sha256(raw).hexdigest()
        if "format" in state or "ciphertext" in state:
            result = verify_encrypted_integration_state(
                path, configuration, max_plaintext_bytes=maximum,
                max_json_depth=depth,
            )
            if result["state_revision"] != revision:
                raise ConfigStoreError("state_file_changed")
            return {**result, "legacy_requires_migration": False}
        if len(raw) > maximum:
            raise ConfigStoreError("state_too_large")
        return {
            "verified": True,
            "format": "immomanager/integration-state-legacy-json",
            "state_revision": revision,
            "legacy_requires_migration": True,
        }
    except ConfigStoreError:
        raise RecoveryError(
            "Integrationszugänge konnten mit den gesicherten Schlüsseln und "
            "Prüfgrenzen nicht vollständig geprüft werden. Unveränderte "
            "vollständige Sicherung verwenden; das Ziel wurde nicht freigegeben."
        ) from None
