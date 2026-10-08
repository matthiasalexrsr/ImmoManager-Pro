"""Wall-clock schedules in the installation's time zone (Europe/Berlin), DST-correct.

An occurrence is identified by its local calendar date, never by its UTC instant:
a daily slot exists exactly once per local day, also when the wall time falls into
the spring gap (it runs after the gap) or the autumn overlap (the first instance).
"""

from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

BERLIN = ZoneInfo("Europe/Berlin")


def utcnow() -> datetime:
    """Naive UTC, as stored in the DateTime columns."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def as_aware_utc(moment: datetime) -> datetime:
    return moment.replace(tzinfo=timezone.utc) if moment.tzinfo is None else moment.astimezone(timezone.utc)


def local_today(now: datetime | None = None, tz: ZoneInfo = BERLIN) -> date:
    """The installation's calendar date (not the server's, not UTC's)."""
    return as_aware_utc(now or utcnow()).astimezone(tz).date()


@dataclass(frozen=True)
class DailyAt:
    hour: int
    minute: int = 0
    tz: ZoneInfo = field(default=BERLIN)

    @property
    def version(self) -> str:
        return f"daily@{self.hour:02d}:{self.minute:02d} {self.tz.key}"

    def instant(self, day: date) -> datetime:
        """UTC instant of the slot on a local date.

        fold=0: in the spring gap the pre-transition offset applies, i.e. 02:30 becomes
        03:30 local; in the autumn overlap the first (summer time) instance is used.
        """
        local = datetime.combine(day, time(self.hour, self.minute), tzinfo=self.tz)
        return local.astimezone(timezone.utc)

    def latest_due(self, now: datetime | None = None) -> date:
        """Local date of the most recent slot at or before now."""
        moment = as_aware_utc(now or utcnow())
        today = moment.astimezone(self.tz).date()
        return today if self.instant(today) <= moment else today - timedelta(days=1)

    def occurrences(self, after: datetime, until: datetime) -> Iterator[tuple[date, datetime]]:
        """Slots with after < instant <= until, one per local date."""
        start, end = as_aware_utc(after), as_aware_utc(until)
        day = start.astimezone(self.tz).date() - timedelta(days=1)
        while True:
            moment = self.instant(day)
            if moment > end:
                return
            if moment > start:
                yield day, moment
            day += timedelta(days=1)


def parse_hh_mm(value: str) -> tuple[int, int]:
    hour, _, minute = value.strip().partition(":")
    parsed = int(hour), int(minute or 0)
    if not (0 <= parsed[0] <= 23 and 0 <= parsed[1] <= 59):
        raise ValueError(f"invalid time of day: {value!r}")
    return parsed


@dataclass(frozen=True)
class MonthlyAt:
    """One slot per local month on `day` (clamped to the month's last day), DST-correct like DailyAt."""
    day: int
    hour: int
    minute: int = 0
    tz: ZoneInfo = field(default=BERLIN)

    @property
    def version(self) -> str:
        return f"monthly@{self.day:02d} {self.hour:02d}:{self.minute:02d} {self.tz.key}"

    def slot(self, year: int, month: int) -> date:
        following = date(year + month // 12, month % 12 + 1, 1)
        return date(year, month, min(self.day, (following - timedelta(days=1)).day))

    def instant(self, day: date) -> datetime:
        return DailyAt(self.hour, self.minute, self.tz).instant(day)

    def latest_due(self, now: datetime | None = None) -> date:
        moment = as_aware_utc(now or utcnow())
        local = moment.astimezone(self.tz).date()
        slot = self.slot(local.year, local.month)
        if self.instant(slot) <= moment:
            return slot
        previous = local.replace(day=1) - timedelta(days=1)
        return self.slot(previous.year, previous.month)
