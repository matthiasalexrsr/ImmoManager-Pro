"""Rental deposit (Mietkaution, § 551 BGB): cap, instalments, receipts, interest, settlement arithmetic.

Pure functions on exact amounts; no storage. Rules (docs/DEPOSITS_20261011.md):

* Cap: at most three monthly rents without operating-cost advances (net cold rent,
  § 551 I BGB). A higher amount needs an explicit reason; the cap is a warning, not
  a refusal, because a higher agreed amount is void only in its excess.
* Instalments: up to three. The first is due at the start of the tenancy, the
  others together with the two rent payments that follow it (§ 551 II BGB; rent is
  due by the third working day of the month, as LeaseEngine counts it).
* Receipts are amounts of allocated bookings; they settle the instalments in due
  order (oldest first), each amount once.
* Interest (§ 551 III BGB) of a cash deposit: rate periods (annual percent, valid
  from a day until the next period starts; none before the first). Exact rational
  arithmetic, interest days from the receipt day (inclusive) to the end day
  (exclusive), actual days of the calendar year (365 or 366). Interest is rounded
  half up to the cent once per calendar year (on 31 December) and at the end day,
  and from then on bears interest itself (yearly capitalisation). No statutory rate
  is assumed; without a rate period the interest is zero.
* Settlement: credit = received principal + interest. Claims are new claims
  (defects, other claims) and offsets of claims already open in the ledger (open
  receivables, rent arrears). A retention keeps a part back for an open utility
  statement period. Result = credit − claims − retention: positive is the payout,
  negative the remaining claim. Offsets of existing claims and a retention need
  cover by the credit; only new claims can be left over as a remaining claim, so
  nothing is claimed twice.
"""

from __future__ import annotations

from calendar import isleap
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from fractions import Fraction

from .calendar_days import rent_due_date
from .money import CENT, ZERO, money

MONEY_FORMS = ("cash", "transfer", "deposit_account")
SECURITY_FORMS = ("guarantee", "pledged_savings")
FORMS = MONEY_FORMS + SECURITY_FORMS
MAX_INSTALMENTS = 3
CAP_MONTHS = 3
MAX_RATE = Decimal("25")
RATE_PLACES = 4

NEW_CLAIMS = ("defect", "other")
OFFSETS = ("receivable", "rent_arrears")
ITEM_KINDS = NEW_CLAIMS + OFFSETS + ("retention",)


class DepositRuleError(ValueError):
    """An input the deposit rules refuse; the message is for the user."""


# ─── Agreement ───────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class CapCheck:
    cold_rent: Decimal | None
    cap: Decimal | None
    exceeds: bool
    excess: Decimal


def check_cap(amount: Decimal, cold_rent: Decimal | None) -> CapCheck:
    """Three net cold rents; unknown when the cold rent is unknown or zero."""
    amount = money(amount)
    if cold_rent is None or money(cold_rent) <= 0:
        return CapCheck(None, None, False, ZERO)
    cap = money(cold_rent) * CAP_MONTHS
    return CapCheck(money(cold_rent), cap, amount > cap, max(amount - cap, ZERO))


