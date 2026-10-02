"""Pure recurrence tests; no app import, database, clock or notifications."""
from dataclasses import replace
from datetime import date, datetime, timedelta

import pytest

from backend.services.recurrence import (
    CatchUpLimit,
    Plan,
    RecurrenceError,
    catch_up,
    occurrence_at,
    occurrence_key,
    parse_plan,
    task_candidates,
)


def dates(plan, through, **kwargs):
    return [item.occurrence_date for item in catch_up(plan, through, **kwargs)]


@pytest.mark.parametrize("year,last", [(2023, 28), (2024, 29)])
def test_january_31_never_loses_anchor(year, last):
    plan = Plan("p", date(year, 1, 31), "MONTHLY")
    assert dates(plan, date(year, 4, 30)) == [
        date(year, 1, 31), date(year, 2, last),
        date(year, 3, 31), date(year, 4, 30),
    ]


def test_leap_day_returns_after_three_clamped_years():
    plan = Plan("p", date(2024, 2, 29), "YEARLY")
    assert dates(plan, date(2028, 2, 29)) == [
        date(2024, 2, 29), date(2025, 2, 28), date(2026, 2, 28),
        date(2027, 2, 28), date(2028, 2, 29),
    ]
    assert occurrence_at(Plan("p", date(2096, 2, 29), "YEARLY", 4), 1) == date(2100, 2, 28)
    assert occurrence_at(Plan("p", date(2096, 2, 29), "YEARLY", 4), 2) == date(2104, 2, 29)


@pytest.mark.parametrize("frequency,interval,anchor,expected", [
    ("DAILY", 2, date(2024, 2, 27), date(2024, 3, 2)),
    ("WEEKLY", 2, date(2024, 1, 1), date(2024, 1, 29)),
    ("MONTHLY", 2, date(2023, 12, 31), date(2024, 4, 30)),
    ("MONTHLY", 13, date(2023, 1, 31), date(2025, 3, 31)),
    ("YEARLY", 4, date(2020, 2, 29), date(2028, 2, 29)),
])
def test_intervals(frequency, interval, anchor, expected):
    assert occurrence_at(Plan("p", anchor, frequency, interval), 2) == expected


def test_clamping_is_not_implicit_end_of_month():
    assert occurrence_at(Plan("p", date(2023, 2, 28), "MONTHLY"), 1) == date(2023, 3, 28)
    assert occurrence_at(Plan("p", date(2023, 4, 30), "MONTHLY"), 1) == date(2023, 5, 30)


@pytest.mark.parametrize("text", [
    "FREQ=DAILY;INTERVAL=0", "FREQ=DAILY;INTERVAL=-1",
    "FREQ=DAILY;INTERVAL=1.5", "FREQ=DAILY;COUNT=0",
    "FREQ=DAILY;COUNT=-2", "FREQ=HOURLY", "INTERVAL=1",
    "FREQ=DAILY;FREQ=WEEKLY", "FREQ=DAILY;INTERVAL=1;interval=2",
    "FREQ=MONTHLY;BYDAY=MO", "FREQ=DAILY;", "FREQ=DAILY;BROKEN",
    "FREQ=DAILY;UNTIL=20230229", "FREQ=DAILY;UNTIL=2024-13-01",
    "FREQ=DAILY;UNTIL=20240131T000000Z", "FREQ=DAILY;UNTIL=2024-W05-1",
    "", "x" * 1025,
])
def test_rejects_malformed_or_unsupported_rules(text):
    with pytest.raises(RecurrenceError):
        parse_plan("p", date(2023, 1, 1), text)


@pytest.mark.parametrize("interval", [0, -1, True, 1.5, "2"])
def test_interval_type_is_strict(interval):
    with pytest.raises(RecurrenceError):
        Plan("p", date(2024, 1, 1), "DAILY", interval)


@pytest.mark.parametrize("end", ["2024-02-29", "20240229"])
def test_inclusive_until_and_count(end):
    p = parse_plan("p", date(2024, 1, 31), f"RRULE:freq=monthly;COUNT=3;UNTIL={end}")
    assert dates(p, date(2025, 1, 1)) == [date(2024, 1, 31), date(2024, 2, 29)]
    assert dates(replace(p, until=None), date(2025, 1, 1))[-1] == date(2024, 3, 31)
    assert dates(replace(p, count=1), date(2025, 1, 1)) == [p.anchor]


def test_effective_versions_preserve_phase_and_count():
    p = Plan("p", date(2024, 1, 31), "MONTHLY", count=4)
    boundary = date(2024, 3, 31)
    old = replace(p, effective_to=boundary)
    new = replace(p, effective_from=boundary)
    assert dates(old, date(2024, 12, 31)) + dates(new, date(2024, 12, 31)) == dates(
        p, date(2024, 12, 31)
    )
    assert [o.index for o in catch_up(new, date(2024, 12, 31))] == [2, 3]


