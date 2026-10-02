"""Pure date recurrence: anchored clamping, NOT full RFC 5545.
COUNT includes index 0; COUNT/UNTIL both bound the sequence.
Validity: [effective_from, effective_to). No I/O or implicit clock.
"""
import re
from calendar import monthrange
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, timedelta


class RecurrenceError(ValueError):
    """Invalid or unsupported recurrence input."""


class CatchUpLimit(RecurrenceError):
    """Too many missing dates; nothing has been returned or persisted."""


def _date(value: object, name: str) -> None:
    if type(value) is not date:
        raise RecurrenceError(f"{name}: expected date, not datetime/string")


def _positive(value: object, name: str) -> None:
    if type(value) is not int or value < 1:
        raise RecurrenceError(f"{name}: expected positive integer")


def occurrence_key(plan_id: str, day: date) -> tuple[str, date]:
    if not isinstance(plan_id, str) or not plan_id or plan_id.strip() != plan_id:
        raise RecurrenceError("plan_id: expected nonblank, trimmed string")
    if any(ord(char) < 32 for char in plan_id):
        raise RecurrenceError("plan_id: control characters are forbidden")
    _date(day, "occurrence_date")
    return plan_id, day


@dataclass(frozen=True, slots=True)
class Plan:
    plan_id: str
    anchor: date
    frequency: str
    interval: int = 1
    count: int | None = None
    until: date | None = None
    effective_from: date | None = None
    effective_to: date | None = None

    def __post_init__(self) -> None:
        occurrence_key(self.plan_id, self.anchor)
        if self.frequency not in ("DAILY", "WEEKLY", "MONTHLY", "YEARLY"):
            raise RecurrenceError("Unsupported FREQ")
        _positive(self.interval, "INTERVAL")
        if self.count is not None:
            _positive(self.count, "COUNT")
        for name in ("until", "effective_from", "effective_to"):
            value = getattr(self, name)
            if value is not None:
                _date(value, name)
        if self.until is not None and self.until < self.anchor:
            raise RecurrenceError("UNTIL precedes anchor")
        start = max(self.anchor, self.effective_from or self.anchor)
        if self.effective_to is not None and self.effective_to <= start:
            raise RecurrenceError("Empty/inverted effective interval")


@dataclass(frozen=True, slots=True)
class Occurrence:
    plan_id: str
    occurrence_date: date
    index: int

    @property
    def key(self) -> tuple[str, date]:
        return occurrence_key(self.plan_id, self.occurrence_date)


def parse_plan(
    plan_id: str, anchor: date, text: str, *,
    legacy_child_count: bool = False,
    effective_from: date | None = None,
    effective_to: date | None = None,
) -> Plan:
    """Strict application-rule parser. Existing task COUNT means children:
    opt into legacy_child_count to preserve COUNT=n children / COUNT=0 unlimited.
    """
    if type(legacy_child_count) is not bool:
        raise RecurrenceError("legacy_child_count: expected bool")
    if not isinstance(text, str) or not text.strip() or len(text) > 1024:
        raise RecurrenceError("Expected nonempty recurrence rule (max 1024 chars)")
    text = text.strip()
    if text.upper().startswith("RRULE:"):
        text = text[6:]
    parts: dict[str, str] = {}
    for segment in text.split(";"):
        key, sep, value = segment.partition("=")
        key, value = key.strip().upper(), value.strip()
        if not sep or not value or key in parts:
            raise RecurrenceError("Malformed or duplicate rule part")
        if key not in {"FREQ", "INTERVAL", "COUNT", "UNTIL"}:
            raise RecurrenceError(f"Unsupported rule part: {key}")
        parts[key] = value
    if "FREQ" not in parts:
        raise RecurrenceError("FREQ is required")

    def number(key: str, default: str) -> int:
        value = parts.get(key, default)
        if not re.fullmatch(r"[0-9]+", value):
            raise RecurrenceError(f"{key}: expected decimal integer")
        return int(value)

    count = number("COUNT", "0") if "COUNT" in parts else None
    if legacy_child_count and count is not None:
        count = count + 1 if count > 0 else None
    until = None
    if "UNTIL" in parts:
        value = parts["UNTIL"]
        if not re.fullmatch(r"(?:[0-9]{8}|[0-9]{4}-[0-9]{2}-[0-9]{2})", value):
            raise RecurrenceError("UNTIL: expected YYYYMMDD or YYYY-MM-DD")
        try:
            until = date.fromisoformat(value)
        except ValueError as exc:
            raise RecurrenceError("Invalid UNTIL date") from exc
    return Plan(
        plan_id, anchor, parts["FREQ"].upper(), number("INTERVAL", "1"),
        count, until, effective_from, effective_to,
    )


