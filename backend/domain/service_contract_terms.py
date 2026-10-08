"""Terms of property service contracts (Objektverträge): terms, renewals, notice deadlines.

Calendar rules (German civil code, the usual reading for contract terms):

* A term of N months that begins on day S ends on the day before the day of the
  last month that has S's number; if that month has no such day, on its last day
  (§§ 187 II, 188 II, III BGB). 01.01. + 12 months ends 31.12.; 31.01. + 1 month
  ends 28.02. (29.02. in leap years); 29.02.2028 + 12 months ends 28.02.2029.
* A notice period starts the day after the notice is received (§ 187 I) and ends
  on the day of the last week or month that has the receipt day's name or number,
  or the last day of a shorter month (§ 188 II, III). The latest receipt day for an
  end date is the last day whose period still ends on or before that date: 3 months
  to 31.12. means 30.09., to 30.06. means 31.03., to 28.02.2027 means 30.11.2026.
* § 193 BGB (weekends, holidays) does not move notice periods; the dates stand.

Renewal modes: ``none`` ends after the first term; ``fixed`` renews by
``renewal_months`` unless cancelled in time (each renewal starts the day after the
previous term); ``indefinite`` runs on after the first term (or from the start) and
ends on the next ``notice_to`` date (any day, month, quarter, year end) the notice
period reaches.
"""

from __future__ import annotations

import calendar
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, timedelta

RENEWAL_MODES = ("none", "fixed", "indefinite")
NOTICE_UNITS = ("day", "week", "month")
NOTICE_ANCHORS = ("term_end", "any_day", "month_end", "quarter_end", "year_end")
# a monthly renewal from 1900 to 2100 still stays below this
MAX_TERMS = 2500


def days_in_month(year: int, month: int) -> int:
    return calendar.monthrange(year, month)[1]


def add_months(day: date, months: int) -> date:
    """Same day number `months` later (or earlier); the month's last day if it is shorter."""
    index = day.year * 12 + day.month - 1 + months
    year, month = divmod(index, 12)
    month += 1
    return date(year, month, min(day.day, days_in_month(year, month)))


def term_end(start: date, months: int) -> date:
    """Last day of a term of `months` months beginning at the start of `start`."""
    if months <= 0:
        raise ValueError("Laufzeit muss mindestens einen Monat betragen")
    index = start.year * 12 + start.month - 1 + months
    year, month = divmod(index, 12)
    month += 1
    last = days_in_month(year, month)
    if start.day > last:
        return date(year, month, last)       # § 188 III: no corresponding day
    return date(year, month, start.day) - timedelta(days=1)


def notice_period_end(received: date, value: int, unit: str) -> date:
    """Last day of a notice period received on `received` (receipt day not counted)."""
    if value < 0:
        raise ValueError("Kündigungsfrist darf nicht negativ sein")
    if unit == "day":
        return received + timedelta(days=value)
    if unit == "week":
        return received + timedelta(weeks=value)
    if unit == "month":
        return add_months(received, value)
    raise ValueError(f"Unbekannte Fristeinheit: {unit}")


def latest_notice_date(end: date, value: int, unit: str) -> date:
    """Latest receipt day of a notice for the contract to end on `end`."""
    if unit in ("day", "week"):
        return end - timedelta(days=value * (7 if unit == "week" else 1))
    candidate = add_months(end, -value)
    # notice_period_end is monotonic in the receipt day: step to the last day that still fits
    while notice_period_end(candidate + timedelta(days=1), value, unit) <= end:
        candidate += timedelta(days=1)
    while notice_period_end(candidate, value, unit) > end:
        candidate -= timedelta(days=1)
    return candidate


def anchor_on_or_after(day: date, anchor: str) -> date:
    """First end date of the given kind on or after `day`."""
    if anchor in ("any_day", "term_end"):
        return day
    if anchor == "month_end":
        return date(day.year, day.month, days_in_month(day.year, day.month))
    if anchor == "quarter_end":
        month = (day.month - 1) // 3 * 3 + 3
        return date(day.year, month, days_in_month(day.year, month))
    if anchor == "year_end":
        return date(day.year, 12, 31)
    raise ValueError(f"Unbekannter Kündigungstermin: {anchor}")


