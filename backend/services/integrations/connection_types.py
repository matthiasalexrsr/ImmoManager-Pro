"""Explicit commands for private connections, mappings and action preparation."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ConnectionCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    idempotency_key: str = Field(min_length=1, max_length=128)


class ConnectionCreate(ConnectionCommand):
    provider_id: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=200)
    config: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = False


class ConnectionUpdate(ConnectionCommand):
    base_revision: int = Field(ge=1)
    name: str | None = Field(default=None, min_length=1, max_length=200)
    config: dict[str, Any] | None = None
    clear_secrets: list[str] = Field(default_factory=list)
    enabled: bool | None = None
    archived: bool | None = None


class LegacyAdoption(ConnectionCommand):
    provider_id: str = Field(min_length=1, max_length=80)
    expected_source_hash: str = Field(pattern=r"^[0-9a-f]{64}$")


class SourceObservation(ConnectionCommand):
    source_kind: str = Field(min_length=1, max_length=100)
    external_key: str = Field(min_length=1, max_length=2048)
    raw: dict[str, Any]
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    base_revision: int | None = Field(default=None, ge=1)


class MappingDecision(ConnectionCommand):
    base_revision: int = Field(ge=1)
    source_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    target_kind: str = Field(min_length=1, max_length=60)
    target_id: str = Field(min_length=1, max_length=120)
    target_revision: str = Field(min_length=1, max_length=200)
    decision: Literal["mapped", "accepted"]


class RunPreparation(ConnectionCommand):
    config_revision: int = Field(ge=1)
    action: str = Field(min_length=1, max_length=100)
    payload: dict[str, Any] = Field(default_factory=dict)
    source_kind: str | None = Field(default=None, min_length=1, max_length=60)
    source_id: str | None = Field(default=None, min_length=1, max_length=120)
    source_revision: str | None = Field(default=None, min_length=1, max_length=200)

    @model_validator(mode="after")
    def complete_source(self):
        if any(value is not None for value in (self.source_kind, self.source_id, self.source_revision)):
            if not all(value for value in (self.source_kind, self.source_id, self.source_revision)):
                raise ValueError("Quellart, Quellkennung und Quellrevision werden gemeinsam benötigt.")
        return self


class RunDispatch(ConnectionCommand):
    base_revision: int = Field(ge=1)
    confirm: Literal[True]


class RunReconcile(ConnectionCommand):
    base_revision: int = Field(ge=1)
    lookup_action: str = Field(min_length=1, max_length=100)
    lookup_payload: dict[str, Any] = Field(default_factory=dict)


class RunCancellation(ConnectionCommand):
    base_revision: int = Field(ge=1)
    reason: str = Field(min_length=1, max_length=500)


class RecordedResultReconcile(ConnectionCommand):
    """Acknowledge a verified retained result, never execute the original action again."""
    base_revision: int = Field(ge=1)
    attempt_id: str = Field(min_length=1, max_length=36)
    reason: str = Field(min_length=1, max_length=500)
    confirm: Literal[True]
