"""Actual encrypted full-container roundtrip of reviewed dispute originals."""

import shutil
import sqlite3
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text, update

from backend.db.billing_dispute_models import DISPUTE_TABLES, BillingDisputeEventORM
from backend.services.billing_dispute_database import validate_dispute_database
from backend.services.full_recovery import create_full_backup, restore_full_backup
from backend.services.recovery_archive import RecoveryError
from backend.tests.form_draft_api_support import application, migrate
from backend.tests.test_billing_consumption_http import context as context_fixture
from backend.tests.test_billing_dispute_database import populated, privileged_edit
from backend.tests.test_full_recovery import PASSPHRASE
from backend.tests.test_full_recovery import plan as plan
from backend.tests.test_full_recovery import runtime_template as runtime_template

context = context_fixture


@pytest.fixture
def draft_http(monkeypatch, tmp_path):
    url = "sqlite:///" + (tmp_path / "full-dispute-source.sqlite").as_posix()
    migrate(url, monkeypatch)
    engine = create_engine(url, hide_parameters=True, connect_args={"check_same_thread": False})
    try:
        with application(monkeypatch, engine) as active:
            yield active
    finally:
        engine.dispose()


def original_rows(path):
    with sqlite3.connect(path) as connection:
        return tuple(tuple(connection.execute('SELECT * FROM "' + name + '" ORDER BY ' + order))
                     for name, order in (*((name, "id") for name in (*DISPUTE_TABLES, "document_versions")),
                                         ("document_version_chunks", "version_id, position")))


def copy_to_offline_plan(context, plan, tmp_path):
    context["active"].store.db.remove()
    source = Path(context["active"].engine.url.database)
    with sqlite3.connect(source) as reader, sqlite3.connect(plan.database) as destination:
        reader.backup(destination)
    (plan.uploads / "documents").mkdir(exist_ok=True)
    shutil.copyfile(tmp_path / "source/documents/approval.txt", plan.uploads / "documents/approval.txt")


def test_full_encrypted_restore_preserves_case_commands_events_original_evidence(context, plan, monkeypatch, tmp_path):
    _, receipt = populated(context, monkeypatch, tmp_path)
    copy_to_offline_plan(context, plan, tmp_path)
    before = original_rows(plan.database)
    archive, target = tmp_path / "dispute-originals.immobak", tmp_path / "restored-disputes"
    create_full_backup(plan, archive, PASSPHRASE, offline=True)
    result = restore_full_backup(archive, target, PASSPHRASE)
    assert result["signing_key_rotated"]
    assert original_rows(target / "database.sqlite3") == before == original_rows(plan.database)
    assert tuple(map(len, before[:4])) == (1, 2, 2, 1)
    assert (target / "uploads/documents/approval.txt").read_bytes() == (plan.uploads / "documents/approval.txt").read_bytes()
    with sqlite3.connect(target / "database.sqlite3") as connection:
        assert validate_dispute_database(connection)
        assert connection.execute("SELECT reason FROM billing_dispute_events WHERE id=?", (receipt["event_id"],)).fetchone()[0].startswith("Synthetischer Originalgrund")
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            connection.execute("UPDATE billing_dispute_events SET reason='overwrite after restore'")


def test_reinstalled_native_guards_cannot_hide_changed_original_before_archive_publication(context, plan, monkeypatch, tmp_path):
    _, receipt = populated(context, monkeypatch, tmp_path)
    with privileged_edit(context["active"].engine) as connection:
        connection.execute(update(BillingDisputeEventORM).where(BillingDisputeEventORM.id == receipt["event_id"]).values(reason="Changed retained original"))
    copy_to_offline_plan(context, plan, tmp_path)
    before = original_rows(plan.database)
    archive = tmp_path / "never-published-disputes.immobak"
    with pytest.raises(RecoveryError, match="Widerspruchsoriginale"):
        create_full_backup(plan, archive, PASSPHRASE, offline=True)
    assert not archive.exists()
    assert original_rows(plan.database) == before
    assert not list(tmp_path.glob(".immo-backup-*"))
    with context["active"].engine.connect() as connection:
        assert connection.scalar(text("SELECT COUNT(*) FROM billing_dispute_events")) == 2
