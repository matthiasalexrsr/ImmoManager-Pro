"""The receipt command is atomic across independent PostgreSQL connections."""

import threading

from sqlalchemy.orm import Session
from test_document_versions_postgres import postgres  # noqa: F401
from test_rent_payments import payment, seed, user

from backend.repositories import SQLAlchemyStore
from backend.services import rent_payments


def test_concurrent_receipt_retries_commit_one_booking_and_allocation(postgres):  # noqa: F811
    engine, _ = postgres
    with Session(engine) as db:
        estate = seed(SQLAlchemyStore(db))
    actor, _ = user()
    request = rent_payments.ContractPaymentRequest.model_validate(payment(estate))
    gate = threading.Barrier(3)
    results = []

    def pay():
        with Session(engine) as db:
            try:
                gate.wait(timeout=10)
                results.append(rent_payments.record_payment(SQLAlchemyStore(db), request, actor.id))
            except BaseException as error:
                results.append(error)

    threads = [threading.Thread(target=pay) for _ in range(3)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)
        assert not thread.is_alive()
    assert all(isinstance(result, dict) for result in results), results
    assert sorted(result["replayed"] for result in results) == [False, True, True]
    with Session(engine) as db:
        target = SQLAlchemyStore(db)
        assert len(target.list_bookings()) == len(target.list_payment_allocations()) == 1
