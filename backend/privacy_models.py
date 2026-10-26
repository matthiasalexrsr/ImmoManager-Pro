from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

ResourceKind = Literal["document", "e_invoice_intake", "import_batch", "portability_export", "portal_case", "portal_identity"]


class Command(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    idempotency_key: str = Field(min_length=16, max_length=100)


class ControlChange(Command):
    action: Literal["hold", "release_hold", "restrict", "release_restriction", "erase"]
    expected_revision: int = Field(ge=0)
    source_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    reason: str = Field(min_length=10, max_length=2000)


class OpenRequest(Command):
    subject_kind: Literal["tenant", "contact"]
    subject_id: str = Field(min_length=1, max_length=100)
    request_type: Literal["access", "erasure"]
    verification: str = Field(min_length=10, max_length=2000)
    due_on: date


class DecideRequest(Command):
    expected_revision: int = Field(ge=1)
    source_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    outcome: Literal["fulfilled", "partially_fulfilled", "deferred", "declined"]
    reason: str = Field(min_length=10, max_length=4000)


class CompleteRestoreReview(Command):
    expected_revision: int = Field(ge=1)
    journal_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    reason: str = Field(min_length=20, max_length=4000)
    decisions_reconciled: Literal[True]


class JournalControl(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(pattern=r"^[a-f0-9]{64}$")
    kind: ResourceKind
    record_id: str = Field(min_length=1, max_length=100)
    held: bool = Field(strict=True)
    restricted: bool = Field(strict=True)
    erased_at: datetime | None
    erasure_due: bool = Field(strict=True)
    revision: int = Field(ge=1)
    reason: str = Field(min_length=10, max_length=2000)
    actor_id: str = Field(min_length=1, max_length=50)
    source_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    file_keys_sha256: list[Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]] | None = Field(default=None, max_length=1000)
    created_at: datetime
    updated_at: datetime


class ImportJournal(Command):
    controls: list[JournalControl] = Field(max_length=100_000)
    source_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    reason: str = Field(min_length=20, max_length=2000)
