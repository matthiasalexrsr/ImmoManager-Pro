"""Core contracts for integration providers and run tracking."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Protocol
from uuid import uuid4


@dataclass
class IntegrationActionResult:
    success: bool
    message: str
    details: dict | None = None


@dataclass
class IntegrationManifest:
    integration_id: str
    name: str
    category: str
    description: str
    planned: bool = False
    enabled_by_default: bool = False
    capabilities: list[str] = field(default_factory=list)


@dataclass
class IntegrationRunRecord:
    integration_id: str
    success: bool
    message: str
    payload: dict
    details: dict | None = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    id: str = field(default_factory=lambda: uuid4().hex)


class IntegrationProvider(Protocol):
    """Provider contract for external integration modules."""

    @property
    def manifest(self) -> IntegrationManifest:
        ...

    def is_configured(self, config: dict) -> bool:
        ...

    def health(self, config: dict) -> dict:
        ...

    def run(self, payload: dict, config: dict) -> IntegrationActionResult:
        ...