def occurrence_at(plan: Plan, index: int) -> date | None:
    """Base sequence index, independent of the effective/catch-up window."""
    if type(index) is not int or index < 0:
        raise RecurrenceError("index: expected nonnegative integer")
    if plan.count is not None and index >= plan.count:
        return None
    anchor, step = plan.anchor, index * plan.interval
    if plan.frequency in ("DAILY", "WEEKLY"):
        days = step * (7 if plan.frequency == "WEEKLY" else 1)
        if days > (date.max - anchor).days:
            return None
        result = anchor + timedelta(days=days)
    else:
        months = step * (12 if plan.frequency == "YEARLY" else 1)
        absolute = (anchor.year - 1) * 12 + anchor.month - 1 + months
        year, month = absolute // 12 + 1, absolute % 12 + 1
        if year > date.max.year:
            return None
        result = date(year, month, min(anchor.day, monthrange(year, month)[1]))
    return None if plan.until is not None and result > plan.until else result


def _seek(plan: Plan, lower: date) -> int:
    """Jump near lower without replaying every date since a historic anchor."""
    anchor = plan.anchor
    if plan.frequency in ("DAILY", "WEEKLY"):
        step = plan.interval * (7 if plan.frequency == "WEEKLY" else 1)
        return max(0, (lower - anchor).days // step)
    months = (lower.year - anchor.year) * 12 + lower.month - anchor.month
    step = plan.interval * (12 if plan.frequency == "YEARLY" else 1)
    return max(0, months // step)


def catch_up(
    plan: Plan, as_of: date, *,
    recorded: Iterable[tuple[str, date]] = (),
    since: date | None = None,
    limit: int = 10_000,
) -> tuple[Occurrence, ...]:
    """Missing dates through as_of, inclusive. Recorded keys use immutable
    dates, including cancelled/moved/deleted instances. Overflow never truncates.
    """
    _date(as_of, "as_of")
    _positive(limit, "limit")
    if since is not None:
        _date(since, "since")
        if since > as_of:
            raise RecurrenceError("since is after as_of")
    seen: set[tuple[str, date]] = set()
    for key in recorded:
        if not isinstance(key, tuple) or len(key) != 2:
            raise RecurrenceError("recorded: expected (plan_id, date) tuples")
        seen.add(occurrence_key(*key))
    lower = max(plan.anchor, plan.effective_from or plan.anchor, since or plan.anchor)
    upper = min(as_of, plan.until or date.max)
    if plan.effective_to is not None:
        upper = min(upper, plan.effective_to - timedelta(days=1))
    if lower > upper:
        return ()
    result: list[Occurrence] = []
    index = _seek(plan, lower)
    while True:
        day = occurrence_at(plan, index)
        if day is None or day > upper:
            break
        key = occurrence_key(plan.plan_id, day)
        if day >= lower and key not in seen:
            if len(result) == limit:
                raise CatchUpLimit("Split catch-up into smaller explicit date windows")
            result.append(Occurrence(plan.plan_id, day, index))
            seen.add(key)
        index += 1
    return tuple(result)


def task_candidates(
    plan: Plan, as_of: date, *,
    children: Iterable[tuple[date, str]] = (),
    full_catch_up: bool = False,
) -> tuple[Occurrence, ...]:
    """Preserve one-open-child policy unless full_catch_up is explicit.
    children: (immutable occurrence_date, status); index 0 is the template.
    """
    if type(full_catch_up) is not bool:
        raise RecurrenceError("full_catch_up: expected bool")
    _date(as_of, "as_of")
    keys = [occurrence_key(plan.plan_id, plan.anchor)]
    blocked = False
    for day, status in children:
        keys.append(occurrence_key(plan.plan_id, day))
        if not isinstance(status, str) or not status.strip():
            raise RecurrenceError("Expected task status")
        blocked = blocked or status in {"open", "in_progress"}
    if blocked and not full_catch_up:
        return ()
    missing = catch_up(plan, as_of, recorded=keys)
    return missing if full_catch_up else missing[:1]
