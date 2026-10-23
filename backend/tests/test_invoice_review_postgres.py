"""Invoice review on a real PostgreSQL server: migration with guarded downgrade, immutable history,
the review flow in exact cents, concurrent decisions and transfers, portfolio boundary.

Opt in with IMMO_TEST_POSTGRES_ADMIN_URL (see test_document_versions_postgres.py).
"""

import threading
from datetime import date

import pytest
import sqlalchemy as sa
from alembic import command
from fastapi import HTTPException
from sqlalchemy.orm import Session
from test_document_versions_postgres import postgres  # noqa: F401  (fixture: own database per test)

from backend import auth
from backend.invoice_review_models import (
    CheckRequest,
    CostTransferRequest,
    DecisionRequest,
    ReceiptPatch,
    ReceiptRequest,
)
from backend.models import (
    AccountCreate,
    AllocationKeyCreate,
    BillingPeriodCreate,
    BookingCreate,
    InvoiceCreate,
    PortfolioCreate,
    PropertyCreate,
)
from backend.repositories import SQLAlchemyStore
from backend.services import invoice_review as service
from backend.services import maintenance_projects as projects
from backend.services.portfolio_scope import scope_context, scope_from_user
from backend.storage import NotFoundError

PREVIOUS = "5e8b2d4f7a19"
COMPLETE: dict[str, bool | None] = {key: True for key in ("supplier_name_address", "recipient_name_address", "tax_number", "description",
                                  "service_date")}


def _store(engine):
    return SQLAlchemyStore(Session(engine))


def _seed(engine) -> dict:
    seed = _store(engine)
    north = seed.create_portfolio(PortfolioCreate(name="Nord"))
    south = seed.create_portfolio(PortfolioCreate(name="Süd"))
    house_n = seed.create_property(PropertyCreate(portfolio_id=north.id, name="Nordhaus", property_type="residential"))
    house_s = seed.create_property(PropertyCreate(portfolio_id=south.id, name="Südhaus", property_type="residential"))
    account = seed.create_account(AccountCreate(portfolio_id=north.id, name="Konto", account_type="bank"))
    seed.db.close()
    owner = auth.register_user("owner", "owner@example.com", "Owner", "Secret123", "eigentuemer")
    return {"north": north, "south": south, "house_n": house_n, "house_s": house_s, "account": account,
            "owner": owner}


def _invoice(engine, house, number="RE-1", gross=1190.0, net=1000.0):
    target = _store(engine)
    invoice = target.create_invoice(InvoiceCreate.model_validate({    # invoice_number: a UI contract field
        "property_id": house.id, "supplier": "Dach Müller GmbH", "invoice_date": date(2026, 5, 1), "net_amount": net,
        "vat_amount": round(gross - net, 2), "gross_amount": gross, "invoice_number": number}))
    target.db.close()
    return invoice


def _approved(engine, seeded, invoice, **receipt):
    actor = seeded["owner"].id
    target = _store(engine)
    service.start_review(target, invoice.id, ReceiptRequest(**receipt), actor)
    service.factual_check(target, invoice.id, CheckRequest(result="confirmed"), actor)
    service.arithmetic_check(target, invoice.id, CheckRequest(result="confirmed", checklist=COMPLETE), actor)
    service.decide(target, invoice.id, DecisionRequest(decision="approve"), actor)
    target.db.close()


def test_invoice_review_migration_and_history_guard_on_postgres(postgres):  # noqa: F811
    engine, config = postgres
    seeded = _seed(engine)
    inspector = sa.inspect(engine)
    keys = {(k["constrained_columns"][0], k["referred_table"], k["options"].get("ondelete"))
            for table in ("invoice_reviews", "invoice_review_events", "invoice_cost_transfers")
            for k in inspector.get_foreign_keys(table)}
    assert {("invoice_id", "invoices", "RESTRICT"), ("document_id", "documents", "SET NULL"),
            ("cost_item_id", "cost_items", "CASCADE"), ("change_order_id", "maintenance_change_orders",
                                                         "SET NULL")} <= keys
    invoice = _invoice(engine, seeded["house_n"])
    _approved(engine, seeded, invoice)
    with engine.begin() as connection:
        assert connection.execute(sa.text("SELECT COUNT(*) FROM invoice_review_events")).scalar() == 4
    with pytest.raises(sa.exc.DBAPIError, match="immutable"):
        with engine.begin() as connection:
            connection.execute(sa.text("UPDATE invoice_review_events SET reason = 'geändert'"))
    with pytest.raises(sa.exc.IntegrityError):            # RESTRICT: the invoice keeps its evidence
        with engine.begin() as connection:
            connection.execute(sa.text("DELETE FROM invoices WHERE id = :id"), {"id": invoice.id})
    with engine.begin() as connection:
        before = connection.execute(sa.text("SELECT version_num FROM alembic_version")).scalar()
    with pytest.raises(RuntimeError, match="invoice reviews"):
        command.downgrade(config, PREVIOUS)
    with engine.begin() as connection:     # refused in one transaction: the revision stays as it was
        assert connection.execute(sa.text("SELECT version_num FROM alembic_version")).scalar() == before
        connection.execute(sa.text("DELETE FROM invoice_review_events"))
        connection.execute(sa.text("DELETE FROM invoice_reviews"))
    command.downgrade(config, PREVIOUS)
    names = set(sa.inspect(engine).get_table_names())
    assert "invoice_reviews" not in names and "invoices" in names
    with engine.begin() as connection:
        assert connection.execute(sa.text("SELECT COUNT(*) FROM invoices")).scalar() == 1
    command.upgrade(config, "head")
    assert "invoice_review_events" in sa.inspect(engine).get_table_names()
    with pytest.raises(sa.exc.DBAPIError, match="immutable"):
        with engine.begin() as connection:
            connection.execute(sa.text(
                "INSERT INTO invoice_review_events (id, invoice_id, seq, action, details, created_at) "
                "VALUES ('e', :id, 1, 'received', '{}', now())"), {"id": invoice.id})
            connection.execute(sa.text("UPDATE invoice_review_events SET action = 'x'"))


