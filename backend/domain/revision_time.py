"""Timestamps used as edit revisions must advance beyond the API's 1 ms tolerance."""

from datetime import datetime, timedelta, timezone


def next_updated_at(previous: datetime | None, current: datetime) -> datetime:
    current = current.replace(tzinfo=timezone.utc) if current.tzinfo is None else current.astimezone(timezone.utc)
    if previous is None:
        return current
    previous = (previous.replace(tzinfo=timezone.utc) if previous.tzinfo is None
                else previous.astimezone(timezone.utc))
    return max(current, previous + timedelta(milliseconds=2))
