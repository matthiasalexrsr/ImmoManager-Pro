"""Shared helpers for list endpoint sorting, filtering, and pagination."""

from __future__ import annotations

import logging
from datetime import date

logger = logging.getLogger(__name__)


def apply_sort(items: list, sort_by: str | None, sort_order: str = "asc") -> list:
    """Sort a list of Pydantic models by a field name.

    Returns the list unchanged if sort_by is None or the field doesn't exist.
    Handles non-string sort_by (e.g. FastAPI Query objects in direct test calls).
    """
    if not sort_by or not isinstance(sort_by, str) or not items:
        return items
    if not isinstance(sort_order, str):
        sort_order = "asc"
    # Validate the field exists on the model
    first = items[0]
    if not hasattr(first, sort_by):
        logger.debug("sort_by field %r not found on model %s", sort_by, type(first).__name__)
        return items
    reverse = sort_order.lower() == "desc"
    return sorted(
        items,
        key=lambda x: (getattr(x, sort_by, None) is None, getattr(x, sort_by, None) or ""),
        reverse=reverse,
    )


def apply_date_filter(
    items: list,
    field: str,
    date_from: date | None,
    date_to: date | None,
) -> list:
    """Filter items by a date field within [date_from, date_to].

    Uses isinstance guards to handle FastAPI Query objects passed directly in tests.
    Silently skips items where the field is missing or None.
    """
    if not items:
        return items

    has_from = isinstance(date_from, date)
    has_to = isinstance(date_to, date)

    if not has_from and not has_to:
        return items

    filtered = []
    for item in items:
        val = getattr(item, field, None)
        if val is None:
            continue
        # Convert string dates to date objects for comparison
        if isinstance(val, str):
            try:
                val = date.fromisoformat(val)
            except (ValueError, TypeError):
                continue
        if has_from and val < date_from:
            continue
        if has_to and val > date_to:
            continue
        filtered.append(item)
    return filtered


def safe_paginate(items: list, skip: int, limit: int) -> list:
    """Slice *items* with bounds-safe skip and limit.

    Never raises IndexError; returns empty list for out-of-range values.
    """
    safe_skip = max(0, int(skip) if isinstance(skip, (int, float)) else 0)
    safe_limit = max(1, min(1000, int(limit) if isinstance(limit, (int, float)) else 100))
    return items[safe_skip : safe_skip + safe_limit]
