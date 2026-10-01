"""Preservation guards leave source bytes/history intact instead of deepcopying engines."""
import pytest
from sqlalchemy import select

from backend.db.bank_import_models import BankImportORM, BankImportSourceORM
from backend.models import AccountCreate, AccountPatch, PortfolioCreate
from backend.services.bank_import import BankImportError, journal
from backend.services.bank_import_guards import (
    guard_bank_import_account_delete,
    guard_bank_import_business_transfer,
    guard_bank_import_portfolio_delete,
    guard_bank_import_reset,
)
from backend.tests.test_bank_imports import account, bank_store, confirm, stage  # noqa: F401


def test_reviewed_source_is_preserved_across_rejected_reset_and_json_transfer(bank_store):  # noqa: F811
    selected = account(bank_store)
    job = stage(bank_store, selected.id, "date;amount;text\n2026-01-01;1.01;Preserve original\n")
    confirm(bank_store, job)
    other = bank_store.create_account(AccountCreate(portfolio_id=selected.portfolio_id, name="Other unaffected account", account_type="bank"))
    with journal(bank_store) as db:
        original = db.scalar(select(BankImportSourceORM.data).where(BankImportSourceORM.import_id == job["id"]))
    for operation in (lambda: guard_bank_import_reset(bank_store),
                      lambda: guard_bank_import_business_transfer(bank_store, operation="replace"),
                      lambda: guard_bank_import_business_transfer(bank_store, operation="export"),
                      lambda: guard_bank_import_account_delete(bank_store, selected.id)):
        with pytest.raises(BankImportError) as blocked:
            operation()
        assert blocked.value.status == 409 and "preserve" in blocked.value.recovery
    guard_bank_import_account_delete(bank_store, other.id)
    guard_bank_import_business_transfer(bank_store, operation="merge", memory_journal_preserved=True)
    if hasattr(bank_store, "db"):
        guard_bank_import_business_transfer(bank_store, operation="merge")
    else:
        with pytest.raises(BankImportError) as unpreserved:
            guard_bank_import_business_transfer(bank_store, operation="merge")
        assert unpreserved.value.code == "BANK_MEMORY_JOURNAL_SEPARATE"
    with journal(bank_store) as db:
        assert db.scalar(select(BankImportORM.state).where(BankImportORM.id == job["id"])) == "committed"
        assert db.scalar(select(BankImportSourceORM.data).where(BankImportSourceORM.import_id == job["id"])) == original
    assert len(bank_store.list_bookings()) == 1


def test_empty_memory_journal_merge_reports_actionable_error_without_deepcopy(bank_store):  # noqa: F811
    guard_bank_import_reset(bank_store)
    guard_bank_import_business_transfer(bank_store, operation="replace")
    if hasattr(bank_store, "db"):
        pytest.skip("Memory engine copy failure")
    with journal(bank_store):
        pass
    with pytest.raises(BankImportError) as blocked:
        guard_bank_import_business_transfer(bank_store, operation="merge")
    assert blocked.value.code == "BANK_MEMORY_JOURNAL_SEPARATE"
    guard_bank_import_reset(bank_store)


def test_portfolio_guard_uses_current_account_parent_and_preserves_source(bank_store):  # noqa: F811
    selected = account(bank_store)
    job = stage(bank_store, selected.id, "date;amount;text\n2026-01-01;1;Portfolio evidence\n")
    destination = bank_store.create_portfolio(PortfolioCreate(name="Current parent"))
    with pytest.raises(BankImportError) as blocked:
        guard_bank_import_portfolio_delete(bank_store, selected.portfolio_id)
    assert blocked.value.code == "BANK_PORTFOLIO_IMPORT_HISTORY" and blocked.value.status == 409
    guard_bank_import_portfolio_delete(bank_store, destination.id)
    bank_store._patch_entity("account", selected.id, AccountPatch(portfolio_id=destination.id))
    guard_bank_import_portfolio_delete(bank_store, selected.portfolio_id)
    with pytest.raises(BankImportError):
        guard_bank_import_portfolio_delete(bank_store, destination.id)
    with journal(bank_store) as db:
        assert db.scalar(select(BankImportSourceORM.data).where(BankImportSourceORM.import_id == job["id"]))
