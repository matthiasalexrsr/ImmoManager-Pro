"""Booking totals for the finance reports: one classification, one filter, exact cents.

Side: a booking is income or expense by the type of its category; without one, money with a
tenant is income (rent and its returns), anything else counts by its sign. A reversal (Storno)
carries the category and tenant of the booking it cancels and the opposite sign
(domain.booking_reversal), so it lands on that booking's side and nets it: a returned rent
payment lowers the income, it is no expense of its own.

Owner money: a category of type "private" holds what the owners take out (withdrawal,
distribution) or put in from private means (contribution). Such a booking moves the account
balance but is neither income nor expense: its side is "withdrawal" or "contribution" by its sign
(a reversal again on the side of the booking it cancels), and no result, cost or tax figure counts it.

Filter (FinanceFilter): period by date (inclusive), portfolio, property, unit, owner. A booking
belongs to the portfolio of its account and to the property it names, or else to the property of
its unit; other records (contracts, receivables, invoices) belong to the property they name and to
its portfolio. The request's portfolio boundary applies on top (services.portfolio_scope): SQL
sums run through the request's session, memory sums over its scoped collections. With an owner,
every amount counts with that owner's part of it (services.ownership, OwnerView): the parts of all
owners and of the part nobody is recorded for add up to the whole report.

Sums: SQL stores add integer cents in the database (exact on SQLite and PostgreSQL), the memory
store adds Decimal cents (domain.money). Both give the same result for the same data.
"""

from __future__ import annotations

from calendar import monthrange
from collections import defaultdict
from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal
from typing import Any, Iterable, Optional

from fastapi import HTTPException

from ..domain.money import ZERO, from_cents, money
from ..storage import NotFoundError

SIDES = ("income", "expense")
PRIVATE = "private"                                   # category type of the owners' own money
PRIVATE_SIDES = ("withdrawal", "contribution")
GROUPS = frozenset({"month", "category", "account"})


# ---------------------------------------------------------------------------
# Months
# ---------------------------------------------------------------------------

def month_start(day: date) -> date:
    return day.replace(day=1)


def month_end(day: date) -> date:
    return day.replace(day=monthrange(day.year, day.month)[1])


def add_months(day: date, months: int) -> date:
    """The same day *months* calendar months later (or earlier), clamped to the month's end."""
    index = day.month - 1 + months
    year, month = day.year + index // 12, index % 12 + 1
    return day.replace(year=year, month=month, day=min(day.day, monthrange(year, month)[1]))


def month_key(day: date) -> str:
    return f"{day.year:04d}-{day.month:02d}"


def months_between(first: date, last: date) -> list[date]:
    """First days of every calendar month from *first* to *last*, both included."""
    months, current, end = [], month_start(first), month_start(last)
    while current <= end:
        months.append(current)
        if current == end:
            break
        current = add_months(current, 1)
    return months


# ---------------------------------------------------------------------------
# Filter
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class FinanceFilter:
    date_from: Optional[date] = None
    date_to: Optional[date] = None
    portfolio_id: Optional[str] = None
    property_id: Optional[str] = None
    unit_id: Optional[str] = None
    owner_contact_id: Optional[str] = None     # services.ownership.NOBODY: the part no owner is recorded for

    def with_period(self, date_from: Optional[date], date_to: Optional[date]) -> "FinanceFilter":
        return replace(self, date_from=date_from, date_to=date_to)

    def without_owner(self) -> "FinanceFilter":
        return replace(self, owner_contact_id=None)

    @property
    def below_portfolio(self) -> bool:
        """Narrowed to a property or unit: account opening balances do not belong to it."""
        return bool(self.property_id or self.unit_id)

    def opening_accounts(self, store: Any) -> list:
        """The accounts whose opening balance belongs to the filter.

        Opening balances belong to accounts, not to properties or units. With an owner: the accounts
        held by that owner alone (``owner_contact_id``); "none" takes the accounts nobody holds alone.
        """
        if self.below_portfolio:
            return []
        accounts = [a for a in store.list_accounts() if not self.portfolio_id or a.portfolio_id == self.portfolio_id]
        if self.owner_contact_id:
            holder = None if self.owner_contact_id == "none" else self.owner_contact_id
            accounts = [a for a in accounts if (getattr(a, "owner_contact_id", None) or None) == holder]
        return accounts

    def in_period(self, day: Optional[date]) -> bool:
        if day is None:
            return self.date_from is None and self.date_to is None
        return (self.date_from is None or day >= self.date_from) and (self.date_to is None or day <= self.date_to)

    def echo(self) -> dict[str, Optional[str]]:
        """The filter as applied, for the response."""
        return {
            "date_from": self.date_from.isoformat() if self.date_from else None,
            "date_to": self.date_to.isoformat() if self.date_to else None,
            "portfolio_id": self.portfolio_id,
            "property_id": self.property_id,
            "unit_id": self.unit_id,
            **({"owner_contact_id": self.owner_contact_id} if self.owner_contact_id else {}),
        }