def test_review_flow_in_cents_with_skonto_and_project_figures_on_postgres(postgres):  # noqa: F811
    engine, _ = postgres
    seeded = _seed(engine)
    invoice = _invoice(engine, seeded["house_n"], gross=1190.0, net=1000.0)
    _approved(engine, seeded, invoice, skonto_percent=2.0, skonto_days=10)
    target = _store(engine)
    booking = target.create_booking(BookingCreate(account_id=seeded["account"].id, property_id=seeded["house_n"].id,
                                                  booking_date=date(2026, 5, 9), amount=-1166.2))
    from backend.maintenance_models import InvoicePaymentCreate

    projects.add_invoice_payment(target, invoice.id, InvoicePaymentCreate(booking_id=booking.id, amount=1166.2),
                                 seeded["owner"].id)
    view = service.review_view(target, invoice.id, {"role": "eigentuemer"}, today=date(2026, 6, 1))
    assert view["settlement"]["payment_status"] == "paid"
    assert (view["settlement"]["skonto_taken"], view["settlement"]["flow_amount"]) == (23.8, 1166.2)
    assert service.inbox(target, skonto=True, today=date(2026, 5, 10))["total"] == 0
    assert [e["action"] for e in view["history"]] == ["received", "factual_check", "arithmetic_check", "approved"]
    target.db.close()


def test_concurrent_decisions_and_transfers_happen_once_on_postgres(postgres):  # noqa: F811
    engine, _ = postgres
    seeded = _seed(engine)
    invoice = _invoice(engine, seeded["house_n"])
    actor = seeded["owner"].id
    setup = _store(engine)
    service.start_review(setup, invoice.id, ReceiptRequest(recoverable=True, property_id=seeded["house_n"].id),
                         actor)
    service.factual_check(setup, invoice.id, CheckRequest(result="confirmed"), actor)
    service.arithmetic_check(setup, invoice.id, CheckRequest(result="confirmed", checklist=COMPLETE), actor)
    period = setup.create_billing_period(BillingPeriodCreate(property_id=seeded["house_n"].id, label="BK 2026",
                                                             start_date=date(2026, 1, 1), end_date=date(2026, 12, 31)))
    key = setup.create_allocation_key(AllocationKeyCreate(property_id=seeded["house_n"].id, name="Fläche",
                                                          key_type="area_sqm"))
    setup.db.close()

    def race(operation) -> list:
        results: list = []
        barrier = threading.Barrier(4)

        def run():
            target = _store(engine)
            barrier.wait()
            try:
                operation(target)
                results.append("ok")
            except HTTPException as error:
                results.append(error.status_code)
            finally:
                target.db.close()

        threads = [threading.Thread(target=run) for _ in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        return results

    decided = race(lambda t: service.decide(t, invoice.id, DecisionRequest(decision="approve"), actor))
    assert sorted(decided, key=str) == [409, 409, 409, "ok"]
    transferred = race(lambda t: service.transfer_cost(
        t, invoice.id, CostTransferRequest(billing_period_id=period.id, allocation_key_id=key.id), actor))
    assert sorted(transferred, key=str) == [409, 409, 409, "ok"]
    with engine.begin() as connection:
        assert connection.execute(sa.text("SELECT COUNT(*) FROM cost_items")).scalar() == 1
        seqs = [row[0] for row in connection.execute(sa.text(
            "SELECT seq FROM invoice_review_events WHERE invoice_id = :id ORDER BY seq"), {"id": invoice.id})]
    assert seqs == [1, 2, 3, 4, 5]


def test_portfolio_boundary_of_reviews_on_postgres(postgres):  # noqa: F811
    engine, _ = postgres
    seeded = _seed(engine)
    mine = _invoice(engine, seeded["house_n"], number="N-1")
    foreign = _invoice(engine, seeded["house_s"], number="S-1")
    _approved(engine, seeded, foreign)
    user = auth.register_user("nora", "nora@example.com", "Nora", "Secret123", "verwalter",
                              portfolio_access="selected", portfolio_ids=[seeded["north"].id])
    stored = auth.get_user_by_id(user.id)
    assert stored is not None
    staff = _store(engine)
    with scope_context(scope_from_user(stored)):
        page = service.inbox(staff)
        assert (page["total"], [row["invoice_id"] for row in page["items"]]) == (1, [mine.id])
        with pytest.raises(NotFoundError):
            service.review_view(staff, foreign.id, {"role": "verwalter"})
        with pytest.raises(NotFoundError):
            service.decide(staff, foreign.id, DecisionRequest(decision="reject", reason="x"), user.id)
        assert service.payment_proposals(staff)["total"] == 0
        service.start_review(staff, mine.id, ReceiptRequest(), user.id)
        with pytest.raises((HTTPException, NotFoundError)):
            service.patch_review(staff, mine.id, ReceiptPatch(property_id=seeded["house_s"].id), user.id)
    staff.db.close()
    check = _store(engine)
    assert service.review_view(check, mine.id, None)["review"]["property_id"] is None
    check.db.close()
