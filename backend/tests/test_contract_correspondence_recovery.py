"""Actual encrypted full archive, source gone and before-security hook proof."""

import hashlib
import shutil
import sqlite3
import time
from contextlib import closing

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend import auth
from backend.db.contract_correspondence_models import ensure_contract_correspondence_schema
from backend.repositories.sql_store import SQLAlchemyStore
from backend.services import contract_correspondence as service
from backend.services import recovery_sessions
from backend.services.contract_correspondence_types import ApproveLetter, CreateLetter, ManualEvent, RevisionCommand
from backend.services.contract_correspondence_validation import validate_correspondence_journal
from backend.services.full_recovery import create_full_backup, restore_full_backup
from backend.tests.test_contract_correspondence import data
from backend.tests.test_full_recovery import PASSPHRASE
from backend.tests.test_full_recovery import plan as plan
from backend.tests.test_full_recovery import runtime_template as runtime_template


def seed(plan, monkeypatch):
    engine = create_engine("sqlite:///" + plan.database.as_posix())
    try:
        with engine.begin() as connection:
            ensure_contract_correspondence_schema(connection)
        with Session(engine) as db:
            store = SQLAlchemyStore(db)
            actor_id = db.connection().exec_driver_sql("SELECT id FROM users LIMIT 1").scalar_one()
            monkeypatch.setattr(auth, "get_user_by_id", lambda identifier: dict(id=actor_id, role="eigentuemer", is_active=True,
                portfolio_access="all") if identifier == actor_id else None)
            contract = store.list_contracts()[0]
            row = service.create_draft(store, contract.id, CreateLetter(idempotency_key="archive-create",
                expected_contract_etag=service.lifecycle.contract_etag(contract), data=data()), actor_id)
            reviewed = service.review_draft(store, contract.id, row["id"], RevisionCommand(idempotency_key="archive-review",
                expected_revision=row["revision"], expected_contract_etag=row["source_contract_etag"]), actor_id)
            result = service.approve_draft(store, contract.id, row["id"], ApproveLetter(idempotency_key="archive-approve",
                expected_revision=reviewed["revision"], expected_contract_etag=reviewed["source_contract_etag"],
                reviewed_hash=reviewed["review_hash"], confirmed=True), actor_id)
            sent = service.record_event(store, contract.id, row["id"], ManualEvent(idempotency_key="archive-manual-send",
                expected_revision=result["revision"], expected_event_revision=0, kind="dispatched", event_date="2026-10-02",
                channel="post", reference="Synthetic manual observation", note="No automatic dispatch", confirmed=True), actor_id)
            pdf = service.read_pdf_for_key(store, "contract-correspondence/" + row["id"] + ".pdf", actor_id)
            return result, sent, actor_id, pdf
    finally:
        engine.dispose()


def journal(path):
    with closing(sqlite3.connect(path)) as db:
        assert validate_correspondence_journal(db)
        return tuple(tuple(db.execute("SELECT * FROM " + table + " ORDER BY id")) for table in (
            "contract_correspondence_drafts", "contract_correspondence_commands", "contract_correspondence_events"))


def test_actual_encrypted_archive_source_gone_keeps_exact_local_letter_and_manual_observation(plan, tmp_path, monkeypatch):
    row, sent, actor_id, pdf = seed(plan, monkeypatch)
    before = journal(plan.database)
    archive = tmp_path / "complete-correspondence.immobak"
    create_full_backup(plan, archive, PASSPHRASE, offline=True)
    assert b"Synthetic manual observation" not in archive.read_bytes()
    # Exercise the actual production pre-security validator without injecting
    # another validation hook into the restore transaction.
    source = plan.database.parent.resolve()
    assert source == (tmp_path / "source").resolve()
    shutil.rmtree(source)
    target = tmp_path / "restored-correspondence"
    restore_full_backup(archive, target, PASSPHRASE)
    image = target / "database.sqlite3"
    assert journal(image) == before
    engine = create_engine("sqlite:///" + image.as_posix())
    try:
        with Session(engine) as db:
            store = SQLAlchemyStore(db)
            result = service.get_draft(store, row["contract_id"], row["id"], actor_id)
            assert result["document_version_id"] == row["document_version_id"]
            assert service.events(store, row["contract_id"], row["id"], actor_id)["items"][0]["id"] == sent["event"]["id"]
            compiled, _ = service.prepare_download(store, row["contract_id"], row["id"], actor_id, parent=tmp_path)
            try:
                assert compiled.path.read_bytes() == pdf
                assert compiled.manifest["sha256"] == hashlib.sha256(pdf).hexdigest()
            finally:
                compiled.close()
    finally:
        engine.dispose()


def test_invalid_manual_chain_is_rejected_before_the_actual_session_restore_dml(plan, tmp_path, monkeypatch):
    seed(plan, monkeypatch)
    image = tmp_path / "owned-invalid.sqlite"
    with closing(sqlite3.connect(plan.database)) as source, closing(sqlite3.connect(image)) as db:
        source.backup(db)
        db.execute("DROP TRIGGER immo_contract_correspondence_events_update")
        db.execute("UPDATE contract_correspondence_events SET event_revision=2")
        db.commit()
    before = image.read_bytes()
    with pytest.raises(recovery_sessions.SessionRestoreError, match="restore_contract_correspondence_invalid"):
        recovery_sessions.secure_sqlite_restore(image, plan.configuration, deadline=time.monotonic() + 30)
    assert image.read_bytes() == before
