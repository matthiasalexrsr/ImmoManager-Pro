"""The installation's calendar: one "today" for every module.

Due dates, reminders, reports and letters count in Europe/Berlin, like the scheduled jobs, never in the
server's zone: a Docker container runs in UTC, where the previous day lasts until 1 or 2 a.m.
``date.today()`` is therefore not used outside the tests (``test_clock.py`` guards that).
"""

from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

BERLIN = ZoneInfo("Europe/Berlin")


def local_today(now: datetime | None = None, tz: ZoneInfo = BERLIN) -> date:
    """The installation's calendar date (not the server's, not UTC's); a naive ``now`` is UTC."""
    moment = now or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(tz).date()


def local_date(moment: datetime, tz: ZoneInfo = BERLIN) -> date:
    """The installation's calendar day of a stored instant (``…_at``, UTC; naive means UTC)."""
    return local_today(moment, tz)
