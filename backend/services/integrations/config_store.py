"""Persistence backends for integration settings."""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
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
        return dict(self._state)

    def save(self, state: dict) -> None:
        self._state = dict(state)


class JsonFileIntegrationConfigStore(IntegrationConfigStore):
    def __init__(self, file_path: str) -> None:
        self._path = Path(file_path)

    def load(self) -> dict:
        if not self._path.exists():
            return {}
        try:
            return json.loads(self._path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}

    def save(self, state: dict) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
