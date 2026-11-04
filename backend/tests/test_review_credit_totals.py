"""The fast review aggregate must equal the existing allocation/mirroring rules."""
from collections import defaultdict
from decimal import Decimal

import pytest
from test_payment_allocation import client, yilmaz  # noqa: F401

from backend.dependencies import store
from backend.services.payment_allocations import accounted_by_booking, credited_by_tenant, non_rent_shares


def canonical(bookings):
    expected: dict[str, Decimal] = defaultdict(lambda: Decimal(0))
    for rows in credited_by_tenant(store, bookings=bookings).values():
        for row, _, amount in rows:
            expected[row.id] += amount
    for key, amount in non_rent_shares(store, [row.id for row in bookings]).items():
        expected[key] += amount
    return {key: value for key, value in expected.items() if value}


@pytest.mark.parametrize("kind", ["stored", "legacy", "legacy_reversal", "partly_unassigned"])
def test_review_totals_match_canonical_credit_and_reservation_rules(client, yilmaz, kind):  # noqa: F811
    booking = store.list_bookings()[0]
    if kind == "legacy":
        for allocation in store.list_payment_allocations():
            store.delete_payment_allocation(allocation.id)
    elif kind == "legacy_reversal":
        result = client.post(f"/api/v1/bookings/{booking.id}/reverse", json={"booking_date": "2026-01-01", "amount": .01})
        assert result.status_code == 201, result.text
        for allocation in store.list_payment_allocations(booking_id=result.json()["id"]):
            store.delete_payment_allocation(allocation.id)
    elif kind == "partly_unassigned":
        result = client.post("/api/v1/bookings", json={"account_id": yilmaz["account"]["id"],
            "tenant_id": yilmaz["tenant"]["id"], "booking_date": "2026-01-03", "amount": 2000})
        assert result.status_code == 201, result.text
    bookings = store.list_bookings()
    expected: dict[str, Decimal] = defaultdict(lambda: Decimal(0))
    for rows in credited_by_tenant(store, bookings=bookings).values():
        for row, _, amount in rows:
            expected[row.id] += amount
    for key, amount in non_rent_shares(store, [row.id for row in bookings]).items():
        expected[key] += amount
    actual = accounted_by_booking(store, bookings)
    assert {key: amount for key, amount in actual.items() if amount} == {key: amount for key, amount in expected.items() if amount}


def test_scoped_review_counts_hidden_contract_shares_without_returning_foreign_sources(client, yilmaz):  # noqa: F811
    from backend import auth
    from backend.services.portfolio_scope import scope_context, scope_from_user

    north_id = store.get_account(yilmaz["account"]["id"]).portfolio_id
    south = client.post("/api/v1/portfolios", json={"name": "Nur im anderen Portfolio"}).json()
    prop = client.post("/api/v1/properties", json={"portfolio_id": south["id"], "name": "Anderes Objekt", "property_type": "residential"}).json()
    unit = client.post("/api/v1/units", json={"property_id": prop["id"], "label": "Süd", "unit_type": "flat", "cold_rent": 570}).json()
    contract = client.post("/api/v1/contracts", json={"contract_number": "Süd-Vertrag", "property_id": prop["id"],
        "unit_id": unit["id"], "tenant_id": yilmaz["tenant"]["id"], "start_date": "2024-03-01"}).json()
    booking = store.list_bookings()[0]
    split = client.put(f"/api/v1/bookings/{booking.id}/allocations", json=[
        {"contract_id": yilmaz["Whg 1.OG"]["id"], "amount": 1000}, {"contract_id": contract["id"], "amount": 570}])
    assert split.status_code == 200, split.text
    account = client.post("/api/v1/accounts", json={"portfolio_id": south["id"], "name": "Südkonto", "account_type": "bank"}).json()
    foreign = client.post("/api/v1/bookings", json={"account_id": account["id"], "tenant_id": yilmaz["tenant"]["id"],
        "booking_date": "2025-09-03", "amount": 999}).json()
    staff = auth.register_user("review-scoped", "review-scoped@example.test", "Scoped reader", "Synthetic123!", "readonly",
                               portfolio_access="selected", portfolio_ids=[north_id])
    user = auth.get_user_by_id(staff.id)
    assert user is not None
    with scope_context(scope_from_user(user)):
        bookings = store.list_bookings()
        assert foreign["id"] not in {row.id for row in bookings}
        assert len(store.list_payment_allocations(booking_id=booking.id)) == 1
        actual = accounted_by_booking(store, bookings)
        assert {key: value for key, value in actual.items() if value} == canonical(bookings)
        assert actual[booking.id] == Decimal("1570")
        assert foreign["id"] not in actual


@pytest.mark.skipif(not hasattr(store, "db"), reason="SQL identity-map values before an explicit flush")
def test_pending_allocation_edits_use_the_canonical_path_without_flushing(client, yilmaz):  # noqa: F811
    from backend.db.orm_models import PaymentAllocationORM

    booking = store.list_bookings()[0]
    allocation = store.list_payment_allocations(booking_id=booking.id)[0]
    row = store.db.get(PaymentAllocationORM, allocation.id)
    assert row is not None
    try:
        row.amount = 101.23
        with store.db.no_autoflush:
            bookings = store.list_bookings()
            expected = canonical(bookings)
            assert accounted_by_booking(store, bookings) == expected
            assert row in store.db.dirty, "A read helper must not flush caller-owned changes"
    finally:
        store.db.rollback()


@pytest.mark.skipif(not hasattr(store, "db"), reason="Legacy fractional-cent values in a SQLite numeric column")
@pytest.mark.parametrize("legacy_amount,expected_sum", [(.005, ".02"), (1.005, "2.02"), (1.004999999, "2.00")])
def test_sql_review_rounds_each_legacy_allocation_before_summing(client, yilmaz, legacy_amount, expected_sum):  # noqa: F811
    from sqlalchemy import update

    from backend.db.orm_models import PaymentAllocationORM

    if store.db.get_bind().dialect.name != "sqlite":
        pytest.skip("PostgreSQL rounds stored Numeric(12,2) values itself")
    booking = store.list_bookings()[0]
    store.db.execute(update(PaymentAllocationORM).where(PaymentAllocationORM.booking_id == booking.id).values(amount=legacy_amount))
    store.db.commit()
    bookings = store.list_bookings()
    expected = canonical(bookings)
    assert expected[booking.id] == Decimal(expected_sum)
    assert accounted_by_booking(store, bookings) == expected
