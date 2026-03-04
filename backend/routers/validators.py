"""Shared validation helpers for router endpoints.

Provides reusable input validation functions that raise storage.ValidationError
on invalid data, ensuring consistent error responses across all endpoints.
"""

from __future__ import annotations

import re
from datetime import date

from ..storage import ValidationError

_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE
)


def validate_uuid(value: str, name: str = "id") -> str:
    """Validate that *value* looks like a UUID. Returns the value unchanged.

    Raises ``ValidationError`` with a descriptive message if the format is wrong.
    """
    if not value or not isinstance(value, str):
        raise ValidationError(f"{name} darf nicht leer sein")
    if not _UUID_RE.match(value):
        raise ValidationError(f"{name} hat ein ungültiges Format: {value!r}")
    return value


def validate_pagination(skip: int | None, limit: int | None) -> tuple[int, int]:
    """Return clamped (skip, limit) that are always safe for slicing.

    *skip* is clamped to >= 0; *limit* is clamped to [1, 1000].
    """
    safe_skip = max(0, int(skip or 0))
    safe_limit = max(1, min(1000, int(limit or 100)))
    return safe_skip, safe_limit


def validate_date_range(
    date_from: date | None, date_to: date | None
) -> tuple[date | None, date | None]:
    """Validate that *date_from* <= *date_to* when both are provided.

    Returns the pair unchanged, or raises ``ValidationError``.
    """
    if isinstance(date_from, date) and isinstance(date_to, date):
        if date_from > date_to:
            raise ValidationError(
                f"date_from ({date_from}) darf nicht nach date_to ({date_to}) liegen"
            )
    return date_from, date_to


def validate_sort_field(
    sort_by: str | None, allowed_fields: set[str]
) -> str | None:
    """Return *sort_by* only if it is in the *allowed_fields* set.

    Returns ``None`` (no sorting) for unknown or empty values — never raises.
    """
    if not sort_by or not isinstance(sort_by, str):
        return None
    return sort_by if sort_by in allowed_fields else None


def safe_int(
    value, default: int = 0, min_val: int | None = None, max_val: int | None = None
) -> int:
    """Coerce *value* to int, falling back to *default* on failure.

    Optionally clamps the result to [min_val, max_val].
    """
    try:
        result = int(value)
    except (TypeError, ValueError):
        result = default
    if min_val is not None:
        result = max(result, min_val)
    if max_val is not None:
        result = min(result, max_val)
    return result
