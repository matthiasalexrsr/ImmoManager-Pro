"""Monthly obligations remain consistent across payment, reversal and reporting."""

from datetime import date

from backend.models import ReceivableCreate, ReceivablePatch
from backend.routers import reports
from backend.services.rent_ledger import list_open_items
from backend.services.report_service import compute_receivables_aging
from backend.tests import test_rent_ledger as support
from backend.tests.test_bank_payments import reversal
from backend.tests.test_payments import payload, seed

ledger_store = support.ledger_store


def test_monthly_debt_is_in_summary_aging_and_open_items_after_reversal(ledger_store, monkeypatch):
    charge = seed(ledger_store, "rent_charge")
    other = ledger_store.create_receivable(ReceivableCreate(contract_id=charge.contract_id, due_date=date(2026, 9, 3), amount_due=20))
    monkeypatch.setattr(reports, "store", ledger_store)
    payment = ledger_store.record_payment("rent_charge", charge.id, payload("30.10"))
    ledger_store.record_payment("receivable", other.id, payload("0.10"))
    assert reports.get_summary()["finance"]["openRentCharges"] == 70.2
    assert reports.get_summary()["finance"]["openOtherReceivables"] == 19.9
    assert reports.get_summary()["finance"]["openReceivables"] == 90.1
    assert reports.get_receivables_aging()["openTotal"] == 90.1
    assert list_open_items(ledger_store)["total_outstanding"] == 90.1
    ledger_store.reverse_payment("rent_charge", charge.id, payment.id, reversal())
    assert reports.get_summary()["finance"]["openReceivables"] == 120.2
    assert reports.get_receivables_aging()["openTotal"] == 120.2
    assert list_open_items(ledger_store)["total_outstanding"] == 120.2


def test_cancelled_other_obligation_is_excluded_from_aging_and_reporting(ledger_store, monkeypatch):
    charge = seed(ledger_store, "receivable")
    ledger_store._patch_entity("receivable", charge.id, ReceivablePatch(status="cancelled"))
    monkeypatch.setattr(reports, "store", ledger_store)
    assert reports.get_summary()["finance"]["openReceivables"] == 0
    assert reports.get_receivables_aging()["openTotal"] == 0
    assert list_open_items(ledger_store)["items"] == []


def test_aging_keeps_exact_cents_and_uses_monthly_due_date(ledger_store):
    charge = seed(ledger_store, "rent_charge")
    ledger_store.record_payment("rent_charge", charge.id, payload("100.29"))
    result = compute_receivables_aging(receivables=[], rent_charges=ledger_store.list_rent_charges(), today=date(2026, 10, 3))
    assert result["openTotal"] == 0.01
    assert result["buckets"]["days1to30"] == 0.01
