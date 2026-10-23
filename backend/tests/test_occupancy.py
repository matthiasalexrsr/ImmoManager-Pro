"""Usage segments of units in a billing period and day-based proration."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Optional

import pytest

from backend.domain.occupancy import (
    OverlappingTenanciesError,
    Segment,
    billable_contracts,
    prorate_monthly,
    unit_segments,
    unit_status_on,
)

Y2025 = (date(2025, 1, 1), date(2025, 12, 31))


@dataclass
class C:
    id: str
    start_date: date
    end_date: Optional[date] = None
    unit_id: str = "u"
    property_id: str = "p"
    status: str = "active"


def _summary(segments: list[Segment]) -> list[tuple]:
    return [(s.contract_id, s.start, s.end, s.days) for s in segments]


def test_tenancy_for_the_whole_period():
    assert _summary(unit_segments("u", [C("a", date(2020, 4, 1))], *Y2025)) == [
        ("a", date(2025, 1, 1), date(2025, 12, 31), 365),
    ]


def test_tenant_change_with_vacancy_in_between():
    """Leipzig, WE 06: Lukas until 30.06., two months vacant, Sophie from 01.09."""
    contracts = [C("sophie", date(2025, 9, 1)), C("lukas", date(2021, 3, 1), date(2025, 6, 30), status="terminated")]

    assert _summary(unit_segments("u", contracts, *Y2025)) == [
        ("lukas", date(2025, 1, 1), date(2025, 6, 30), 181),
        (None, date(2025, 7, 1), date(2025, 8, 31), 62),
        ("sophie", date(2025, 9, 1), date(2025, 12, 31), 122),
    ]


def test_move_in_on_the_15th_leaves_the_start_vacant():
    segments = unit_segments("u", [C("a", date(2025, 3, 15))], *Y2025)

    assert _summary(segments) == [
        (None, date(2025, 1, 1), date(2025, 3, 14), 73),
        ("a", date(2025, 3, 15), date(2025, 12, 31), 292),
    ]


def test_leap_year_has_366_days():
    segments = unit_segments("u", [C("a", date(2020, 1, 1))], date(2024, 1, 1), date(2024, 12, 31))

    assert segments[0].days == 366


def test_seamless_change_has_no_vacancy():
    contracts = [C("a", date(2020, 1, 1), date(2025, 6, 30)), C("b", date(2025, 7, 1))]

    assert [s.contract_id for s in unit_segments("u", contracts, *Y2025)] == ["a", "b"]


def test_unit_without_tenancy_is_vacant_all_period():
    assert _summary(unit_segments("u", [], *Y2025)) == [(None, date(2025, 1, 1), date(2025, 12, 31), 365)]


def test_contracts_of_other_units_and_outside_the_period_are_ignored():
    contracts = [C("other", date(2020, 1, 1), unit_id="x"), C("old", date(2019, 1, 1), date(2024, 12, 31))]

    assert _summary(unit_segments("u", contracts, *Y2025)) == [(None, date(2025, 1, 1), date(2025, 12, 31), 365)]


def test_overlapping_tenancies_are_an_error():
    contracts = [C("a", date(2020, 1, 1)), C("b", date(2025, 6, 1))]

    with pytest.raises(OverlappingTenanciesError) as exc:
        unit_segments("u", contracts, *Y2025)
    assert exc.value.contract_ids == ("a", "b")


def test_billable_contracts_skip_drafts_but_keep_ended_ones():
    contracts = [
        C("active", date(2020, 1, 1)),
        C("ended", date(2020, 1, 1), date(2025, 3, 31), status="expired"),
        C("draft", date(2025, 1, 1), status="draft"),
        C("before", date(2020, 1, 1), date(2024, 12, 31), status="terminated"),
        C("elsewhere", date(2020, 1, 1), property_id="q"),
    ]

    assert [c.id for c in billable_contracts(contracts, "p", *Y2025)] == ["active", "ended"]


@pytest.mark.parametrize("start,end,expected", [
    (date(2025, 1, 1), date(2025, 12, 31), Decimal("2400")),   # 12 full months
    (date(2025, 9, 1), date(2025, 12, 31), Decimal("800")),    # Sophie: 4 months
    (date(2025, 9, 16), date(2025, 12, 31), Decimal("700")),   # move-in on 16.09.: 15/30 of September
    (date(2024, 2, 15), date(2024, 2, 29), Decimal("200") * 15 / 29),  # leap February
])
def test_prorate_monthly_counts_partial_months_by_days(start, end, expected):
    assert prorate_monthly(lambda month: Decimal("200"), start, end) == expected


def test_prorate_monthly_asks_for_each_month():
    seen: list[date] = []

    def amount(month: date) -> Decimal:
        seen.append(month)
        return Decimal("0")

    prorate_monthly(amount, date(2025, 11, 20), date(2026, 1, 5))

    assert seen == [date(2025, 11, 1), date(2025, 12, 1), date(2026, 1, 1)]


TODAY = date(2026, 10, 4)


@pytest.mark.parametrize("stored, contracts, expected", [
    ("vacant", [C("a", date(2026, 9, 1))], "occupied"),  # moved in, status never changed
    ("occupied", [C("a", date(2021, 3, 1), date(2026, 6, 30), status="terminated")], "vacant"),  # moved out
    ("occupied", [C("a", date(2026, 11, 1))], "vacant"),  # next tenant not in yet
    ("reserved", [C("a", date(2026, 11, 1))], "reserved"),
    ("renovation", [C("a", date(2020, 1, 1), date(2026, 3, 31), status="terminated")], "renovation"),
    ("occupied", [], "occupied"),  # no contracts at all, e.g. the owner lives there
    ("occupied", [C("a", date(2026, 1, 1), status="draft")], "occupied"),  # drafts do not count
    ("vacant", [C("a", date(2026, 1, 1), date(2026, 12, 31), status="expired")], "vacant"),
])
def test_unit_status_follows_the_contracts(stored, contracts, expected):
    """Regression: dashboard and occupancy report counted the stored flag, which nobody updates."""
    assert unit_status_on(TODAY, stored, contracts) == expected
