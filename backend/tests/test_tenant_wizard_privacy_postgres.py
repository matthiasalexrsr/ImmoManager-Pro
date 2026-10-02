"""Disposable UUID PostgreSQL schema; no production URL or emulated PG proof."""

from concurrent.futures import ThreadPoolExecutor
from datetime import date
from threading import Event, current_thread

import pytest
from alembic import command as alembic_command
from alembic.config import Config
from sqlalchemy import event
from sqlalchemy.orm import Session

from backend.repositories.sql_store import SQLAlchemyStore
from backend.services import contract_wizard as wizard
from backend.services.contract_wizard_types import SignatureCreate
from backend.services.file_storage import LocalStorage
from backend.services.tenant_privacy import (
    PrivacyConflict,
    anonymize_tenant_profile,
    export_tenant_metadata,
    preview_tenant_anonymization,
)
from backend.tests.test_contract_wizard_postgres import postgres as postgres_fixture
from backend.tests.test_contract_wizard_workflow import command, prepare, publish
from backend.tests.test_tenant_wizard_privacy import (
    test_complete_download_preserves_pdf_original_signers_commands_and_template_after_source_loss as check_download,
)
from backend.tests.test_tenant_wizard_privacy import (
    test_private_editors_remain_opaque_but_revision_changes_invalidate_review_and_block_normal_delete as check_private,
)
from backend.tests.test_tenant_wizard_privacy import (
    test_profile_anonymization_names_retained_wizard_pii_and_preserves_exact_immutable_bytes as check_retained,
)

postgres = postgres_fixture


@pytest.fixture
def active_pg(postgres, tmp_path, monkeypatch):
    # Disclosure also queries finance/private drafts. Use the actual application
    # head, rather than pinning their evolving ORM columns to wizard revision v1.
    postgres.store.db.rollback()
    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", postgres.engine.url.render_as_string(hide_password=False).replace("%", "%%"))
    alembic_command.upgrade(config, "head")
    postgres.tmp = tmp_path
    postgres.storage = LocalStorage(str(tmp_path / "uploads"))
    monkeypatch.setattr("backend.services.contract_attachment.get_file_storage", lambda: postgres.storage)
    return postgres


def test_pg_full_scoped_download_and_source_loss(active_pg):
    check_download(active_pg)


def test_pg_profile_retains_immutable_evidence_and_private_draft_cas(active_pg):
    check_retained(active_pg)
    check_private(active_pg)


def test_pg_actual_signature_writer_excludes_profile_plan_and_never_deadlocks(active_pg):
    row = prepare(active_pg, tenant_id=active_pg.tenant.id, new_tenant=None)
    row = wizard.publish_draft(active_pg.store, row["id"], publish(row), "actor")
    preview = preview_tenant_anonymization(active_pg.store, active_pg.tenant.id)
    locked, release = Event(), Event()
    def pause_after_lock(_connection, _cursor, statement, _parameters, _context, _many):
        if (current_thread().name.startswith("journal-writer") and "contract_wizard_drafts" in statement
                and "FOR UPDATE" in statement.upper() and not locked.is_set()):
            locked.set()
            assert release.wait(15), "privacy operation did not return within the bounded test deadline"
    def sign():
        with Session(active_pg.engine) as db:
            return wizard.record_signature(SQLAlchemyStore(db), row["id"], SignatureCreate(
                **command(row, "parallel-signature").model_dump(), confirmed=True,
                signed_date=date(2026, 10, 1), tenant_signer="Concurrent signer",
                landlord_signer="Synthetic owner", reference="Independent factual evidence"), "actor")
    event.listen(active_pg.engine, "after_cursor_execute", pause_after_lock)
    try:
        with ThreadPoolExecutor(max_workers=1, thread_name_prefix="journal-writer") as pool:
            future = pool.submit(sign)
            try:
                assert locked.wait(10)
                with pytest.raises(PrivacyConflict, match="gerade geändert"):
                    anonymize_tenant_profile(active_pg.store, active_pg.tenant.id,
                        plan_hash=preview["plan_hash"], confirm_tenant_id=active_pg.tenant.id)
                assert active_pg.store.get_tenant(active_pg.tenant.id).full_name == active_pg.tenant.full_name
            finally:
                release.set()
            assert future.result(timeout=10)["state"] == "signed"
    finally:
        release.set()
        event.remove(active_pg.engine, "after_cursor_execute", pause_after_lock)
    assert export_tenant_metadata(active_pg.store, active_pg.tenant.id)["contract_signature_evidence"][0]["reference"] == "Independent factual evidence"
    with pytest.raises(PrivacyConflict, match="Datenstand"):
        anonymize_tenant_profile(active_pg.store, active_pg.tenant.id,
            plan_hash=preview["plan_hash"], confirm_tenant_id=active_pg.tenant.id)
