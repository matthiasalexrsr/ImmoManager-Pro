"""Booking cash, derived allocations and reversal limits share one write unit."""

from concurrent.futures import ThreadPoolExecutor
from datetime import date
from threading import Barrier
from typing import Any, cast

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, scoped_session, sessionmaker
from test_rent_payments import seed

from backend import auth
from backend.models import BookingCreate, BookingPatch
from backend.repositories import SQLAlchemyStore
from backend.routers import bookings
from backend.services.portfolio_scope import scope_context, scope_from_user
from backend.storage import InMemoryStore


@pytest.fixture(params=["memory", "sqlite"])
def estate(request, tmp_path, monkeypatch):
    monkeypatch.setattr(auth, "_user_store", auth.InMemoryUserStore())
    engine = None
    target: Any
    if request.param == "memory":
        target = InMemoryStore()
    else:
        from backend.db.orm_models import Base

        engine = create_engine(f"sqlite:///{(tmp_path / 'bookings.db').as_posix()}")

        @event.listens_for(engine, "connect")
        def settings(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("PRAGMA journal_mode=WAL")

        Base.metadata.create_all(engine)
        target = SQLAlchemyStore(cast(Session, scoped_session(sessionmaker(engine))))
    data = seed(target)
    monkeypatch.setattr(bookings, "store", target)
    yield target, data, engine
    if engine is not None:
        target.db.remove()
        engine.dispose()


def payload(data, **changes):
    return BookingCreate(account_id=data["account"].id, tenant_id=data["tenant"].id,
                         booking_date=date(2026, 1, 7), amount=100, **changes)


def snapshot(target):
    return ([row.model_dump() for row in target.list_bookings()],
            sorted((row.model_dump() for row in target.list_payment_allocations()), key=lambda row: row["id"]))


@pytest.mark.parametrize("operation", ["create", "reverse", "put", "patch"])
def test_allocation_failure_restores_cash_and_allocations(estate, monkeypatch, operation):
    target, data, engine = estate
    original = bookings.create_booking(payload(data)) if operation != "create" else None
    before = snapshot(target)
    commits = []
    if engine is not None:
        event.listen(engine, "commit", lambda _: commits.append(1))
    real_allocate = bookings.auto_allocate

    def fail_after_allocation(writer, booking):
        real_allocate(writer, booking)
        raise RuntimeError("allocation failed after writing")

    monkeypatch.setattr(bookings, "auto_allocate", fail_after_allocation)
    with pytest.raises(RuntimeError, match="allocation failed"):
        if operation == "create":
            bookings.create_booking(payload(data))
        else:
            assert original is not None
            if operation == "reverse":
                bookings.reverse_booking(original.id)
            elif operation == "put":
                bookings.update_booking(original.id, payload(data, payment_text="edited"))
            else:
                bookings.patch_booking(original.id, BookingPatch(payment_text="edited"))
    assert snapshot(target) == before
    assert commits == []


def test_all_four_mutations_have_one_sql_commit_including_allocation(estate):
    target, data, engine = estate
    commits = []
    if engine is not None:
        event.listen(engine, "commit", lambda _: commits.append(1))
    original = bookings.create_booking(payload(data))
    bookings.update_booking(original.id, payload(data, payment_text="put"))
    bookings.patch_booking(original.id, BookingPatch(payment_text="patch"))
    reversal = bookings.reverse_booking(original.id)
    assert len(target.list_bookings()) == len(target.list_payment_allocations()) == 2
    assert sum(row.amount for row in target.list_payment_allocations()) == 0
    assert reversal.amount == -100
    if engine is not None:
        assert len(commits) == 4


def test_failure_while_reallocating_reversals_restores_every_allocation(estate, monkeypatch):
    target, data, _ = estate
    original = bookings.create_booking(payload(data))
    bookings.reverse_booking(original.id)
    before = snapshot(target)
    real_reallocate = bookings.reallocate_reversals

    def fail_after_reversals(writer, booking):
        real_reallocate(writer, booking)
        raise RuntimeError("reversal allocation failed")

    monkeypatch.setattr(bookings, "reallocate_reversals", fail_after_reversals)
    with pytest.raises(RuntimeError, match="reversal allocation failed"):
        bookings.patch_booking(original.id, BookingPatch(payment_text="edited"))
    assert snapshot(target) == before


def test_concurrent_full_reversals_cannot_exceed_original(estate):
    target, data, _ = estate
    original = bookings.create_booking(payload(data))
    gate = Barrier(2)

    def reverse(_):
        gate.wait(timeout=10)
        try:
            return bookings.reverse_booking(original.id).amount
        except HTTPException as error:
            return error.status_code

    with ThreadPoolExecutor(2) as workers:
        outcomes = list(workers.map(reverse, range(2)))
    assert sorted(outcomes) == [-100, 400]
    assert len(target.list_bookings()) == len(target.list_payment_allocations()) == 2
    assert sum(row.amount for row in target.list_bookings()) == 0


@pytest.mark.parametrize("change", [{"is_active": False}, {"role": "readonly"},
                                    {"portfolio_access": "selected", "portfolio_ids": []}])
def test_actor_change_before_publication_rolls_back_everything(estate, monkeypatch, change):
    target, data, _ = estate
    actor = auth.register_user("writer", "writer@test.invalid", "Writer", "Secret123", "buchhaltung")
    user = auth.get_user_by_id(actor.id)
    assert user is not None
    captured = scope_from_user(user)
    real_allocate = bookings.auto_allocate

    def change_actor(writer, booking):
        real_allocate(writer, booking)
        auth.update_user(actor.id, change)

    monkeypatch.setattr(bookings, "auto_allocate", change_actor)
    with scope_context(captured), pytest.raises(HTTPException) as error:
        bookings.create_booking(payload(data))
    assert error.value.status_code in (401, 403)
    assert snapshot(target) == ([], [])


def test_hidden_parent_is_rejected_without_writing(estate):
    target, data, _ = estate
    actor = auth.register_user("writer", "writer@test.invalid", "Writer", "Secret123", "buchhaltung",
                               portfolio_access="selected", portfolio_ids=[])
    user = auth.get_user_by_id(actor.id)
    assert user is not None
    with scope_context(scope_from_user(user)), pytest.raises(HTTPException):
        bookings.create_booking(payload(data))
    assert snapshot(target) == ([], [])


@pytest.mark.parametrize("operation", ["put", "patch", "reverse"])
def test_selected_actor_cannot_mutate_known_hidden_booking(estate, operation):
    target, data, _ = estate
    hidden = seed(target, number="MV-hidden")
    original = bookings.create_booking(payload(hidden))
    before = snapshot(target)
    actor = auth.register_user("writer", "writer@test.invalid", "Writer", "Secret123", "buchhaltung",
                               portfolio_access="selected", portfolio_ids=[data["portfolio"].id])
    user = auth.get_user_by_id(actor.id)
    assert user is not None
    with scope_context(scope_from_user(user)), pytest.raises(HTTPException) as error:
        if operation == "put":
            bookings.update_booking(original.id, payload(data))
        elif operation == "patch":
            bookings.patch_booking(original.id, BookingPatch(payment_text="hidden edit"))
        else:
            bookings.reverse_booking(original.id)
    assert error.value.status_code == 404
    assert snapshot(target) == before


def test_selected_actor_visible_write_and_allocation_rollback_keep_hidden_rows(estate, monkeypatch):
    target, data, _ = estate
    hidden = seed(target, number="MV-hidden")
    bookings.create_booking(payload(hidden))
    actor = auth.register_user("writer", "writer@test.invalid", "Writer", "Secret123", "buchhaltung",
                               portfolio_access="selected", portfolio_ids=[data["portfolio"].id])
    user = auth.get_user_by_id(actor.id)
    assert user is not None
    scope = scope_from_user(user)
    with scope_context(scope):
        visible = bookings.create_booking(payload(data))
        assert len(target.list_bookings()) == len(target.list_payment_allocations()) == 1
    before = snapshot(target)
    real_allocate = bookings.auto_allocate

    def fail(writer, booking):
        real_allocate(writer, booking)
        raise RuntimeError("allocation failed")

    monkeypatch.setattr(bookings, "auto_allocate", fail)
    with scope_context(scope), pytest.raises(RuntimeError, match="allocation failed"):
        bookings.patch_booking(visible.id, BookingPatch(payment_text="edited"))
    assert snapshot(target) == before


def test_memory_unit_journals_changed_keys_without_copying_history(monkeypatch):
    from backend.services.booking_writes import booking_write

    class History(dict):
        def __iter__(self):
            raise AssertionError("must not enumerate historical bookings")

        def __deepcopy__(self, memo):
            raise AssertionError("must not copy historical bookings")

    target = InMemoryStore()
    raw = object.__getattribute__(target, "__dict__")
    old = object()
    raw["bookings"] = History({"old": old})
    raw["_resource_grants"] = {("contacts", "old-contact", "p")}
    with pytest.raises(RuntimeError):
        with booking_write(target):
            raw["bookings"]["new"] = object()
            raw["_resource_grants"].update({("bookings", "new", "p")})
            assert len(raw["bookings"].before) == 1
            raise RuntimeError("undo")
    assert raw["bookings"] == {"old": old}
    assert raw["_resource_grants"] == {("contacts", "old-contact", "p")}


@pytest.mark.parametrize("fail", [False, True])
def test_sql_unit_preserves_unrelated_pending_caller_edits(estate, monkeypatch, fail):
    from backend.db.orm_models import TenantORM

    target, data, engine = estate
    if engine is None:
        pytest.skip("SQL caller identity-map contract")
    tenant = target.db.get(TenantORM, data["tenant"].id)
    tenant.full_name = "Pending caller edit"
    if fail:
        def broken_allocation(*_):
            raise RuntimeError("allocation failed")

        monkeypatch.setattr(bookings, "auto_allocate", broken_allocation)
        with pytest.raises(RuntimeError, match="allocation failed"):
            bookings.create_booking(payload(data))
    else:
        bookings.create_booking(payload(data))
    assert tenant.full_name == "Pending caller edit" and tenant in target.db.dirty
    with Session(engine) as check:
        persisted = check.get(TenantORM, tenant.id)
        assert persisted is not None and persisted.full_name != tenant.full_name
    target.db.rollback()


def test_existing_sqlite_write_transaction_is_refused_without_touching_caller(estate):
    from backend.db.orm_models import TenantORM

    target, data, engine = estate
    if engine is None:
        pytest.skip("SQL caller transaction contract")
    tenant = target.db.get(TenantORM, data["tenant"].id)
    tenant.full_name = "Flushed caller edit"
    target.db.flush()
    with pytest.raises(RuntimeError, match="eigene Transaktion"):
        bookings.create_booking(payload(data))
    assert tenant.full_name == "Flushed caller edit"
    assert target.db.connection().connection.driver_connection.in_transaction
    target.db.rollback()
    assert snapshot(target) == ([], [])


def test_successful_nested_unit_depends_on_outer_commit(estate):
    from backend.services.booking_writes import booking_write

    target, data, _ = estate
    with pytest.raises(RuntimeError, match="outer failed"):
        with booking_write(target) as outer:
            with booking_write(outer, changes=payload(data).model_dump()) as inner:
                booking = inner.create_booking(payload(data))
                bookings.auto_allocate(inner, booking)
            raise RuntimeError("outer failed")
    assert snapshot(target) == ([], [])


def test_caught_nested_failure_rolls_back_only_inner_savepoint(estate):
    from backend.services.booking_writes import booking_write

    target, data, engine = estate
    commits = []
    if engine is not None:
        event.listen(engine, "commit", lambda _: commits.append(1))
    with booking_write(target, changes=payload(data).model_dump()) as outer:
        kept = outer.create_booking(payload(data))
        bookings.auto_allocate(outer, kept)
        with pytest.raises(RuntimeError, match="inner failed"):
            with booking_write(outer, changes=payload(data).model_dump()) as inner:
                discarded = inner.create_booking(payload(data))
                bookings.auto_allocate(inner, discarded)
                raise RuntimeError("inner failed")
    assert [row.id for row in target.list_bookings()] == [kept.id]
    assert len(target.list_payment_allocations()) == 1
    if engine is not None:
        assert len(commits) == 1
