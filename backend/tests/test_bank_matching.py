"""Real bounded suggestions, central receipts, stale review and exact bank budgets."""
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from decimal import Decimal
from threading import Barrier
from uuid import uuid4

import pytest
from sqlalchemy import event, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.db.orm_models import PaymentORM
from backend.models import AccountCreate, BookingCreate, InvoiceCreate, InvoicePatch, RentChargeCreate
from backend.repositories.sql_store import SQLAlchemyStore
from backend.services.bank_matching import MatchConfirm, MatchError, SuggestionQuery, confirm_match, suggestions
from backend.services.data_transfer import export_store_data, import_store_data
from backend.services.invoice_payment_schema import ensure_invoice_payment_immutability
from backend.services.payments import PaymentCreate, PaymentReversalCreate
from backend.storage import ValidationError
from backend.tests.test_bank_payments import active_store  # noqa: F401
from backend.tests.test_payments import seed


def setup(store, kind="rent_charge", *, amount="100.30", text="P-1"):
    charge = seed(store, "rent_charge")
    contract = store.get_contract(charge.contract_id)
    prop = store.get_property(contract.property_id)
    account = store.create_account(AccountCreate(portfolio_id=prop.portfolio_id, name="Bank", account_type="bank"))
    target = charge if kind == "rent_charge" else store.create_invoice(InvoiceCreate(property_id=prop.id,
        supplier="Synthetic supplier", invoice_number="INV-AX", invoice_date=date(2026, 9, 1),
        net_amount=100.30, gross_amount=100.30, vat_rate=0))
    booking = store.create_booking(BookingCreate(account_id=account.id, booking_date=date(2026, 9, 5),
        amount=float(amount), payment_text=text))
    return target, booking


def command(page, *, amount="40.10", key=None):
    return MatchConfirm(review_token=page["items"][0]["review_token"], amount=amount,
        idempotency_key=key or str(uuid4()), note="Explicit manual review")


@pytest.mark.parametrize("kind", ["rent_charge", "invoice"])
def test_suggestions_create_nothing_and_explicit_partial_payment_replay_reversal_are_central(active_store, kind):  # noqa: F811
    target, booking = setup(active_store, kind, amount="-100.30" if kind == "invoice" else "100.30",
        text="INV-AX" if kind == "invoice" else "P-1")
    page = suggestions(active_store, booking.id, SuggestionQuery(kind=kind))
    assert page["items"][0]["id"] == target.id
    assert page["items"][0]["reasons"] == ["reference", "amount_exact", "same_portfolio"]
    assert active_store.list_payments() == []
    request = command(page)
    receipt = confirm_match(active_store, booking.id, request)
    assert receipt.entity_type == kind and receipt.amount == Decimal("40.10") and receipt.booking_id == booking.id
    assert confirm_match(active_store, booking.id, request).id == receipt.id
    updated = getattr(active_store, f"get_{kind}")(target.id)
    assert updated.amount_paid == 40.10 and updated.status == "partial"
    assert active_store.get_booking(booking.id).allocated_amount == 40.10
    reversal = active_store.reverse_payment(kind, target.id, receipt.id, PaymentReversalCreate(
        idempotency_key=str(uuid4()), reversal_date=date(2026, 9, 6), reason="Reviewed correction"))
    assert reversal.amount == receipt.amount
    assert active_store.get_booking(booking.id).allocated_amount == 0
    assert getattr(active_store, f"get_{kind}")(target.id).amount_paid == 0
    assert active_store.list_payments(kind, target.id)[0].reversal.id == reversal.id
    assert len(active_store.list_bookings()) == 1


def test_reference_ties_are_explicit_and_keysets_are_bounded_without_count_or_n_plus_one(active_store):  # noqa: F811
    target, booking = setup(active_store)
    others = [active_store.create_rent_charge(RentChargeCreate(contract_id=target.contract_id,
        month=f"2027-{month:02d}", cold_rent=100.30)) for month in range(1, 7)]
    reads = []
    engine = active_store.db.get_bind() if hasattr(active_store, "db") else None
    def capture(_, __, statement, *args):
        if statement.lstrip().upper().startswith(("SELECT", "WITH")):
            reads.append(statement)
    if engine:
        event.listen(engine, "before_cursor_execute", capture)
    try:
        page = suggestions(active_store, booking.id, SuggestionQuery(page_size=2))
    finally:
        if engine:
            event.remove(engine, "before_cursor_execute", capture)
    assert page["ambiguous"] and page["has_more"] and len(page["items"]) == 2
    assert not any("count(" in statement.lower() for statement in reads)
    if engine:
        assert len(reads) <= 4  # booking/account + one joined target page, no per-target reads
        assert any("LIMIT" in statement and "rent_charges" in statement for statement in reads)
    seen = [item["id"] for item in page["items"]]
    while page["has_more"]:
        page = suggestions(active_store, booking.id, SuggestionQuery(page_size=2, cursor=page["next_cursor"]))
        seen.extend(item["id"] for item in page["items"])
    assert set(seen) == {target.id, *(row.id for row in others)} and len(seen) == 7
    assert not active_store.list_payments()


