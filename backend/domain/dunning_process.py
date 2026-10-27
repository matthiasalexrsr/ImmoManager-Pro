"""Dunning as a process: open items, payment application, default interest, stage timing.

Pure functions on exact cents (domain.money); no store, no clock.

Open items. A contract's claims are its rent months (from the rent history), stored
receivables that may be dunned, and the fees and interest earlier letters charged.
Every payment credited to the contract is applied, in the order of its booking date,
to the oldest open claim (§ 366 II BGB: the older debt first); among claims due on
the same day costs come before interest before the principal (§ 367 I BGB). A claim
is reduced on the day of the payment.

Default interest (§ 288 I BGB, consumer): base rate (§ 247 BGB) + 5 percentage
points a year (business premises, no consumer involved: 9 points, § 288 II BGB), on the outstanding principal of a claim, for every day after the day
interest was last charged up to and including the letter date, never on fees or
interest (§ 289 BGB). The base rate is taken from periods entered by hand; a day
without a known base rate earns no interest and is reported as missing, nothing is
assumed. Days are counted exactly and divided by 365 (also in leap years). Each
segment (constant principal and rate) is computed exactly; the sum per claim is
rounded half up to the cent once.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from .money import ZERO, cents, money

STAGES = (1, 2, 3, 4)
STAGE_LABELS = {1: "Zahlungserinnerung", 2: "1. Mahnung", 3: "2. Mahnung", 4: "Letzte Mahnung"}
PRINCIPAL_KINDS = frozenset({"rent", "receivable"})
CHARGE_KINDS = frozenset({"fee", "interest"})
_KIND_ORDER = {"fee": 0, "interest": 1, "rent": 2, "receivable": 2}
CONSUMER_SURCHARGE = Decimal("5")     # percentage points above the base rate, § 288 I 2 BGB
BUSINESS_SURCHARGE = Decimal("9")     # no consumer involved (business premises), § 288 II BGB
DAYS_PER_YEAR = Decimal("365")
HUNDRED = Decimal("100")


@dataclass(frozen=True)
class StageRule:
    stage: int
    label: str
    days_after: int              # stage 1: after the due date; later stages: after the previous letter
    fee: Decimal
    payment_deadline_days: int
    charge_interest: bool = True


# R12-18: a consumer owes only the actual cost of a letter (postage, material); flat fees above
# about 2.50 € are often refused in court. The fees stay adjustable in the settings.
REMINDER_FEE = Decimal("2.50")
DEFAULT_RULES: tuple[StageRule, ...] = (
    StageRule(1, "Zahlungserinnerung", 7, Decimal("0.00"), 14, False),
    StageRule(2, "1. Mahnung", 14, REMINDER_FEE, 14, True),
    StageRule(3, "2. Mahnung", 14, REMINDER_FEE, 10, True),
    StageRule(4, "Letzte Mahnung vor Abgabe", 14, REMINDER_FEE, 7, True),
)


def check_rules(rules: Sequence[StageRule]) -> list[StageRule]:
    ordered = sorted(rules, key=lambda rule: rule.stage)
    if [rule.stage for rule in ordered] != list(STAGES):
        raise ValueError("Es werden genau die Stufen 1 bis 4 erwartet.")
    for rule in ordered:
        if rule.days_after < 0 or rule.payment_deadline_days < 1 or money(rule.fee) < 0:
            raise ValueError(f"Stufe {rule.stage}: Tage, Frist oder Gebühr ungültig.")
    return ordered


@dataclass(frozen=True)
class Claim:
    key: str
    kind: str                    # rent | receivable | fee | interest
    due_date: date
    amount: Decimal
    description: str
    receivable_id: str | None = None

    @property
    def principal(self) -> bool:
        return self.kind in PRINCIPAL_KINDS


@dataclass(frozen=True)
class Payment:
    day: date
    amount: Decimal
    claim_key: str | None = None


@dataclass(frozen=True)
class OpenItem:
    claim: Claim
    paid: Decimal
    outstanding: Decimal
    reductions: tuple[tuple[date, Decimal], ...] = ()

    def outstanding_on(self, day: date) -> Decimal:
        """What is still owed at the end of `day` (a payment on that day counts)."""
        return self.claim.amount - sum((amount for when, amount in self.reductions if when <= day), ZERO)


def _claim_order(claim: Claim) -> tuple:
    return (claim.due_date, _KIND_ORDER.get(claim.kind, 3), claim.key)


def apply_payments(claims: Iterable[Claim], payments: Iterable[Payment]) -> tuple[list[OpenItem], Decimal]:
    """Apply dated payments to their named claim, otherwise oldest-first; return items and surplus."""
    ordered = sorted(claims, key=_claim_order)
    remaining = {claim.key: money(claim.amount) for claim in ordered}
    reductions: dict[str, list[tuple[date, Decimal]]] = {claim.key: [] for claim in ordered}
    unapplied = ZERO
    for payment in sorted(payments, key=lambda p: (p.day, p.claim_key is None, p.amount < 0)):
        left = money(payment.amount)
        if left < 0 and payment.claim_key in remaining:
            # A dated, claim-specific return restores the previously settled principal.
            claim = next(c for c in ordered if c.key == payment.claim_key)
            restored = min(-left, money(claim.amount) - remaining[claim.key])
            remaining[claim.key] += restored
            reductions[claim.key].append((payment.day, -restored))
            continue
        if left <= 0:
            continue
        for claim in ordered:
            if payment.claim_key is not None and payment.claim_key != claim.key:
                continue
            if left == 0:
                break
            open_amount = remaining[claim.key]
            if open_amount <= 0:
                continue
            taken = min(open_amount, left)
            remaining[claim.key] = open_amount - taken
            reductions[claim.key].append((payment.day, taken))
            left -= taken
        unapplied += left
    items = [OpenItem(claim, money(claim.amount) - remaining[claim.key], remaining[claim.key],
                      tuple(reductions[claim.key])) for claim in ordered]
    return items, unapplied


# ─── Default interest ─────────────────────────────────────────────────────────

@dataclass(frozen=True)
class RatePeriod:
    valid_from: date
    base_rate: Decimal


@dataclass(frozen=True)
class InterestSegment:
    start: date
    end: date                    # inclusive
    days: int
    principal: Decimal
    annual_percent: Decimal | None   # None: no base rate known for these days
    exact: Decimal


@dataclass(frozen=True)
class InterestResult:
    amount: Decimal              # rounded half up to the cent
    segments: tuple[InterestSegment, ...] = ()
    missing_from: date | None = None     # first day without a known base rate

    def as_dict(self) -> dict[str, Any]:
        return {"amount": str(self.amount), "missing_from": self.missing_from.isoformat() if self.missing_from else None,
                "segments": [{"start": s.start.isoformat(), "end": s.end.isoformat(), "days": s.days,
                              "principal": str(s.principal),
                              "annual_percent": None if s.annual_percent is None else str(s.annual_percent),
                              "exact": str(s.exact)} for s in self.segments]}


def _rate_on(rates: Sequence[RatePeriod], day: date) -> Decimal | None:
    found = None
    for period in rates:
        if period.valid_from <= day:
            found = period.base_rate
        else:
            break
    return found


def default_interest(item: OpenItem, *, charged_until: date, until: date, rates: Iterable[RatePeriod],
                     surcharge: Decimal = CONSUMER_SURCHARGE) -> InterestResult:
    """Interest on the item's principal for the days after `charged_until` up to and including `until`."""
    start = charged_until + timedelta(days=1)
    if not item.claim.principal or start > until:
        return InterestResult(ZERO)
    ordered = sorted(rates, key=lambda period: period.valid_from)
    boundaries = {start, until + timedelta(days=1)}
    boundaries |= {period.valid_from for period in ordered if start < period.valid_from <= until}
    boundaries |= {when for when, _ in item.reductions if start < when <= until}
    points = sorted(boundaries)
    segments: list[InterestSegment] = []
    total = ZERO
    missing: date | None = None
    for begin, after in zip(points, points[1:]):
        end = after - timedelta(days=1)
        principal = item.claim.amount - sum((amount for when, amount in item.reductions if when <= begin), ZERO)
        if principal <= 0:
            continue
        days = (after - begin).days
        base = _rate_on(ordered, begin)
        if base is None:
            missing = missing or begin
            segments.append(InterestSegment(begin, end, days, principal, None, ZERO))
            continue
        annual = base + surcharge
        exact = principal * annual / HUNDRED * Decimal(days) / DAYS_PER_YEAR if annual > 0 else ZERO
        total += exact
        segments.append(InterestSegment(begin, end, days, principal, annual, exact))
    return InterestResult(cents(total), tuple(segments), missing)


