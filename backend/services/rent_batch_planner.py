"""Pure target planning; caller owns frozen snapshots, writes and auth.
Source(snapshot_hash, id, inclusive) yields rows in Unicode-codepoint ID order.
"""
import hashlib
import json
import re
from calendar import monthrange
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import date

VERSION = 1
STATES = frozenset({"active", "terminated", "expired", "draft"})
LAST_MONTH = date.max.year * 12 - 1


class PlanError(ValueError):
    pass


def _id(value: str) -> str:
    if (not isinstance(value, str) or not value or value != value.strip()
            or any(ord(c) < 32 or 0xD800 <= ord(c) <= 0xDFFF for c in value)):
        raise PlanError("Invalid identifier")
    return value


def _hash(value: object) -> str:
    if not isinstance(value, str) or not re.fullmatch("[0-9a-f]{64}", value):
        raise PlanError("Invalid SHA256")
    return value


def _json(value: object) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=True,
                      separators=(",", ":"), allow_nan=False)


def month_index(value: str) -> int:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{4}-(0[1-9]|1[0-2])", value):
        raise PlanError("Expected YYYY-MM")
    year, month = int(value[:4]), int(value[5:])
    if not 1 <= year <= date.max.year:
        raise PlanError("Year outside calendar")
    return (year - 1) * 12 + month - 1


def month_text(index: int) -> str:
    if type(index) is not int or not 0 <= index <= LAST_MONTH:
        raise PlanError("Month outside calendar")
    return f"{index // 12 + 1:04d}-{index % 12 + 1:02d}"


def _month(day: date) -> int:
    return (day.year - 1) * 12 + day.month - 1


@dataclass(frozen=True, slots=True)
class Contract:
    id: str
    start_date: date
    end_date: date | None = None
    status: str = "active"
    property_id: str | None = None
    unit_id: str | None = None
    basis_revision: str = "calendar-only"

    def __post_init__(self) -> None:
        _id(self.id)
        _id(self.basis_revision)
        for value in (self.property_id, self.unit_id):
            if value is not None:
                _id(value)
        if type(self.start_date) is not date:
            raise PlanError("Expected start date (not datetime/string)")
        if self.end_date is not None:
            if type(self.end_date) is not date or self.end_date < self.start_date:
                raise PlanError("Invalid contract end")
        if not isinstance(self.status, str) or self.status not in STATES:
            raise PlanError("Unknown contract status")

    def canonical(self) -> str:
        return _json({
            "id": self.id, "start": self.start_date.isoformat(),
            "end": self.end_date.isoformat() if self.end_date else None,
            "status": self.status, "property_id": self.property_id,
            "unit_id": self.unit_id, "basis_revision": self.basis_revision,
        })

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256(self.canonical().encode("ascii")).hexdigest()


def contract_snapshot_hash(rows: Iterable[Contract]) -> str:
    """Stream once during snapshot preparation."""
    digest = hashlib.sha256(b"immo-rent-contracts-v1\n")
    previous = None
    for row in rows:
        if type(row) is not Contract or (previous is not None and row.id <= previous):
            raise PlanError("Unordered/duplicate Contract rows")
        digest.update(row.canonical().encode("ascii") + b"\n")
        previous = row.id
    return digest.hexdigest()


@dataclass(frozen=True, slots=True)
class Plan:
    start_month: str
    end_month: str
    cutoff_month: str
    snapshot_hash: str
    statuses: tuple[str, ...] = ("active",)
    property_id: str | None = None
    unit_id: str | None = None

    def __post_init__(self) -> None:
        if month_index(self.end_month) < month_index(self.start_month):
            raise PlanError("Inverted month range")
        month_index(self.cutoff_month)
        _hash(self.snapshot_hash)
        if (not isinstance(self.statuses, (tuple, list)) or not self.statuses
                or any(not isinstance(s, str) or s not in STATES for s in self.statuses)):
            raise PlanError("Invalid statuses")
        object.__setattr__(self, "statuses", tuple(sorted(set(self.statuses))))
        for value in (self.property_id, self.unit_id):
            if value is not None:
                _id(value)

    def canonical(self) -> str:
        return _json({
            "format": "rent-batch-plan", "version": VERSION,
            "canonicalization": "sorted-json-ascii-v1",
            "ordering": "unicode-codepoint-id-then-month-v1",
            "policy": "full-touched-month-inclusive-cutoff-v1",
            "start": self.start_month, "end": self.end_month,
            "cutoff": self.cutoff_month, "snapshot": self.snapshot_hash,
            "filters": {"statuses": self.statuses, "property_id": self.property_id,
                        "unit_id": self.unit_id},
        })

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256(self.canonical().encode("ascii")).hexdigest()


