"""Shared helpers for list endpoint sorting and filtering."""

from __future__ import annotations


def apply_sort(items: list, sort_by: str | None, sort_order: str = "asc") -> list:
    """Sort a list of Pydantic models by a field name.

    Returns the list unchanged if sort_by is None or the field doesn't exist.
    """
    if not sort_by or not isinstance(sort_by, str) or not items:
        return items
    if not isinstance(sort_order, str):
        sort_order = "asc"
    # Validate the field exists on the model
    first = items[0]
    if not hasattr(first, sort_by):
        return items
    reverse = sort_order.lower() == "desc"
    return sorted(
        items,
        key=lambda x: (getattr(x, sort_by, None) is None, getattr(x, sort_by, None) or ""),
        reverse=reverse,
    )