def _month_after(day: date, months: int) -> date:
    month = day.month - 1 + months
    return date(day.year + month // 12, month % 12 + 1, 1)


def instalment_due_dates(start: date, count: int, federal_state: str | None = None) -> list[date]:
    """The first at the start of the tenancy, each further one with the rent of the following month.

    Rent is due by the third working day of a month (without the holidays of the property's
    ``federal_state``); the rent of the start month counts as paid together with the first
    instalment (§ 551 II BGB: "zusammen mit den unmittelbar folgenden Mietzahlungen").
    """
    if not 1 <= count <= MAX_INSTALMENTS:
        raise DepositRuleError(f"Eine Kaution wird in höchstens {MAX_INSTALMENTS} Raten gezahlt.")
    return [start] + [rent_due_date(_month_after(start, months), federal_state) for months in range(1, count)]


def split_amount(total: Decimal, count: int) -> list[Decimal]:
    """Equal instalments in cents; the cents that do not divide go to the first."""
    total = money(total)
    if total <= 0:
        raise DepositRuleError("Der Kautionsbetrag muss größer als 0 sein.")
    if not 1 <= count <= MAX_INSTALMENTS:
        raise DepositRuleError(f"Eine Kaution wird in höchstens {MAX_INSTALMENTS} Raten gezahlt.")
    cents = int(total / CENT)
    base, rest = divmod(cents, count)
    return [(Decimal(base + (rest if index == 0 else 0)) * CENT).quantize(CENT) for index in range(count)]


@dataclass(frozen=True)
class Instalment:
    number: int
    due_date: date
    amount: Decimal


def schedule(total: Decimal, start: date, amounts: Sequence[Decimal] | None = None,
             count: int | None = None, federal_state: str | None = None) -> list[Instalment]:
    """The instalments of an agreement: given amounts (in order) or an equal split."""
    if amounts is None:
        values = split_amount(total, count or 1)
    else:
        values = [money(value) for value in amounts]
        if not 1 <= len(values) <= MAX_INSTALMENTS:
            raise DepositRuleError(f"Eine Kaution wird in höchstens {MAX_INSTALMENTS} Raten gezahlt.")
        if any(value <= 0 for value in values):
            raise DepositRuleError("Jede Rate muss größer als 0 sein.")
        if sum(values, ZERO) != money(total):
            raise DepositRuleError("Die Raten ergeben zusammen nicht den Kautionsbetrag.")
    return [Instalment(number, due, value)
            for number, (due, value) in enumerate(zip(instalment_due_dates(start, len(values), federal_state), values), 1)]


# ─── Receipts ────────────────────────────────────────────────────────────────

@dataclass
class InstalmentState:
    number: int
    due_date: date
    amount: Decimal
    paid: Decimal = ZERO

    @property
    def open(self) -> Decimal:
        return max(self.amount - self.paid, ZERO)

    def status(self, today: date) -> str:
        if self.paid >= self.amount:
            return "paid"
        if self.paid > 0:
            return "partial" if today <= self.due_date else "partial_overdue"
        return "open" if today <= self.due_date else "overdue"


def apply_receipts(instalments: Sequence[Instalment], receipts: Iterable[tuple[date, Decimal]]
                   ) -> tuple[list[InstalmentState], Decimal]:
    """Receipts (day, amount; corrections negative) settle the instalments oldest first.

    Returns the instalment states and what was received beyond the agreed amount.
    Every receipt counts once: the net received amount is distributed, never more.
    """
    states = [InstalmentState(i.number, i.due_date, money(i.amount)) for i in instalments]
    net = sum((money(amount) for _, amount in receipts), ZERO)
    remaining = max(net, ZERO)
    for state in sorted(states, key=lambda s: (s.due_date, s.number)):
        state.paid = min(state.amount, remaining)
        remaining -= state.paid
    return states, remaining


# ─── Interest ────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class RatePeriod:
    valid_from: date
    percent: Decimal


def parse_rate(value: object) -> Decimal:
    """An annual rate in percent, exact, at most four decimal places, 0 to 25."""
    try:
        rate = Decimal(str(value).strip().replace(",", "."))
    except Exception:
        raise DepositRuleError("Ungültiger Zinssatz.") from None
    if not rate.is_finite():
        raise DepositRuleError("Ungültiger Zinssatz.")
    exponent = rate.as_tuple().exponent
    if isinstance(exponent, int) and -exponent > RATE_PLACES:
        raise DepositRuleError(f"Zinssätze haben höchstens {RATE_PLACES} Nachkommastellen.")
    if rate < 0 or rate > MAX_RATE:
        raise DepositRuleError(f"Der Zinssatz liegt zwischen 0 und {MAX_RATE} %.")
    return rate.normalize() if rate != 0 else Decimal("0")


@dataclass
class InterestYear:
    year: int
    start: date
    end: date            # exclusive
    principal_start: Decimal
    interest: Decimal


@dataclass
class InterestResult:
    total: Decimal
    years: list[InterestYear] = field(default_factory=list)
    balance: Decimal = ZERO     # principal + capitalised interest at the end day


def _round(value: Fraction) -> Decimal:
    return (Decimal(value.numerator) / Decimal(value.denominator)).quantize(CENT, rounding=ROUND_HALF_UP) \
        if value else ZERO


def _rate_on(rates: Sequence[RatePeriod], day: date) -> Decimal:
    current = ZERO
    for period in rates:
        if period.valid_from <= day:
            current = period.percent
        else:
            break
    return current


def interest(events: Iterable[tuple[date, Decimal]], rates: Iterable[RatePeriod], until: date) -> InterestResult:
    """Interest of a balance that changes on the event days, up to (excluding) `until`.

    The exact interest of every interval with constant balance and rate is a
    fraction balance × percent / 100 × days / days of the year; the sum of a
    calendar year is rounded half up to the cent and capitalised on 31 December.
    """
    changes = sorted(((day, money(amount)) for day, amount in events), key=lambda item: item[0])
    periods = sorted(rates, key=lambda r: r.valid_from)
    if len({p.valid_from for p in periods}) != len(periods):
        raise DepositRuleError("Je Tag gibt es nur einen Zinssatz.")
    result = InterestResult(ZERO)
    if not changes or changes[0][0] >= until:
        result.balance = sum((amount for day, amount in changes if day < until), ZERO)
        return result
    boundaries = {until}
    boundaries.update(day for day, _ in changes if day < until)
    boundaries.update(p.valid_from for p in periods if changes[0][0] < p.valid_from < until)
    first = changes[0][0]
    boundaries.update(date(year, 1, 1) for year in range(first.year + 1, until.year + 1))
    points = sorted(day for day in boundaries if day >= first)

    balance = ZERO
    pending = list(changes)
    accrued = Fraction(0)
    year_start, year_principal = first, None
    for index, start in enumerate(points[:-1]):
        end = points[index + 1]
        while pending and pending[0][0] <= start:
            balance += pending.pop(0)[1]
        if year_principal is None:
            year_principal = balance
        rate = _rate_on(periods, start)
        days = (end - start).days
        if rate and balance > 0 and days:
            year_days = 366 if isleap(start.year) else 365
            accrued += Fraction(balance) * Fraction(rate) * days / (100 * year_days)
        if end.month == 1 and end.day == 1 or end == until:
            booked = _round(accrued)
            result.years.append(InterestYear(start.year, year_start, end, year_principal, booked))
            result.total += booked
            balance += booked
            accrued = Fraction(0)
            year_start, year_principal = end, None
    result.balance = balance + sum((amount for day, amount in pending if day < until), ZERO)
    return result


# ─── Settlement ──────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Item:
    kind: str
    amount: Decimal


@dataclass(frozen=True)
class Outcome:
    principal: Decimal
    interest: Decimal
    credit: Decimal
    new_claims: Decimal
    offsets: Decimal
    retention: Decimal
    claims: Decimal
    result: Decimal          # > 0 payout, < 0 remaining claim
    payout: Decimal
    remaining_claim: Decimal
    covered: Decimal         # claims and retention the deposit covers


def settle(principal: Decimal, interest_amount: Decimal, items: Iterable[Item], *, allow_retention: bool = True
           ) -> Outcome:
    principal, interest_amount = money(principal), money(interest_amount)
    if principal < 0 or interest_amount < 0:
        raise DepositRuleError("Kaution und Zinsen können nicht negativ sein.")
    values = list(items)
    for item in values:
        if item.kind not in ITEM_KINDS:
            raise DepositRuleError("Unbekannte Art einer Abrechnungsposition.")
        if money(item.amount) <= 0:
            raise DepositRuleError("Jede Abrechnungsposition braucht einen Betrag größer als 0.")
    retentions = [money(item.amount) for item in values if item.kind == "retention"]
    if len(retentions) > 1:
        raise DepositRuleError("Je Abrechnung gibt es höchstens einen Einbehalt.")
    if retentions and not allow_retention:
        raise DepositRuleError("Die Freigabe eines Einbehalts behält nichts weiter ein.")
    credit = principal + interest_amount
    new_claims = sum((money(i.amount) for i in values if i.kind in NEW_CLAIMS), ZERO)
    offsets = sum((money(i.amount) for i in values if i.kind in OFFSETS), ZERO)
    retention = retentions[0] if retentions else ZERO
    if offsets > credit:
        raise DepositRuleError("Verrechnungen mit offenen Forderungen dürfen das Kautionsguthaben nicht übersteigen; "
                               "der Rest bleibt die bestehende Forderung.")
    claims = new_claims + offsets
    if retention and retention > credit - claims:
        raise DepositRuleError("Der Einbehalt ist höher als das, was nach den Ansprüchen von der Kaution übrig bleibt.")
    result = credit - claims - retention
    return Outcome(principal, interest_amount, credit, new_claims, offsets, retention, claims, result,
                   max(result, ZERO), max(-result, ZERO), min(credit, claims + retention))
