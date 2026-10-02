"""Genuine PostgreSQL gates use a dedicated UUID schema, never a SQLite fallback."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from threading import Barrier
from uuid import uuid4

from sqlalchemy import select, update

from backend.db.orm_models import PaymentORM
from backend.repositories.sql_store import SQLAlchemyStore
from backend.services.bank_matching import MatchConfirm, SuggestionQuery, confirm_match, suggestions
from backend.services.payment_history import PaymentHistoryQuery, payment_history
from backend.services.payments import PaymentCreate
from backend.tests.test_bank_matching import command, setup
from backend.tests.test_private_server_concurrency import postgres_database  # noqa: F401


def test_pg_invoice_preview_and_parallel_confirmation_share_one_receipt(postgres_database):  # noqa: F811
    _, factory, _, _ = postgres_database
    with factory() as session:
        store = SQLAlchemyStore(session)
        _, booking = setup(store, "invoice", amount="-100.30", text="INV-AX")
        page = suggestions(store, booking.id, SuggestionQuery(kind="invoice", page_size=1))
        assert page["items"][0]["reasons"] == ["reference", "amount_exact", "same_portfolio"]
        request = command(page, amount="100.30")
    barrier = Barrier(2)
    def confirm():
        with factory() as session:
            barrier.wait(timeout=15)
            return confirm_match(SQLAlchemyStore(session), booking.id, request).id
    with ThreadPoolExecutor(max_workers=2) as pool:
        ids = list(pool.map(lambda _: confirm(), range(2)))
    assert ids[0] == ids[1]
    with factory() as session:
        assert len(session.scalars(select(PaymentORM)).all()) == 1


def test_pg_rental_date_keyset_is_deterministic(postgres_database):  # noqa: F811
    _, factory, _, _ = postgres_database
    with factory() as session:
        store = SQLAlchemyStore(session)
        target, booking = setup(store)
        from backend.models import RentChargeCreate
        other = store.create_rent_charge(RentChargeCreate(contract_id=target.contract_id, month="2027-01", cold_rent=100.30))
        first = suggestions(store, booking.id, SuggestionQuery(page_size=1))
        second = suggestions(store, booking.id, SuggestionQuery(page_size=1, cursor=first["next_cursor"]))
        assert [first["items"][0]["id"], second["items"][0]["id"]] == [target.id, other.id]
        assert not second["has_more"]
        assert isinstance(MatchConfirm.model_validate(command(first).model_dump()), MatchConfirm)


def test_pg_receipt_history_keeps_all_identical_timestamp_ties(postgres_database):  # noqa: F811
    _, factory, _, _ = postgres_database
    with factory() as session:
        store = SQLAlchemyStore(session)
        target, booking = setup(store)
        receipts = [store.record_payment("rent_charge", target.id, PaymentCreate(idempotency_key=str(uuid4()),
            booking_id=booking.id, payment_date=booking.booking_date, amount="1.01")) for _ in range(5)]
        session.execute(update(PaymentORM).values(created_at=datetime(2026, 9, 5, 12)))
        session.commit()
        page = payment_history(store, "booking", booking.id, PaymentHistoryQuery(page_size=2))
        seen = list(page["items"])
        while page["has_more"]:
            page = payment_history(store, "booking", booking.id, PaymentHistoryQuery(page_size=2, cursor=page["next_cursor"]))
            seen.extend(page["items"])
        assert [item.id for item in seen] == sorted(item.id for item in receipts)
