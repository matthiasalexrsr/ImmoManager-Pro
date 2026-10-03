"""Explicit runtime construction; fresh initialization is a separate operation.

This module imports no application/config/settings/providers. Callers supply the
selected configuration; normal construction never loads or initializes a file.
Root owns the lifetime lease and explicit launcher permission for initialize_new.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from copy import deepcopy
from threading import Lock
from types import MappingProxyType

from .config_store import (
    _JSON_DEPTH,
    _LIMIT,
    ConfigStoreError,
    InMemoryIntegrationConfigStore,
    IntegrationConfigStore,
)
from .encrypted_config_store import EncryptedJsonIntegrationConfigStore

_KEY_FIELDS = (
    "encryption_key", "encryption_keyring", "encryption_active_key_id",
    "encryption_index_key", "encryption_legacy_jwt_keys",
)
MAINTENANCE_HELP = "python -m backend.integration_state_upgrade convert --help"
_INSTRUCTIONS = {
    "plaintext_state_requires_migration": (
        "Die Integrationsdatei ist noch unverschlüsselt. Anwendung und Hintergrundprozesse beenden; "
        "den vollständigen gesicherten Wartungsweg verwenden: " + MAINTENANCE_HELP
    ),
    "state_missing": (
        "Die Integrationsdatei fehlt. Vorhandenen Bestand aus einer vollständigen Sicherung wiederherstellen. "
        "Eine ausdrücklich neue Datei nur über den Launcher mit --initialize-integrations anlegen; "
        "Hilfe: python -m backend --help"
    ),
    "encryption_key_unavailable": (
        "Dauerhafte Feldschlüssel fehlen oder sind ungültig. Die vollständige Schlüsselkonfiguration "
        "der ausgewählten Installation wiederherstellen; keine Ersatzschlüssel für vorhandene Daten erzeugen."
    ),
    "state_busy": (
        "Ein anderer Schreibvorgang hält die Integrationsdatei. Den Vorgang beenden oder das "
        "positive Wartebudget integration_state_lock_timeout_seconds prüfen."
    ),
    "state_revision_conflict": (
        "Der Integrationszustand wurde inzwischen geändert. Den aktuellen Zustand neu laden "
        "und die gewünschten Änderungen erneut prüfen, bevor sie gespeichert werden."
    ),
    "state_io_failed": (
        "Ein Dateivorgang ist fehlgeschlagen; ob eine Änderung veröffentlicht wurde, ist ungewiss. "
        "Den aktuellen Integrationszustand und die vollständige Sicherung prüfen, bevor der Vorgang "
        "erneut ausgeführt wird; nicht automatisch wiederholen."
    ),
    "lock_close_failed": (
        "Die Dateisperre konnte nicht sicher geschlossen werden; ob eine Änderung veröffentlicht wurde, "
        "ist ungewiss. Den aktuellen Integrationszustand und die vollständige Sicherung prüfen, bevor "
        "der Vorgang erneut ausgeführt wird; nicht automatisch wiederholen."
    ),
    "state_too_large": (
        "Die Integrationsdatei überschreitet das gewählte Nutzdatenbudget. Ein ausreichendes positives "
        "integration_state_payload_bytes und passendes Vollsicherungsprofil konfigurieren."
    ),
    "state_too_deep": (
        "Die Integrationsdatei überschreitet die gewählte JSON-Tiefe. Ein ausreichendes positives "
        "integration_state_json_depth konfigurieren; vorhandene Felder nicht entfernen."
    ),
    "explicit_initialization_required": (
        "Erstinitialisierung muss ausdrücklich über den Launcher mit --initialize-integrations "
        "unter der Installationssperre erfolgen; Hilfe: python -m backend --help"
    ),
    "integration_state_path_required": (
        "Für die ausdrückliche Erstinitialisierung muss eine dauerhafte Integrationsdatei "
        "der ausgewählten Installation konfiguriert sein."
    ),
}


def runtime_state_instruction(code: str) -> str:
    """Fixed safe actions only; never interpolate paths, exceptions or values."""
    return _INSTRUCTIONS.get(code, (
        "Integrationszustand konnte nicht unverändert bestätigt werden. Vollständige Originaldatei, "
        "passende Schlüsselkonfiguration und Dateirechte prüfen; keine automatische Wiederholung "
        "oder leere Ersatzkonfiguration verwenden."
    ))


def _configuration(values: Mapping) -> dict:
    if not isinstance(values, Mapping):
        raise ConfigStoreError("invalid_runtime_configuration")
    result = {}
    for key, value in values.items():
        if not isinstance(key, str) or key.lower() in result:
            raise ConfigStoreError("invalid_runtime_configuration")
        result[key.lower()] = value
    return result


def _integer(values: Mapping, name: str, default: int, code: str) -> int:
    value = values.get(name, default)
    if isinstance(value, str):
        raw = value.strip()
        if not raw.isascii() or not raw.isdecimal():
            raise ConfigStoreError(code)
        try:
            value = int(raw)
        except ValueError:
            raise ConfigStoreError(code) from None
    if type(value) is not int or value < 1:
        raise ConfigStoreError(code)
    return value


def _wait(values: Mapping) -> float:
    value = values.get("integration_state_lock_timeout_seconds", 5.0)
    if isinstance(value, str):
        try:
            value = float(value)
        except ValueError:
            raise ConfigStoreError("invalid_lock_timeout") from None
    if type(value) not in (int, float):
        raise ConfigStoreError("invalid_lock_timeout")
    try:
        value = float(value)
    except (ValueError, OverflowError):
        raise ConfigStoreError("invalid_lock_timeout") from None
    if not math.isfinite(value) or value <= 0:
        raise ConfigStoreError("invalid_lock_timeout")
    return value


class RuntimeEncryptedIntegrationConfigStore(IntegrationConfigStore):
    """Defer even path failures; delegate actual work to the existing cipher store."""

    def __init__(self, path, *, maximum: int, depth: int, wait: float, keys: Mapping):
        self._path = path
        self._maximum, self._depth, self._wait, self._keys = maximum, depth, wait, keys
        self._store: EncryptedJsonIntegrationConfigStore | None = None
        self._construction_lock = Lock()

    def _materialize(self) -> EncryptedJsonIntegrationConfigStore:
        with self._construction_lock:
            if self._store is None:
                if not isinstance(self._path, str) or not self._path.strip():
                    raise ConfigStoreError("invalid_store_path")
                self._store = EncryptedJsonIntegrationConfigStore(
                    self._path, max_plaintext_bytes=self._maximum, max_json_depth=self._depth,
                    lock_timeout=self._wait, keyring=self._keys,
                )
            return self._store

    def load(self) -> dict:
        return self._materialize().load()

    def save(self, state: dict) -> None:
        self._materialize().save(state)

    def update(self, mutate) -> dict:
        return self._materialize().update(mutate)

    def load_with_revision(self) -> tuple[dict, str]:
        return self._materialize().load_with_revision()

    def update_if_revision(self, expected_revision: str, mutate) -> tuple[dict, str]:
        return self._materialize().update_if_revision(expected_revision, mutate)


def configured_runtime_store(explicit_configuration: Mapping) -> IntegrationConfigStore:
    """Construct only; all selected file/key validation happens on actual use."""
    values = _configuration(explicit_configuration)
    maximum = _integer(values, "integration_state_payload_bytes", _LIMIT, "invalid_store_limit")
    depth = _integer(values, "integration_state_json_depth", _JSON_DEPTH, "invalid_json_depth")
    wait = _wait(values)
    path = values.get("integration_state_file")
    if path is None or path == "":
        return InMemoryIntegrationConfigStore(max_bytes=maximum, max_json_depth=depth)
    # A non-None immutable explicit snapshot prevents ring_for's ambient branch.
    # Keep malformed keys deferred so registration cannot abort other modules.
    keys = MappingProxyType(deepcopy({name: values[name] for name in _KEY_FIELDS if name in values}))
    return RuntimeEncryptedIntegrationConfigStore(
        path, maximum=maximum, depth=depth, wait=wait, keys=keys,
    )


def initialize_new(
    explicit_configuration: Mapping, *, expected_missing: bool = True,
) -> EncryptedJsonIntegrationConfigStore:
    """Explicit bootstrap under Root's held lifetime lease, never normal startup.

    Existing valid encrypted bytes are authenticated as an unchanged no-op;
    plaintext/damaged/wrong-key files never become empty or get replaced.
    """
    if type(expected_missing) is not bool or expected_missing is not True:
        raise ConfigStoreError("explicit_initialization_required")
    selected = configured_runtime_store(explicit_configuration)
    if not isinstance(selected, RuntimeEncryptedIntegrationConfigStore):
        raise ConfigStoreError("integration_state_path_required")
    store = selected._materialize()
    ring = store._ring()
    if not ring.active_key_id or ring.active_key_id not in ring.keys:
        raise ConfigStoreError("encryption_key_unavailable")
    store.initialize()
    return store
