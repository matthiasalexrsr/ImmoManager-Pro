"""Real posted corrections, credit receipts and coherent tenant snapshots."""

import json
from dataclasses import is_dataclass

import pytest
from sqlalchemy import event, update

from backend.db.credit_models import CreditReceiptORM
from backend.models import ContractPatch
from backend.services import credit_ledger as credit
from backend.services.tenant_data_graph import TenantExportError
from backend.services.tenant_privacy import (
    PrivacyConflict,
    anonymize_tenant_profile,
    export_tenant_metadata,
    preview_tenant_anonymization,
)
from backend.tests.test_bank_payments import bank_booking
from backend.tests.test_credit_ledger import (
    correct,
    credit_scenario,
    offset,
    payout,
    reversal,
)
from backend.tests.test_credit_ledger import credit_store as _credit_store

credit_store = _credit_store

def test_current_credit_export_has_real_offset_provenance_and_reversal(credit_store, monkeypatch):
    source, contract, period, _ = credit_scenario(credit_store, monkeypatch)
    _, revised = correct(credit_store, period, 90)
    target = credit_store.get_receivable(revised.receivable_id)
    receipt = credit.create_receipt(credit_store, offset(source, target))
    cash = credit.create_receipt(credit_store, payout(source))
    graph = export_tenant_metadata(credit_store, contract.tenant_id)
    assert graph["schema_version"] == "tenant-data-graph/2"
    assert {row["id"] for row in graph["credit_receipts"]} == {receipt.id, cash.id}
    linked = next(row for row in graph["payments"] if row["id"] == receipt.payment_id)
    assert linked["credit_receipt_id"] == receipt.id
    assert graph["credit_balances"][0]["available_amount"] == "0.00"
    assert graph["credit_balances"][0]["remaining_amount"] == "0.00"
    credit.reverse_receipt(credit_store, receipt.id, reversal())
    after = export_tenant_metadata(credit_store, contract.tenant_id)
    reversed_row = next(row for row in after["credit_receipts"] if row["id"] == receipt.id)
    payment = next(row for row in after["payments"] if row["id"] == receipt.payment_id)
    assert reversed_row["reversal"]["payment_reversal_id"] == payment["reversal"]["id"]
    assert after["credit_balances"][0]["remaining_amount"] == "40.00"
    assert after["credit_balances"][0]["reserved_amount"] == "40.00"
    assert after["credit_balances"][0]["available_amount"] == "0.00"


def test_shared_portfolio_never_expands_credit_export_to_other_contract(credit_store, monkeypatch):
    source, contract, _, _ = credit_scenario(credit_store, monkeypatch, count=2)
    source = credit._settlements(credit_store, contract.id)[0]
    # The service's contract-filtered source reader works with both actual stores.
    other = next(row for row in credit_store.list_contracts() if row.id != contract.id)
    foreign_source = credit._settlements(credit_store, other.id)[0]
    credit.create_receipt(credit_store, payout(source, "10", note="OWN NOTE"))
    credit.create_receipt(credit_store, payout(foreign_source, "10", note="FOREIGN NOTE MUST NOT LEAK"))
    graph = export_tenant_metadata(credit_store, contract.tenant_id)
    assert "FOREIGN NOTE" not in json.dumps(graph)
    assert {row["contract_id"] for row in graph["credit_receipts"]} == {contract.id}
    assert {row["contract_id"] for row in graph["credit_balances"]} == {contract.id}


def test_unassigned_negative_bank_text_is_excluded_but_credit_link_remains(credit_store, monkeypatch):
    source, contract, _, charge = credit_scenario(credit_store, monkeypatch)
    bank = bank_booking(credit_store, charge, -100)
    from backend.models import BookingPatch
    credit_store._patch_entity("booking", bank.id, BookingPatch(
        tenant_id=None, payment_text="PRIVATE SHARED BANK TEXT MUST NOT LEAK", receipt_url="/uploads/private.pdf"))
    receipt = credit.create_receipt(credit_store, payout(source, "60", method="bank", booking_id=bank.id))
    graph = export_tenant_metadata(credit_store, contract.tenant_id)
    encoded = json.dumps(graph)
    assert "PRIVATE SHARED BANK" not in encoded and "/uploads/private.pdf" not in encoded
    assert graph["credit_receipts"][0]["booking_id"] == receipt.booking_id
    assert bank.id not in {row["id"] for row in graph["bookings"]}


