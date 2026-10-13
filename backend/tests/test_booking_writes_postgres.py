"""Real PostgreSQL transactions serialize reversals and fence the current actor."""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event
from typing import cast

import pytest
from fastapi import HTTPException
from sqlalchemy import event, update
from sqlalchemy.orm import Session, scoped_session, sessionmaker
from test_booking_writes import payload, snapshot
from test_document_versions_postgres import postgres  # noqa: F401
from test_rent_payments import seed

from backend import auth
from backend.db.orm_models import AccountORM
from backend.models import ContractCreate, PortfolioCreate, UnitCreate
from backend.repositories import SQLAlchemyStore
from backend.routers import bookings
from backend.services import booking_writes
from backend.services.portfolio_scope import scope_context, scope_from_user


@pytest.fixture
def estate(postgres, monkeypatch):  # noqa: F811
    engine, _ = postgres
    sessions = scoped_session(sessionmaker(engine))
    target = SQLAlchemyStore(cast(Session, sessions))
    data = seed(target)
    actor = auth.register_user("writer", "writer@test.invalid", "Writer", "Secret123", "buchhaltung",
                               portfolio_access="selected", portfolio_ids=[data["portfolio"].id])
    user = auth.get_user_by_id(actor.id)
    assert user is not None
    scope = scope_from_user(user)
    monkeypatch.setattr(bookings, "store", target)
    yield target, data, engine, scope
    sessions.remove()


def test_postgres_allocation_failure_and_success_commit_count(estate, monkeypatch):
    target, data, engine, scope = estate
    real_allocate = bookings.auto_allocate
    commits = []
    event.listen(engine, "commit", lambda _: commits.append(1))

    def fail(writer, booking):
        real_allocate(writer, booking)
        raise RuntimeError("allocation failed")

    monkeypatch.setattr(bookings, "auto_allocate", fail)
    with scope_context(scope), pytest.raises(RuntimeError, match="allocation failed"):
        bookings.create_booking(payload(data))
    assert snapshot(target) == ([], []) and commits == []
    monkeypatch.setattr(bookings, "auto_allocate", real_allocate)
    with scope_context(scope):
        bookings.create_booking(payload(data))
    assert len(commits) == 1
    assert len(target.list_bookings()) == len(target.list_payment_allocations()) == 1


@pytest.mark.parametrize("direct", [False, True])
def test_postgres_competing_reversals_hold_original_until_commit(estate, direct):
    target, data, _, scope = estate
    with scope_context(scope):
        original = bookings.create_booking(payload(data))
    gate = Barrier(2)

    def reverse(_):
        gate.wait(timeout=10)
        try:
            with scope_context(scope):
                if direct:
                    return bookings.create_booking(payload(data).model_copy(update={
                        "amount": -70, "reverses_booking_id": original.id})).amount
                return bookings.reverse_booking(original.id).amount
        except HTTPException as error:
            return error.status_code
        finally:
            target.db.remove()

    with ThreadPoolExecutor(2) as workers:
        outcomes = list(workers.map(reverse, range(2)))
    assert sorted(outcomes) == [-70 if direct else -100, 400]
    assert len(target.list_bookings()) == len(target.list_payment_allocations()) == 2
    assert sum(row.amount for row in target.list_bookings()) == (30 if direct else 0)


def test_postgres_actor_revocation_waits_for_complete_booking_unit(estate, monkeypatch):
    target, data, _, scope = estate
    allocated, release, revoking, revoked = Event(), Event(), Event(), Event()
    real_allocate = bookings.auto_allocate

    def pause(writer, booking):
        real_allocate(writer, booking)
        allocated.set()
        assert release.wait(timeout=10)

    monkeypatch.setattr(bookings, "auto_allocate", pause)

    def pay():
        try:
            with scope_context(scope):
                return bookings.create_booking(payload(data))
        finally:
            target.db.remove()

    def revoke():
        revoking.set()
        auth.update_user(scope.user_id, {"is_active": False})
        revoked.set()

    with ThreadPoolExecutor(2) as workers:
        paid = workers.submit(pay)
        assert allocated.wait(timeout=10)
        withdrawal = workers.submit(revoke)
        assert revoking.wait(timeout=10)
        try:
            assert not revoked.wait(timeout=0.2)
        finally:
            release.set()
        paid.result(timeout=10)
        withdrawal.result(timeout=10)
    assert revoked.is_set()
    assert len(target.list_bookings()) == len(target.list_payment_allocations()) == 1
    with scope_context(scope), pytest.raises(HTTPException) as error:
        bookings.create_booking(payload(data))
    assert error.value.status_code == 401
    assert len(target.list_bookings()) == 1


def test_postgres_owner_parent_move_waits_for_booking_and_allocation_commit(estate, monkeypatch):
    target, data, engine, scope = estate
    south = target.create_portfolio(PortfolioCreate(name="Foreign portfolio"))
    allocated, release, moving, moved = Event(), Event(), Event(), Event()
    real_allocate = bookings.auto_allocate

    def pause(writer, booking):
        real_allocate(writer, booking)
        allocated.set()
        assert release.wait(timeout=10)

    monkeypatch.setattr(bookings, "auto_allocate", pause)

    def pay():
        try:
            with scope_context(scope):
                return bookings.create_booking(payload(data))
        finally:
            target.db.remove()

    def owner_move():
        moving.set()
        with engine.begin() as connection:
            connection.execute(update(AccountORM).where(AccountORM.id == data["account"].id)
                               .values(portfolio_id=south.id))
        moved.set()

    with ThreadPoolExecutor(2) as workers:
        paid = workers.submit(pay)
        assert allocated.wait(timeout=10)
        relocation = workers.submit(owner_move)
        assert moving.wait(timeout=10)
        try:
            assert not moved.wait(timeout=0.2)
        finally:
            release.set()
        paid.result(timeout=10)
        relocation.result(timeout=10)
    assert moved.is_set()
    assert len(target.list_bookings()) == len(target.list_payment_allocations()) == 1


def test_postgres_new_contract_cannot_enter_unlocked_candidate_set(estate, monkeypatch):
    target, data, _, scope = estate
    extra = target.create_unit(UnitCreate(property_id=data["prop"].id, label="Garage", unit_type="garage", cold_rent=100))
    locked, release, inserting, inserted = Event(), Event(), Event(), Event()
    real_lock = booking_writes._lock_parents

    def pause(*args):
        real_lock(*args)
        locked.set()
        assert release.wait(timeout=10)

    monkeypatch.setattr(booking_writes, "_lock_parents", pause)

    def pay():
        try:
            with scope_context(scope):
                return bookings.create_booking(payload(data))
        finally:
            target.db.remove()

    def add_contract():
        inserting.set()
        try:
            target.create_contract(ContractCreate(contract_number="NEW", property_id=data["prop"].id,
                                                   unit_id=extra.id, tenant_id=data["tenant"].id,
                                                   start_date=data["contract"].start_date, status="active"))
            inserted.set()
        finally:
            target.db.remove()

    with ThreadPoolExecutor(2) as workers:
        paid = workers.submit(pay)
        assert locked.wait(timeout=10)
        contract = workers.submit(add_contract)
        assert inserting.wait(timeout=10)
        try:
            assert not inserted.wait(timeout=0.2)
        finally:
            release.set()
        paid.result(timeout=10)
        contract.result(timeout=10)
    assert inserted.is_set()
    assert {row.contract_id for row in target.list_payment_allocations()} == {data["contract"].id}
