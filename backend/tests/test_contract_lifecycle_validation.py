"""Full offline journal validation and fail-closed corruption, synthetic DB only."""

import sqlite3
from contextlib import closing
from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy import update

from backend.db.contract_lifecycle_models import ContractLifecycleDraftORM
from backend.db.orm_models import ContractORM
from backend.services import contract_lifecycle as service
from backend.services.contract_lifecycle_validation import JournalValidationError, validate_lifecycle_journal
from backend.tests.test_contract_lifecycle import active as active
from backend.tests.test_contract_lifecycle import confirmation, prepare, supersession


def test_sqlalchemy_and_native_sqlite_complete_journal_survive_offline_source_copy(active, tmp_path):
    if active.engine is None:
        pytest.skip("Native database restoration evidence")
    row = prepare(active, operation="renewal")
    done = service.confirm_draft(active.store, active.contract.id, row["id"], confirmation(row), "actor")
    with active.engine.connect() as connection:
        original_options = dict(connection.get_execution_options())
        assert validate_lifecycle_journal(connection) is True
        assert dict(connection.get_execution_options()) == original_options
    with closing(sqlite3.connect(active.engine.url.database)) as source, closing(sqlite3.connect(tmp_path / "restored.db")) as restored:
        source.backup(restored)
        assert validate_lifecycle_journal(restored) is True
        # A historical successor may itself later end; no snapshot is rewritten.
        restored.execute("UPDATE contracts SET end_date='2028-12-31',status='terminated' WHERE id=?", (done["successor_contract_id"],))
        assert validate_lifecycle_journal(restored) is True
        restored.execute("DROP TRIGGER immo_contract_lifecycle_commands_delete")
        restored.execute("DELETE FROM contract_lifecycle_commands WHERE operation='confirm'")
        with pytest.raises(JournalValidationError, match="history is incomplete"):
            validate_lifecycle_journal(restored)


def test_absent_pair_is_legacy_compatible_but_partial_schema_fails_before_any_mutation(tmp_path):
    with closing(sqlite3.connect(tmp_path / "legacy.db")) as connection:
        assert validate_lifecycle_journal(connection) is False
        connection.execute("CREATE TABLE contract_lifecycle_drafts(id TEXT)")
        with pytest.raises(JournalValidationError, match="Incomplete"):
            validate_lifecycle_journal(connection)
        assert connection.execute("SELECT COUNT(*) FROM contract_lifecycle_drafts").fetchone() == (0,)


def test_historic_source_reparenting_fails_closed_without_leaking_review(active):
    row = prepare(active)
    if active.engine:
        with active.engine.begin() as connection:
            connection.execute(update(ContractORM).where(ContractORM.id == active.contract.id).values(contract_number="Safe metadata change"))
        with active.engine.connect() as connection:
            assert validate_lifecycle_journal(connection)
        with active.engine.begin() as connection:
            connection.execute(update(ContractLifecycleDraftORM).where(ContractLifecycleDraftORM.id == row["id"])
                               .values(review_hash="0" * 64))
    else:
        active.store.__dict__["contract_lifecycle_drafts"][row["id"]].review_hash = "0" * 64
    with pytest.raises(HTTPException) as exc:
        service.get_draft(active.store, active.contract.id, row["id"], "actor")
    assert exc.value.status_code == 503 and "Synthetic" not in exc.value.detail
    if active.engine:
        with active.engine.connect() as connection, pytest.raises(JournalValidationError):
            validate_lifecycle_journal(connection)


def test_corrupt_hidden_draft_never_silently_filters_authorized_history(active):
    row = prepare(active)
    foreign_id = active.users["foreign"]["portfolio_ids"][0]
    if active.engine:
        with active.engine.begin() as connection:
            connection.execute(update(ContractLifecycleDraftORM).where(ContractLifecycleDraftORM.id == row["id"])
                               .values(portfolio_id=foreign_id))
    else:
        active.store.__dict__["contract_lifecycle_drafts"][row["id"]].portfolio_id = foreign_id
    for action in (lambda: service.get_draft(active.store, active.contract.id, row["id"], "actor"),
                   lambda: service.list_drafts(active.store, active.contract.id, "readonly", history=True)):
        with pytest.raises(HTTPException) as exc:
            action()
        assert exc.value.status_code == 503 and foreign_id not in exc.value.detail