def validate_filter(store: Any, flt: FinanceFilter, *, require_visible: bool = False) -> None:
    """A visible filter must describe one consistent portfolio/property/unit path.

    Lookups use the caller's current scope. An inaccessible record stays missing;
    only contradictions between records the caller can read produce a 422.
    """
    if flt.date_from and flt.date_to and flt.date_from > flt.date_to:
        raise HTTPException(422, "Der Berichtszeitraum beginnt nach seinem Ende.")
    try:
        if flt.owner_contact_id and flt.owner_contact_id != "none":
            store.get_contact(flt.owner_contact_id)
        if flt.portfolio_id:
            store.get_portfolio(flt.portfolio_id)
        prop = store.get_property(flt.property_id) if flt.property_id else None
        unit = store.get_unit(flt.unit_id) if flt.unit_id else None
    except NotFoundError:
        # Legacy reports intentionally display an empty, unavailable selection
        # for missing/hidden IDs. Versioned definitions require visible sources.
        if require_visible:
            raise
        return
    if prop is not None and unit is not None and unit.property_id != prop.id:
        raise HTTPException(422, "Die gewählte Einheit gehört nicht zur gewählten Immobilie.")
    if flt.portfolio_id:
        selected_property = prop or (store.get_property(unit.property_id) if unit is not None else None)
        if selected_property is not None and selected_property.portfolio_id != flt.portfolio_id:
            raise HTTPException(422, "Die gewählte Immobilie oder Einheit gehört nicht zum gewählten Portfolio.")


class Dimensions:
    """Where records belong (portfolio, property, unit), read once per calculation."""

    def __init__(self, store: Any, flt: FinanceFilter) -> None:
        validate_filter(store, flt)
        self.store, self.flt = store, flt
        self._unit_property: Optional[dict[str, str]] = None
        self._property_portfolio: Optional[dict[str, str]] = None
        self._account_portfolio: Optional[dict[str, str]] = None

    def unit_property(self, unit_id: Optional[str]) -> Optional[str]:
        if self._unit_property is None:
            self._unit_property = {u.id: u.property_id for u in self.store.list_units()}
        return self._unit_property.get(unit_id) if unit_id else None

    def property_portfolio(self, property_id: Optional[str]) -> Optional[str]:
        if self._property_portfolio is None:
            self._property_portfolio = {p.id: p.portfolio_id for p in self.store.list_properties()}
        return self._property_portfolio.get(property_id) if property_id else None

    def account_portfolio(self, account_id: Optional[str]) -> Optional[str]:
        if self._account_portfolio is None:
            self._account_portfolio = {a.id: a.portfolio_id for a in self.store.list_accounts()}
        return self._account_portfolio.get(account_id) if account_id else None

    def _place_matches(self, property_id: Optional[str], unit_id: Optional[str]) -> bool:
        flt = self.flt
        if flt.unit_id and unit_id != flt.unit_id:
            return False
        if flt.property_id and (property_id or self.unit_property(unit_id)) != flt.property_id:
            return False
        return True

    def matches(self, property_id: Optional[str], unit_id: Optional[str] = None) -> bool:
        """A record naming a property and/or unit; its portfolio is that of the property."""
        if not self._place_matches(property_id, unit_id):
            return False
        if self.flt.portfolio_id:
            return self.property_portfolio(property_id or self.unit_property(unit_id)) == self.flt.portfolio_id
        return True

    def booking_matches(self, booking: Any) -> bool:
        if not self.flt.in_period(booking.booking_date) or not self._place_matches(booking.property_id,
                                                                                     booking.unit_id):
            return False
        return not self.flt.portfolio_id or self.account_portfolio(booking.account_id) == self.flt.portfolio_id

    def contract_matches(self, contract: Any) -> bool:
        return self.matches(contract.property_id, contract.unit_id)

    def property_record_matches(self, prop: Any) -> bool:
        flt = self.flt
        if flt.portfolio_id and prop.portfolio_id != flt.portfolio_id:
            return False
        if flt.property_id and prop.id != flt.property_id:
            return False
        return not flt.unit_id or self.unit_property(flt.unit_id) == prop.id

    def unit_record_matches(self, unit: Any) -> bool:
        return self.matches(unit.property_id, unit.id)


