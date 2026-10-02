"""Private DTOs for the portal contract observed on 2026-10-02.

Sources are explicit snapshots, never public/logging representations. Provider
identities do not imply an internal property, tenant, unit or billing mapping.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

TEHA_PORTAL_CONTRACT_VERSION = "observed-2026-10-02-v1"


class TehaError(Exception):
    """Safe operational error: no request, response, credentials or provider text."""

    def __init__(self, code: str, *, retryable: bool = False,
                 retry_after_seconds: float | None = None, http_status: int | None = None):
        self.code = code
        self.retryable = retryable
        self.retry_after_seconds = retry_after_seconds
        self.http_status = http_status
        super().__init__(code)

    def __repr__(self) -> str:
        return f"TehaError({self.code!r}, retryable={self.retryable!r}, http_status={self.http_status!r})"


@dataclass(frozen=True, repr=False)
class _PrivateSource:
    _source: dict[str, Any] = field(repr=False, kw_only=True)

    def source_snapshot(self) -> dict[str, Any]:
        """Explicit private provenance access; callers must authorize persistence."""
        return deepcopy(self._source)

    def __repr__(self) -> str:
        return f"<{type(self).__name__} private provider data>"


@dataclass(frozen=True, repr=False)
class TehaAccount(_PrivateSource):
    account_id: int
    mandant_id: int


@dataclass(frozen=True, repr=False)
class TehaPropertyPeriod(_PrivateSource):
    object_id: int
    period_number: int
    lieg_nr: str
    period_from_raw: str
    period_to_raw: str

    @property
    def identity(self) -> tuple[int, int]:
        return self.object_id, self.period_number


@dataclass(frozen=True, repr=False)
class TehaDocument(_PrivateSource):
    reference: str
    filename: str
    lieg_nr: str

    def properties_snapshot(self) -> dict[str, Any]:
        return deepcopy(self._source["properties"])

    def attachments_snapshot(self) -> list[Any]:
        return deepcopy(self._source["attachments"])


@dataclass(frozen=True, repr=False)
class TehaDocumentContent:
    reference: str
    lieg_nr: str
    content: bytes = field(repr=False)
    sha256: str
    media_type: str = "application/pdf"

    @property
    def size_bytes(self) -> int:
        return len(self.content)

    def __repr__(self) -> str:
        return "<TehaDocumentContent private original bytes>"


@dataclass(frozen=True, repr=False)
class TehaTechnicalOrder(_PrivateSource):
    termin_id: int
    order_number: int
    period_number: int
    lieg_nr: str
    termin_from_raw: str
    termin_to_raw: str
    period_to_raw: str


@dataclass(frozen=True, repr=False)
class TehaOrderUser(_PrivateSource):
    user_id: int
    unit_id: int
    sequence_number: str
    # serviceterminId was null in the live sample; no numeric type is inferred.


def parse_naive_iso_datetime(value: str) -> datetime:
    """Optional explicit conversion; no local/server timezone is invented.

    The live dates are ISO datetimes without timezone. Raw strings remain in
    DTOs. A changed format or timezone requires an explicit adapter revision.
    """
    try:
        result = datetime.fromisoformat(value)
        if "T" not in value or result.tzinfo is not None:
            raise ValueError
        return result
    except (ValueError, TypeError):
        raise TehaError("provider_datetime_invalid") from None