def test_credit_changes_invalidate_reviewed_anonymization_plan(credit_store, monkeypatch):
    source, contract, _, _ = credit_scenario(credit_store, monkeypatch)
    credit_store._patch_entity("contract", contract.id, ContractPatch(status="terminated"))
    plan = preview_tenant_anonymization(credit_store, contract.tenant_id)
    assert plan["retained_collections"]["credit_receipts"] == 0
    assert plan["retained_collections"]["credit_balances"] == 1
    receipt = credit.create_receipt(credit_store, payout(source, "10"))
    with pytest.raises(PrivacyConflict, match="Datenstand"):
        anonymize_tenant_profile(credit_store, contract.tenant_id, plan_hash=plan["plan_hash"],
                                confirm_tenant_id=contract.tenant_id)
    fresh = preview_tenant_anonymization(credit_store, contract.tenant_id)
    anonymize_tenant_profile(credit_store, contract.tenant_id, plan_hash=fresh["plan_hash"],
                            confirm_tenant_id=contract.tenant_id)
    assert export_tenant_metadata(credit_store, contract.tenant_id)["credit_receipts"][0]["id"] == receipt.id


def test_broken_offset_provenance_fails_before_any_export(credit_store, monkeypatch):
    source, contract, period, _ = credit_scenario(credit_store, monkeypatch)
    _, revised = correct(credit_store, period, 90)
    receipt = credit.create_receipt(credit_store, offset(source, credit_store.get_receivable(revised.receivable_id)))
    if is_dataclass(credit_store):
        row = credit_store.credit_receipts[receipt.idempotency_key]
        credit_store.credit_receipts[receipt.idempotency_key] = row.model_copy(update={"payment_id": "missing"})
    else:
        credit_store.db.execute(update(CreditReceiptORM).where(CreditReceiptORM.id == receipt.id).values(payment_id="missing"))
        credit_store.db.commit()
    with pytest.raises(TenantExportError):
        export_tenant_metadata(credit_store, contract.tenant_id)


def test_credit_journal_queries_reversals_in_one_bounded_join(credit_store, monkeypatch):
    if is_dataclass(credit_store):
        pytest.skip("SQL query shape")
    source, contract, _, _ = credit_scenario(credit_store, monkeypatch)
    for index in range(12):
        receipt = credit.create_receipt(credit_store, payout(source, "1", key=f"receipt-{index}"))
        credit.reverse_receipt(credit_store, receipt.id, reversal(key=f"reverse-{index}"))
    statements = []
    engine = credit_store.db.get_bind()
    def record(_, __, statement, ___, ____, _____):
        statements.append(statement)
    event.listen(engine, "before_cursor_execute", record)
    try:
        rows = credit.journal(credit_store, contract.id, limit=12)["receipts"]
    finally:
        event.remove(engine, "before_cursor_execute", record)
    assert len(rows) == 12 and all(row.reversal is not None for row in rows)
    assert sum("credit_reversals" in statement for statement in statements) == 1


def test_rent_account_keeps_historical_rent_and_current_unspent_credit_separate(credit_store, monkeypatch):
    from datetime import date

    from backend.routers import contracts
    source, contract, _, _ = credit_scenario(credit_store, monkeypatch)
    credit.create_receipt(credit_store, payout(source, "60"))
    monkeypatch.setattr(contracts, "store", credit_store)
    result = contracts.get_contract_settlement(contract.id, as_of=date(2025, 1, 31))
    assert result["source"] == "booked_rent_charges"
    assert result["credit_snapshot"]["reference"] == "current_snapshot"
    assert result["credit_snapshot"]["available_amount"] == "40.00"
    assert result["credit_snapshot"]["remaining_amount"] == "40.00"
