"""Usage segments of units in a billing period (Nutzungszeiträume).

A unit's billing period splits into tenancies, from move-in to move-out with
both days included, and the vacant gaps between them. Utility costs are shared
by the days of each segment; vacant days are the landlord's.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Callable, Iterable, Optional, Protocol, TypeVar

from .lease_engine import OCCUPYING_CONTRACT_STATUSES

# Every contract except a draft is billed for the days it covers; whether it
# still runs is decided by its dates, not by its status.
NON_BILLABLE_STATUSES = frozenset({"draft"})


class Tenancy(Protocol):
    id: str
    unit_id: str
    property_id: str
    status: str
    start_date: date
    end_date: Optional[date]


class StoredUnit(Protocol):
    id: str
    status: str


T = TypeVar("T", bound=Tenancy)


@dataclass(frozen=True)
class Segment:
    unit_id: str
    start: date
    end: date
    contract_id: Optional[str] = None  # None: vacant, borne by the landlord

    @property
    def days(self) -> int:
        return days_between(self.start, self.end)

    @property
    def is_vacancy(self) -> bool:
        return self.contract_id is None


class OverlappingTenanciesError(ValueError):
    def __init__(self, unit_id: str, first: Tenancy, second: Tenancy):
        self.unit_id = unit_id
        self.contract_ids = (first.id, second.id)
        super().__init__(f"Verträge {first.id} und {second.id} überschneiden sich in Einheit {unit_id}")


def days_between(start: date, end: date) -> int:
    """Days from start to end, both included."""
    return (end - start).days + 1


def billable_contracts(contracts: Iterable[T], property_id: str, start: date, end: date) -> list[T]:
    """Contracts of the property whose term touches [start, end]; drafts excluded."""
    return [
        c for c in contracts
        if c.property_id == property_id
        and c.status not in NON_BILLABLE_STATUSES
        and c.start_date <= end
        and (c.end_date is None or c.end_date >= start)
    ]


def unit_segments(unit_id: str, contracts: Iterable[Tenancy], start: date, end: date) -> list[Segment]:
    """Split [start, end] of a unit into tenancies and vacant gaps, in order.

    Raises OverlappingTenanciesError if two tenancies share a day.
    """
    tenancies = sorted((c for c in contracts if c.unit_id == unit_id), key=lambda c: (c.start_date, c.id))
    segments: list[Segment] = []
    cursor = start
    previous: Optional[Tenancy] = None
    for contract in tenancies:
        seg_start = max(contract.start_date, start)
        seg_end = min(contract.end_date or end, end)
        if seg_end < seg_start:
            continue
        if seg_start < cursor and previous is not None:
            raise OverlappingTenanciesError(unit_id, previous, contract)
        if seg_start > cursor:
            segments.append(Segment(unit_id, cursor, seg_start - timedelta(days=1)))
        segments.append(Segment(unit_id, seg_start, seg_end, contract.id))
        cursor = seg_end + timedelta(days=1)
        previous = contract
    if cursor <= end:
        segments.append(Segment(unit_id, cursor, end))
    return segments


def unit_status_on(day: date, stored_status: Optional[str], contracts: Iterable[Tenancy]) -> str:
    """A unit's status on *day*, read from its contracts.

    The unit is occupied while an active or terminated contract covers the day.
    Without one, a stored "occupied" is outdated as soon as the unit has
    contracts at all: the tenant has moved out or the next one is not in yet.
    Other stored statuses (vacant, reserved, renovation) stay as entered, and
    so does everything for units without contracts, such as owner-occupied ones.
    """
    tenancies = [c for c in contracts if c.status not in NON_BILLABLE_STATUSES]
    if any(
        c.status in OCCUPYING_CONTRACT_STATUSES and c.start_date <= day and (c.end_date is None or day <= c.end_date)
        for c in tenancies
    ):
        return "occupied"
    status = stored_status or "vacant"
    return "vacant" if status == "occupied" and tenancies else status


def unit_statuses_on(day: date, units: Iterable[StoredUnit], contracts: Iterable[Tenancy]) -> dict[str, str]:
    """unit_status_on for many units at once, keyed by unit id."""
    by_unit: dict[str, list[Tenancy]] = {}
    for contract in contracts:
        by_unit.setdefault(contract.unit_id, []).append(contract)
    return {unit.id: unit_status_on(day, unit.status, by_unit.get(unit.id, [])) for unit in units}


def prorate_monthly(amount_for_month: Callable[[date], Decimal], start: date, end: date) -> Decimal:
    """Sum a monthly amount over [start, end]; partial months count by their days.

    ``amount_for_month`` gets the first day of each month, so a later caller
    can return the amount valid in that month. The result is not rounded.
    """
    total = Decimal("0")
    month = date(start.year, start.month, 1)
    while month <= end:
        days_in_month = calendar.monthrange(month.year, month.month)[1]
        month_end = month.replace(day=days_in_month)
        covered = days_between(max(start, month), min(end, month_end))
        amount = Decimal(amount_for_month(month))
        total += amount if covered == days_in_month else amount * covered / days_in_month
        month = month_end + timedelta(days=1)
    return total