@pytest.mark.parametrize("change", ["booking", "target", "tamper", "filter"])
def test_changed_sources_and_tampered_or_foreign_reviews_fail_without_any_receipt(active_store, change):  # noqa: F811
    target, booking = setup(active_store)
    page = suggestions(active_store, booking.id, SuggestionQuery(page_size=1))
    request = command(page)
    if change == "booking":
        active_store.update_booking(booking.id, BookingCreate(**{**booking.model_dump(include=set(BookingCreate.model_fields)), "amount": 99.99}))
    elif change == "target":
        active_store.update_rent_charge(target.id, RentChargeCreate(**{**target.model_dump(include=set(RentChargeCreate.model_fields)), "cold_rent": 99.99}))
    elif change == "tamper":
        request = request.model_copy(update={"review_token": request.review_token[:-5] + "XXXXX"})
    else:
        booking = active_store.create_booking(BookingCreate(**booking.model_dump(include=set(BookingCreate.model_fields))))
    with pytest.raises(MatchError):
        confirm_match(active_store, booking.id, request)
    assert active_store.list_payments() == []
    assert active_store.get_booking(booking.id).allocated_amount == 0


def test_invoice_receipts_guard_edits_deletes_and_restore_exact_signed_allocations(active_store):  # noqa: F811
    target, booking = setup(active_store, "invoice", amount="-100.30", text="INV-AX")
    page = suggestions(active_store, booking.id, SuggestionQuery(kind="invoice"))
    receipt = confirm_match(active_store, booking.id, command(page))
    active_store.reverse_payment("invoice", target.id, receipt.id, PaymentReversalCreate(
        idempotency_key=str(uuid4()), reversal_date=date(2026, 9, 6), reason="Correction"))
    active_store.record_payment("invoice", target.id, PaymentCreate(idempotency_key=str(uuid4()),
        amount="10.10", booking_id=booking.id, payment_date=booking.booking_date))
    with pytest.raises(ValidationError):
        active_store._patch_entity("invoice", target.id, InvoicePatch(gross_amount=1))
    with pytest.raises(ValidationError):
        active_store.delete_invoice(target.id)
    snapshot = export_store_data(active_store, "synthetic-bank-matching")
    snapshot["bookings"][0]["allocated_amount"] = 999999
    import_store_data(active_store, snapshot, replace_existing=True)
    restored = active_store.list_invoices()[0]
    assert restored.amount_paid == 10.10 and restored.status == "partial"
    assert active_store.list_bookings()[0].allocated_amount == 10.10
    history = active_store.list_payments("invoice", restored.id)
    assert len(history) == 2 and len([row for row in history if row.reversal]) == 1


def test_two_independent_sql_confirmers_publish_only_one_receipt(active_store):  # noqa: F811
    if not hasattr(active_store, "db"):
        pytest.skip("Independent SQL sessions; memory uses its existing mutation RLock")
    _, booking = setup(active_store, "invoice", amount="-100.30", text="INV-AX")
    page = suggestions(active_store, booking.id, SuggestionQuery(kind="invoice"))
    request = command(page, amount="100.30")
    engine = active_store.db.get_bind()
    active_store.db.rollback()
    barrier = Barrier(2)
    def confirm():
        with Session(engine) as session:
            barrier.wait()
            return confirm_match(SQLAlchemyStore(session), booking.id, request).id
    with ThreadPoolExecutor(max_workers=2) as pool:
        ids = list(pool.map(lambda _: confirm(), range(2)))
    assert ids[0] == ids[1]
    with Session(engine) as fresh:
        assert len(fresh.scalars(select(PaymentORM)).all()) == 1


def test_invoice_receipts_are_immutable_models_and_actual_sql_updates_are_rejected(active_store):  # noqa: F811
    from pydantic import ValidationError as ModelValidationError
    from sqlalchemy import update

    from backend.db.orm_models import PaymentReversalORM
    target, booking = setup(active_store, "invoice", amount="-100.30", text="INV-AX")
    receipt = confirm_match(active_store, booking.id, command(suggestions(active_store, booking.id, SuggestionQuery(kind="invoice"))))
    with pytest.raises(ModelValidationError):
        receipt.amount = Decimal("1.00")
    reversal = active_store.reverse_payment("invoice", target.id, receipt.id, PaymentReversalCreate(
        idempotency_key=str(uuid4()), reversal_date=date(2026, 9, 6), reason="Correction"))
    if hasattr(active_store, "db"):
        with active_store.db.get_bind().begin() as connection:
            ensure_invoice_payment_immutability(connection)
        for model, identifier in ((PaymentORM, receipt.id), (PaymentReversalORM, reversal.id)):
            with pytest.raises(IntegrityError):
                with active_store.db.get_bind().begin() as connection:
                    connection.execute(update(model.__table__).where(model.id == identifier).values(amount=1))
        assert active_store.list_payments("invoice", target.id)[0].amount == Decimal("40.10")


