"""Persistence backends for integration settings."""

from __future__ import annotations

import json
import os
import tempfile
from abc import ABC, abstractmethod
from copy import deepcopy
from pathlib import Path


class IntegrationConfigStore(ABC):
    @abstractmethod
    def load(self) -> dict:
        ...

    @abstractmethod
    def save(self, state: dict) -> None:
        ...


class InMemoryIntegrationConfigStore(IntegrationConfigStore):
    def __init__(self) -> None:
        self._state: dict = {}

    def load(self) -> dict:
        return deepcopy(self._state)

    def save(self, state: dict) -> None:
        self._state = deepcopy(state)


class JsonFileIntegrationConfigStore(IntegrationConfigStore):
    def __init__(self, file_path: str) -> None:
        self._path = Path(file_path)

    @property
    def history_path(self) -> str:
        return str(self._path.with_suffix(self._path.suffix + ".history.sqlite3"))

    def load(self) -> dict:
        if not self._path.exists():
            return {}
        state = json.loads(self._path.read_text(encoding="utf-8"))
        if not isinstance(state, dict) or not isinstance(state.get("config", {}), dict) or not isinstance(state.get("enabled", {}), dict):
            raise ValueError("Ungültige gespeicherte Integrationskonfiguration")
        return state

    def save(self, state: dict) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        content = json.dumps(state, ensure_ascii=False, indent=2)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self._path.parent,
                                             prefix=f".{self._path.name}.", suffix=".tmp", delete=False) as file:
                temporary = file.name
                file.write(content)
                file.flush()
                os.fsync(file.fileno())
            os.replace(temporary, self._path)
            temporary = None
        finally:
            if temporary is not None:
                Path(temporary).unlink(missing_ok=True)
