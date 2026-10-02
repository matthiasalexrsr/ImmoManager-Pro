"""Explicit publication commands; originals are never inferred or replaced."""

from pydantic import BaseModel, ConfigDict, Field, StrictBool, field_validator


class VersionCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    idempotency_key: str = Field(min_length=1, max_length=100, pattern=r"^[A-Za-z0-9_.:-]+$")
    expected_document_etag: str = Field(min_length=1)
    expected_head_id: str | None = None
    comment: str = Field(min_length=1)
    confirmed: StrictBool

    @field_validator("comment")
    @classmethod
    def nonblank(cls, value):
        if not value.strip() or any(ord(char) < 32 and char not in "\n\t" for char in value):
            raise ValueError("Ein nachvollziehbarer Kommentar ist erforderlich.")
        return value.strip()


class OriginalCommand(VersionCommand):
    expected_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class RestoreCommand(VersionCommand):
    source_version_id: str = Field(min_length=1)