def test_review_expiry_and_changed_cursor_filters_are_recoverable_without_writes(active_store, monkeypatch):  # noqa: F811
    from backend.services import bank_matching
    target, booking = setup(active_store)
    active_store.create_rent_charge(RentChargeCreate(contract_id=target.contract_id, month="2027-01", cold_rent=100.30))
    page = suggestions(active_store, booking.id, SuggestionQuery(page_size=1))
    with pytest.raises(MatchError) as changed:
        suggestions(active_store, booking.id, SuggestionQuery(page_size=1, search="another", cursor=page["next_cursor"]))
    assert changed.value.code == "MATCH_SOURCE_CHANGED"
    now = bank_matching.time()
    monkeypatch.setattr(bank_matching, "time", lambda: now + bank_matching.LIFETIME + 1)
    with pytest.raises(MatchError) as expired:
        confirm_match(active_store, booking.id, command(page))
    assert expired.value.code == "MATCH_REVIEW_EXPIRED" and expired.value.status == 400
    assert active_store.list_payments() == []


def test_sql_suggestions_refresh_a_previously_loaded_invoice_after_an_external_edit(active_store):  # noqa: F811
    if not hasattr(active_store, "db"):
        pytest.skip("SQL identity-cache regression; Memory reads current locked models")
    from backend.db.orm_models import InvoiceORM
    target, booking = setup(active_store, "invoice", amount="-100.30", text="INV-AX")
    held = active_store.db.get(InvoiceORM, target.id)
    active_store.db.rollback()
    # Keep a real cached ORM identity alive through the independent transaction.
    held = active_store.db.get(InvoiceORM, target.id)
    with Session(active_store.db.get_bind()) as other:
        other.execute(InvoiceORM.__table__.update().where(InvoiceORM.id == target.id).values(gross_amount=90))
        other.commit()
    page = suggestions(active_store, booking.id, SuggestionQuery(kind="invoice"))
    assert page["items"][0]["open_cents"] == 9000
    assert "amount_exact" not in page["items"][0]["reasons"]
    assert held.gross_amount == Decimal("90.00")


def test_invoice_payments_do_not_duplicate_or_redate_tax_cash_sources(active_store):  # noqa: F811
    from backend.services.annual_tax_source import cash_source
    target, booking = setup(active_store, "invoice", amount="-100.30", text="INV-AX")
    portfolio = active_store.get_account(booking.account_id).portfolio_id
    with cash_source(active_store, portfolio, 2026) as rows:
        before = list(rows)
    receipt = confirm_match(active_store, booking.id, command(suggestions(active_store, booking.id, SuggestionQuery(kind="invoice"))))
    with cash_source(active_store, portfolio, 2026) as rows:
        after = list(rows)
    assert len(before) == len(after) == 1
    assert after[0]["id"] == before[0]["id"] == booking.id
    assert Decimal(after[0]["amount"]) == Decimal("-100.30")
    assert after[0]["booking_date"] == before[0]["booking_date"] == "2026-09-05"
    assert receipt.payment_date == booking.booking_date and active_store.get_invoice(target.id).amount_paid == 40.10
    with pytest.raises(ValidationError):
        active_store.record_payment("invoice", target.id, PaymentCreate(idempotency_key=str(uuid4()), amount="0.01",
            booking_id=booking.id, payment_date=date(2026, 9, 6)))


def test_invoice_evidence_does_not_leak_into_tenant_graph_or_silently_drop_tenant_cash(active_store):  # noqa: F811
    from backend.services.tenant_data_graph import TenantExportError, tenant_data_graph
    target, booking = setup(active_store, "invoice", amount="-100.30", text="INV-AX")
    tenant_id = active_store.list_contracts()[0].tenant_id
    confirm_match(active_store, booking.id, command(suggestions(active_store, booking.id, SuggestionQuery(kind="invoice"))))
    graph = tenant_data_graph(active_store, tenant_id)
    assert graph["payments"] == [] and "INV-AX" not in str(graph)
    own_source = active_store.create_booking(BookingCreate(account_id=booking.account_id, booking_date=booking.booking_date,
        amount=-100.30, tenant_id=tenant_id))
    active_store.record_payment("invoice", target.id, PaymentCreate(idempotency_key=str(uuid4()), amount=".01",
        booking_id=own_source.id, payment_date=own_source.booking_date))
    with pytest.raises(TenantExportError, match="invoice evidence outside"):
        tenant_data_graph(active_store, tenant_id)