# ─── Stage timing ────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class StageDue:
    stage: int | None            # the next stage, None when the last stage is reached
    due_on: date | None          # from when it may be sent
    due: bool


def next_stage(current_stage: int, *, rules: Sequence[StageRule], as_of: date, oldest_overdue: date | None,
               last_letter_date: date | None, last_deadline: date | None) -> StageDue:
    by_stage = {rule.stage: rule for rule in rules}
    if current_stage >= STAGES[-1]:
        return StageDue(None, None, False)
    stage = current_stage + 1
    rule = by_stage[stage]
    if current_stage == 0:
        if oldest_overdue is None:
            return StageDue(stage, None, False)
        due_on = max(oldest_overdue + timedelta(days=rule.days_after), oldest_overdue + timedelta(days=1))
    else:
        assert last_letter_date is not None and last_deadline is not None
        due_on = max(last_letter_date + timedelta(days=rule.days_after), last_deadline + timedelta(days=1))
    return StageDue(stage, due_on, as_of >= due_on)


# ─── Letter figures ──────────────────────────────────────────────────────────

@dataclass
class LetterFigures:
    stage: int
    letter_date: date
    payment_deadline: date
    lines: list[dict[str, Any]] = field(default_factory=list)
    principal: Decimal = ZERO
    earlier_charges: Decimal = ZERO
    fee: Decimal = ZERO
    interest: Decimal = ZERO
    interest_missing_from: date | None = None

    @property
    def total(self) -> Decimal:
        return self.principal + self.earlier_charges + self.fee + self.interest


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str).encode()


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()
