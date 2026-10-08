"""Finance sums on a real PostgreSQL server: exact cents in the database, reversals netted,
the portfolio boundary applied, and the reversal migration.

Opt in with IMMO_TEST_POSTGRES_ADMIN_URL (see test_document_versions_postgres.py).
"""

from datetime import date
from decimal import Decimal

import pytest
import sqlalchemy as sa
from alembic import command
from sqlalchemy.orm import Session
from test_document_versions_postgres import postgres  # noqa: F401  (fixture: own database per test)

from backend import auth
from backend.models import AccountCreate, BookingCreate, CategoryCreate, PortfolioCreate
from backend.repositories import SQLAlchemyStore
from backend.services import report_service
from backend.services.finance_ledger import FinanceFilter, booking_totals
from backend.services.portfolio_scope import scope_context, scope_from_user


def _store(engine):
    return SQLAlchemyStore(Session(engine))


def _seed(engine) -> dict:
    seed = _store(engine)
    north = seed.create_portfolio(PortfolioCreate(name="Nord"))
    south = seed.create_portfolio(PortfolioCreate(name="Süd"))
    acc_n = seed.create_account(AccountCreate(portfolio_id=north.id, name="Nord", account_type="bank"))
    acc_s = seed.create_account(AccountCreate(portfolio_id=south.id, name="Süd", account_type="bank"))
    rent = seed.create_category(CategoryCreate(portfolio_id=north.id, name="Miete", category_type="income"))

    def book(account, day, amount, **fields):
        return seed.create_booking(BookingCreate(account_id=account.id, booking_date=date.fromisoformat(day),
                                                 amount=amount, status="booked", **fields))

    for _ in range(100):
        book(acc_n, "2026-01-15", 11.11)
    book(acc_n, "2026-01-20", -0.10)
    book(acc_n, "2026-01-21", -0.20)
    paid = book(acc_n, "2026-02-03", 633.33, category_id=rent.id)
    book(acc_n, "2026-02-10", -633.33, category_id=rent.id, reverses_booking_id=paid.id)
    book(acc_s, "2026-02-05", 700.0)
    seed.db.close()
    return {"north": north, "south": south, "acc_n": acc_n, "acc_s": acc_s, "paid": paid}


def test_booking_sums_are_exact_decimal_cents_on_postgres(postgres):  # noqa: F811
    engine, _ = postgres
    seeded = _seed(engine)
    with engine.connect() as connection:
        # the database itself adds exactly (NUMERIC since d7a2f9c4e681)
        assert connection.exec_driver_sql("SELECT SUM(amount) FROM bookings WHERE amount = 11.11").scalar() == \
            Decimal("1111.00")
    target = _store(engine)
    rows = booking_totals(target, FinanceFilter(), by=("month",))
    assert all(isinstance(row.amount, Decimal) for row in rows)
    by_month: dict[tuple, Decimal] = {}
    for row in rows:
        by_month[(row.month, row.side)] = by_month.get((row.month, row.side), Decimal("0")) + row.amount
    # January: 100 x 11.11 in, 0.10 + 0.20 out; February: the rent and its reversal net to zero
    assert by_month == {("2026-01", "income"): Decimal("1111.00"), ("2026-01", "expense"): Decimal("-0.30"),
                        ("2026-02", "income"): Decimal("700.00")}
    cash = report_service.compute_cashflow(target, FinanceFilter(date_from=date(2026, 1, 1),
                                                                 date_to=date(2026, 3, 31)))
    assert (cash["incomeTotal"], cash["expenseTotal"], cash["netTotal"]) == (1811.0, 0.3, 1810.7)
    assert [m["net"] for m in cash["monthly"]] == [1110.7, 700.0, 0.0]
    north = [row.amount for row in booking_totals(target, FinanceFilter(), by=("account",))
             if row.account_id == seeded["acc_n"].id]
    assert sum(north, Decimal("0")) == Decimal("1110.70")
    target.db.close()


def test_restricted_sums_on_postgres_stop_at_the_portfolio(postgres):  # noqa: F811
    engine, _ = postgres
    seeded = _seed(engine)
    staff = auth.register_user("staff", "s@example.com", "Staff", "Secret123", "verwalter",
                               portfolio_access="selected", portfolio_ids=[seeded["north"].id])
    stored = auth.get_user_by_id(staff.id)
    assert stored is not None
    target = _store(engine)
    with scope_context(scope_from_user(stored)):
        total = sum((row.amount for row in booking_totals(target, FinanceFilter())), Decimal("0"))
        other = booking_totals(target, FinanceFilter(portfolio_id=seeded["south"].id))
    assert total == Decimal("1110.70") and other == []
    target.db.close()


def test_reversal_migration_on_postgres(postgres):  # noqa: F811
    engine, config = postgres
    seeded = _seed(engine)
    inspector = sa.inspect(engine)
    keys = [key for key in inspector.get_foreign_keys("bookings") if key["constrained_columns"] == ["reverses_booking_id"]]
    assert [(key["referred_table"], key["options"].get("ondelete")) for key in keys] == [("bookings", "SET NULL")]
    assert "idx_bookings_reverses" in {index["name"] for index in inspector.get_indexes("bookings")}

    with pytest.raises(RuntimeError, match="reversals exist"):
        command.downgrade(config, "b8e3d5f7a2c4")
    with engine.begin() as connection:
        connection.exec_driver_sql("DELETE FROM bookings WHERE reverses_booking_id IS NOT NULL")
    command.downgrade(config, "b8e3d5f7a2c4")
    assert "reverses_booking_id" not in {c["name"] for c in sa.inspect(engine).get_columns("bookings")}
    command.upgrade(config, "head")
    with engine.connect() as connection:
        assert connection.exec_driver_sql("SELECT amount FROM bookings WHERE id = %s",
                                          (seeded["paid"].id,)).scalar() == Decimal("633.33")
