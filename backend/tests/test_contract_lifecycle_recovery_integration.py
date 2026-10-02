"""Complete synthetic recovery preserves lifecycle evidence before security DML."""

import hashlib
import shutil
import sqlite3
import time
from contextlib import closing
from datetime import date, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend import auth
from backend.db.session_models import AuthSessionORM
from backend.repositories.sql_store import SQLAlchemyStore
from backend.services import contract_lifecycle as lifecycle
from backend.services.contract_lifecycle_types import Confirmation, DraftCreate, RevisionCommand
from backend.services.contract_lifecycle_validation import validate_lifecycle_journal
from backend.services.full_recovery import _database_info, create_full_backup, restore_full_backup
from backend.services.recovery_archive import RecoveryError
from backend.services.recovery_sessions import SessionRestoreError, secure_sqlite_restore
from backend.services.recovery_validation import validate_file_references
from backend.tests.test_full_recovery import PASSPHRASE, plan, runtime_template  # noqa: F401


def seed_journal(recovery_plan, monkeypatch):
    engine = create_engine("sqlite:///" + recovery_plan.database.as_posix())
    monkeypatch.setattr(lifecycle, "today", lambda: date(2026, 10, 2))
    with Session(engine) as db:
        store = SQLAlchemyStore(db)
        actor_id = db.connection().exec_driver_sql("SELECT id FROM users LIMIT 1").scalar_one()
        monkeypatch.setattr(auth, "get_user_by_id", lambda identifier: dict(
            id=actor_id, role="eigentuemer", is_active=True, portfolio_access="all") if identifier == actor_id else None)
        contract = store.list_contracts()[0]
        payload = DraftCreate(idempotency_key="recovery-create", expected_contract_etag=lifecycle.contract_etag(contract),
            data={"operation": "termination", "reason": "Synthetic recorded management decision", "termination_end_date": "2026-11-30"})
        row = lifecycle.create_draft(store, contract.id, payload, actor_id)
        reviewed = lifecycle.review_draft(store, contract.id, row["id"], RevisionCommand(
            idempotency_key="recovery-review", expected_revision=row["revision"], expected_contract_etag=row["source_contract_etag"]), actor_id)
        confirmed = lifecycle.confirm_draft(store, contract.id, row["id"], Confirmation(
            idempotency_key="recovery-confirm", expected_revision=reviewed["revision"], expected_contract_etag=reviewed["source_contract_etag"],
            reviewed_hash=reviewed["review_hash"], confirmed=True), actor_id)
        stamp = datetime(2026, 10, 2)
        family = str(uuid4())
        db.add(AuthSessionORM(id=family, user_id=actor_id, device_label="Synthetic restore family",
            created_at=stamp, last_used_at=stamp, expires_at=stamp + timedelta(days=5), generation=0,
            current_refresh_hash=hashlib.sha256(b"synthetic-nonsecret-family").hexdigest()))
        db.commit()
        assert store.get_contract(contract.id).end_date == date(2026, 11, 30)
    engine.dispose()
    return confirmed, family


def journal_rows(path):
    with closing(sqlite3.connect(path)) as db:
        return tuple(db.execute("SELECT * FROM " + table + " ORDER BY id").fetchall()
            for table in ("contract_lifecycle_drafts", "contract_lifecycle_commands"))


def corrupt_confirmation(image):
    with closing(sqlite3.connect(image)) as db:
        for (name,) in db.execute("SELECT name FROM sqlite_master WHERE type='trigger' AND tbl_name='contract_lifecycle_commands'").fetchall():
            db.execute('DROP TRIGGER "' + name.replace('"', '""') + '"')
        db.execute("DELETE FROM contract_lifecycle_commands WHERE operation='confirm'")
        db.commit()


def test_source_gone_complete_restore_keeps_exact_journal_and_obligations(plan, tmp_path, monkeypatch):  # noqa: F811
    row, family = seed_journal(plan, monkeypatch)
    before = journal_rows(plan.database)
    before_counts = _database_info(plan.database)["rows"]
    archive = tmp_path / "complete-lifecycle.immobak"
    create_full_backup(plan, archive, PASSPHRASE, offline=True)
    # This is solely the fixture's synthetic source, checked before deletion.
    source = plan.database.parent.resolve()
    assert source == (tmp_path / "source").resolve()
    shutil.rmtree(source)
    target = tmp_path / "restored-lifecycle"
    result = restore_full_backup(archive, target, PASSPHRASE)
    restored = target / "database.sqlite3"
    assert result["sessions_revoked"] == 1
    assert journal_rows(restored) == before
    with closing(sqlite3.connect(restored)) as db:
        assert validate_lifecycle_journal(db)
        assert db.execute("SELECT end_date,status FROM contracts WHERE id=?", (row["contract_id"],)).fetchone() == ("2026-11-30", "active")
        assert db.execute("SELECT revoked_at FROM auth_sessions WHERE id=?", (family,)).fetchone()[0] is not None
        for table in ("payments", "payment_reversals", "bookings", "receivables", "rent_charges"):
            assert db.execute("SELECT COUNT(*) FROM " + table).fetchone()[0] == before_counts[table]


def test_corrupt_journal_refuses_scan_and_security_before_family_revocation(plan, tmp_path, monkeypatch):  # noqa: F811
    _, family = seed_journal(plan, monkeypatch)
    image = tmp_path / "corrupt-staged.sqlite"
    with closing(sqlite3.connect(plan.database)) as source, closing(sqlite3.connect(image)) as destination:
        source.backup(destination)
    corrupt_confirmation(image)
    with pytest.raises(RecoveryError, match="Vertragsablaufhistorie"):
        validate_file_references(image, str(plan.uploads), expected_upload_files={"proof.bin"})
    with pytest.raises(SessionRestoreError, match="restore_contract_lifecycle_invalid"):
        secure_sqlite_restore(image, plan.configuration, deadline=time.monotonic() + 30)
    with closing(sqlite3.connect(image)) as db:
        assert db.execute("SELECT revoked_at FROM auth_sessions WHERE id=?", (family,)).fetchone()[0] is None
    assert len(journal_rows(plan.database)[1]) == 3


def test_pre_z1_absent_pair_is_allowed_but_half_pair_refuses_before_mutation(plan, tmp_path):  # noqa: F811
    image = tmp_path / "pre-z1.sqlite"
    with closing(sqlite3.connect(plan.database)) as source, closing(sqlite3.connect(image)) as db:
        source.backup(db)
        db.execute("DROP TABLE contract_lifecycle_commands")
        db.execute("DROP TABLE contract_lifecycle_drafts")
        db.commit()
        assert validate_lifecycle_journal(db) is False
    assert "users" in _database_info(image)["rows"]
    with closing(sqlite3.connect(image)) as db:
        db.execute("CREATE TABLE contract_lifecycle_drafts(id TEXT)")
        db.commit()
    with pytest.raises(RecoveryError, match="Vertragsablaufhistorie"):
        _database_info(image)
    with pytest.raises(SessionRestoreError, match="restore_contract_lifecycle_invalid"):
        secure_sqlite_restore(image, plan.configuration, deadline=time.monotonic() + 30)