# ---------------------------------------------------------------------------
# Booking totals
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class BookingTotal:
    """Signed sum of the bookings that share a classification (and the requested groups)."""

    side: str            # income or expense; withdrawal or contribution for the owners' own money
    tenant: bool         # names a tenant: rent, its returns and refunds
    classified: bool     # has an income or expense category
    unit: bool           # names a unit
    amount: Decimal
    month: Optional[str] = None
    category_id: Optional[str] = None
    account_id: Optional[str] = None


def booking_side(category_type: Optional[str], booking: Any) -> str:
    if category_type in SIDES:
        return str(category_type)
    positive = money(booking.amount) > 0
    if getattr(booking, "reverses_booking_id", None):
        positive = not positive     # a reversal sits on the side of the booking it cancels
    if category_type == PRIVATE:
        return "contribution" if positive else "withdrawal"
    if booking.tenant_id:
        return "income"
    return "income" if positive else "expense"


def booking_totals(store: Any, flt: FinanceFilter, *, by: Iterable[str] = ()) -> list[BookingTotal]:
    """Bookings matching the filter, summed per classification and per requested group."""
    groups = frozenset(by)
    if groups - GROUPS:
        raise ValueError(f"unknown groups: {sorted(groups - GROUPS)}")
    validate_filter(store, flt)
    if flt.owner_contact_id:
        return _owner_totals(store, flt, groups)
    if hasattr(store, "db"):
        return _sql_totals(store.db, flt, groups)
    return _memory_totals(store, flt, groups)


def booking_sources(store: Any, flt: FinanceFilter) -> list[Any]:
    """The scoped rows behind the same aggregate, filtered in SQL before loading.

    The owner of the filter does not narrow the rows: OwnerView gives each one's part.
    """
    flt = flt.without_owner()
    validate_filter(store, flt)
    if hasattr(store, "db"):
        from sqlalchemy import select

        from ..db.orm_models import BookingORM
        # The session bounds this select and each select of the filter by the portfolio scope
        # (portfolio_scope._scope_queries), once; a boundary added here as well was bounded again.
        query = select(BookingORM).where(*_sql_conditions(flt))
        return list(store.db.scalars(query.order_by(BookingORM.booking_date, BookingORM.id)))
    dimensions = Dimensions(store, flt)
    return sorted((booking for booking in store.list_bookings() if dimensions.booking_matches(booking)),
                  key=lambda booking: (booking.booking_date, booking.id))


def first_booking_date(store: Any, flt: FinanceFilter) -> Optional[date]:
    """The earliest booking date within the filter (its period and owner ignored)."""
    unbounded = flt.with_period(None, None).without_owner()
    validate_filter(store, unbounded)
    if hasattr(store, "db"):
        from sqlalchemy import func, select

        from ..db.orm_models import BookingORM

        bookings = BookingORM.__table__
        return store.db.scalar(select(func.min(bookings.c.booking_date)).where(*_sql_conditions(unbounded)))
    dims = Dimensions(store, unbounded)
    return min((b.booking_date for b in store.list_bookings() if dims.booking_matches(b)), default=None)


def _memory_totals(store: Any, flt: FinanceFilter, groups: frozenset[str]) -> list[BookingTotal]:
    dims = Dimensions(store, flt)
    types = {c.id: c.category_type for c in store.list_categories()}
    sums: dict[tuple, Decimal] = defaultdict(lambda: ZERO)
    for booking in store.list_bookings():
        if not dims.booking_matches(booking):
            continue
        category_type = types.get(booking.category_id) if booking.category_id else None
        key = (booking_side(category_type, booking), bool(booking.tenant_id), category_type in SIDES,
               bool(booking.unit_id),
               month_key(booking.booking_date) if "month" in groups else None,
               booking.category_id if "category" in groups else None,
               booking.account_id if "account" in groups else None)
        sums[key] += money(booking.amount)
    return [BookingTotal(side=key[0], tenant=key[1], classified=key[2], unit=key[3], amount=amount,
                         month=key[4], category_id=key[5], account_id=key[6])
            for key, amount in sums.items()]


def _owner_totals(store: Any, flt: FinanceFilter, groups: frozenset[str]) -> list[BookingTotal]:
    """Like _memory_totals, each booking counting with the owner's part of it."""
    from .ownership import OwnerView

    view = OwnerView(store, flt)
    types = {c.id: c.category_type for c in store.list_categories()}
    sums: dict[tuple, Decimal] = defaultdict(lambda: ZERO)
    for booking in booking_sources(store, flt):
        part = view.booking(booking)
        if not part:
            continue
        category_type = types.get(booking.category_id) if booking.category_id else None
        key = (booking_side(category_type, booking), bool(booking.tenant_id), category_type in SIDES,
               bool(booking.unit_id),
               month_key(booking.booking_date) if "month" in groups else None,
               booking.category_id if "category" in groups else None,
               booking.account_id if "account" in groups else None)
        sums[key] += part
    return [BookingTotal(side=key[0], tenant=key[1], classified=key[2], unit=key[3], amount=amount,
                         month=key[4], category_id=key[5], account_id=key[6])
            for key, amount in sums.items()]


