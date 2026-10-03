"""Versioned, secret-free installation plans and calendar-period scheduling."""

from datetime import datetime, time
from pathlib import Path
from typing import Literal
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class BackupOperationError(RuntimeError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


class Installation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    backend: Literal["sqlite", "private_server"]
    app_root: Path
    python: Path
    packaged: bool = False
    data_dir: Path | None = None
    project: str | None = None
    compose_file: Path | None = None
    env_file: Path | None = None

    @field_validator("app_root", "python", "data_dir", "compose_file", "env_file")
    @classmethod
    def absolute(cls, value):
        if value is not None and not value.is_absolute():
            raise ValueError("Use an explicit absolute installation path")
        return value

    @model_validator(mode="after")
    def selected_backend(self):
        if self.backend == "sqlite":
            if self.data_dir is None or any(value is not None for value in (self.project, self.compose_file, self.env_file)):
                raise ValueError("Select one SQLite data directory")
        elif self.packaged or self.data_dir is not None or not all((self.project, self.compose_file, self.env_file)):
            raise ValueError("Select one private Compose project/profile/environment")
        return self


class BackupPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: Literal[1] = 1
    id: UUID = Field(default_factory=uuid4)
    revision: int = Field(default=1, ge=1, strict=True)
    installation: Installation
    destination: Path
    second_destination: Path | None = None
    key_id: str = Field(default="initial", pattern=r"^[a-zA-Z0-9_-]+$")
    key_files: dict[str, Path]
    timezone: str = "Europe/Berlin"
    daily_at: time = time(2, 15)
    monthly_at: time = time(3, 30)
    retention_days: int = Field(default=90, ge=1, strict=True)
    retry_seconds: int = Field(default=900, ge=1, strict=True)
    runtime_timeout_seconds: float = Field(default=120, gt=0, allow_inf_nan=False)
    capacity_file: Path | None = None
    enabled: bool = True

    @field_validator("destination", "second_destination", "capacity_file")
    @classmethod
    def absolute(cls, value):
        return Installation.absolute(value)

    @field_validator("timezone")
    @classmethod
    def known_zone(cls, value):
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError("Unknown IANA timezone") from None
        return value

    @field_validator("daily_at", "monthly_at")
    @classmethod
    def local_time(cls, value):
        if value.tzinfo is not None or value.microsecond:
            raise ValueError("Use a local wall-clock time without offset or fractions")
        return value

    @model_validator(mode="after")
    def references(self):
        if self.key_id not in self.key_files:
            raise ValueError("Current backup key reference is missing")
        for key, path in self.key_files.items():
            if not key or not path.is_absolute():
                raise ValueError("Use an absolute private key file reference")
        if self.second_destination is not None and self.second_destination == self.destination:
            raise ValueError("Second destination must differ from primary destination")
        return self


def due_period(plan: BackupPlan, kind: Literal["backup", "probe"], now: datetime, last_success: str | None) -> str | None:
    """One current complete image, not fictional snapshots for missed dates.

    Comparing the current valid local wall clock means a spring gap runs at the
    next real time, and the persisted period suppresses a second autumn fold.
    """
    if now.tzinfo is None:
        raise ValueError("An aware clock is required")
    if not plan.enabled:
        return None
    local = now.astimezone(ZoneInfo(plan.timezone))
    period = local.strftime("%Y-%m-%d" if kind == "backup" else "%Y-%m")
    target = plan.daily_at if kind == "backup" else plan.monthly_at
    ready = local.time() >= target if kind == "backup" or local.day == 1 else True
    return period if ready and (last_success is None or period > last_success) else None
