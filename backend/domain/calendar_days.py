"""Calendar rules shared by deadlines and due dates: Easter, public holidays, working days.

The nine holidays every German state keeps count everywhere. A property's federal state adds
that state's own statewide holidays (Epiphany, Corpus Christi, Reformation Day …). Holidays
kept only in some municipalities (Corpus Christi in parts of Saxony and Thuringia, Assumption
in parts of Bavaria, the Augsburg Peace Festival) and one-off holidays are not known.
"""

from datetime import date, timedelta
from functools import lru_cache

STATES = {
    "BW": "Baden-Württemberg", "BY": "Bayern", "BE": "Berlin", "BB": "Brandenburg", "HB": "Bremen",
    "HH": "Hamburg", "HE": "Hessen", "MV": "Mecklenburg-Vorpommern", "NI": "Niedersachsen",
    "NW": "Nordrhein-Westfalen", "RP": "Rheinland-Pfalz", "SL": "Saarland", "SN": "Sachsen",
    "ST": "Sachsen-Anhalt", "SH": "Schleswig-Holstein", "TH": "Thüringen",
}

# statewide holidays beyond the nationwide ones: name, states, first year (None: before 1990)
_REGIONAL = (
    ("Heilige Drei Könige", ("BW", "BY", "ST"), None),
    ("Internationaler Frauentag", ("BE",), 2019),
    ("Internationaler Frauentag", ("MV",), 2023),
    ("Fronleichnam", ("BW", "BY", "HE", "NW", "RP", "SL"), None),
    ("Mariä Himmelfahrt", ("SL",), None),
    ("Weltkindertag", ("TH",), 2019),
    ("Reformationstag", ("BB", "MV", "SN", "ST", "TH"), None),
    ("Reformationstag", ("HB", "HH", "NI", "SH"), 2018),
    ("Allerheiligen", ("BW", "BY", "NW", "RP", "SL"), None),
    ("Buß- und Bettag", ("SN",), None),
)


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


def _national(year: int) -> dict[date, str]:
    sunday = easter(year)
    return {date(year, 1, 1): "Neujahr", sunday - timedelta(days=2): "Karfreitag",
            sunday + timedelta(days=1): "Ostermontag", date(year, 5, 1): "Tag der Arbeit",
            sunday + timedelta(days=39): "Christi Himmelfahrt", sunday + timedelta(days=50): "Pfingstmontag",
            date(year, 10, 3): "Tag der Deutschen Einheit", date(year, 12, 25): "1. Weihnachtstag",
            date(year, 12, 26): "2. Weihnachtstag"}


def _regional_day(name: str, year: int) -> date:
    if name == "Fronleichnam":
        return easter(year) + timedelta(days=60)
    if name == "Buß- und Bettag":                  # the Wednesday before 23 November
        return date(year, 11, 22) - timedelta(days=(date(year, 11, 22).weekday() - 2) % 7)
    month, day = {"Heilige Drei Könige": (1, 6), "Internationaler Frauentag": (3, 8),
                  "Mariä Himmelfahrt": (8, 15), "Weltkindertag": (9, 20), "Reformationstag": (10, 31),
                  "Allerheiligen": (11, 1)}[name]
    return date(year, month, day)


@lru_cache(maxsize=512)
def _holidays(year: int, state: str | None) -> dict[date, str]:
    days = _national(year)
    if state in STATES:
        for name, states, since in _REGIONAL:
            if state in states and (since is None or year >= since):
                days.setdefault(_regional_day(name, year), name)
    return days


def holiday_names(year: int, state: str | None = None) -> dict[date, str]:
    """The public holidays of a year: the nationwide ones, plus the state's own with a known state."""
    return dict(_holidays(year, state))


def national_holidays(year: int) -> set[date]:
    return set(_holidays(year, None))


def holidays(year: int, state: str | None = None) -> set[date]:
    return set(_holidays(year, state))


def holiday_name(day: date, state: str | None = None) -> str | None:
    return _holidays(day.year, state).get(day)


def is_working_day(day: date, state: str | None = None) -> bool:
    """Monday to Friday and no public holiday there."""
    return day.weekday() < 5 and day not in _holidays(day.year, state)


def deadline_end(day: date, state: str | None = None) -> date:
    """§ 193 BGB: a deadline ending on a Saturday, Sunday or public holiday ends on the next working day."""
    while not is_working_day(day, state):
        day += timedelta(days=1)
    return day


def rent_due_date(period_start: date, state: str | None = None) -> date:
    """§ 556b Abs. 1 BGB: rent is due by the third working day of its period.

    Saturdays do not count for paying rent (BGH, 13.07.2010, VIII ZR 291/09),
    nor do Sundays and holidays (with the property's state, its own too). A
    period that starts mid-month (moving in) counts from its first day.
    """
    count, current = 0, period_start
    while True:
        if is_working_day(current, state):
            count += 1
            if count == 3:
                return current
        current += timedelta(days=1)