def _sql_conditions(flt: FinanceFilter) -> list[Any]:
    from sqlalchemy import and_, or_, select

    from ..db.orm_models import AccountORM, BookingORM, UnitORM

    bookings, accounts, units = BookingORM.__table__, AccountORM.__table__, UnitORM.__table__
    conditions: list[Any] = []
    if flt.date_from:
        conditions.append(bookings.c.booking_date >= flt.date_from)
    if flt.date_to:
        conditions.append(bookings.c.booking_date <= flt.date_to)
    if flt.portfolio_id:
        conditions.append(bookings.c.account_id.in_(
            select(accounts.c.id).where(accounts.c.portfolio_id == flt.portfolio_id)))
    if flt.property_id:
        conditions.append(or_(
            bookings.c.property_id == flt.property_id,
            and_(bookings.c.property_id.is_(None),
                 bookings.c.unit_id.in_(select(units.c.id).where(units.c.property_id == flt.property_id)))))
    if flt.unit_id:
        conditions.append(bookings.c.unit_id == flt.unit_id)
    return conditions


def _cents(db: Any, column: Any) -> Any:
    """The amount as integer cents, rounded half up like domain.money."""
    from sqlalchemy import BigInteger, Numeric, case, cast, func

    if db.get_bind().dialect.name == "sqlite":
        # SQLite keeps REAL values: a value entered as 1.005 is 1.00499999…; the nudge rounds it
        # like the decimal it was entered as, and leaves values of whole cents unchanged.
        nudge = case((column < 0, -1e-7), else_=1e-7)
        return cast(func.round(column * 100 + nudge), BigInteger)
    return cast(func.round(cast(column, Numeric), 2) * 100, BigInteger)


def _sql_totals(db: Any, flt: FinanceFilter, groups: frozenset[str]) -> list[BookingTotal]:
    from sqlalchemy import and_, case, extract, func, literal, or_, select

    from ..db.orm_models import BookingORM, CategoryORM

    bookings, categories = BookingORM.__table__, CategoryORM.__table__
    category_type = categories.c.category_type
    classified = category_type.in_(SIDES)
    incoming = or_(and_(bookings.c.reverses_booking_id.is_(None), bookings.c.amount > 0),
                   and_(bookings.c.reverses_booking_id.is_not(None), bookings.c.amount < 0))
    side = case((classified, category_type),
                (category_type == PRIVATE, case((incoming, literal("contribution")), else_=literal("withdrawal"))),
                (bookings.c.tenant_id.is_not(None), literal("income")),
                (incoming, literal("income")), else_=literal("expense"))
    columns = [
        side.label("side"),
        case((bookings.c.tenant_id.is_not(None), 1), else_=0).label("tenant"),
        case((classified, 1), else_=0).label("classified"),
        case((bookings.c.unit_id.is_not(None), 1), else_=0).label("unit"),
    ]
    if "month" in groups:
        columns += [extract("year", bookings.c.booking_date).label("year"),
                    extract("month", bookings.c.booking_date).label("month")]
    if "category" in groups:
        columns.append(bookings.c.category_id.label("category_id"))
    if "account" in groups:
        columns.append(bookings.c.account_id.label("account_id"))
    columns.append(_cents(db, bookings.c.amount).label("cents"))
    # Classified per row first, grouped outside: PostgreSQL would not match bound literals of the
    # CASE expressions between SELECT and GROUP BY.
    rows = (select(*columns)
            .select_from(bookings.outerjoin(categories, categories.c.id == bookings.c.category_id))
            .where(*_sql_conditions(flt))
            .subquery())
    keys = [column for column in rows.c if column.name != "cents"]
    result = db.execute(select(*keys, func.sum(rows.c.cents).label("cents")).group_by(*keys)).mappings()
    totals = []
    for row in result:
        month = f"{int(row['year']):04d}-{int(row['month']):02d}" if "month" in groups else None
        totals.append(BookingTotal(
            side=row["side"], tenant=bool(row["tenant"]), classified=bool(row["classified"]),
            unit=bool(row["unit"]), amount=from_cents(row["cents"]), month=month,
            category_id=row["category_id"] if "category" in groups else None,
            account_id=row["account_id"] if "account" in groups else None))
    return totals