@dataclass(frozen=True, slots=True)
class Cursor:
    plan_hash: str
    contract_id: str | None = None
    month: str | None = None  # Next month; None = contract exhausted.
    contract_hash: str | None = None
    done: bool = False

    def __post_init__(self) -> None:
        _hash(self.plan_hash)
        if type(self.done) is not bool:
            raise PlanError("Invalid cursor flag")
        if self.contract_id is not None:
            _id(self.contract_id)
        if self.month is not None:
            month_index(self.month)
            if self.contract_id is None or self.done:
                raise PlanError("Invalid pending cursor")
            _hash(self.contract_hash)
        elif self.contract_hash is not None:
            raise PlanError("Unexpected row hash")

    def dump(self) -> str:
        return _json({
            "version": VERSION, "plan_hash": self.plan_hash,
            "contract_id": self.contract_id, "month": self.month,
            "contract_hash": self.contract_hash, "done": self.done,
        })


def load_cursor(plan: Plan, raw: str) -> Cursor:
    try:
        value = json.loads(raw)
        if type(value) is not dict or type(value.get("version")) is not int:
            raise PlanError("Invalid cursor format")
        if value.pop("version") != VERSION:
            raise PlanError("Unsupported cursor version")
        cursor = Cursor(**value)
        if cursor.dump() != raw or cursor.plan_hash != plan.fingerprint:
            raise PlanError("Noncanonical/unbound cursor")
        return cursor
    except (TypeError, ValueError) as exc:
        raise PlanError("Cannot load cursor") from exc


@dataclass(frozen=True, slots=True)
class Target:
    contract_id: str
    month: str
    partial_month: bool
    basis_revision: str

    @property
    def key(self) -> tuple[str, str]:
        return self.contract_id, self.month


@dataclass(frozen=True, slots=True)
class Batch:
    expected_cursor: Cursor
    next_cursor: Cursor
    targets: tuple[Target, ...]
    contracts_read: int
    examined: int
    existing: int


Source = Callable[[str, str | None, bool], Iterable[Contract]]


def plan_tick(
    plan: Plan, cursor: Cursor, open_contracts: Source,
    is_completed: Callable[[str, str], bool], *, batch_size: int,
) -> Batch:
    """Bounded rows AND probes; commit targets + cursor together."""
    if type(batch_size) is not int or batch_size < 1:
        raise PlanError("Invalid batch size")
    if cursor.plan_hash != plan.fingerprint:
        raise PlanError("Plan/cursor mismatch")
    ph = plan.fingerprint
    if cursor.done:
        return Batch(cursor, cursor, (), 0, 0, 0)
    first = month_index(plan.start_month)
    upper = min(month_index(plan.end_month), month_index(plan.cutoff_month))
    if upper < first:
        return Batch(cursor, Cursor(ph, done=True), (), 0, 0, 0)
    pending = cursor.month is not None
    rows = iter(open_contracts(plan.snapshot_hash, cursor.contract_id, pending))
    proposed, previous = cursor, cursor.contract_id
    targets = []
    scanned = examined = existing = 0
    try:
        while scanned < batch_size and examined < batch_size:
            try:
                row = next(rows)
            except StopIteration:
                if pending:
                    raise PlanError("Missing resume row") from None
                proposed = Cursor(ph, proposed.contract_id, done=True)
                break
            if type(row) is not Contract:
                raise PlanError("Expected typed Contract")
            if pending:
                if row.id != cursor.contract_id or row.fingerprint != cursor.contract_hash:
                    raise PlanError("Changed/missing resume row")
            elif previous is not None and row.id <= previous:
                raise PlanError("Unordered/duplicate keyset")
            scanned += 1
            previous = row.id
            low = max(first, _month(row.start_date))
            high = min(upper, _month(row.end_date) if row.end_date else upper)
            selected = (row.status in plan.statuses
                        and (plan.property_id is None or row.property_id == plan.property_id)
                        and (plan.unit_id is None or row.unit_id == plan.unit_id))
            if pending:
                assert cursor.month is not None  # Cursor invariant established above.
            n = month_index(cursor.month) if cursor.month is not None and pending else low
            if pending and (not selected or not low <= n <= high):
                raise PlanError("Resume outside plan")
            pending = False
            if not selected or low > high:
                proposed = Cursor(ph, row.id)
                continue
            row_hash = row.fingerprint
            while n <= high and examined < batch_size:
                month = month_text(n)
                exists = is_completed(row.id, month)
                if type(exists) is not bool:
                    raise PlanError("Probe must return bool")
                examined += 1
                if exists:
                    existing += 1
                else:
                    last_day = monthrange(n // 12 + 1, n % 12 + 1)[1]
                    partial = (
                        n == _month(row.start_date) and row.start_date.day != 1
                    ) or (
                        row.end_date is not None and n == _month(row.end_date)
                        and row.end_date.day != last_day
                    )
                    targets.append(Target(row.id, month, partial, row.basis_revision))
                proposed = (Cursor(ph, row.id, month_text(n + 1), row_hash)
                            if n < high else Cursor(ph, row.id))
                n += 1
    finally:
        close = getattr(rows, "close", None)
        if close is not None:
            close()
    return Batch(cursor, proposed, tuple(targets), scanned, examined, existing)