@dataclass(frozen=True)
class Terms:
    start: date
    end_date: date | None = None              # agreed end of the first term
    minimum_term_months: int | None = None    # or the first term's length
    renewal_mode: str = "none"
    renewal_months: int | None = None
    notice_value: int | None = None
    notice_unit: str | None = None
    notice_to: str = "term_end"
    cancelled_on: date | None = None
    cancellation_effective: date | None = None

    @classmethod
    def of(cls, contract) -> "Terms":
        return cls(
            start=contract.start_date, end_date=contract.end_date,
            minimum_term_months=contract.minimum_term_months, renewal_mode=contract.renewal_mode,
            renewal_months=contract.renewal_months, notice_value=contract.notice_period_value,
            notice_unit=contract.notice_period_unit, notice_to=contract.notice_to,
            cancelled_on=contract.cancelled_on, cancellation_effective=contract.cancellation_effective,
        )

    @property
    def first_term_end(self) -> date | None:
        if self.end_date is not None:
            return self.end_date
        if self.minimum_term_months:
            return term_end(self.start, self.minimum_term_months)
        return None

    @property
    def has_notice_period(self) -> bool:
        return bool(self.notice_unit) and self.notice_value is not None

    def problems(self) -> list[str]:
        """Contradictions in the terms (German, for the API)."""
        found = []
        if self.end_date is not None and self.end_date < self.start:
            found.append("Das Laufzeitende liegt vor dem Vertragsbeginn")
        if self.end_date is not None and self.minimum_term_months:
            found.append("Bitte entweder ein Laufzeitende oder eine Mindestlaufzeit angeben, nicht beides")
        if (self.notice_value is None) != (not self.notice_unit):
            found.append("Kündigungsfrist braucht Zahl und Einheit")
        if self.renewal_mode not in RENEWAL_MODES:
            found.append(f"Unbekannte Verlängerungsart: {self.renewal_mode}")
        elif self.renewal_mode in ("none", "fixed") and self.first_term_end is None:
            found.append("Ohne unbefristete Fortsetzung braucht der Vertrag ein Laufzeitende oder eine Mindestlaufzeit")
        if self.renewal_mode == "fixed":
            if not self.renewal_months:
                found.append("Automatische Verlängerung braucht die Verlängerungsdauer in Monaten")
            if not self.has_notice_period:
                found.append("Automatische Verlängerung braucht eine Kündigungsfrist")
        if self.renewal_mode == "indefinite":
            if not self.has_notice_period:
                found.append("Ein unbefristeter Vertrag braucht eine Kündigungsfrist")
            if self.notice_to == "term_end":
                found.append("Bei unbefristeter Laufzeit bitte den Kündigungstermin wählen (Monats-, Quartals-, "
                             "Jahresende oder jederzeit)")
        if self.cancellation_effective is not None:
            if self.cancelled_on is None:
                found.append("Zum Kündigungstermin fehlt das Datum der Kündigung")
            elif self.cancellation_effective < self.start:
                found.append("Der Kündigungstermin liegt vor dem Vertragsbeginn")
        if self.cancelled_on is not None and self.cancellation_effective is None:
            found.append("Zur Kündigung fehlt der Termin, zu dem sie wirkt")
        return found

    # --- terms -------------------------------------------------------------------

    def terms(self) -> Iterator[tuple[date, date]]:
        """(start, end) of the first term and, for fixed renewals, every renewal after it."""
        first_end = self.first_term_end
        if first_end is None:
            return
        yield self.start, first_end
        if self.renewal_mode != "fixed" or not self.renewal_months:
            return
        begin = first_end + timedelta(days=1)
        for _ in range(MAX_TERMS):
            end = term_end(begin, self.renewal_months)
            yield begin, end
            begin = end + timedelta(days=1)

    def term_containing(self, day: date) -> tuple[date, date | None] | None:
        """The term `day` falls into; open end (None) in an indefinite phase."""
        if day < self.start:
            return None
        end = self.effective_end
        if end is not None and day > end:
            return None
        for begin, finish in self.terms():
            if finish >= day:
                return begin, min(finish, end) if end else finish
        if self.renewal_mode == "indefinite":
            first_end = self.first_term_end
            begin = first_end + timedelta(days=1) if first_end else self.start
            return begin, end
        return None

    @property
    def effective_end(self) -> date | None:
        """Day the contract ends as things stand: the cancellation, or the end without renewal."""
        if self.cancellation_effective is not None:
            return self.cancellation_effective
        if self.renewal_mode == "none":
            return self.first_term_end
        return None

    def status(self, day: date) -> str:
        if day < self.start:
            return "upcoming"
        end = self.effective_end
        if end is not None and end < day:
            return "ended"
        if self.cancellation_effective is not None:
            return "cancelled"
        return "active"

    # --- notice ------------------------------------------------------------------

    def next_notice_deadline(self, day: date) -> tuple[date, date] | None:
        """(latest receipt day, end it reaches) of the next term end a notice can still reach.

        None when nothing needs a notice: no renewal, already cancelled, or an
        indefinite phase (it ends whenever a notice is given, see earliest_end).
        """
        if self.cancellation_effective is not None or not self.has_notice_period:
            return None
        if self.renewal_mode not in ("fixed", "indefinite"):
            return None
        assert self.notice_value is not None and self.notice_unit is not None
        for _, finish in self.terms():
            if finish < day:
                continue
            deadline = latest_notice_date(finish, self.notice_value, self.notice_unit)
            if deadline >= day:
                return deadline, finish
            if self.renewal_mode != "fixed":
                return None
        return None

    def earliest_end(self, notice_on: date) -> date | None:
        """End date a notice received on `notice_on` reaches."""
        if self.renewal_mode == "none" or not self.has_notice_period:
            return self.first_term_end if self.renewal_mode == "none" else None
        assert self.notice_value is not None and self.notice_unit is not None
        reached = notice_period_end(notice_on, self.notice_value, self.notice_unit)
        if self.renewal_mode == "fixed":
            for _, finish in self.terms():
                if finish >= reached:
                    return finish
            return None
        first_end = self.first_term_end
        if first_end is not None:
            if reached <= first_end:
                return first_end
            reached = max(reached, first_end + timedelta(days=1))
        return anchor_on_or_after(max(reached, self.start), self.notice_to)

    def renewal_after(self, finish: date) -> tuple[date, date] | None:
        """The renewal that follows the term ending on `finish` (fixed renewals only)."""
        if self.renewal_mode != "fixed" or not self.renewal_months:
            return None
        begin = finish + timedelta(days=1)
        return begin, term_end(begin, self.renewal_months)