def test_catch_up_is_restart_safe_and_does_not_count_only_new_items():
    p = Plan("p", date(2024, 1, 31), "MONTHLY", count=4)
    first = catch_up(p, date(2024, 2, 29))
    recorded = [o.key for o in first]
    saved = list(recorded)
    remaining = catch_up(p, date(2024, 12, 31), recorded=reversed(recorded))
    assert recorded == saved
    assert [o.index for o in remaining] == [2, 3]
    all_items = first + remaining
    assert len({o.key for o in all_items}) == 4
    assert catch_up(p, date(2024, 12, 31), recorded=[o.key for o in all_items]) == ()
    assert catch_up(p, date(2024, 12, 31)) == all_items
    assert catch_up(p, date(2024, 12, 31), recorded=recorded * 2) == remaining


def test_same_day_in_another_plan_does_not_suppress_occurrence():
    p = Plan("p", date(2024, 1, 1), "DAILY", count=1)
    result = catch_up(p, p.anchor, recorded=[("other", p.anchor)])
    assert result[0].key == ("p", p.anchor)


def test_legacy_task_count_and_open_child_policy():
    p = parse_plan("p", date(2024, 1, 31), "FREQ=MONTHLY;COUNT=2", legacy_child_count=True)
    feb = task_candidates(p, date(2024, 3, 31))
    assert [o.occurrence_date for o in feb] == [date(2024, 2, 29)]
    assert task_candidates(p, date(2024, 3, 31), children=[(feb[0].occurrence_date, "open")]) == ()
    done = [(feb[0].occurrence_date, "completed")]
    march = task_candidates(p, date(2024, 4, 30), children=done)
    assert [o.occurrence_date for o in march] == [date(2024, 3, 31)]
    assert task_candidates(p, date(2024, 4, 30), children=done + [
        (march[0].occurrence_date, "cancelled")
    ]) == ()
    one = parse_plan("p", p.anchor, "FREQ=MONTHLY;COUNT=1", legacy_child_count=True)
    assert len(task_candidates(one, date(2025, 1, 1))) == 1
    unlimited = parse_plan("p", p.anchor, "FREQ=MONTHLY;COUNT=0", legacy_child_count=True)
    assert unlimited.count is None


def test_explicit_task_catch_up_and_moved_instance_identity():
    p = parse_plan("p", date(2024, 1, 31), "FREQ=MONTHLY", legacy_child_count=True)
    # February task may now be due in March: identity remains February 29.
    children = [(date(2024, 2, 29), "in_progress")]
    got = task_candidates(p, date(2024, 4, 30), children=children, full_catch_up=True)
    assert [o.occurrence_date for o in got] == [date(2024, 3, 31), date(2024, 4, 30)]


def test_catch_up_windows_equal_full_run():
    p = Plan("p", date(2024, 1, 31), "MONTHLY")
    cut = date(2024, 2, 29)
    first = catch_up(p, cut)
    second = catch_up(p, date(2024, 6, 30), since=cut + timedelta(days=1))
    assert first + second == catch_up(p, date(2024, 6, 30))


def test_seek_near_date_max_and_overflow():
    p = Plan("p", date.min, "DAILY")
    assert dates(p, date.max, since=date.max) == [date.max]
    for frequency in ("DAILY", "WEEKLY", "MONTHLY", "YEARLY"):
        q = Plan("p", date.max, frequency)
        assert dates(q, date.max) == [date.max]
        assert occurrence_at(q, 1) is None


def test_limits_never_silently_truncate_or_move_clock():
    p = Plan("p", date(2024, 1, 1), "DAILY", count=3)
    with pytest.raises(CatchUpLimit):
        catch_up(p, date(2024, 1, 3), limit=2)
    assert len(catch_up(p, date(2024, 1, 3), limit=3)) == 3
    assert len(catch_up(p, date(2024, 1, 3), limit=1, recorded=[
        ("p", date(2024, 1, 1)), ("p", date(2024, 1, 2))
    ])) == 1
    assert catch_up(p, date(2023, 12, 31)) == ()


def test_dates_ids_and_ranges_are_validated():
    p = Plan("p", date(2024, 1, 31), "MONTHLY")
    invalid = [
        lambda: catch_up(p, datetime(2024, 2, 1)),
        lambda: catch_up(p, date(2024, 2, 1), since=date(2024, 3, 1)),
        lambda: catch_up(p, date(2024, 2, 1), limit=True),
        lambda: replace(p, until=date(2024, 1, 1)),
        lambda: replace(p, effective_to=p.anchor),
        lambda: replace(p, count=True),
        lambda: replace(p, anchor=datetime(2024, 1, 31)),
        lambda: occurrence_key(" ", p.anchor),
        lambda: occurrence_key("p\n", p.anchor),
        lambda: occurrence_at(p, -1),
        lambda: occurrence_at(p, True),
        lambda: catch_up(p, p.anchor, recorded=[("p", "2024-01-31")]),
    ]
    for operation in invalid:
        with pytest.raises(RecurrenceError):
            operation()
