"""Calendar rules shared by deadlines and due dates: Easter, nationwide holidays, working days.

Only the nine holidays every German state keeps are known; regional holidays
(e.g. Epiphany, Corpus Christi, Reformation Day) are not, so a due date in a
state with one of them can be a day early.
"""

from datetime import date, timedelta


def easter(year: int) -> date:
    """Easter Sunday (anonymous Gregorian algorithm)."""
    a, b, c = year % 19, year // 100, year % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    lead = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * lead) // 451
    month = (h + lead - 7 * m + 114) // 31
    return date(year, month, (h + lead - 7 * m + 114) % 31 + 1)


def national_holidays(year: int) -> set[date]:
    sunday = easter(year)
    return {date(year, 1, 1), date(year, 5, 1), date(year, 10, 3), date(year, 12, 25), date(year, 12, 26),
            sunday - timedelta(days=2), sunday + timedelta(days=1), sunday + timedelta(days=39),
            sunday + timedelta(days=50)}


def rent_due_date(period_start: date) -> date:
    """§ 556b Abs. 1 BGB: rent is due by the third working day of its period.

    Saturdays do not count for paying rent (BGH, 13.07.2010, VIII ZR 291/09),
    nor do Sundays and holidays. A period that starts mid-month (moving in)
    counts from its first day.
    """
    count, current = 0, period_start
    while True:
        if current.weekday() < 5 and current not in national_holidays(current.year):
            count += 1
            if count == 3:
                return current
        current += timedelta(days=1)
