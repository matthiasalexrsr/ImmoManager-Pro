"""Validated private draft envelopes. Incomplete field values remain strings."""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class DraftIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid")
    collection: str = Field(min_length=1, max_length=80, pattern=r"^[a-z][a-z/-]*$")
    entity_id: str | None = Field(None, min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_.:-]+$")
    form_key: str = Field("crud", min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_.:-]+$")
    owner_id: str | None = Field(None, min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_.:-]+$")


class DraftWrite(DraftIdentity):
    expected_revision: str | None = Field(None, pattern=r"^[0-9a-f-]{36}$")
    schema_signature: str = Field(alias="schema", min_length=1, max_length=4096)
    values: dict[str, Any]
    original_values: dict[str, Any] = Field(default_factory=dict)
    edit_revision: dict[str, Any] | None = None
    submission_pending: bool = False


class DraftDelete(DraftIdentity):
    expected_revision: str = Field(pattern=r"^[0-9a-f-]{36}$")