def test_supersession_chain_survives_source_loss_with_old_reply_and_stale_private_review(active, tmp_path):
    original, old_payload, second = supersession(active)
    stale = prepare(active, key="private-stale", termination_end_date="2026-10-30")
    accepted = service.confirm_draft(active.store, active.contract.id, second["id"], confirmation(second, "confirm-earlier"), "actor")
    following = prepare(active, key="earlier-again", termination_end_date="2026-10-29")
    service.confirm_draft(active.store, active.contract.id, following["id"], confirmation(following, "confirm-again"), "actor")
    assert service.get_draft(active.store, active.contract.id, stale["id"], "actor")["state"] == "reviewed"
    assert service.get_draft(active.store, active.contract.id, accepted["id"], "readonly")["state"] == "superseded"
    assert service.confirm_draft(active.store, active.contract.id, original["id"], old_payload, "actor") == original
    if active.engine:
        with active.engine.connect() as connection:
            assert validate_lifecycle_journal(connection)
        with closing(sqlite3.connect(active.engine.url.database)) as source, closing(sqlite3.connect(tmp_path / "restored-chain.db")) as restored:
            source.backup(restored)
        source_path = Path(active.engine.url.database)
        assert source_path.parent == tmp_path  # Only this explicitly owned fixture.
        active.db.close()
        active.engine.dispose()
        source_path.unlink()
        assert not source_path.exists()
        with closing(sqlite3.connect(tmp_path / "restored-chain.db")) as restored:
            assert validate_lifecycle_journal(restored)
            assert restored.execute("SELECT COUNT(*) FROM contract_lifecycle_drafts WHERE state='superseded'").fetchone() == (2,)


@pytest.mark.parametrize("changes", [{"end_date": None}, {"status": "terminated"}])
def test_alternative_current_parent_state_is_refused_before_online_or_offline_publication(active, changes):
    row = prepare(active)
    service.confirm_draft(active.store, active.contract.id, row["id"], confirmation(row), "actor")
    # An owned corrupt restore fixture deliberately bypasses ordinary guards.
    if active.engine:
        with active.engine.begin() as connection:
            connection.execute(update(ContractORM).where(ContractORM.id == active.contract.id).values(**changes))
        with active.engine.connect() as connection, pytest.raises(JournalValidationError, match="contradicts"):
            validate_lifecycle_journal(connection)
    else:
        active.store.contracts[active.contract.id] = active.store.contracts[active.contract.id].model_copy(update=changes)
    with pytest.raises(HTTPException) as exc:
        service.get_draft(active.store, active.contract.id, row["id"], "readonly")
    assert exc.value.status_code == 503


@pytest.mark.parametrize("corruption", ["missing-backlink", "foreign-predecessor", "cycle"])
def test_corrupt_supersession_binding_and_cycle_fail_closed_without_foreign_ids(active, corruption):
    original, _, second = supersession(active)
    done = service.confirm_draft(active.store, active.contract.id, second["id"], confirmation(second, "confirm-earlier"), "actor")
    foreign = active.users["foreign"]["portfolio_ids"][0]
    if corruption == "missing-backlink":
        identifier, values = original["id"], {"superseded_by_draft_id": None}
    elif corruption == "foreign-predecessor":
        identifier, values = original["id"], {"portfolio_id": foreign}
    else:
        identifier, values = original["id"], {"supersedes_draft_id": done["id"]}
    if active.engine:
        with active.engine.begin() as connection:
            connection.exec_driver_sql("DROP TRIGGER immo_contract_lifecycle_drafts_update")
            connection.execute(update(ContractLifecycleDraftORM).where(ContractLifecycleDraftORM.id == identifier).values(**values))
        with active.engine.connect() as connection, pytest.raises(JournalValidationError):
            validate_lifecycle_journal(connection)
    else:
        row = active.store.__dict__["contract_lifecycle_drafts"][identifier]
        for key, value in values.items():
            setattr(row, key, value)
    with pytest.raises(HTTPException) as exc:
        service.get_draft(active.store, active.contract.id, original["id"], "readonly")
    assert exc.value.status_code == 503 and foreign not in exc.value.detail
